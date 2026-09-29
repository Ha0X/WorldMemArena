"""Configure model/transport and invoke the repository CLI evaluation.

The optional persistent-session mode enables the explicitly documented local repair.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import eval_framework
from eval_framework.config import load_harness_config, resolve_judge_model
from eval_framework.baselines._clients.harness_api import build_harness_target
from wma_transport import start_proxy


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sample-index',type=int,default=1)
    p.add_argument('--output',required=True)
    p.add_argument('--judge',default='gpt-5.4-mini')
    p.add_argument('--dataset',default='.cache/worldmemarena_gui')
    p.add_argument('--dry-run',action='store_true')
    p.add_argument('--persistent-session',action='store_true',help='Local adapter repair: one resumed thread per sample')
    p.add_argument('--isolated',action='store_true',help='External Landlock/seccomp/namespace sandbox; requires persistent-session')
    p.add_argument('--max-sessions',type=int)
    args=p.parse_args()
    if args.isolated and not args.persistent_session:
        p.error('--isolated requires --persistent-session')
    output=Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f'Output directory must be empty to avoid mixing thread traces: {output}')
    output.mkdir(parents=True,exist_ok=True)
    os.environ['OPENAI_MODEL_JUDGE']=args.judge
    os.environ['EVAL_API_CALL_LOG']=str(output/'judge_api_calls.jsonl')
    os.environ['WMA_NATIVE_TRACE']=str(output/'codex_calls')
    cfg=load_harness_config()['codex']
    original={k:v for k,v in cfg.items() if k!='api_key'}
    c=tomllib.loads((Path(cfg['codex_home']).expanduser()/'config.toml').read_text())
    if args.isolated:
        from wma_isolated_sample import prepare, install_attachment_gate
        isolated_root, proxy = prepare(output, c)
        cfg.update(workdir=str(isolated_root/'work'), codex_home=str(isolated_root/'home/.codex'))
        install_attachment_gate(output, args.dataset)
    else:
        proxy=start_proxy(output/'transport.jsonl',output/'request_audit.jsonl')
        os.environ['WMA_NATIVE_PROXY']=f'http://127.0.0.1:{proxy.server_port}'
    # Change only target model, connection settings and logging/transport executable.
    cfg.update(model='gpt-6-astra', api_key='', base_url='https://api.icodeeasy.cc',
               runner=str(ROOT/'scripts/codex_native_logged.py'))
    if args.persistent_session:
        cfg['codex_persistent_session']=True
        if not args.isolated:
            cfg['workdir']=tempfile.mkdtemp(prefix='wma-persistent-sample-')
    target=build_harness_target('Harness-Codex')
    effective={k:str(v) if isinstance(v,Path) else v for k,v in asdict(target).items() if k!='api_key'}
    if c.get('model_provider')!='icodeeasy':
        raise RuntimeError('Expected existing icodeeasy provider in native CODEX_HOME')
    selected={k:c[k] for k in ['model','model_provider','model_reasoning_effort','features','memories','sandbox_mode','approval_policy'] if k in c}
    cli_args=['--dataset',args.dataset,'--dataset-type','worldmemarena','--baseline','Harness-Codex',
              '--sample-index',str(args.sample_index),'--output-dir',str(output/'evaluation'),'--max-eval-workers','5']
    if args.max_sessions:
        cli_args += ['--max-sessions',str(args.max_sessions)]
    sources=['eval_framework/cli.py','eval_framework/pipeline/runner.py','eval_framework/pipeline/qa_runner.py',
             'eval_framework/memory_adapters/harness_native.py','eval_framework/baselines/_clients/harness_api.py','eval_framework/openai_compat.py',
             'scripts/run_native_codex_gpt6.py','scripts/codex_native_logged.py','scripts/wma_transport.py']
    if args.isolated:
        sources += ['scripts/wma_isolation.py','scripts/wma_isolated_sample.py']
    manifest=dict(status='prepared',original_harness=original,effective_harness=effective,
                  inherited_codex_settings=selected,host_mcp_names=list(c.get('mcp_servers',{})),
                  judge=resolve_judge_model(),cli_args=cli_args,
                  codex_version=subprocess.check_output(['codex','--version'],text=True).strip(),
                  git_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                  source_hashes={s:hashlib.sha256((ROOT/s).read_bytes()).hexdigest() for s in sources},
                  overrides=['model gpt-6-astra','provider/auth via existing home and inherited environment',
                             'localhost transport; disable request compression','JSON trace output; evaluator workers=5'],
                  no_protocol_changes=not args.persistent_session,
                  protocol='persistent_thread_local_repair' if args.persistent_session else 'repository_native')
    if args.persistent_session:
        manifest['overrides'] += ['Persistent thread instead of ephemeral calls; reset per sample',
                                  'Fresh per-run sample workspace under /tmp']
    if args.isolated:
        manifest['isolation'] = dict(profile='landlock_seccomp_namespaces_v1', root=str(isolated_root),
            inner_sandbox='danger-full-access', external_sandbox=True,
            image_access='Only exact attachment files from already delivered sessions; no added image input',
            credentials='Real API key retained in external proxy; placeholder only inside')
        manifest['overrides'][1] = 'Provider via external credential-holding proxy; sanitized environment'
        manifest['overrides'] += ['Fresh CODEX_HOME; copied reasoning effort/personality only; no host history/MCP/hooks',
                                  'Landlock + seccomp + user/net/PID/IPC/UTS namespaces replaces unavailable bwrap']
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'model':target.model,'judge':resolve_judge_model(),'workdir':str(target.workdir),
                      'codex_home':str(target.codex_home),'ephemeral':target.ephemeral,'output':str(output)},indent=2),flush=True)
    from eval_framework.cli import main as repository_main
    try:
        repository_main(cli_args+(['--dry-run'] if args.dry_run else []))
        manifest['status']='dry_run_passed' if args.dry_run else 'complete'
    except BaseException:
        manifest['status']='failed'
        raise
    finally:
        (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        proxy.shutdown()
        proxy.server_close()


if __name__=='__main__':
    main()
