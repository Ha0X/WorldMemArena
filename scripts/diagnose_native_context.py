"""Diagnostic only: compare native checkpoint input with explicit observed history.

Does not modify benchmark prompts, adapter or reported scores. No gold is sent.
"""
import hashlib
import argparse
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import eval_framework
import requests
from eval_framework.config import load_harness_config
from eval_framework.baselines._clients.harness_api import build_harness_target,_call_codex_exec_prompt
from eval_framework.cli import _parse_batch_answer_json
from wma_transport import start_proxy


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tool-probe',action='store_true')
    parser.add_argument('--capture-tools',action='store_true')
    args=parser.parse_args()
    output=ROOT/'exp_log/native_codex_gpt6/context_diagnostic'
    if args.tool_probe:output=output/'tool_probe'
    if args.capture_tools:output=output/'verified'
    output.mkdir(parents=True,exist_ok=True)
    source=ROOT/'exp_log/native_codex_gpt6/excel_01_run3/codex_calls'
    calls=sorted(source.iterdir())
    sessions=[json.loads((p/'args.json').read_text())[-1] for p in calls[:5]]
    qa=json.loads((calls[5]/'args.json').read_text())[-1]
    assert all('--- SESSION' in p for p in sessions) and qa.startswith('Now answer')
    original_post=requests.post
    case=''
    def recorded_post(url,**kwargs):
        payload=json.loads(kwargs['data'])
        inputs=payload.get('input',[])
        users=[x for x in inputs if isinstance(x,dict) and x.get('role')=='user'] if isinstance(inputs,list) else []
        user_text=json.dumps(users,ensure_ascii=False)
        metadata=dict(case=case,model=payload.get('model'),input_items=len(inputs),user_messages=len(users),
                      payload_keys=list(payload),input_roles=[x.get('role',x.get('type')) for x in inputs if isinstance(x,dict)],
                      tool_name_mentions={name:json.dumps(payload).count(name) for name in ['exec_command','shell_command','apply_patch','functions.exec','tool_call']},
                      user_session_markers=user_text.count('--- SESSION'),contains_purchased='Purchased' in user_text,
                      previous_response_id_present=bool(payload.get('previous_response_id')),
                      tool_names=[t.get('name',t.get('type')) for t in payload.get('tools',[])],
                      request_sha256=hashlib.sha256(kwargs['data']).hexdigest())
        with (output/'request_metadata.jsonl').open('a') as f:f.write(json.dumps(metadata)+'\n')
        if args.capture_tools:
            for item in inputs:
                if isinstance(item,dict) and item.get('type') in ['custom_tool_call','custom_tool_call_output','function_call','function_call_output']:
                    with (output/'tool_exchange.jsonl').open('a') as f:f.write(json.dumps(item,ensure_ascii=False)+'\n')
        return original_post(url,**kwargs)
    requests.post=recorded_post
    proxy=start_proxy(output/'transport.jsonl')
    os.environ['WMA_NATIVE_PROXY']=f'http://127.0.0.1:{proxy.server_port}'
    os.environ['WMA_NATIVE_TRACE']=str(output/'calls')
    cfg=load_harness_config()['codex']
    cfg.update(model='gpt-6-astra',api_key='',base_url='https://api.icodeeasy.cc',runner=str(ROOT/'scripts/codex_native_logged.py'))
    target=build_harness_target('Harness-Codex')
    results={}
    try:
        cases=[('tool_probe','Use an available shell tool to run pwd, then report its output. Do not read or modify files. If no shell tool is available, say NO_SHELL_TOOL.')] if args.tool_probe else [('qa_only',qa),('observed_history_plus_qa','\n\n'.join(sessions+[qa]))]
        for case,prompt in cases:
            (output/f'{case}.prompt.txt').write_text(prompt)
            print('Running diagnostic',case,flush=True)
            raw,_=_call_codex_exec_prompt(target,prompt=prompt,image_paths=None,max_images=0,max_image_bytes=0)
            (output/f'{case}.answer.txt').write_text(raw)
            if args.tool_probe:
                print(raw,flush=True)
                continue
            answers=_parse_batch_answer_json(raw,11)
            results[case]=dict(answers=answers,abstentions=answers.count('Not mentioned in memory.'))
            (output/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
            print(case,'first_answer',answers[0],'abstentions',results[case]['abstentions'],flush=True)
    finally:
        proxy.shutdown()
        requests.post=original_post


if __name__=='__main__':main()
