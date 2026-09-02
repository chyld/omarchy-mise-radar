#!/usr/bin/python3
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
        if not os.path.isfile(MISE):
            self.skipTest("mise not installed at /usr/bin/mise")
        start = time.monotonic()
        proc = run_helper(["0.05", "262144", "0.2", MISE, "--", "outdated", "--bump", "--json"], timeout=10)
        elapsed = time.monotonic() - start
        self.assertEqual(proc.returncode, 124, proc.stderr)
        self.assertLess(elapsed, 3.0)
        self.assertLessEqual(len(proc.stdout), 262144)

    def test_sigterm_reaps(self):
        if not os.path.isfile(MISE):
            self.skipTest("mise not installed at /usr/bin/mise")
        cmd = [PYTHON, HELPER, "15", "262144", "0.2", MISE, "--", "outdated", "--bump", "--json"]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            time.sleep(0.15)
            proc.send_signal(signal.SIGTERM)
            try:
                rc = proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                self.fail("supervisor did not exit after SIGTERM")
            self.assertNotEqual(rc, 0)
        finally:
            if proc.stdout is not None:
                proc.stdout.close()
            if proc.stderr is not None:
                proc.stderr.close()


if __name__ == "__main__":
    unittest.main()
