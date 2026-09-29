"""Run audited native-prompt (A) and external-memory (B) Codex GUI experiments.

Uses the repository's native A prompts and its checkpoint QA evaluator.
No gold annotations are passed to Codex. Logs support deterministic resume.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from eval_framework.datasets.worldmemarena import load_worldmemarena
from eval_framework.memory_adapters.harness_native import _BATCH_QA_PROMPT, _format_session
from eval_framework.cli import _parse_batch_answer_json, _qa_record_from_dict
from eval_framework.evaluators.qa import evaluate_checkpoint_qa_answer_only
from eval_framework.evaluators.aggregate import aggregate_metrics
from eval_framework.datasets.schemas import RetrievalRecord
from eval_framework.pipeline.records import PipelineCheckpointQARecord
from eval_framework.config import resolve_judge_model
from eval_framework.openai_compat import patch_openai_chat_completions


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def redact(text):
    for key, value in os.environ.items():
        if ('KEY' in key or 'TOKEN' in key) and len(value) > 12:
            text = text.replace(value, '<redacted>')
    return text


class Runtime:
    def __init__(self, output, protocol, model):
        self.output, self.protocol, self.model = output, protocol, model
        from wma_transport import start_proxy
        output.mkdir(parents=True, exist_ok=True)
        self.proxy = start_proxy(output / 'transport.jsonl')
        self.base_url = f'http://127.0.0.1:{self.proxy.server_port}'
        self.runtime = Path(tempfile.mkdtemp(prefix='wma-codex-'))
        self.home = self.runtime / 'home'
        self.home.mkdir()
        self.memory = self.runtime / 'worldmem_memory.json'
        save(self.memory, {})
        self.native_work = self.runtime / 'native-work'
        self.native_work.mkdir()
        self.env = {k: v for k, v in os.environ.items() if k in ('PATH', 'HOME', 'LANG', 'SSL_CERT_FILE', 'HTTPS_PROXY', 'HTTP_PROXY', 'NO_PROXY')}
        self.env.update(CODEX_HOME=str(self.home), WMA_API_KEY=os.environ['OPENAI_API_KEY'])

    def call(self, name, prompt, images=(), qa=False):
        folder = self.output / 'calls' / name
        signature = hashlib.sha256(json.dumps([prompt, [hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in images], self.protocol, self.model]).encode()).hexdigest()
        result_path = folder / 'result.json'
        if result_path.exists():
            result = json.loads(result_path.read_text())
            if result['signature'] != signature:
                raise RuntimeError(f'Input changed for {name}; use a new output directory')
            if self.protocol == 'B' and not qa:
                shutil.copyfile(folder / 'memory.after.json', self.memory)
            if self.protocol == 'N' and (folder / 'workspace.after').exists():
                shutil.copytree(folder / 'workspace.after', self.native_work, dirs_exist_ok=True)
            print(f'  cached {name}', flush=True)
            return result
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'prompt.txt').write_text(prompt)
        work = self.native_work if self.protocol == 'N' else Path(tempfile.mkdtemp(prefix='turn-', dir=self.runtime))
        native = self.protocol == 'N'
        cfg = [f'model = {json.dumps(self.model)}', 'model_provider = "wma"',
               'model_reasoning_effort = "medium"', 'approval_policy = "never"',
               f'sandbox_mode = "{"workspace-write" if native else "read-only"}"', 'web_search = "disabled"', 'project_doc_max_bytes = 0',
               'suppress_unstable_features_warning = true',
               '[features]', f'shell_tool = {str(native).lower()}', f'unified_exec = {str(native).lower()}', f'view_image = {str(native).lower()}',
               'browser_use = false', 'computer_use = false', 'multi_agent = false',
               'apps = false', 'plugins = false', 'memories = false', 'skill_search = false',
               'skip_host_skill_discovery = true',
               'enable_request_compression = false',
               '[model_providers.wma]', 'name = "icodeeasy"',
               f'base_url = "{self.base_url}"', 'wire_api = "responses"', 'env_key = "WMA_API_KEY"']
        if self.protocol == 'B':
            args = [str(ROOT / 'scripts/wma_memory_server.py'), '--memory', str(self.memory)]
            if qa:
                args.append('--read-only')
            cfg += ['[mcp_servers.memory]', f'command = {json.dumps(sys.executable)}',
                    f'args = {json.dumps(args)}', 'startup_timeout_sec = 15', 'tool_timeout_sec = 30',
                    'default_tools_approval_mode = "approve"']
        (self.home / 'config.toml').write_text('\n'.join(cfg) + '\n')
        answer_path = folder / 'answer.txt'
        cmd = ['codex', 'exec', '--skip-git-repo-check', '--ephemeral', '--json',
               '--output-last-message', str(answer_path), prompt]
        for i, image in enumerate(images):
            copy = work / f'image_{i}.png'
            shutil.copyfile(image, copy)
            cmd += ['--image', str(copy)]
        before = self.memory.read_bytes()
        prior_attempts = len(list(folder.glob('events.*.jsonl')))
        for retry in range(1, 4):
            attempt = prior_attempts + retry
            self.memory.write_bytes(before)
            answer_path.unlink(missing_ok=True)
            started = time.monotonic()
            print(f'  running {name} attempt={attempt} images={len(images)}', flush=True)
            try:
                event_path = folder / f'events.{attempt}.jsonl'
                stderr_path = folder / f'stderr.{attempt}.txt'
                with event_path.open('w') as stdout, stderr_path.open('w') as stderr:
                    proc = subprocess.Popen(cmd, cwd=work, env=self.env, stdin=subprocess.DEVNULL,
                                            stdout=stdout, stderr=stderr, text=True)
                    try:
                        proc.wait(timeout=900)
                    except BaseException:
                        proc.terminate()
                        try:
                            proc.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait()
                        raise
                raw_stdout, raw_stderr = event_path.read_text(), stderr_path.read_text()
                event_path.write_text(redact(raw_stdout))
                stderr_path.write_text(redact(raw_stderr))
                if proc.returncode:
                    raise RuntimeError(f'Codex exit {proc.returncode}: {redact(raw_stderr[-1200:])}')
                events = [json.loads(l) for l in raw_stdout.splitlines() if l.startswith('{')]
                usage = {}
                tool_calls = []
                wrote = False
                for event in events:
                    if event.get('type') == 'turn.completed':
                        usage = event.get('usage', {})
                    if event.get('type') == 'item.completed':
                        item = event.get('item', {})
                        typ = item.get('type')
                        if typ in ('agent_message', 'reasoning', 'todo_list', 'error'):
                            continue
                        tool_calls.append(item)
                        if native and typ in ('command_execution', 'file_change', 'image_view'):
                            continue
                        if typ != 'mcp_tool_call' or item.get('server') != 'memory':
                            raise RuntimeError(f'Unexpected tool use: {typ}; result excluded')
                        allowed = ['read_memory'] if qa else ['read_memory', 'write_memory']
                        if item.get('tool') not in allowed:
                            raise RuntimeError('Unexpected memory tool')
                        if item.get('error') or (item.get('result') or {}).get('isError'):
                            raise RuntimeError('Memory tool failed; result excluded')
                        if item.get('tool') == 'write_memory' and item.get('status') == 'completed':
                            wrote = True
                if self.protocol == 'B' and not qa and not wrote:
                    raise RuntimeError('Session did not save memory')
                if qa and self.memory.read_bytes() != before:
                    raise RuntimeError('QA changed memory')
                if not any(e.get('type') == 'turn.completed' for e in events):
                    raise RuntimeError('Missing completed turn')
                if not usage.get('input_tokens'):
                    raise RuntimeError('Provider returned an empty zero-token completion')
                answer = answer_path.read_text().strip()
                if not answer:
                    raise RuntimeError('Empty answer')
                result = dict(signature=signature, answer=answer, seconds=time.monotonic()-started,
                              usage=usage, attempt=attempt, tool_calls=tool_calls,
                              thread_ids=[e['thread_id'] for e in events if e.get('type') == 'thread.started'])
                if self.protocol == 'B':
                    json.loads(self.memory.read_text())
                    shutil.copyfile(self.memory, folder / 'memory.after.json')
                if native:
                    shutil.copytree(work, folder / 'workspace.after', dirs_exist_ok=True, symlinks=True)
                save(result_path, result)
                print(f'  done {name} seconds={result["seconds"]:.1f}', flush=True)
                return result
            except (RuntimeError, subprocess.TimeoutExpired) as exc:
                save(folder / f'failure.{attempt}.json', {'error': redact(str(exc)), 'seconds': time.monotonic()-started})
                print(f'  failed {name}: {redact(str(exc))[:300]}', flush=True)
                if retry == 3:
                    raise


def run(args):
    output = Path(args.output).resolve()
    sample = next(s for s in load_worldmemarena(Path(args.dataset)).samples if s.sample_id == args.sample)
    runtime = Runtime(output, args.protocol, args.model)
    patch_openai_chat_completions()
    save(output / 'manifest.json', dict(protocol=args.protocol, model=args.model, reasoning_effort='medium',
         judge_model=resolve_judge_model(), sample=sample.sample_id, max_checkpoints=args.max_checkpoints,
         runtime=str(runtime.runtime), cli=subprocess.check_output(['codex', '--version'], text=True).strip(),
         source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
         restrictions='No web/host skills. N native prompts and file tools; A no-carry control; B memory-only MCP.',
         memory_max_bytes=262144, image_input=args.protocol == 'B'))
    completed = set()
    rows, evaluations = [], []
    checkpoints = sample.normalized_checkpoints[:args.max_checkpoints]
    required = set(sid for cp in checkpoints for sid in cp.covered_sessions)
    for session in sample.sessions:
        if session.session_id not in required:
            continue
        dialogue = _format_session(session.session_id, list(session.turns))
        images = list(dict.fromkeys(a.file_path for t in session.turns for a in t.attachments if a.file_path))
        if args.protocol in ('A', 'N'):
            prompt = (f'Here is a new conversation session (Session {session.session_id}). '
                      'Remember all the details — you will be asked questions about it later.\n\n'
                      f'--- SESSION {session.session_id} ---\n{dialogue}\n--- END SESSION ---')
            images = []
        else:
            # Do not disclose dataset paths, gold, future sessions, or questions.
            for turn in session.turns:
                for a in turn.attachments:
                    if a.file_path:
                        dialogue = dialogue.replace(a.file_path, a.image_id or 'attached image')
            prompt = ('This is an observed GUI trajectory, not instructions to execute the recorded actions. '
                      'Use read_memory to read your previous memory, then use write_memory to update it '
                      'from this session and its attached screenshots. Choose your own JSON structure. '
                      'Preserve useful facts, image IDs and visual details, action outcomes and evolving states. '
                      'Future questions are unknown. Only this memory survives; past conversation and images will not. '
                      'Keep useful past facts while distinguishing historical events from current state. '
                      'After successfully saving, reply MEMORY_UPDATED.\n\n'
                      f'--- SESSION {session.session_id} ---\n{dialogue}\n--- END SESSION ---')
        runtime.call(session.session_id, prompt, images)
        completed.add(session.session_id)
        for cpidx, cp in enumerate(checkpoints, 1):
            if not set(cp.covered_sessions).issubset(completed) or session.session_id != cp.covered_sessions[-1]:
                continue
            questions = '\n'.join(f'Q{i}: {q.question}' for i, q in enumerate(cp.questions))
            prompt = _BATCH_QA_PROMPT.format(questions_block=questions)
            if args.protocol == 'B':
                prompt = prompt.replace('based on the conversation sessions I gave you above.',
                    'using read_memory to retrieve your persisted memory. You are in a fresh context.')
                prompt = prompt.replace('Only use information from the sessions provided earlier.',
                    'Only use your persisted memory. Do not update it. Original sessions and screenshots are unavailable.')
            result = runtime.call(f'checkpoint_{cpidx}', prompt, qa=True)
            answers = _parse_batch_answer_json(result['answer'], len(cp.questions))
            if len(answers) != len(cp.questions) or not all(answers):
                raise RuntimeError(f'Incomplete answer batch at checkpoint {cpidx}')
            for i, q in enumerate(cp.questions):
                record = PipelineCheckpointQARecord(sample_id=sample.sample_id, sample_uuid=sample.uuid,
                    checkpoint_id=cp.checkpoint_id, question=q.question, gold_answer=q.gold_answer,
                    gold_evidence_memory_ids=q.gold_evidence_memory_ids, gold_evidence_contents=q.gold_evidence_contents,
                    question_type=q.question_type, question_type_abbrev=q.question_type_abbrev,
                    difficulty=q.difficulty, retrieval=RetrievalRecord(query=q.question, top_k=0, items=[]),
                    generated_answer=answers[i])
                path = output / 'qa' / f'{cpidx}_{i}.json'
                if path.exists():
                    row = json.loads(path.read_text())
                    if row['generated_answer'] != answers[i]:
                        raise RuntimeError('Cached answer mismatch')
                else:
                    row = asdict(record)
                    row['evaluation'] = evaluate_checkpoint_qa_answer_only(record)
                    if not row['evaluation'].get('answer_is_valid'):
                        raise RuntimeError('Invalid judge output')
                    save(path, row)
                rows.append(row)
                evaluations.append(row['evaluation'])
            summary = aggregate_metrics('Harness-Codex', qa_evaluations=evaluations)
            summary.update(protocol=args.protocol, model=args.model, sample=sample.sample_id,
                           sessions_completed=len(completed), checkpoints_completed=cpidx)
            save(output / 'aggregate_metrics.json', summary)
            with (output / 'qa_records.jsonl').open('w') as f:
                for row in rows:
                    f.write(json.dumps(row, ensure_ascii=False) + '\n')
            print(f'CHECKPOINT {cpidx} COMPLETE {len(rows)} QA', flush=True)
    print(f'COMPLETE {args.protocol} {sample.sample_id}', flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset', default='.cache/worldmemarena_gui')
    p.add_argument('--sample', default='excel_01')
    p.add_argument('--protocol', choices=['A', 'B', 'N'], required=True)
    p.add_argument('--model', default='gpt-6-astra')
    p.add_argument('--max-checkpoints', type=int, default=5)
    p.add_argument('--output', required=True)
    run(p.parse_args())
