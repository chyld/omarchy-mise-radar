"""Controlled responses for the QML integration test; never invokes mise."""
import json
import pathlib
import sys
import time

import os
import stat

assert sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode
assert os.environ["PATH"] == "/usr/bin:/bin"
assert "GITHUB_TOKEN" not in os.environ and "PYTHONPATH" not in os.environ

# Test-only counter inside the runner's fresh private directory. Validate and
# update the held descriptor, never follow a replaced file or block on a FIFO.
counter = pathlib.Path(__file__).with_name('calls.json')
fd = os.open(counter, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
try:
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_nlink != 1 or st.st_mode & 0o077:
        raise ValueError("unsafe test counter")
    raw = os.read(fd, 257)
    if len(raw) > 256:
        raise ValueError("oversize test counter")
    state = json.loads(raw) if raw else {'ls': 0, 'outdated': 0}
    kind = sys.argv[6]
    state[kind] += 1
    payload = json.dumps(state).encode()
    if os.pwrite(fd, payload, 0) != len(payload):
        raise OSError("short counter write")
    os.ftruncate(fd, len(payload))
finally:
    os.close(fd)
run = state['ls']
if kind == 'ls':
    if run == 6:
        print('{"node": "invalid versions"}')
    else:
        print(json.dumps({'node': [{'active': True, 'installed': True, 'version': '1.0', 'requested_version': 'latest'}]}))
else:
    if run in (1, 3):
        print('{"node": "invalid record"}')
    elif run == 4:
        print('not JSON')
    elif run == 5:
        sys.exit(1)
    elif run == 7:
        sys.exit(124)
    elif run == 8:
        # Deliberately violate the helper contract to test the QML fallback.
        for _ in range(40):
            sys.stdout.write('x' * 8192)
            sys.stdout.flush()
    elif run == 10:
        time.sleep(30)
    elif run == 9:
        print('{}')
    else:
        print(json.dumps({'node': {'latest': '2.0'}}))
