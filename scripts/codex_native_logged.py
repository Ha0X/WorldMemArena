#!/usr/bin/env python3
"""Transparent Codex transport/log wrapper for the repository native harness."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from wma_isolation import CODEX_BINARY, clean_env, command


def main():
    root = Path(os.environ['WMA_NATIVE_TRACE'])
    folder = root / (str(time.time_ns()) + '-' + uuid.uuid4().hex[:6])
    folder.mkdir(parents=True)
    args = sys.argv[1:]
    isolated_root = os.environ.get('WMA_ISOLATION_ROOT')
    if not isolated_root and 'danger-full-access' in args:
        raise RuntimeError('Unrestricted inner mode requires the external isolation launcher')
    (folder/'args.json').write_text(json.dumps(args, ensure_ascii=False, indent=2))
    transport = ['-c', 'model_providers.icodeeasy.base_url='+json.dumps(os.environ['WMA_NATIVE_PROXY']),
           '-c', 'model_providers.icodeeasy.requires_openai_auth=false',
           '-c', 'model_providers.icodeeasy.env_key="OPENAI_API_KEY"',
           '-c', 'features.enable_request_compression=false']
    cmd = ['/usr/local/bin/codex', *args]
    # Output formatting only; preserve native last-message file and exec arguments.
    idx = cmd.index('exec')
    insertion = idx+2 if cmd[idx+1:idx+2] == ['resume'] else idx+1
    cmd[insertion:insertion] = ([] if '--json' in args else ['--json']) + transport
    if isolated_root:
        output_file = Path(args[args.index('--output-last-message')+1]).resolve(strict=True)
        if not output_file.is_relative_to(Path(isolated_root)/'work'):
            raise RuntimeError('Last-message file must belong to isolated workspace')
        uid = Path(isolated_root).stat().st_uid
        os.chown(output_file, uid, uid)
        # The outer restrictions apply to the CLI and all of its descendants.
        # Inner bwrap is unavailable in this container; never use this mode alone.
        for i, arg in enumerate(cmd[:-1]):
            if arg == '--sandbox':
                cmd[i+1] = 'danger-full-access'
            elif arg in ('--config', '-c') and cmd[i+1].startswith('sandbox_mode='):
                cmd[i+1] = 'sandbox_mode="danger-full-access"'
        cmd[0] = str(CODEX_BINARY)
        read_files = json.loads(os.environ.get('WMA_ISOLATION_READ_FILES', '[]'))
        cmd = command(isolated_root, os.environ['WMA_ISOLATION_BRIDGE'], cmd, read_files)
        (folder/'isolation.json').write_text(json.dumps({'profile':'landlock_seccomp_namespaces_v1',
            'root':isolated_root, 'inner_sandbox':'danger-full-access', 'outer_enforced':True,
            'read_files':read_files}))
    started = time.monotonic()
    with (folder/'events.jsonl').open('w') as out, (folder/'stderr.txt').open('w') as err:
        env = dict(os.environ)
        env['OPENAI_BASE_URL'] = env['WMA_NATIVE_PROXY']
        env['OPENAI_API_BASE'] = env['WMA_NATIVE_PROXY']
        if isolated_root:
            env = clean_env(isolated_root)
        result = subprocess.run(cmd, stdin=sys.stdin, stdout=out, stderr=err, env=env)
    events = [json.loads(line) for line in (folder/'events.jsonl').read_text().splitlines() if line.startswith('{')]
    valid = any(e.get('type') == 'turn.completed' and e.get('usage', {}).get('input_tokens', 0) > 0 for e in events)
    code = result.returncode or (0 if valid else 1)
    (folder/'status.json').write_text(json.dumps({'exit_code':code,'codex_exit_code':result.returncode,'valid_completion':valid,'seconds':time.monotonic()-started}))
    sys.stdout.write((folder/'events.jsonl').read_text())
    # Repository handles process failures; keep details in trace, avoid credentials in console.
    if code:
        print(f'Codex exit {result.returncode}, valid_completion={valid}; trace: {folder}', file=sys.stderr)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
