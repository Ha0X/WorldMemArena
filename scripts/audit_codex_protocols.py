"""Audit complete GUI runs against dataset questions and successful tool traces."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from eval_framework.datasets.worldmemarena import load_worldmemarena
from eval_framework.cli import _parse_batch_answer_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runs', nargs='+')
    parser.add_argument('--dataset', default='.cache/worldmemarena_gui')
    parser.add_argument('--output', default='exp_log/codex_gui_report/audit.json')
    args = parser.parse_args()
    samples = {s.sample_id: s for s in load_worldmemarena(Path(args.dataset)).samples}
    all_threads = set()
    reports = []
    for name in args.runs:
        root = Path(name)
        manifest = json.loads((root / 'manifest.json').read_text())
        sample = samples[manifest['sample']]
        protocol = manifest['protocol']
        errors, counts = [], Counter()
        def check(condition, message):
            if not condition:
                errors.append(message)
        checkpoints = sample.normalized_checkpoints[:manifest['max_checkpoints']]
        required = {sid for cp in checkpoints for sid in cp.covered_sessions}
        expected_calls = required | {f'checkpoint_{i}' for i in range(1, len(checkpoints)+1)}
        calls = {p.parent.name: json.loads(p.read_text()) for p in (root/'calls').glob('*/result.json')}
        check(set(calls) == expected_calls, f'Call set differs: missing={sorted(expected_calls-set(calls))}, extra={sorted(set(calls)-expected_calls)}')
        for call_name, call in calls.items():
            check(call['usage'].get('input_tokens', 0) > 0, f'{call_name}: zero input tokens')
            check(len(call['thread_ids']) == 1, f'{call_name}: expected one thread')
            for thread in call['thread_ids']:
                check(thread not in all_threads, f'{call_name}: reused thread {thread}')
                all_threads.add(thread)
            events = [json.loads(line) for line in (root/'calls'/call_name/f'events.{call["attempt"]}.jsonl').read_text().splitlines() if line.startswith('{')]
            check(any(e.get('type') == 'turn.completed' for e in events), f'{call_name}: no completed turn')
            observed = [e['item'] for e in events if e.get('type') == 'item.completed' and e['item'].get('type') not in ('agent_message', 'reasoning', 'todo_list', 'error')]
            check(observed == call['tool_calls'], f'{call_name}: event/result tool mismatch')
            qa = call_name.startswith('checkpoint_')
            for tool in observed:
                counts[tool.get('tool', tool['type'])] += 1
                if protocol == 'B':
                    check(tool['type'] == 'mcp_tool_call' and tool.get('server') == 'memory', f'{call_name}: nonmemory tool')
                    check(tool.get('tool') in (['read_memory'] if qa else ['read_memory', 'write_memory']), f'{call_name}: disallowed tool')
                    check(not tool.get('error') and not (tool.get('result') or {}).get('isError'), f'{call_name}: tool error')
            if protocol == 'B' and not qa:
                check(any(t.get('tool') == 'write_memory' and t.get('status') == 'completed' for t in observed), f'{call_name}: missing successful write')
        rows_path = root/'qa_records.jsonl'
        rows = [json.loads(line) for line in rows_path.read_text().splitlines()] if rows_path.exists() else []
        expected = [(cp.checkpoint_id, q.question, q.gold_answer) for cp in checkpoints for q in cp.questions]
        actual = [(r['checkpoint_id'], r['question'], r['gold_answer']) for r in rows]
        check(actual == expected, 'QA rows do not exactly match ordered dataset checkpoints/questions/gold')
        for row in rows:
            ev = row['evaluation']
            check(ev.get('answer_is_valid') and ev['answer_label'] in ('Correct', 'Hallucination', 'Omission'), 'Invalid judge result')
        for i, cp in enumerate(checkpoints, 1):
            call_name = f'checkpoint_{i}'
            if call_name not in calls:
                continue
            answers = _parse_batch_answer_json(calls[call_name]['answer'], len(cp.questions))
            cp_rows = [r for r in rows if r['checkpoint_id'] == cp.checkpoint_id]
            check([r['generated_answer'] for r in cp_rows] == answers, f'{call_name}: answer/QA mismatch')
            if protocol == 'B':
                before = root/'calls'/cp.covered_sessions[-1]/'memory.after.json'
                after = root/'calls'/call_name/'memory.after.json'
                check(before.read_bytes() == after.read_bytes(), f'{call_name}: QA memory mutated')
        if protocol == 'N' and counts:
            errors.append('N used tools: manual gold/future-access audit required')
        reports.append(dict(protocol=protocol, sample=sample.sample_id, calls=len(calls), qa=len(rows), tool_counts=dict(counts), passed=not errors, errors=errors))
    source_paths = ['scripts/run_codex_protocols.py', 'scripts/wma_memory_server.py', 'scripts/wma_transport.py', 'scripts/summarize_codex_protocols.py', 'scripts/audit_codex_protocols.py', 'eval_framework/memory_adapters/harness_native.py', 'eval_framework/baselines/_clients/harness_api.py']
    result = dict(audited_at=datetime.now(timezone.utc).isoformat(),
                  passed=all(r['passed'] for r in reports), runs=reports, unique_threads=len(all_threads),
                  source_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in source_paths},
                  dataset_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((Path(args.dataset)/'agent'/'gui').rglob('*.json'))})
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
    sys.exit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
