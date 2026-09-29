"""Strict input/state/isolation audit and paper-metric report for completed samples."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from statistics import mean
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from eval_framework.datasets.worldmemarena import load_worldmemarena
from eval_framework.memory_adapters.harness_native import _format_session, _BATCH_QA_PROMPT
from eval_framework.cli import _parse_batch_answer_json
from summarize_native_codex import stats, readlines

METRICS = ['qa_c', 'qa_h', 'qa_o', 'f1', 'bleu1']
PAPER = dict(qa_c=.5362, qa_h=.2076, qa_o=.2562, f1=.3256, bleu1=.1012)


def audit(path, samples):
    manifest = json.loads((path/'manifest.json').read_text())
    assert manifest['status'] == 'complete', f'Incomplete: {path}'
    assert manifest['protocol'] == 'persistent_thread_local_repair'
    assert manifest['isolation']['external_sandbox']
    for source, digest in manifest['source_hashes'].items():
        assert hashlib.sha256((ROOT/source).read_bytes()).hexdigest() == digest, f'Source drift: {source}'
    rows = readlines(path/'evaluation/qa_records.jsonl')
    sample = samples[rows[0]['sample_id']]
    expected = [(cp.checkpoint_id, q.question, q.gold_answer) for cp in sample.normalized_checkpoints for q in cp.questions]
    assert [(r['checkpoint_id'], r['question'], r['gold_answer']) for r in rows] == expected
    assert all(r['sample_id'] == sample.sample_id and r['eval']['answer_is_valid'] for r in rows)
    assert all(r['eval']['answer_label'] in ('Correct', 'Hallucination', 'Omission') for r in rows)
    prompts, cp_answers, expected_files, expected_gate = [], [], [], []
    allowed = set()
    order = {s.session_id:i for i,s in enumerate(sample.sessions)}
    for session in sample.sessions:
        sid = session.session_id
        current = [str(Path(a.file_path).resolve()) for turn in session.turns for a in turn.attachments if a.file_path]
        allowed.update(current)
        expected_gate.append(dict(session_id=sid, current=current, allowed=sorted(allowed)))
        prompts.append(f'Here is a new conversation session (Session {sid}). Remember all the details — you will be asked questions about it later.\n\n--- SESSION {sid} ---\n{_format_session(sid,list(session.turns))}\n--- END SESSION ---')
        expected_files.append(sorted(allowed))
        for cp in sample.normalized_checkpoints:
            if sid == max(cp.covered_sessions, key=order.__getitem__):
                prompts.append(_BATCH_QA_PROMPT.format(questions_block='\n'.join(f'Q{i}: {q.question}' for i,q in enumerate(cp.questions))))
                expected_files.append(sorted(allowed))
                cp_answers.append((len(prompts)-1,cp))
    assert readlines(path/'attachment_gate.jsonl') == expected_gate, 'Attachment timing mismatch'
    calls = sorted((path/'codex_calls').iterdir())
    assert len(calls) == len(prompts), f'Unexpected call count: {len(calls)} vs {len(prompts)}'
    threads = set()
    usage, cli_tools = {}, Counter()
    per_call_usage = []
    answers, tool_records, warnings = [], [], []
    seconds = 0
    first_thread = None
    for i, folder in enumerate(calls):
        argv = json.loads((folder/'args.json').read_text())
        assert argv[-1] == prompts[i], f'Prompt drift: {folder}'
        assert argv[argv.index('--model')+1] == 'gpt-6-astra'
        assert '--ephemeral' not in argv and '--image' not in argv
        if i:
            assert argv[argv.index('exec')+1] == 'resume' and argv[-2] == first_thread
        else:
            assert argv[argv.index('exec')+1] != 'resume'
        isolation = json.loads((folder/'isolation.json').read_text())
        assert isolation['outer_enforced'] and isolation['root'] == manifest['isolation']['root']
        assert isolation['read_files'] == expected_files[i], f'Future/unexpected input access: {folder}'
        status = json.loads((folder/'status.json').read_text())
        assert status['exit_code'] == 0 and status['valid_completion']
        seconds += status['seconds']
        stderr = (folder/'stderr.txt').read_text()
        assert 'rollout writer failed' not in stderr, f'History persistence failure: {folder}'
        warnings.extend(line for line in stderr.splitlines() if 'ERROR' in line or 'WARN' in line)
        events = readlines(folder/'events.jsonl')
        started = [e['thread_id'] for e in events if e['type'] == 'thread.started']
        assert len(started) == 1
        if first_thread is None:
            first_thread = started[0]
        threads.update(started)
        completed = [e for e in events if e['type'] == 'turn.completed']
        assert len(completed) == 1 and completed[0]['usage']['input_tokens'] > 0
        # Codex 0.158 resume emits cumulative thread usage, not per-call usage.
        snapshot = completed[0]['usage']
        assert all(value >= usage.get(key, 0) for key,value in snapshot.items()), 'Usage counter reset needs inspection'
        per_call_usage.append({key:value-usage.get(key,0) for key,value in snapshot.items()})
        usage = dict(snapshot)
        messages = []
        for event in events:
            if event['type'] == 'item.completed':
                item = event['item']
                if item['type'] == 'agent_message':
                    messages.append(item['text'])
                elif item['type'] not in ('reasoning', 'todo_list', 'error'):
                    cli_tools[item['type']] += 1
                    tool_records.append(dict(call_index=i, item=item))
        assert messages, f'No final message: {folder}'
        answers.append(messages[-1])
    assert len(threads) == 1, 'Sample contains multiple threads'
    for index, cp in cp_answers:
        parsed = _parse_batch_answer_json(answers[index], len(cp.questions))
        assert len(parsed) == len(cp.questions) and all(parsed)
        assert parsed == [r['generated_answer'] for r in rows if r['checkpoint_id'] == cp.checkpoint_id]
    by_cp, by_type = defaultdict(list), defaultdict(list)
    for row in rows:
        by_cp[row['checkpoint_id']].append(row)
        by_type[row['question_type_abbrev']].append(row)
    audit_requests = readlines(path/'request_audit.jsonl')
    assert all(r['model'] == 'gpt-6-astra' for r in audit_requests)
    unique = {}
    for request in audit_requests:
        for item in request['tool_exchanges']:
            unique.setdefault(json.dumps(item,sort_keys=True), item)
    exchanges = list(unique.values())
    judge = readlines(path/'judge_api_calls.jsonl')
    assert not any(r['status'] != 'ok' for r in judge), 'Judge request errors require inspection'
    root = Path(manifest['isolation']['root'])
    state = path/'state_snapshot' if (path/'state_snapshot').exists() else root
    rollout_events = [e for f in (state/'home/.codex/sessions').rglob('*.jsonl') for e in readlines(f)]
    token_info = [e['payload']['info'] for e in rollout_events if e.get('type')=='event_msg'
                  and e.get('payload',{}).get('type')=='token_count' and e['payload'].get('info')]
    assert token_info, 'Missing persistent usage evidence'
    assert all(token_info[-1]['total_token_usage'][k] == v for k,v in usage.items()), 'CLI/rollout cumulative usage mismatch'
    result = dict(path=str(path), sample=sample.sample_id, **stats(rows),
        calls=len(calls), thread_id=first_thread, isolated_root=str(root), host_uid=root.stat().st_uid,
        seconds=seconds, usage=usage, per_call_usage=per_call_usage,
        usage_semantics='Final cumulative thread usage, checked against rollout total_token_usage; not a sum of cumulative snapshots',
        observed_model_context_window=token_info[-1].get('model_context_window'), image_files=len(allowed),
        abstentions=sum(r['generated_answer'].strip() == 'Not mentioned in memory.' for r in rows),
        correct_abstentions=sum(r['generated_answer'].strip() == 'Not mentioned in memory.' and r['eval']['answer_label']=='Correct' for r in rows),
        cli_tool_counts=dict(cli_tools), tool_records=tool_records, request_count=len(audit_requests),
        transport_tool_item_counts=dict(Counter(e['type'] for e in exchanges)),
        transport_tool_exchanges=exchanges, runtime_warning_counts=dict(Counter(w.split(' ERROR ')[-1].split(': ')[0] for w in warnings)),
        judge_requested=manifest['judge'], judge_response_models=dict(Counter(x.get('response_model','unknown') for x in judge)),
        audit='passed: complete QA, exact native prompts/order, one thread, exact resume IDs, staged attachment access, valid calls, no rollout write errors',
        checkpoints={k:stats(v) for k,v in by_cp.items()}, question_types={k:stats(v) for k,v in by_type.items()})
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('runs', nargs='+')
    p.add_argument('--output', required=True)
    args = p.parse_args()
    samples = {s.sample_id:s for s in load_worldmemarena(ROOT/'.cache/worldmemarena_gui').samples}
    runs = [audit(Path(path),samples) for path in args.runs]
    for field in ('sample', 'thread_id', 'isolated_root', 'host_uid'):
        assert len({r[field] for r in runs}) == len(runs), f'Shared sample state: {field}'
    macro = {k:mean(r[k] for r in runs) for k in METRICS}
    result = dict(scope='GUI subset; persistent-thread local adapter repair, external isolation',
        model='Codex CLI 0.158.0 + gpt-6-astra (requested model identifier)',
        dataset_revision='e2148757921fc7e2d66d8ed899823b763227c341',
        runs=runs, macro=macro, paper_reference=PAPER,
        comparable='Same repository QA metrics and per-sample macro averaging; different backbone, judge identity, dataset scope and unverified author runtime')
    output = Path(args.output)
    output.mkdir(parents=True,exist_ok=True)
    (output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    lines = ['# Codex + GPT-6：持续 thread、隔离运行的 GUI 子集结果', '',
        '通过仓库真实 CLI / pipeline / native harness adapter；保留 session 与 QA 提示词。数值为百分数，跨样本使用宏平均。',
        '这是本地适配后的完整子集结果，不是旧 N/B，也不是断开历史的原生故障诊断。', '',
        '| 方法 / 样本 | QA 数 | QA-C ↑ | QA-H ↓ | QA-O ↓ | F1 ↑ | BLEU-1 ↑ |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for r in runs:
        lines.append(f'| {r["sample"]} | {r["n"]} | '+' | '.join(f'{100*r[k]:.2f}' for k in METRICS)+' |')
    lines.append(f'| 本地宏平均（{len(runs)} 个 GUI 样本） | {sum(r["n"] for r in runs)} | '+' | '.join(f'{100*macro[k]:.2f}' for k in METRICS)+' |')
    lines += ['| 论文 Table 3 Codex–GPT-5.4-nano（更广数据范围） | — | 53.62 | 20.76 | 25.62 | 32.56 | 10.12 |', '',
        '## 可比范围', '',
        '- 对齐论文 harness 范式：顺序输入多 session，阶段性 QA，沿用仓库 QA-C/H/O、F1、BLEU-1 与样本宏平均。Gold 留在评分端。',
        '- 本地仅所列 GUI 样本各一次运行；论文表是更广的评测集合。没有同子集官方预测，不能把差值解释为 GPT-6 的能力提升/下降，也不作显著性结论。',
        '- 被测 backbone 固定 gpt-6-astra；论文行名是 GPT-5.4-nano（正文另写 GPT-5.4）。当前报告保留表格名称。',
        '- Judge 请求 gpt-5.4-mini，实际返回标识见下表；其身份不宣称与论文相同。F1/BLEU-1 是程序计算。',
        '- Excel 两例定性抽查发现：judge 将 gold/evidence 未涵盖、但已见轨迹实际存在的细节判为 Hallucination。主表保留原始评分，未人工改分；见 [抽查证据](../excel_01/judge_spotcheck.md)。该检查不代表所有错误标签都有问题。',
        '- 每样本一个精确 resume 的 thread，QA/答案进入后续历史，不输入 gold。该策略是用户接受的本地适配，作者确切持久化实现未确认。',
        '- 原生 adapter 提供 caption 与图片路径，不主动附图。本地按 session 到达开放精确图片文件，工具可自行读取；没有开放未来图片或整个数据目录。',
        '- 使用独立工作目录/CODEX_HOME/数字 UID 及外层隔离，替代容器内不可用的 bubblewrap。额外自定义 memory MCP、固定 JSON 记忆、手工历史拼接均未加入。',
        '- 未评估 memory-writing / retrieval 等生命周期指标，不填零。', '', '## 审计与运行', '',
        '| 样本 | 调用数 | 请求数 | 同 thread | 可读图片 | Judge 返回标识 |', '|---|---:|---:|---|---:|---|']
    for r in runs:
        lines.append(f'| {r["sample"]} | {r["calls"]} | {r["request_count"]} | 是 | {r["image_files"]} | {json.dumps(r["judge_response_models"])} |')
    if all(not r['cli_tool_counts'] and not r['transport_tool_item_counts'] for r in runs):
        lines += ['', '本轮正式样本均未观察到主动工具调用（CLI 与实际请求审计均为空）。工具能力由独立验收证明可用；本轮分数主要反映持续上下文路径，不能据此声称已评估自主磁盘记忆管理的效果。']
    if any(r['runtime_warning_counts'] for r in runs):
        lines += ['', '保留运行日志告警：'+json.dumps({r['sample']:r['runtime_warning_counts'] for r in runs if r['runtime_warning_counts']},ensure_ascii=False)+'。文件管理日志为 OutputTextDelta without active item；各次调用仍有有效 completion，全部 QA 最终答案与评分记录一致，未发现 rollout 写入失败。']
    lines += ['', '审计检查逐项原生提示词/输入顺序、全部 QA/gold 对应关系、有效 completion、精确 thread ID、样本间隔离、每次调用的图片白名单，以及 QA 原始回复与评分记录一致性。',
        '工具使用同时保留 CLI 事件和去重后的实际请求工具交换，二者不相加。Codex resume 的 token usage 是 thread 累计值，本报告取最后累计值并与持久化 rollout 核对，不将每次累计快照重复相加。具体工具、token、耗时和运行 warning 见 results.json。', '',
        '## 每个 checkpoint', '', '| 样本 | checkpoint | QA 数 | QA-C | F1 |', '|---|---|---:|---:|---:|']
    for r in runs:
        for cp,s in r['checkpoints'].items():
            lines.append(f'| {r["sample"]} | {cp} | {s["n"]} | {100*s["qa_c"]:.2f} | {100*s["f1"]:.2f} |')
    (output/'report.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines[:12+len(runs)]))


if __name__ == '__main__':
    main()
