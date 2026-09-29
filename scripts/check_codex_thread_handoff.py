"""Live, benchmark-independent acceptance check for the persistent Codex adapter."""
import json
import argparse
import os
from pathlib import Path
import secrets
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import eval_framework
from eval_framework.config import load_harness_config
from eval_framework.memory_adapters.harness_native import HarnessMemoryAdapter
from wma_transport import start_proxy


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--updates',action='store_true')
    parser.add_argument('--output', help='New output directory; existing nonempty directories are rejected')
    args=parser.parse_args()
    root=ROOT/'exp_log/codex_persistent/handoff_check'
    if args.updates:root=ROOT/'exp_log/codex_persistent/handoff_update_check'
    if args.output:root=Path(args.output).resolve()
    if root.exists() and any(root.iterdir()):
        raise RuntimeError(f'Refusing to overwrite prior acceptance logs: {root}')
    root.mkdir(parents=True,exist_ok=True)
    proxy=start_proxy(root/'transport.jsonl',root/'request_audit.jsonl')
    os.environ['WMA_NATIVE_PROXY']=f'http://127.0.0.1:{proxy.server_port}'
    os.environ['WMA_NATIVE_TRACE']=str(root/'calls')
    cfg=load_harness_config()['codex']
    cfg.update(model='gpt-6-astra',api_key='',base_url='https://api.icodeeasy.cc',
               runner=str(ROOT/'scripts/codex_native_logged.py'),codex_persistent_session=True)
    adapter=HarnessMemoryAdapter(baseline_name='Harness-Codex')
    fact='WMA_'+secrets.token_hex(12)
    try:
        adapter.reset()
        adapter._send_message('This is a synthetic memory transport check. The code for parcel Cedar is '+fact+'. Remember it for the next message. No file or tool use is needed.')
        first=adapter._codex_thread_state['thread_id']
        answer=adapter._send_message('What is the code for parcel Cedar? Reply with only the code if you know it, otherwise UNKNOWN. Do not use tools.')
        same=adapter._codex_thread_state['thread_id']==first
        update_result=None
        if args.updates:
            revised='WMA_'+secrets.token_hex(12)
            adapter._send_message('Update: parcel Cedar now uses code '+revised+'. Its previous code is obsolete. Remember the current code. Do not use tools.')
            current=adapter._send_message('What is the current code for parcel Cedar? Reply only with the code. Do not use tools.')
            after_qa=adapter._send_message('Without changing the state, repeat the current code for parcel Cedar. Reply only with the code. Do not use tools.')
            update_result=dict(expected=revised,current=current,after_qa=after_qa,
                               same_thread=adapter._codex_thread_state['thread_id']==first)
        adapter.reset()
        reset_empty=not adapter._codex_thread_state
        fresh=adapter._send_message('What is the code for parcel Cedar? Reply with only the code if it was provided in this conversation, otherwise UNKNOWN. Do not use tools.')
        second=adapter._codex_thread_state['thread_id']
        result=dict(passed=answer.strip()==fact and same and reset_empty and second!=first and fresh.strip()=='UNKNOWN',
                    expected=fact,resumed_answer=answer,new_sample_answer=fresh,
                    first_thread=first,second_thread=second,same_thread_on_resume=same,reset_empty=reset_empty)
        if update_result:
            result['update']=update_result
            result['passed'] &= current.strip()==revised and after_qa.strip()==revised and update_result['same_thread']
        (root/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2),flush=True)
        assert result['passed'],result
    finally:proxy.shutdown()


if __name__=='__main__':main()
