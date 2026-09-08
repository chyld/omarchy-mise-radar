#!/usr/bin/python3
"""Exercise real QML with controlled responses in a fresh private directory.

Requires Omarchy/Quickshell and Wayland. No installed plugin or mise config is
modified. Test processes, combined output and execution time are bounded.
"""
from pathlib import Path
import os
import runpy
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    supervisor = runpy.run_path(str(ROOT / 'supervise.py'))
    shell = Path('/usr/share/omarchy/shell')
    with tempfile.TemporaryDirectory(prefix='mise-radar-test-') as directory:
        target = Path(directory)
        plugin = target / 'plugin'
        plugin.mkdir()
        for name in ('BarWidget.qml', 'Panel.qml', 'Service.qml', 'Model.js', 'qmldir'):
            shutil.copy2(ROOT / name, plugin / name)
        shutil.copy2(ROOT / 'tests/qml/fake_supervise.py', plugin / 'supervise.py')
        shutil.copy2(ROOT / 'tests/qml/shell.qml', target / 'shell.qml')
        for name in ('Ui', 'Commons'):
            (target / name).symlink_to(shell / name, target_is_directory=True)
        environment = dict(os.environ,
            RADAR_TEST_PROBE_MS=str(int(supervisor['VERSION_TIMEOUT_SEC'] * 1000)),
            RADAR_TEST_REAP_MS=str(int(supervisor['REAP_TIMEOUT_SEC'] * 1000)),
            PYTHONPATH=str(target), GITHUB_TOKEN='test-only-sentinel')
        proc = subprocess.Popen(['/usr/bin/qs', '-p', str(target), '--no-color'],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=True, env=environment)
        try:
            pidfd = os.pidfd_open(proc.pid)
        except OSError:
            supervisor['terminate_group'](proc, None, 0.2)
            raise
        output = bytearray()
        overflow = supervisor['supervise_child'](proc, pidfd, 262144, 20, 0.2, dest=output)
        text = output.decode('utf-8', 'replace')
        print(text, end='')
        if overflow or proc.returncode or 'FAIL ' in text or 'PASS service errors' not in text:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
