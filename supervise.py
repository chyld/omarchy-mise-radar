#!/usr/bin/python3
"""Isolate a trusted mise invocation in its own process group.

Invoked as:
  /usr/bin/python3 /absolute/path/to/supervise.py \
      TIMEOUT_SEC MAX_BYTES KILL_GRACE_SEC MISE_PATH -- mise-args...

Never searches PATH, never starts a shell, never runs upgrade/install/use.
"""
from __future__ import annotations

import os
import select
import signal
import subprocess
import sys
import time

EXIT_USAGE = 2
EXIT_BAD_PATH = 127
EXIT_TIMEOUT = 124
EXIT_OVERFLOW = 125
EXIT_SIGNAL = 143

ALLOWED_SUBCOMMANDS = ("--version", "ls", "outdated")
CHUNK = 8192
STDERR_CAP = 200

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


def trusted_mise_paths():
    allowed = {"/usr/bin/mise"}
    home = os.environ.get("HOME", "")
    if isinstance(home, str) and home.startswith("/") and ".." not in home:
        allowed.add(home + "/.local/bin/mise")
    return allowed


def is_trusted_mise(path):
    if not isinstance(path, str):
        return False
    if not path.startswith("/") or ".." in path:
        return False
    return path in trusted_mise_paths()


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


def copy_stdout(proc, max_bytes, deadline):
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
        try:
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
        except OSError:
            note_stop("signal")
            break
        copied += len(chunk)
        if overflow:
            break
    return overflow, copied


def main():
    timeout_sec, max_bytes, grace_sec, mise_path, mise_args = parse_argv(sys.argv)

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGHUP, on_signal)
    signal.signal(signal.SIGPIPE, signal.SIG_IGN)

    if stop_reason is not None:
        sys.exit(EXIT_SIGNAL)

    try:
        proc = subprocess.Popen(
            [mise_path] + mise_args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except OSError:
        fail(EXIT_BAD_PATH, "failed to start mise")

    pgid = proc.pid
    deadline = time.monotonic() + timeout_sec
    overflow = False
    try:
        overflow, _copied = copy_stdout(proc, max_bytes, deadline)
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


if __name__ == "__main__":
    main()
