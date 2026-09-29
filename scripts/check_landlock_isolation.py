#!/usr/bin/env python3
"""Local synthetic Landlock probe, NOT a production sandbox launcher.

No model calls, credentials, benchmark data, or container permission changes.
Only the forked child is restricted. ABI 1 gaps are deliberately measured.
"""
import ctypes
import errno
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile


def restrict(work):
    if platform.machine() != "x86_64":
        raise RuntimeError("Probe syscall numbers audited for x86_64 only")
    libc = ctypes.CDLL(None, use_errno=True)

    def syscall(number, *args):
        result = libc.syscall(ctypes.c_long(number), *args)
        if result < 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        return result

    abi = syscall(444, ctypes.c_void_p(), ctypes.c_size_t(0), ctypes.c_uint(1))

    class Ruleset(ctypes.Structure):
        _fields_ = [("access", ctypes.c_uint64)]

    class PathRule(ctypes.Structure):
        _pack_ = 1
        _fields_ = [("access", ctypes.c_uint64), ("fd", ctypes.c_int32)]

    rights = (1 << 13) - 1  # All ABI 1 filesystem rights; no newer rights claimed.
    attr = Ruleset(rights)
    ruleset = syscall(444, ctypes.byref(attr), ctypes.c_size_t(ctypes.sizeof(attr)), ctypes.c_uint(0))
    try:
        for path, access in [(work, rights), ("/usr", 13), ("/lib", 13), ("/lib64", 13), ("/bin", 13)]:
            if not Path(path).exists():
                continue
            fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = PathRule(access, fd)
                syscall(445, ctypes.c_int(ruleset), ctypes.c_int(1), ctypes.byref(rule), ctypes.c_uint(0))
            finally:
                os.close(fd)
        if libc.prctl(38, 1, 0, 0, 0):  # PR_SET_NO_NEW_PRIVS
            raise OSError(ctypes.get_errno(), "no_new_privs failed")
        syscall(446, ctypes.c_int(ruleset), ctypes.c_uint(0))
    finally:
        os.close(ruleset)
    return abi


def child(work, outside):
    abi = restrict(work)
    os.chdir(work)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(work), "LC_ALL": "C"}
    write = subprocess.run(["/bin/bash", "--noprofile", "--norc", "-c", "printf probe > memory.txt"], env=env, capture_output=True)
    read = subprocess.run(["/bin/cat", "memory.txt"], env=env, capture_output=True)
    checks = {"shell_write": write.returncode == 0, "next_process_read": read.returncode == 0 and read.stdout == b"probe"}

    def denied(name, operation):
        try:
            operation()
        except OSError as exc:
            checks[name] = exc.errno in (errno.EACCES, errno.EPERM)
        else:
            checks[name] = False

    denied("outside_read_denied", lambda: outside.read_bytes())
    denied("outside_write_denied", lambda: outside.write_bytes(b"unexpected"))
    denied("outside_listing_denied", lambda: os.listdir(outside.parent))
    denied("outside_unlink_denied", lambda: outside.unlink())
    denied("symlink_read_denied", lambda: (work / "outside-link").read_bytes())
    denied("parent_traversal_denied", lambda: (work / ".." / "hidden" / "synthetic-gold.txt").read_bytes())
    shell = subprocess.run(["/bin/cat", str(outside)], env=env, capture_output=True)
    checks["shell_child_read_denied"] = shell.returncode != 0 and b"Permission denied" in shell.stderr
    # Only synthetic data: demonstrate why Landlock ABI 1 alone is insufficient.
    try:
        os.truncate(outside, 0)
        truncate_allowed = True
    except OSError:
        truncate_allowed = False
    return {"landlock_abi": abi, "checks": checks, "filesystem_probe_passed": all(checks.values()),
            "outside_path_truncate_allowed": truncate_allowed,
            "production_ready": False,
            "limitations": ["ABI 1 does not mediate path truncate or all metadata changes", "No network or process isolation", "Runtime /usr read allowlist is only for this synthetic probe", "Inherited descriptors and credentials require separate production handling"]}


def main():
    with tempfile.TemporaryDirectory(prefix="wma-landlock-probe-") as folder:
        base = Path(folder)
        work = base / "work"
        work.mkdir()
        (base / "hidden").mkdir()
        outside = base / "hidden" / "synthetic-gold.txt"
        outside.write_text("synthetic-only")
        (work / "outside-link").symlink_to(outside)
        reader, writer = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(reader)
            try:
                result = child(work, outside)
                payload = json.dumps(result).encode()
            except BaseException as exc:
                payload = json.dumps({"error": str(exc), "production_ready": False}).encode()
            with os.fdopen(writer, "wb") as stream:
                stream.write(payload)
            os._exit(0)
        os.close(writer)
        with os.fdopen(reader, "rb") as stream:
            result = json.load(stream)
        _, status = os.waitpid(pid, 0)
        result["child_exit_status"] = os.waitstatus_to_exitcode(status)
        result["parent_verified_synthetic_file_size"] = outside.stat().st_size
        print(json.dumps(result, indent=2))
        return 0 if result.get("filesystem_probe_passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
