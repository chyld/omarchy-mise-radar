#!/usr/bin/python3
"""Isolate a trusted mise invocation in its own process group.

Invoked as:
  /usr/bin/python3 /absolute/path/to/supervise.py \
      TIMEOUT_SEC MAX_BYTES KILL_GRACE_SEC MISE_PATH -- mise-args...

Never searches PATH, never starts a shell, never runs upgrade/install/use.
The only accepted binary is Omarchy mise-bin at /usr/bin/mise. Execution is
bound to an opened fd (/proc/self/fd/N), not a reopened pathname.
"""
from __future__ import annotations

import os
import re
import select
import signal
import stat
import subprocess
import sys
import time

EXIT_USAGE = 2
EXIT_BAD_PATH = 127
EXIT_TIMEOUT = 124
EXIT_OVERFLOW = 125
EXIT_SIGNAL = 143

ALLOWED_MISE = "/usr/bin/mise"
ALLOWED_SUBCOMMANDS = ("--version", "ls", "outdated")
CHUNK = 8192
STDERR_CAP = 200
VERSION_TIMEOUT_SEC = 5.0
VERSION_MAX_BYTES = 4096
VERSION_HEAD_RE = re.compile(r"^(?:mise|[0-9]{4}\.)")

stop_reason = None


def note_stop(reason):
    global stop_reason
    if stop_reason is None:
        stop_reason = reason


def on_signal(signum, _frame):
    note_stop("signal")


def write_stderr(msg):
    if not msg:
        return
    data = (msg.strip() + "\n").encode("utf-8", "replace")[:STDERR_CAP]
    try:
        sys.stderr.buffer.write(data)
        sys.stderr.buffer.flush()
    except OSError:
        pass


def fail(code, msg=""):
    write_stderr(msg)
    sys.exit(code)


def parse_positive_float(raw, lo, hi):
    try:
        value = float(raw)
    except ValueError:
        fail(EXIT_USAGE, "invalid number")
    if value < lo or value > hi or value != value:
        fail(EXIT_USAGE, "invalid number")
    return value


def parse_positive_int(raw, lo, hi):
    try:
        value = int(raw, 10)
    except ValueError:
        fail(EXIT_USAGE, "invalid integer")
    if value < lo or value > hi:
        fail(EXIT_USAGE, "invalid integer")
    return value


def is_trusted_mise(path):
    if not isinstance(path, str):
        return False
    if not path.startswith("/") or ".." in path:
        return False
    return path == ALLOWED_MISE


def path_components(path):
    if not isinstance(path, str) or not path.startswith("/") or ".." in path:
        return []
    comps = []
    remaining = path
    while True:
        comps.append(remaining)
        parent = os.path.dirname(remaining)
        if parent == remaining:
            break
        remaining = parent
    comps.reverse()
    return comps


def component_is_trusted(st, expect_dir):
    if st is None:
        return False
    if st.st_uid != 0:
        return False
    if (st.st_mode & 0o022) != 0:
        return False
    if expect_dir:
        return stat.S_ISDIR(st.st_mode)
    return stat.S_ISREG(st.st_mode)


def path_chain_is_trusted(path, lstat_fn=os.lstat):
    comps = path_components(path)
    if not comps:
        return False
    last = len(comps) - 1
    for i, comp in enumerate(comps):
        try:
            st = lstat_fn(comp)
        except OSError:
            return False
        if not component_is_trusted(st, expect_dir=(i != last)):
            return False
    return True


def looks_like_mise_version(data):
    if not data:
        return False
    text = data.decode("utf-8", "replace").lstrip()
    if not text:
        return False
    line = text.split("\n", 1)[0].strip()
    return VERSION_HEAD_RE.match(line) is not None


def parse_argv(argv):
    if len(argv) < 6:
        fail(EXIT_USAGE, "usage: supervise.py TIMEOUT MAX_BYTES GRACE MISE_PATH -- args")
    timeout_sec = parse_positive_float(argv[1], 0.001, 300.0)
    max_bytes = parse_positive_int(argv[2], 1, 1048576)
    grace_sec = parse_positive_float(argv[3], 0.05, 30.0)
    mise_path = argv[4]
    if argv[5] != "--":
        fail(EXIT_USAGE, "expected -- before mise args")
    mise_args = argv[6:]
    if not mise_args:
        fail(EXIT_USAGE, "missing mise args")
    if not is_trusted_mise(mise_path):
        fail(EXIT_BAD_PATH, "untrusted mise path")
    head = mise_args[0]
    if head not in ALLOWED_SUBCOMMANDS:
        fail(EXIT_USAGE, "forbidden mise subcommand")
    return timeout_sec, max_bytes, grace_sec, mise_path, mise_args


