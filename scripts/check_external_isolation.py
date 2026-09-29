"""Synthetic boundary acceptance; does not access benchmark data or call an API."""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
from wma_isolation import CODEX_BINARY, new_sample_uid, clean_env, command


def main():
    with tempfile.TemporaryDirectory(prefix='wma-isolation-check-') as folder:
        base = Path(folder)
        base.chmod(0o711)
        root = base / 'sample'
        uid = new_sample_uid()
        for name in ('work', 'home/.codex', 'tmp'):
            (root / name).mkdir(parents=True)
        hidden = base / 'synthetic-gold.txt'
        hidden.write_text('synthetic-only')
        current_image = base / 'current.png'
        current_image.write_bytes(b'synthetic-current-image')
        (root / 'work/link').symlink_to(hidden)
        for path in [root, root/'work', root/'home', root/'home/.codex', root/'tmp']:
            os.chown(path, uid, uid)
        code = '''
import os, pathlib, socket, subprocess, json, errno
hidden = pathlib.Path(os.environ.get('UNEXPECTED_SECRET', ''))
hidden = pathlib.Path(HIDDEN)
checks = {}
checks['current_image_readable'] = pathlib.Path(CURRENT_IMAGE).read_bytes() == b'synthetic-current-image'
def denied(name, operation):
    try: operation()
    except OSError as e: checks[name] = e.errno in (errno.EACCES, errno.EPERM)
    else: checks[name] = False
denied('outside_read', hidden.read_bytes)
denied('outside_write', lambda: hidden.write_text('bad'))
denied('outside_truncate', lambda: os.truncate(hidden, 0))
denied('outside_chmod', lambda: os.chmod(hidden, 0o777))
with open(CURRENT_IMAGE, 'rb') as f:
    denied('readonly_image_fchmod', lambda: os.fchmod(f.fileno(), 0o777))
denied('outside_unlink', hidden.unlink)
denied('symlink_read', lambda: pathlib.Path('link').read_bytes())
denied('host_proc', lambda: pathlib.Path('/proc/1/environ').read_bytes())
denied('host_home', lambda: os.listdir('/root'))
denied('host_unix_socket', lambda: socket.socket(socket.AF_UNIX))
denied('unix_datagram_socketpair', lambda: socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM))
with socket.socketpair()[0] as s:
    try: s.connect('/tmp/nonexistent-wma-host-socket')
    except OSError: checks['unix_stream_pair_reconnect_denied'] = True
    else: checks['unix_stream_pair_reconnect_denied'] = False
checks['key_scrubbed'] = os.environ.get('OPENAI_API_KEY') == 'sandbox-placeholder-not-a-secret'
checks['no_extra_environment'] = 'UNEXPECTED_SECRET' not in os.environ
subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c', 'printf allowed > memory.txt'], check=True)
checks['shell_write_read'] = subprocess.check_output(['/bin/cat', 'memory.txt']) == b'allowed'
with socket.socket() as s:
    s.settimeout(1)
    try: s.connect(('127.0.0.1', HOST_PORT))
    except OSError: checks['host_loopback_denied'] = True
    else: checks['host_loopback_denied'] = False
with socket.socket() as s:
    s.settimeout(1)
    try: s.connect(('192.0.2.1', 443))
    except OSError: checks['external_network_denied'] = True
    else: checks['external_network_denied'] = False
print(json.dumps(checks))
'''
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            code = code.replace('HIDDEN', repr(str(hidden))).replace('HOST_PORT', str(listener.getsockname()[1]))
            code = code.replace('CURRENT_IMAGE', repr(str(current_image)))
            result = subprocess.run(command(root, base / 'unused.sock', ['/usr/bin/python3', '-c', code], [str(current_image)]),
                                    env={**clean_env(root), 'UNEXPECTED_SECRET': 'synthetic'}, capture_output=True, text=True)
        version = subprocess.run(command(root, base / 'unused.sock', [str(CODEX_BINARY), '--version']),
                                 env=clean_env(root), capture_output=True, text=True)
        checks = json.loads(result.stdout) if result.returncode == 0 else {}
        checks['synthetic_outside_file_unchanged'] = hidden.read_text() == 'synthetic-only'
        checks['codex_binary_starts'] = version.returncode == 0 and 'codex-cli' in version.stdout
        output = dict(passed=result.returncode == 0 and all(checks.values()), checks=checks,
                      probe_exit=result.returncode, stderr=result.stderr,
                      codex_version=version.stdout.strip(), codex_stderr=version.stderr)
        print(json.dumps(output, indent=2))
        return 0 if output['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
