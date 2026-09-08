#!/usr/bin/python3
"""Isolate a trusted mise invocation in its own process group.

Invoked as:
  /usr/bin/python3 -I -S -B /absolute/path/to/supervise.py \
      TIMEOUT_SEC MAX_BYTES KILL_GRACE_SEC MISE_PATH -- mise-args...

Never searches PATH, never starts a shell, never runs upgrade/install/use.
The only accepted binary is Omarchy mise-bin at /usr/bin/mise. Execution is
bound to an opened fd (/proc/self/fd/N), not a reopened pathname.
"""
from __future__ import annotations

import errno
import os
import pwd
import re
import select
import signal
import stat
import subprocess
import sys
import time

EXIT_USAGE = 2
EXIT_BAD_PATH = 126
EXIT_TIMEOUT = 124
EXIT_OVERFLOW = 125
EXIT_SIGNAL = 143

ALLOWED_MISE = "/usr/bin/mise"
ALLOWED_COMMANDS = (("--version",), ("ls", "--json", "--current"),
                    ("outdated", "--bump", "--json"))
CHUNK = 8192
STDERR_CAP = 200
REAP_TIMEOUT_SEC = 2.0
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
    if tuple(mise_args) not in ALLOWED_COMMANDS:
        fail(EXIT_USAGE, "forbidden mise subcommand")
    return timeout_sec, max_bytes, grace_sec, mise_path, mise_args


def open_trusted_mise_fd():
    """Keep the root-owned parent chain open through the final executable open."""
    parent = None
    fd = None
    try:
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        parent = os.open("/", directory_flags)
        if not component_is_trusted(os.fstat(parent), expect_dir=True):
            raise PermissionError("untrusted root")
        for name in ("usr", "bin"):
            child = os.open(name, directory_flags, dir_fd=parent)
            os.close(parent)
            parent = child
            if not component_is_trusted(os.fstat(parent), expect_dir=True):
                raise PermissionError("untrusted parent")
        fd = os.open("mise", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                     dir_fd=parent)
        if not component_is_trusted(os.fstat(fd), expect_dir=False):
            raise PermissionError("untrusted executable")
        os.set_blocking(fd, True)
        return fd
    except OSError:
        if fd is not None:
            os.close(fd)
        fail(EXIT_BAD_PATH, "untrusted mise path")
    finally:
        if parent is not None:
            os.close(parent)


def mise_environment():
    """No ambient credentials, loader hooks, interpreter paths or proxies."""
    env = {"HOME": pwd.getpwuid(os.getuid()).pw_dir, "PATH": "/usr/bin:/bin",
           "LANG": "C.UTF-8", "MISE_MINIMUM_RELEASE_AGE": "0"}
    for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
        value = os.environ.get(key, "")
        if value.startswith("/"):
            env[key] = value
    return env


def spawn_bound_mise(fd, mise_args, grace_sec):
    exec_path = "/proc/self/fd/%d" % fd
    proc = subprocess.Popen(
        ["mise"] + list(mise_args),
        executable=exec_path,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
        pass_fds=(fd,),
        env=mise_environment(),
        cwd=pwd.getpwuid(os.getuid()).pw_dir,
    )
    try:
        pidfd = os.pidfd_open(proc.pid)
    except OSError:
        terminate_group(proc, None, grace_sec)
        fail(1, "pidfd_open failed")
    return proc, pidfd


def close_pidfd(pidfd):
    if pidfd is None:
        return
    try:
        os.close(pidfd)
    except OSError:
        pass


def reap_proc(proc, timeout=REAP_TIMEOUT_SEC):
    if proc is None:
        return True
    reaped = True
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        reaped = False
    if proc.stdout is not None:
        try:
            proc.stdout.close()
        except OSError:
            pass
    return reaped


def leader_has_exited(pidfd):
    """Return (exited, certain). Missing pidfd and waitid errors are not exited."""
    if pidfd is None:
        return False, False
    try:
        info = os.waitid(os.P_PIDFD, pidfd, os.WEXITED | os.WNOHANG | os.WNOWAIT)
    except OSError:
        return False, False
    if info is None:
        return False, True
    return getattr(info, "si_pid", 0) != 0, True


def leader_is_certainly_exited(pidfd):
    exited, certain = leader_has_exited(pidfd)
    return certain and exited


