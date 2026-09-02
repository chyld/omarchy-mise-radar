#!/usr/bin/python3
import errno
import importlib.util
import os
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = "/usr/bin/python3"
HELPER = os.path.join(ROOT, "supervise.py")
MISE = "/usr/bin/mise"

spec = importlib.util.spec_from_file_location("supervise", HELPER)
supervise = importlib.util.module_from_spec(spec)
spec.loader.exec_module(supervise)


def run_helper(args, timeout=20, env=None):
    cmd = [PYTHON, HELPER] + args
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        env=env,
        check=False,
    )


class SuperviseTests(unittest.TestCase):
    def setUp(self):
        supervise.stop_reason = None

    def test_helper_is_absolute(self):
        self.assertTrue(HELPER.startswith("/"))
        self.assertNotIn("..", HELPER)
        self.assertTrue(os.path.isfile(HELPER))

    def test_rejects_relative_mise_path(self):
        proc = run_helper(["5", "1024", "0.1", "usr/bin/mise", "--", "--version"])
        self.assertEqual(proc.returncode, 127)

    def test_rejects_dotdot_mise_path(self):
        proc = run_helper(["5", "1024", "0.1", "/usr/bin/../bin/mise", "--", "--version"])
        self.assertEqual(proc.returncode, 127)

    def test_rejects_untrusted_absolute_path(self):
        proc = run_helper(["5", "1024", "0.1", "/tmp/mise", "--", "--version"])
        self.assertEqual(proc.returncode, 127)

    def test_rejects_non_usr_bin_mise(self):
        proc = run_helper(["5", "1024", "0.1", "/bin/mise", "--", "--version"])
        self.assertEqual(proc.returncode, 127)

    def test_rejects_home_local_bin_mise(self):
        home = os.environ.get("HOME", "/home/chyld")
        proc = run_helper(["5", "1024", "0.1", home + "/.local/bin/mise", "--", "--version"])
        self.assertEqual(proc.returncode, 127)

    def test_is_trusted_mise_only_usr_bin(self):
        self.assertTrue(supervise.is_trusted_mise("/usr/bin/mise"))
        self.assertFalse(supervise.is_trusted_mise("/home/chyld/.local/bin/mise"))
        self.assertFalse(supervise.is_trusted_mise("/usr/bin/../bin/mise"))
        self.assertFalse(supervise.is_trusted_mise("usr/bin/mise"))

    def test_rejects_missing_separator(self):
        proc = run_helper(["5", "1024", "0.1", MISE, "--version"])
        self.assertEqual(proc.returncode, 2)

    def test_rejects_upgrade(self):
        proc = run_helper(["5", "1024", "0.1", MISE, "--", "upgrade"])
        self.assertEqual(proc.returncode, 2)

    def test_rejects_install(self):
        proc = run_helper(["5", "1024", "0.1", MISE, "--", "install", "node"])
        self.assertEqual(proc.returncode, 2)

    def test_rejects_use(self):
        proc = run_helper(["5", "1024", "0.1", MISE, "--", "use", "node"])
        self.assertEqual(proc.returncode, 2)

    def test_path_chain_rejects_nonroot_temp(self):
        with tempfile.TemporaryDirectory() as td:
            fake = os.path.join(td, "mise")
            with open(fake, "wb") as fh:
                fh.write(b"#!/bin/sh\necho 2026.1.1\n")
            os.chmod(fake, 0o755)
            os.chmod(td, 0o755)
            self.assertFalse(supervise.path_chain_is_trusted(fake))
            st = os.lstat(fake)
            self.assertNotEqual(st.st_uid, 0)
            self.assertFalse(supervise.component_is_trusted(st, expect_dir=False))

    def test_path_chain_accepts_usr_bin_mise(self):
        if not os.path.isfile(MISE):
            self.skipTest("mise not installed at /usr/bin/mise")
        self.assertTrue(supervise.path_chain_is_trusted(MISE))

    def test_looks_like_mise_version(self):
        self.assertTrue(supervise.looks_like_mise_version(b"2026.8.15 linux-x64 (2026-08-30)\n"))
        self.assertTrue(supervise.looks_like_mise_version(b"mise 2026.8.15\n"))
        self.assertFalse(supervise.looks_like_mise_version(b""))
        self.assertFalse(supervise.looks_like_mise_version(b"not-mise\n"))
        self.assertFalse(supervise.looks_like_mise_version(b"bash 5.2\n"))

    def test_version_succeeds(self):
        if not os.path.isfile(MISE):
            self.skipTest("mise not installed at /usr/bin/mise")
        proc = run_helper(["5", "262144", "0.2", MISE, "--", "--version"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertGreater(len(proc.stdout), 0)
        self.assertLessEqual(len(proc.stdout), 262144)
        self.assertTrue(supervise.looks_like_mise_version(proc.stdout))

    def test_ls_does_not_leak_version_stdout(self):
        if not os.path.isfile(MISE):
            self.skipTest("mise not installed at /usr/bin/mise")
        proc = run_helper(["15", "262144", "0.2", MISE, "--", "ls", "--json", "--current"], timeout=25)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        stripped = proc.stdout.strip()
        self.assertTrue(stripped.startswith(b"{") or stripped.startswith(b"["), proc.stdout[:80])

    def test_overflow_caps_stdout(self):
        if not os.path.isfile(MISE):
            self.skipTest("mise not installed at /usr/bin/mise")
        proc = run_helper(["5", "1", "0.2", MISE, "--", "--version"])
        self.assertEqual(proc.returncode, 125, proc.stderr)
        self.assertLessEqual(len(proc.stdout), 1)

    def test_timeout_kills_group(self):
        child = subprocess.Popen(
            [PYTHON, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            pidfd = os.pidfd_open(child.pid)
        except OSError:
            child.kill()
            child.wait(timeout=2)
            self.fail("pidfd_open failed")
        try:
            start = time.monotonic()
            overflow = supervise.supervise_child(child, pidfd, 262144, 0.05, 0.2)
            elapsed = time.monotonic() - start
            self.assertFalse(overflow)
            self.assertEqual(supervise.stop_reason, "timeout")
            self.assertIsNotNone(child.returncode)
            self.assertLess(elapsed, 3.0)
        finally:
            try:
                os.close(pidfd)
            except OSError:
                pass
            if child.poll() is None:
                child.kill()
                child.wait(timeout=2)
            if child.stdout is not None:
                child.stdout.close()

    def test_sigterm_reaps(self):
        script = (
            "import os, signal, subprocess, sys, importlib.util\n"
            "spec = importlib.util.spec_from_file_location('supervise', sys.argv[1])\n"
            "supervise = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(supervise)\n"
            "signal.signal(signal.SIGTERM, supervise.on_signal)\n"
            "child = subprocess.Popen(\n"
            "    [sys.executable, '-c', 'import time; time.sleep(30)'],\n"
            "    start_new_session=True,\n"
            "    stdin=subprocess.DEVNULL,\n"
            "    stdout=subprocess.PIPE,\n"
            "    stderr=subprocess.DEVNULL,\n"
            ")\n"
            "try:\n"
            "    pidfd = os.pidfd_open(child.pid)\n"
            "except OSError:\n"
            "    child.kill()\n"
            "    child.wait()\n"
            "    sys.exit(1)\n"
            "sys.stdout.buffer.write(b'r')\n"
            "sys.stdout.buffer.flush()\n"
            "try:\n"
            "    supervise.supervise_child(child, pidfd, 262144, 15.0, 0.2)\n"
            "finally:\n"
            "    if child.poll() is None:\n"
            "        child.kill()\n"
            "        child.wait()\n"
            "sys.exit(143 if supervise.stop_reason == 'signal' else 1)\n"
        )
        proc = subprocess.Popen(
            [PYTHON, "-c", script, HELPER],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            ready = proc.stdout.read(1)
            self.assertEqual(ready, b"r", proc.stderr)
            proc.send_signal(signal.SIGTERM)
            try:
                rc = proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                self.fail("supervisor did not exit after SIGTERM")
            self.assertNotEqual(rc, 0)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=2)
            if proc.stdout is not None:
                proc.stdout.close()
            if proc.stderr is not None:
                proc.stderr.close()

    def test_terminate_group_already_exited_does_not_kill_later_session(self):
        child = subprocess.Popen(
            [PYTHON, "-c", "pass"],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            pidfd = os.pidfd_open(child.pid)
        except OSError:
            child.kill()
            child.wait(timeout=2)
            self.fail("pidfd_open failed")
        sleeper = None
        try:
            deadline = time.monotonic() + 2.0
            exited = False
            while time.monotonic() < deadline:
                try:
                    info = os.waitid(
                        os.P_PIDFD, pidfd, os.WEXITED | os.WNOHANG | os.WNOWAIT
                    )
                except OSError:
                    info = None
                if info is not None and getattr(info, "si_pid", 0):
                    exited = True
                    break
                time.sleep(0.01)
            self.assertTrue(exited, "child did not exit before terminate_group")

            sleeper = subprocess.Popen(
                [PYTHON, "-c", "import time; time.sleep(30)"],
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            recorded = []
            real_killpg = os.killpg

            def spy(pgid, sig):
                recorded.append((pgid, sig))
                return real_killpg(pgid, sig)

            supervise.os.killpg = spy
            try:
                supervise.terminate_group(child, pidfd, 0.2)
            finally:
                supervise.os.killpg = real_killpg

            self.assertIsNone(sleeper.poll())
            os.kill(sleeper.pid, 0)
            self.assertFalse(
                any(sig == signal.SIGKILL for _pgid, sig in recorded),
                recorded,
            )
        finally:
            try:
                os.close(pidfd)
            except OSError:
                pass
            if sleeper is not None and sleeper.poll() is None:
                sleeper.kill()
                sleeper.wait(timeout=2)
            if child.poll() is None:
                child.kill()
                child.wait(timeout=2)

    def test_terminate_group_pidfd_none_does_not_killpg(self):
        child = subprocess.Popen(
            [PYTHON, "-c", "pass"],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        child.wait(timeout=2)
        sleeper = subprocess.Popen(
            [PYTHON, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        recorded = []
        real_killpg = os.killpg

        def spy(pgid, sig):
            recorded.append((pgid, sig))
            return real_killpg(pgid, sig)

        supervise.os.killpg = spy
        try:
            supervise.terminate_group(child, None, 0.2)
            self.assertIsNone(sleeper.poll())
            os.kill(sleeper.pid, 0)
            self.assertEqual(recorded, [])
        finally:
            supervise.os.killpg = real_killpg
            if sleeper.poll() is None:
                sleeper.kill()
            sleeper.wait(timeout=2)

    def test_terminate_group_kills_process_ignoring_sigterm(self):
        child = subprocess.Popen(
            [
                PYTHON,
                "-c",
                "import signal, sys, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); sys.stdout.write(\"r\"); sys.stdout.flush(); time.sleep(30)",
            ],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            pidfd = os.pidfd_open(child.pid)
        except OSError:
            child.kill()
            child.wait(timeout=2)
            self.fail("pidfd_open failed")
        try:
            ready = child.stdout.read(1)
            self.assertEqual(ready, b"r")
            start = time.monotonic()
            supervise.terminate_group(child, pidfd, 0.2)
            elapsed = time.monotonic() - start
            self.assertEqual(child.returncode, -signal.SIGKILL)
            self.assertLess(elapsed, 3.0)
        finally:
            try:
                os.close(pidfd)
            except OSError:
                pass
            if child.poll() is None:
                child.kill()
                child.wait(timeout=2)

    def test_terminate_group_kills_live_descendant_after_leader_exits(self):
        code = (
            "import os, signal, time\n"
            "pid = os.fork()\n"
            "if pid == 0:\n"
            "    try:\n"
            "        os.close(1)\n"
            "    except OSError:\n"
            "        pass\n"
            "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "    time.sleep(30)\n"
            "    os._exit(0)\n"
            "os.write(1, str(pid).encode())\n"
            "try:\n"
            "    os.close(1)\n"
            "except OSError:\n"
            "    pass\n"
            "os._exit(0)\n"
        )
        child = subprocess.Popen(
            [PYTHON, "-c", code],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            pidfd = os.pidfd_open(child.pid)
        except OSError:
            child.kill()
            child.wait(timeout=2)
            self.fail("pidfd_open failed")
        gc_pid = None
        try:
            raw = child.stdout.read(32)
            gc_pid = int(raw.decode().strip())
            deadline = time.monotonic() + 2.0
            exited = False
            while time.monotonic() < deadline:
                try:
                    info = os.waitid(
                        os.P_PIDFD, pidfd, os.WEXITED | os.WNOHANG | os.WNOWAIT
                    )
                except OSError:
                    info = None
                if info is not None and getattr(info, "si_pid", 0):
                    exited = True
                    break
                time.sleep(0.01)
            self.assertTrue(exited, "leader did not exit")
            os.kill(gc_pid, 0)
            supervise.terminate_group(child, pidfd, 0.2)
            dead = False
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                try:
                    os.kill(gc_pid, 0)
                except ProcessLookupError:
                    dead = True
                    break
                time.sleep(0.02)
            if not dead:
                try:
                    os.kill(gc_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.fail("descendant still alive after terminate_group")
        finally:
            try:
                os.close(pidfd)
            except OSError:
                pass
            if gc_pid is not None:
                try:
                    os.kill(gc_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if child.poll() is None:
                child.kill()
                child.wait(timeout=2)

    def test_leader_has_exited_none_is_not_exited(self):
        exited, certain = supervise.leader_has_exited(None)
        self.assertFalse(exited)
        self.assertFalse(certain)
        self.assertTrue(supervise.group_needs_kill(None, 1))

    def test_leader_has_exited_waitid_error_is_not_exited(self):
        real_waitid = supervise.os.waitid

        def boom(*_a, **_k):
            raise OSError(errno.EBADF, "Bad file descriptor")

        supervise.os.waitid = boom
        try:
            exited, certain = supervise.leader_has_exited(7)
            self.assertFalse(exited)
            self.assertFalse(certain)
            self.assertTrue(supervise.group_needs_kill(7, 1))
        finally:
            supervise.os.waitid = real_waitid

    def test_pgid_has_live_members_listdir_error_is_uncertain(self):
        real_listdir = supervise.os.listdir

        def boom(_path):
            raise OSError(errno.EIO, "I/O error")

        supervise.os.listdir = boom
        try:
            has_live, certain = supervise.pgid_has_live_members(os.getpgrp())
            self.assertFalse(certain)
        finally:
            supervise.os.listdir = real_listdir

    def test_pgid_stat_read_error_is_uncertain(self):
        import builtins

        real_open = builtins.open

        def fake_open(path, *a, **k):
            if isinstance(path, str) and path.startswith("/proc/") and path.endswith("/stat"):
                raise OSError(errno.EACCES, "Permission denied")
            return real_open(path, *a, **k)

        supervise.open = fake_open
        try:
            has_live, certain = supervise.pgid_has_live_members(os.getpgrp())
            self.assertFalse(certain)
        finally:
            del supervise.open

    def test_pgid_observation_error_requires_cleanup(self):
        child = subprocess.Popen(
            [PYTHON, "-c", "pass"],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            pidfd = os.pidfd_open(child.pid)
        except OSError:
            child.kill()
            child.wait(timeout=2)
            self.fail("pidfd_open failed")
        try:
            deadline = time.monotonic() + 2.0
            exited = False
            certain = False
            while time.monotonic() < deadline:
                exited, certain = supervise.leader_has_exited(pidfd)
                if certain and exited:
                    break
                time.sleep(0.01)
            self.assertTrue(certain and exited, "child did not exit")
            real_listdir = supervise.os.listdir

            def boom(_path):
                raise OSError(errno.EIO, "I/O error")

            supervise.os.listdir = boom
            try:
                has_live, live_certain = supervise.pgid_has_live_members(child.pid)
                self.assertFalse(live_certain)
                self.assertTrue(supervise.group_needs_kill(pidfd, child.pid))
            finally:
                supervise.os.listdir = real_listdir
        finally:
            try:
                os.close(pidfd)
            except OSError:
                pass
            if child.poll() is None:
                child.kill()
                child.wait(timeout=2)
            if child.stdout is not None:
                child.stdout.close()

    def test_terminate_group_pidfd_none_kills_unreaped_child(self):
        child = subprocess.Popen(
            [PYTHON, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            start = time.monotonic()
            supervise.terminate_group(child, None, 0.2)
            elapsed = time.monotonic() - start
            self.assertIsNotNone(child.returncode)
            self.assertLess(elapsed, 3.0)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=2)
            if child.stdout is not None:
                child.stdout.close()

    def test_spawn_bound_mise_pidfd_failure_kills_child(self):
        spawned = []
        real_popen = supervise.subprocess.Popen
        real_pidfd_open = supervise.os.pidfd_open

        def fake_popen(*_a, **_k):
            proc = real_popen(
                [PYTHON, "-c", "import time; time.sleep(30)"],
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            spawned.append(proc)
            return proc

        def boom(_pid, *_a, **_k):
            raise OSError(errno.EMFILE, "Too many open files")

        supervise.subprocess.Popen = fake_popen
        supervise.os.pidfd_open = boom
        start = time.monotonic()
        try:
            with self.assertRaises(SystemExit) as cm:
                supervise.spawn_bound_mise(0, ["--version"], 0.2)
            elapsed = time.monotonic() - start
            self.assertEqual(cm.exception.code, 1)
            self.assertEqual(len(spawned), 1)
            child = spawned[0]
            self.assertIsNotNone(child.returncode)
            self.assertLess(elapsed, 3.0)
        finally:
            supervise.subprocess.Popen = real_popen
            supervise.os.pidfd_open = real_pidfd_open
            for proc in spawned:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=2)
                if proc.stdout is not None:
                    proc.stdout.close()


if __name__ == "__main__":
    unittest.main()
