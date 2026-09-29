"""External evaluation isolation: user/net/PID namespaces + Landlock + seccomp.

Not a general hostile-code hosting service. This profile restricts benchmark
evidence access, filesystem mutation, direct networking and host process access.
Fail closed on setup errors; no fallback to unrestricted execution.
"""
import argparse
import ctypes
import errno
import json
import os
from pathlib import Path
import platform
import pwd
import secrets
import select
import socket
import socketserver
import subprocess
import sys
import threading

CODEX_VENDOR = Path('/usr/local/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl')
CODEX_BINARY = CODEX_VENDOR / 'bin/codex'
PORT = 18765


def new_sample_uid():
    # A private numeric identity, no system account creation or container changes.
    while True:
        uid = (1 << 29) + secrets.randbelow(1 << 29)
        try:
            pwd.getpwuid(uid)
        except KeyError:
            return uid


def filesystem_policy(root, read_files=()):
    if platform.machine() != 'x86_64':
        raise RuntimeError('Only x86_64 is validated')
    libc = ctypes.CDLL(None, use_errno=True)

    def syscall(number, *args):
        result = libc.syscall(ctypes.c_long(number), *args)
        if result < 0:
            e = ctypes.get_errno()
            raise OSError(e, os.strerror(e))
        return result

    class Ruleset(ctypes.Structure):
        _fields_ = [('access', ctypes.c_uint64)]

    class Rule(ctypes.Structure):
        _pack_ = 1
        _fields_ = [('access', ctypes.c_uint64), ('fd', ctypes.c_int32)]

    abi = syscall(444, ctypes.c_void_p(), ctypes.c_size_t(0), ctypes.c_uint(1))
    rights = (1 << 13) - 1
    attr = Ruleset(rights)
    ruleset = syscall(444, ctypes.byref(attr), ctypes.c_size_t(ctypes.sizeof(attr)), ctypes.c_uint(0))
    # No /proc, host home, dataset, repository, or general /tmp access.
    paths = [(root, rights), ('/usr/bin', 13), ('/usr/lib', 13), ('/lib', 13),
             ('/lib64', 13), ('/bin', 13), (str(CODEX_VENDOR), 13),
             ('/etc/ld.so.cache', 4), ('/etc/localtime', 4),
             ('/dev/null', 6), ('/dev/urandom', 4), ('/dev/random', 4)]
    paths += [(str(Path(p).resolve(strict=True)), 4) for p in read_files]
    try:
        for path, access in paths:
            if not Path(path).exists():
                continue
            fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = Rule(access, fd)
                syscall(445, ctypes.c_int(ruleset), ctypes.c_int(1), ctypes.byref(rule), ctypes.c_uint(0))
            finally:
                os.close(fd)
        if libc.prctl(38, 1, 0, 0, 0):
            raise OSError(ctypes.get_errno(), 'PR_SET_NO_NEW_PRIVS failed')
        syscall(446, ctypes.c_int(ruleset), ctypes.c_uint(0))
    finally:
        os.close(ruleset)
    return abi