def open_trusted_mise_fd():
    if not path_chain_is_trusted(ALLOWED_MISE):
        fail(EXIT_BAD_PATH, "untrusted mise path")
    try:
        fd = os.open(ALLOWED_MISE, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        fail(EXIT_BAD_PATH, "failed to open mise")
    try:
        st = os.fstat(fd)
    except OSError:
        try:
            os.close(fd)
        except OSError:
            pass
        fail(EXIT_BAD_PATH, "failed to open mise")
    if not component_is_trusted(st, expect_dir=False):
        try:
            os.close(fd)
        except OSError:
            pass
        fail(EXIT_BAD_PATH, "untrusted mise path")
    return fd


def spawn_bound_mise(fd, mise_args):
    exec_path = "/proc/self/fd/%d" % fd
    return subprocess.Popen(
        ["mise"] + list(mise_args),
        executable=exec_path,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
        pass_fds=(fd,),
    )


def terminate_group(proc, pgid, grace_sec):
    if pgid is not None:
        try:
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    deadline = time.monotonic() + grace_sec
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            break
        time.sleep(0.05)
    leftover = deadline - time.monotonic()
    if leftover > 0:
        time.sleep(leftover)
    if pgid is not None:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    if proc is not None:
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        if proc.stdout is not None:
            try:
                proc.stdout.close()
            except OSError:
                pass


def copy_stdout(proc, max_bytes, deadline, dest=None):
    fd = proc.stdout.fileno()
    copied = 0
    overflow = False
    while True:
        if stop_reason is not None:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            note_stop("timeout")
            break
        try:
            ready, _, _ = select.select([fd], [], [], min(0.25, remaining))
        except InterruptedError:
            continue
        except (ValueError, OSError):
            break
        if stop_reason is not None:
            break
        if time.monotonic() >= deadline:
            note_stop("timeout")
            break
        if not ready:
            if proc.poll() is not None:
                try:
                    ready, _, _ = select.select([fd], [], [], 0)
                except (InterruptedError, ValueError, OSError):
                    break
                if not ready:
                    break
            else:
                continue
        room = max_bytes - copied
        if room <= 0:
            overflow = True
            break
        try:
            chunk = os.read(fd, min(CHUNK, room + 1))
        except InterruptedError:
            continue
        except OSError:
            break
        if not chunk:
            break
        if len(chunk) > room:
            chunk = chunk[:room]
            overflow = True
        if dest is None:
            try:
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
            except OSError:
                note_stop("signal")
                break
        else:
            dest.extend(chunk)
        copied += len(chunk)
        if overflow:
            break
    return overflow, copied


def supervise_child(proc, max_bytes, timeout_sec, grace_sec, dest=None):
    pgid = proc.pid
    deadline = time.monotonic() + timeout_sec
    overflow = False
    try:
        overflow, _copied = copy_stdout(proc, max_bytes, deadline, dest=dest)
        if overflow:
            note_stop("overflow")
        if stop_reason is not None or overflow:
            terminate_group(proc, pgid, grace_sec)
        else:
            while proc.poll() is None:
                if stop_reason is not None:
                    terminate_group(proc, pgid, grace_sec)
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    note_stop("timeout")
                    terminate_group(proc, pgid, grace_sec)
                    break
                try:
                    proc.wait(timeout=min(0.2, remaining))
                except subprocess.TimeoutExpired:
                    continue
    except Exception:
        terminate_group(proc, pgid, grace_sec)
        fail(1, "supervisor error")
    return overflow


def exit_for_child(overflow, proc):
    if overflow or stop_reason == "overflow":
        sys.exit(EXIT_OVERFLOW)
    if stop_reason == "timeout":
        sys.exit(EXIT_TIMEOUT)
    if stop_reason == "signal":
        sys.exit(EXIT_SIGNAL)
    rc = proc.returncode
    if rc is None:
        sys.exit(1)
    if rc < 0:
        sys.exit(128 + (-rc) if -rc < 128 else 1)
    sys.exit(rc)


def enforce_version_policy(fd, grace_sec):
    try:
        proc = spawn_bound_mise(fd, ["--version"])
    except OSError:
        fail(EXIT_BAD_PATH, "failed to start mise")
    buf = bytearray()
    overflow = supervise_child(
        proc, VERSION_MAX_BYTES, VERSION_TIMEOUT_SEC, grace_sec, dest=buf
    )
    if overflow or stop_reason == "overflow":
        fail(EXIT_BAD_PATH, "mise version check failed")
    if stop_reason == "timeout":
        fail(EXIT_BAD_PATH, "mise version check failed")
    if stop_reason == "signal":
        sys.exit(EXIT_SIGNAL)
    rc = proc.returncode
    if rc != 0:
        fail(EXIT_BAD_PATH, "mise version check failed")
    if not looks_like_mise_version(bytes(buf)):
        fail(EXIT_BAD_PATH, "mise version check failed")


def main():
    timeout_sec, max_bytes, grace_sec, _mise_path, mise_args = parse_argv(sys.argv)

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGHUP, on_signal)
    signal.signal(signal.SIGPIPE, signal.SIG_IGN)

    if stop_reason is not None:
        sys.exit(EXIT_SIGNAL)

    fd = open_trusted_mise_fd()
    try:
        if mise_args[0] in ("ls", "outdated"):
            enforce_version_policy(fd, grace_sec)
        try:
            proc = spawn_bound_mise(fd, mise_args)
        except OSError:
            fail(EXIT_BAD_PATH, "failed to start mise")
        overflow = supervise_child(proc, max_bytes, timeout_sec, grace_sec)
        exit_for_child(overflow, proc)
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


if __name__ == "__main__":
    main()
