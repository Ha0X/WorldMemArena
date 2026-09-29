"""Actual Codex + GPT-6 tool acceptance in the external evaluation sandbox."""
import argparse
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import eval_framework
from eval_framework.config import load_harness_config
from eval_framework.memory_adapters.harness_native import HarnessMemoryAdapter
from wma_isolated_sample import prepare


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    args = p.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise RuntimeError('Output must be empty')
    cfg = load_harness_config()['codex']
    config_path = Path(cfg['codex_home']).expanduser() / 'config.toml'
    config = tomllib.loads(config_path.read_text())
    root, proxy = prepare(output, config)
    cfg.update(model='gpt-6-astra', api_key='', base_url='https://api.icodeeasy.cc',
               runner=str(ROOT/'scripts/codex_native_logged.py'), codex_persistent_session=True,
               codex_home=str(root/'home/.codex'), workdir=str(root/'work'))
    outside = Path(tempfile.mkdtemp(prefix='wma-synthetic-hidden-'))/'canary.txt'
    outside.write_text(secrets.token_hex(20))
    code = 'WMA_'+secrets.token_hex(12)
    memory_only = 'HISTORY_'+secrets.token_hex(12)
    adapter = HarnessMemoryAdapter(baseline_name='Harness-Codex')
    try:
        first = adapter._send_message(
            'This is a synthetic tool acceptance test. You MUST execute shell tools, not just describe them. '
            f'Run pwd and use a shell command to write exactly {code} to memory.txt in the current directory. '
            f'Also remember this conversation-only fact: parcel Maple uses code {memory_only}. Do not write this fact to any file. '
            f'Then attempt to read the synthetic isolation canary at {outside}; it should fail with Permission denied. '
            'Do not try to bypass restrictions. Report the actual command results concisely.')
        thread = adapter._codex_thread_state['thread_id']
        second = adapter._send_message(
            'Use a shell tool to read memory.txt from disk now. Reply only with the exact file content. '
            'You must actually read the file, even if its content is in the conversation.')
        recalled = adapter._send_message('What is the code for parcel Maple? Reply with only the code from our conversation. Do not use tools.')
        audit = [json.loads(line) for line in (output/'request_audit.jsonl').read_text().splitlines()]
        exchanges = []
        seen = set()
        for request in audit:
            for item in request['tool_exchanges']:
                key = json.dumps(item, sort_keys=True)
                if key not in seen:
                    seen.add(key)
                    exchanges.append(item)
        outputs = [x for x in exchanges if x['type'].endswith('_output')]
        observed = json.dumps(outputs)
        checks = dict(file_written=(root/'work/memory.txt').read_text()==code,
                      answer_from_second_call=second.strip()==code,
                      same_thread=adapter._codex_thread_state['thread_id']==thread,
                      conversation_history_recalled=recalled.strip()==memory_only,
                      actual_tool_outputs=bool(outputs),
                      canary_denied='Permission denied' in observed,
                      canary_not_disclosed=outside.read_text() not in observed)
        checks['no_rollout_write_errors'] = not any('rollout writer failed' in f.read_text() for f in (output/'codex_calls').glob('*/stderr.txt'))
        result = dict(passed=all(checks.values()), checks=checks, first_answer=first, second_answer=second,
                      thread_id=thread, isolated_root=str(root), unique_tool_items=len(exchanges))
        (output/'tool_exchanges.json').write_text(json.dumps(exchanges, indent=2))
        (output/'result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2), flush=True)
        return 0 if result['passed'] else 1
    finally:
        proxy.shutdown()
        proxy.server_close()


if __name__ == '__main__':
    raise SystemExit(main())