def syscall_policy():
    lib = ctypes.CDLL('libseccomp.so.2', use_errno=True)
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int

    class Compare(ctypes.Structure):
        _fields_ = [('arg', ctypes.c_uint), ('op', ctypes.c_int),
                    ('a', ctypes.c_uint64), ('b', ctypes.c_uint64)]

    lib.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint, ctypes.POINTER(Compare)]
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    ctx = lib.seccomp_init(0x7fff0000)  # ALLOW, with explicit deny rules.
    if not ctx:
        raise RuntimeError('seccomp_init failed')

    def deny(name, comparisons=(), error=errno.EPERM):
        nr = lib.seccomp_syscall_resolve_name(name.encode())
        if nr < 0:
            return
        array = (Compare * len(comparisons))(*comparisons)
        rc = lib.seccomp_rule_add_array(ctx, 0x50000 | error, nr, len(comparisons), array)
        if rc:
            raise RuntimeError(f'seccomp rule {name}: {rc}')

    try:
        # chmod/fchmod are needed for Codex state. Each sample has a fresh host
        # UID, which owns only that sample's files; normal DAC protects host files.
        for name in ('truncate',
                     'chown', 'fchown', 'lchown', 'fchownat',
                     'utime', 'utimes', 'futimesat',
                     'setxattr', 'lsetxattr', 'fsetxattr', 'removexattr', 'lremovexattr', 'fremovexattr',
                     'ptrace', 'process_vm_readv', 'process_vm_writev', 'pidfd_getfd',
                     'mount', 'umount2', 'pivot_root', 'chroot', 'setns', 'unshare',
                     'fsopen', 'fsconfig', 'fsmount', 'move_mount', 'open_tree', 'mount_setattr',
                     'open_by_handle_at', 'name_to_handle_at', 'io_uring_setup',
                     'bpf', 'perf_event_open', 'userfaultfd', 'keyctl', 'add_key', 'request_key',
                     'reboot', 'kexec_load', 'kexec_file_load', 'init_module', 'finit_module', 'delete_module',
                     'swapon', 'swapoff', 'sethostname', 'setdomainname', 'acct', 'quotactl'):
            deny(name)
        # Rollout persistence updates timestamps through an already-open fd.
        # Permit only that form; DAC still protects read-only root-owned inputs.
        deny('utimensat', [Compare(1, 1, 0, 0)])
        # Force libc to use clone, whose flags can be inspected (clone3 uses a pointer).
        deny('clone3', error=errno.ENOSYS)
        namespace_flags = 0x00020000 | 0x02000000 | 0x04000000 | 0x08000000 | 0x10000000 | 0x20000000 | 0x40000000
        for bit in (1 << i for i in range(32) if namespace_flags & (1 << i)):
            deny('clone', [Compare(0, 7, bit, bit)])  # MASKED_EQ
        # Network namespace has loopback only. AF_UNIX could reach host pathname
        # sockets, so deny it; the trusted relay starts outside this filter.
        for domain in range(0, 64):
            if domain not in (socket.AF_INET, socket.AF_INET6):
                deny('socket', [Compare(0, 4, domain, 0)])
        deny('socket', [Compare(0, 5, 64, 0)])  # GE
        deny('socket', [Compare(1, 7, 15, socket.SOCK_RAW)])
        # Tokio uses connected Unix stream pairs for local signal wakeups.
        # They cannot reconnect to host pathname sockets. Datagram pairs can,
        # so only connected stream pairs are permitted.
        deny('socketpair', [Compare(0, 1, socket.AF_UNIX, 0)])  # NE
        deny('socketpair', [Compare(1, 7, 15, socket.SOCK_DGRAM)])
        deny('socketpair', [Compare(1, 7, 15, socket.SOCK_SEQPACKET)])
        rc = lib.seccomp_load(ctx)
        if rc:
            raise RuntimeError(f'seccomp_load failed: {rc}')
    finally:
        lib.seccomp_release(ctx)


def clean_env(root):
    root = Path(root)
    return {'PATH': f'/usr/bin:/bin:{CODEX_VENDOR / "codex-path"}',
            'HOME': str(root / 'home'), 'CODEX_HOME': str(root / 'home/.codex'),
            'TMPDIR': str(root / 'tmp'), 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
            'OPENAI_API_KEY': 'sandbox-placeholder-not-a-secret',
            'OPENAI_BASE_URL': f'http://127.0.0.1:{PORT}',
            'OPENAI_API_BASE': f'http://127.0.0.1:{PORT}', 'RUST_BACKTRACE': '0'}


def command(root, bridge, argv, read_files=()):
    uid = Path(root).stat().st_uid
    if not (1 << 29) <= uid < (1 << 30):
        raise RuntimeError('Sample must have a dedicated unprivileged numeric owner')
    return ['/usr/bin/setpriv', '--reuid', str(uid), '--regid', str(uid), '--clear-groups',
            '/usr/bin/unshare', '--user', '--map-root-user', '--net', '--pid', '--ipc', '--uts', '--fork', '--kill-child',
            '/usr/bin/python3', str(Path(__file__).resolve()), '--root', str(root),
            '--bridge', str(bridge), '--read-files', json.dumps(list(read_files)), '--', *argv]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--bridge', required=True)
    parser.add_argument('--read-files', default='[]')
    parser.add_argument('argv', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    root = Path(args.root).resolve(strict=True)
    os.umask(0o077)
    if os.getpid() != 1:
        raise RuntimeError('Must run as PID 1 in a fresh namespace through command()')
    subprocess.run(['/usr/sbin/ip', 'link', 'set', 'lo', 'up'], check=True)

    class Relay(socketserver.BaseRequestHandler):
        def handle(self):
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as upstream:
                upstream.connect(args.bridge)
                peers = (self.request, upstream)
                while True:
                    ready, _, _ = select.select(peers, [], [], 610)
                    if not ready:
                        return
                    for peer in ready:
                        data = peer.recv(65536)
                        if not data:
                            return
                        (upstream if peer is self.request else self.request).sendall(data)

    server = socketserver.ThreadingTCPServer(('127.0.0.1', PORT), Relay)
    server.daemon_threads = True

    def restrict():
        filesystem_policy(str(root), json.loads(args.read_files))
        syscall_policy()

    argv = args.argv[1:] if args.argv[:1] == ['--'] else args.argv
    # Fork before starting any relay thread. No non-stdio descriptors survive exec.
    child = subprocess.Popen(argv, cwd=root / 'work', env=clean_env(root),
                             close_fds=True, preexec_fn=restrict)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return child.wait()


if __name__ == '__main__':
    raise SystemExit(main())
