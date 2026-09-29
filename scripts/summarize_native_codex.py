"""Audit and summarize native repository harness outputs without rerunning models."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from statistics import mean
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from eval_framework.datasets.worldmemarena import load_worldmemarena
from eval_framework.memory_adapters.harness_native import _format_session,_BATCH_QA_PROMPT
from eval_framework.cli import _parse_batch_answer_json


def readlines(path):
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def stats(rows):
    counts=Counter(r['eval']['answer_label'] for r in rows)
    return dict(n=len(rows),counts=dict(counts),qa_c=counts['Correct']/len(rows),
                qa_h=counts['Hallucination']/len(rows),qa_o=counts['Omission']/len(rows),
                f1=mean(r['eval']['answer_f1'] for r in rows),bleu1=mean(r['eval']['answer_bleu1'] for r in rows))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('runs',nargs='+');p.add_argument('--output',required=True)
    args=p.parse_args()
    samples={s.sample_id:s for s in load_worldmemarena(ROOT/'.cache/worldmemarena_gui').samples}
    threads=set();runs=[]
    for name in args.runs:
        path=Path(name);manifest=json.loads((path/'manifest.json').read_text())
        assert manifest['status']=='complete',f'Incomplete run {path}'
        rows=readlines(path/'evaluation/qa_records.jsonl');sample=samples[rows[0]['sample_id']]
        expected=[(cp.checkpoint_id,q.question,q.gold_answer) for cp in sample.normalized_checkpoints for q in cp.questions]
        assert [(r['checkpoint_id'],r['question'],r['gold_answer']) for r in rows]==expected
        assert all(r['eval']['answer_is_valid'] for r in rows)
        expected_prompts=[];cp_answers=[]
        order={s.session_id:i for i,s in enumerate(sample.sessions)}
        for session in sample.sessions:
            sid=session.session_id
            expected_prompts.append(f'Here is a new conversation session (Session {sid}). Remember all the details — you will be asked questions about it later.\n\n--- SESSION {sid} ---\n{_format_session(sid,list(session.turns))}\n--- END SESSION ---')
            for cp in sample.normalized_checkpoints:
                if sid==max(cp.covered_sessions,key=order.__getitem__):
                    expected_prompts.append(_BATCH_QA_PROMPT.format(questions_block='\n'.join(f'Q{i}: {q.question}' for i,q in enumerate(cp.questions))))
                    cp_answers.append((len(expected_prompts)-1,cp))
        dirs=sorted((path/'codex_calls').iterdir());assert len(dirs)==len(expected_prompts)
        tool_counts=Counter();answers=[];usage=Counter();seconds=0
        tool_records=[]
        for i,d in enumerate(dirs):
            argv=json.loads((d/'args.json').read_text())
            assert argv[-1]==expected_prompts[i],f'Prompt differs at {d}'
            assert argv[argv.index('--model')+1]=='gpt-6-astra' and '--ephemeral' in argv
            st=json.loads((d/'status.json').read_text());assert st['exit_code']==0 and st['valid_completion']
            seconds+=st['seconds'];events=readlines(d/'events.jsonl')
            ts=[e['thread_id'] for e in events if e['type']=='thread.started'];assert len(ts)==1 and ts[0] not in threads
            threads.update(ts)
            completed=[e for e in events if e['type']=='turn.completed'];assert len(completed)==1 and completed[0]['usage']['input_tokens']>0
            usage.update(completed[0]['usage'])
            messages=[]
            for e in events:
                if e['type']=='item.completed':
                    item=e['item']
                    if item['type']=='agent_message':messages.append(item['text'])
                    elif item['type'] not in ['reasoning','todo_list','error']:
                        tool_counts[item['type']]+=1
                        tool_records.append(dict(call=str(d),item=item))
            assert messages
            answers.append(messages[-1])
        for idx,cp in cp_answers:
            parsed=_parse_batch_answer_json(answers[idx],len(cp.questions))
            assert len(parsed)==len(cp.questions) and all(parsed)
            assert parsed==[r['generated_answer'] for r in rows if r['checkpoint_id']==cp.checkpoint_id]
        by_cp=defaultdict(list);by_type=defaultdict(list)
        for r in rows:by_cp[r['checkpoint_id']].append(r);by_type[r['question_type_abbrev']].append(r)
        api=readlines(path/'judge_api_calls.jsonl')
        runs.append(dict(path=str(path),sample=sample.sample_id,**stats(rows),calls=len(dirs),seconds=seconds,
                         abstentions=sum(r['generated_answer']=='Not mentioned in memory.' for r in rows),
                         correct_abstentions=sum(r['generated_answer']=='Not mentioned in memory.' and r['eval']['answer_label']=='Correct' for r in rows),
                         tool_counts=dict(tool_counts),tool_records=tool_records,
                         audit='record_consistency_passed',
                         tool_access_audit='not_established_from_jsonl_alone',usage=dict(usage),
                         judge_requested=manifest['judge'],judge_response_models=dict(Counter(x.get('response_model','unknown') for x in api if x['status']=='ok')),
                         checkpoints={k:stats(v) for k,v in by_cp.items()},question_types={k:stats(v) for k,v in by_type.items()}))
    metrics=['qa_c','qa_h','qa_o','f1','bleu1'];macro={k:mean(r[k] for r in runs) for k in metrics}
    result=dict(scope='Native repository harness, Codex + gpt-6-astra; available GUI samples only',runs=runs,macro=macro,unique_threads=len(threads),
                interpretation_status='integration_failure_diagnostic_not_model_memory_comparison',
                diagnosis='Checkpoint history handoff absent; separate shell probe failed with bubblewrap permission error. See context_diagnostic.')
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    (output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    lines=['# Codex + GPT-6: native repository harness results','',
           '**Reclassified as integration-failure diagnostics, not valid evidence for model memory ranking.**',
           'Checkpoint inputs lack prior sessions. A separate explicit shell probe failed with a bubblewrap permission error.',
           'CLI JSONL does not expose every custom tool call in this build; no listed tool events cannot certify no tool use.',
           'Repository CLI/pipeline/adapter used. Values are percentages; macro averages give each sample equal weight.',
           'Historical N/B experiments are excluded. Paper row is a broader dataset aggregate, not a matched subset baseline.','',
           '| Sample | QA | QA-C ↑ | QA-H ↓ | QA-O ↓ | F1 ↑ | BLEU-1 ↑ |','|---|---:|---:|---:|---:|---:|---:|']
    for r in runs:lines.append(f'| {r["sample"]} | {r["n"]} | '+' | '.join(f'{100*r[k]:.2f}' for k in metrics)+' |')
    lines.append(f'| Native macro ({len(runs)} samples) | {sum(r["n"] for r in runs)} | '+' | '.join(f'{100*macro[k]:.2f}' for k in metrics)+' |')
    lines+=['| Paper Table 3 Codex–GPT-5.4-nano | — | 53.62 | 20.76 | 25.62 | 32.56 | 10.12 |','',
            f'Validated {len(threads)} distinct threads and all native prompts/QA records against the dataset.',
            'Judge response identifiers: '+json.dumps({r['sample']:r['judge_response_models'] for r in runs})+'.',
            'Judge request is gpt-5.4-mini; provider response labels may differ, so evaluator identity is not established as identical to the paper.',
            'Runtime uses the existing Codex home and /tmp as configured by the repository; no additional memory or tool feature switches.',
            'Transport/auth overrides and JSON logging are recorded in each manifest. Model response identity is provider-reported.',
            'Audit status: '+json.dumps({r['sample']:r['audit'] for r in runs})+'.', '', '## Per-checkpoint results','',
            '| Sample | Checkpoint | QA | QA-C | F1 |','|---|---|---:|---:|---:|']
    for r in runs:
        for cp,s in r['checkpoints'].items():lines.append(f'| {r["sample"]} | {cp} | {s["n"]} | {100*s["qa_c"]:.2f} | {100*s["f1"]:.2f} |')
    lines += ['', '## Abstention diagnostic', '',
              '| Sample | Not mentioned in memory answers | Of these, judged Correct |', '|---|---:|---:|']
    for r in runs:
        lines.append(f'| {r["sample"]} | {r["abstentions"]}/{r["n"]} | {r["correct_abstentions"]} |')
    lines += ['', 'Correct abstentions can reflect questions whose gold states that the information was not captured; they do not demonstrate retained historical facts.']
    (output/'report.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines[:16]))


if __name__=='__main__':main()