def pgid_has_live_members(pgid):
    """Bound the /proc scan; incomplete observation requests conservative cleanup."""
    if pgid is None:
        return False, False
    uncertain = False
    deadline = time.monotonic() + 0.2
    try:
        with os.scandir("/proc") as entries:
            for count, entry in enumerate(entries):
                if count >= 65536 or time.monotonic() >= deadline:
                    return False, False
                if not entry.name.isdigit():
                    continue
                fd = None
                try:
                    fd = os.open(entry.path + "/stat", os.O_RDONLY | os.O_NOFOLLOW
                                 | os.O_NONBLOCK | os.O_CLOEXEC)
                    raw = os.read(fd, 4097)
                    if len(raw) > 4096:
                        uncertain = True
                        continue
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    if exc.errno != errno.ENOENT:
                        uncertain = True
                    continue
                finally:
                    if fd is not None:
                        os.close(fd)
                text = raw.decode("ascii", "replace")
                end = text.rfind(")")
                rest = text[end + 2:].split() if end >= 0 else []
                if len(rest) < 3:
                    uncertain = True
                    continue
                try:
                    member_pgid = int(rest[2])
                except ValueError:
                    uncertain = True
                    continue
                if member_pgid == pgid and rest[0] != "Z":
                    return True, True
    except OSError:
        return False, False
    return False, not uncertain


def group_needs_kill(pidfd, pgid):
    """KILL if this unreaped identity may still have a live leader or descendants."""
    exited, certain = leader_has_exited(pidfd)
    if not certain or not exited:
        return True
    has_live, live_certain = pgid_has_live_members(pgid)
    if not live_certain:
        return True
    return has_live


def terminate_group(proc, pidfd, grace_sec):
    try:
        if proc is not None and proc.returncode is None:
            pgid = proc.pid
            try:
                os.killpg(pgid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            deadline = time.monotonic() + grace_sec
            while time.monotonic() < deadline:
                if not group_needs_kill(pidfd, pgid):
                    break
                time.sleep(0.05)
            if group_needs_kill(pidfd, pgid):
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
    finally:
        if not reap_proc(proc):
            fail(1, "failed to reap mise process")


def copy_stdout(proc, pidfd, max_bytes, deadline, dest=None):
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
            if leader_is_certainly_exited(pidfd):
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
            try:
                extra = os.read(fd, 1)
            except InterruptedError:
                continue
            except OSError:
                break
            if extra:
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


def supervise_child(proc, pidfd, max_bytes, timeout_sec, grace_sec, dest=None):
    deadline = time.monotonic() + timeout_sec
    overflow = False
    signaled = False
    try:
        overflow, _copied = copy_stdout(proc, pidfd, max_bytes, deadline, dest=dest)
        if overflow:
            note_stop("overflow")
        if stop_reason is not None or overflow:
            terminate_group(proc, pidfd, grace_sec)
            signaled = True
        else:
            while not leader_is_certainly_exited(pidfd):
                if stop_reason is not None:
                    terminate_group(proc, pidfd, grace_sec)
                    signaled = True
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    note_stop("timeout")
                    terminate_group(proc, pidfd, grace_sec)
                    signaled = True
                    break
                time.sleep(min(0.2, remaining))
            if not signaled:
                # The leader may exit successfully with descendants still alive.
                # Keep its identity unreaped until the whole group is cleaned up.
                if group_needs_kill(pidfd, proc.pid):
                    terminate_group(proc, pidfd, grace_sec)
                elif not reap_proc(proc):
                    fail(1, "failed to reap mise process")
    except Exception:
        terminate_group(proc, pidfd, grace_sec)
        fail(1, "supervisor error")
    finally:
        close_pidfd(pidfd)
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
        proc, pidfd = spawn_bound_mise(fd, ["--version"], grace_sec)
    except OSError:
        fail(EXIT_BAD_PATH, "failed to start mise")
    buf = bytearray()
    overflow = supervise_child(
        proc, pidfd, VERSION_MAX_BYTES, VERSION_TIMEOUT_SEC, grace_sec, dest=buf
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
            proc, pidfd = spawn_bound_mise(fd, mise_args, grace_sec)
        except OSError:
            fail(EXIT_BAD_PATH, "failed to start mise")
        overflow = supervise_child(proc, pidfd, max_bytes, timeout_sec, grace_sec)
        exit_for_child(overflow, proc)
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


if __name__ == "__main__":
    main()
