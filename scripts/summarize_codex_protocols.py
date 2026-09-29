"""Build a sample-macro report from completed, audited Codex protocol runs."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from statistics import mean


def stats(rows):
    labels = Counter(r['evaluation']['answer_label'] for r in rows)
    n = len(rows)
    return dict(n=n, correct=labels['Correct'], hallucination=labels['Hallucination'], omission=labels['Omission'],
                accuracy=labels['Correct']/n if n else 0,
                f1=mean(r['evaluation']['answer_f1'] for r in rows) if rows else 0,
                bleu1=mean(r['evaluation']['answer_bleu1'] for r in rows) if rows else 0)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('runs', nargs='+')
    p.add_argument('--output', default='exp_log/codex_gui_report')
    args = p.parse_args()
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    runs=[]
    lines=['# GPT-6 + Codex GUI results', '',
           'N = native session/QA prompts, ephemeral CLI, shell/file/image tools and a shared per-sample workspace.',
           'A = native session/QA prompts with ephemeral CLI and no explicit memory transfer, in a restricted tool environment.',
           'B = fresh contexts with controlled persistent JSON memory; current-session images supplied at ingestion.',
           'Judge: gpt-6-astra. Metrics reuse repository judge, F1 and BLEU-1. Values below are percentages.', '',
           '| Protocol | Sample | QA | Correct | Hallucination | Omission | QA-C | F1 | BLEU-1 |',
           '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    seen=set()
    for name in args.runs:
        root=Path(name);manifest=json.loads((root/'manifest.json').read_text())
        key=(manifest['protocol'],manifest['sample'])
        if key in seen: raise ValueError(f'Duplicate run: {key}')
        seen.add(key)
        rows=[json.loads(line) for line in (root/'qa_records.jsonl').read_text().splitlines()]
        s=stats(rows)
        calls=[json.loads(f.read_text()) for f in (root/'calls').glob('*/result.json')]
        threads=[t for c in calls for t in c['thread_ids']]
        if len(threads)!=len(set(threads)): raise ValueError('Thread reused')
        by_cp=defaultdict(list);by_type=defaultdict(list)
        for r in rows:
            by_cp[r['checkpoint_id']].append(r);by_type[r['question_type_abbrev']].append(r)
        run=dict(protocol=key[0],sample=key[1],path=str(root),**s,
                 complete=len(by_cp)==manifest['max_checkpoints'],
                 calls=len(calls),call_seconds=sum(c['seconds'] for c in calls),
                 input_tokens=sum(c['usage'].get('input_tokens',0) for c in calls),
                 cached_input_tokens=sum(c['usage'].get('cached_input_tokens',0) for c in calls),
                 output_tokens=sum(c['usage'].get('output_tokens',0) for c in calls),
                 judge_tokens=sum(r['evaluation'].get('judge_token_usage',{}).get('total_tokens',0) for r in rows),
                 failures=len(list((root/'calls').glob('*/failure.*.json'))),
                 checkpoints={k:stats(v) for k,v in by_cp.items()},
                 question_types={k:stats(v) for k,v in by_type.items()})
        run['memory_bytes']={f.parent.name:f.stat().st_size for f in sorted((root/'calls').glob('S*/memory.after.json'),key=lambda f:int(f.parent.name[1:]))}
        runs.append(run)
        lines.append(f'| {key[0]} | {key[1]} | {s["n"]} | {s["correct"]} | {s["hallucination"]} | {s["omission"]} | {s["accuracy"]*100:.2f} | {s["f1"]*100:.2f} | {s["bleu1"]*100:.2f} |')
    macros={}
    lines += ['', '## Paper reference (not a matched comparison)', '',
              '| Method / scope | QA-C | QA-H | QA-O | F1 | BLEU-1 |',
              '|---|---:|---:|---:|---:|---:|',
              '| Paper Table 3 Codex–GPT-5.4-nano, cross-domain aggregate | 53.62 | 20.76 | 25.62 | 32.56 | 10.12 |']
    for protocol in sorted({r['protocol'] for r in runs}):
        group=[r for r in runs if r['protocol']==protocol]
        macro=dict(accuracy=mean(r['accuracy'] for r in group),f1=mean(r['f1'] for r in group),
                   bleu1=mean(r['bleu1'] for r in group),
                   hallucination=mean(r['hallucination']/r['n'] for r in group),
                   omission=mean(r['omission']/r['n'] for r in group))
        macros[protocol]=macro
        lines.append(f'| Local {protocol}, {len(group)} GUI sample macro mean | {100*macro["accuracy"]:.2f} | {100*macro["hallucination"]:.2f} | {100*macro["omission"]:.2f} | {100*macro["f1"]:.2f} | {100*macro["bleu1"]:.2f} |')
    lines += ['', 'Differences: dataset scope, backbone, judge, CLI version, reasoning budget, tool restrictions, and visual input.',
              'These numbers do not establish improvement over the paper. N/B changes memory transfer and explicit image input.',
              'A is an additional no-carry control with file tools disabled; it is not the native baseline.',
              'B stores textual/structured memory about images; it does not retain original screenshot pixels.',
              'Tool events are audited; this is an input/tool boundary, not an OS-level adversarial sandbox proof.',
              'Successful-call token totals exclude failed attempts, which remain in raw logs.', '', '## Per-checkpoint QA', '',
              '| Protocol | Sample | Checkpoint | QA | QA-C | F1 |', '|---|---|---|---:|---:|---:|']
    for r in runs:
        for cp,s in r['checkpoints'].items():
            lines.append(f'| {r["protocol"]} | {r["sample"]} | {cp} | {s["n"]} | {100*s["accuracy"]:.2f} | {100*s["f1"]:.2f} |')
    if not all(r['complete'] for r in runs):
        lines.insert(2, '**PARTIAL: at least one run has unfinished checkpoints.**')
    lines += ['', '## Calls and token usage', '',
              '| Protocol | Sample | Calls | Call seconds | Input tokens | Cached input tokens | Output tokens | Judge tokens | Failed attempts |',
              '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in runs:
        lines.append(f'| {r["protocol"]} | {r["sample"]} | {r["calls"]} | {r["call_seconds"]:.1f} | {r["input_tokens"]} | {r["cached_input_tokens"]} | {r["output_tokens"]} | {r["judge_tokens"]} | {r["failures"]} |')
    lines += ['', '## Per-question-type QA', '',
              '| Protocol | Sample | Type | QA | QA-C | F1 |', '|---|---|---|---:|---:|---:|']
    for r in runs:
        for typ,s in r['question_types'].items():
            lines.append(f'| {r["protocol"]} | {r["sample"]} | {typ} | {s["n"]} | {100*s["accuracy"]:.2f} | {100*s["f1"]:.2f} |')
    lines += ['', '## External memory footprint', '',
              'Byte counts describe stored JSON, not semantic quality. Full session series are in results.json.', '',
              '| Protocol | Sample | Final bytes | Maximum bytes | Decreases greater than 50% |',
              '|---|---|---:|---:|---|']
    for r in runs:
        sizes=list(r['memory_bytes'].items())
        if sizes:
            drops=[f'{sid0} → {sid1}: {n0} → {n1}' for (sid0,n0),(sid1,n1) in zip(sizes,sizes[1:]) if n1<n0/2]
            lines.append(f'| {r["protocol"]} | {r["sample"]} | {sizes[-1][1]} | {max(n for _,n in sizes)} | {"; ".join(drops) or "None"} |')
    (output/'report.md').write_text('\n'.join(lines)+'\n')
    (output/'results.json').write_text(json.dumps(dict(runs=runs,macro=macros),indent=2)+'\n')
    print('\n'.join(lines[:18]))


if __name__=='__main__': main()
