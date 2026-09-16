import os
import time

import pytest


def make_proc(root, pid, cmdline, environ=None, fds=(), maps=()):
    """A fake /proc/<pid> with cmdline, environ, fd/ symlinks and a maps file."""
    d = os.path.join(root, str(pid))
    os.makedirs(os.path.join(d, "fd"), exist_ok=True)
    with open(os.path.join(d, "cmdline"), "wb") as fh:
        fh.write("\0".join(cmdline.split()).encode() + b"\0")
    with open(os.path.join(d, "environ"), "wb") as fh:
        fh.write(b"".join(f"{k}={v}".encode() + b"\0" for k, v in (environ or {}).items()))
    for i, target in enumerate(fds):
        os.symlink(target, os.path.join(d, "fd", str(i)))
    with open(os.path.join(d, "maps"), "w") as fh:
        for m in maps:
            fh.write(f"7f00000 rw-s 0 00:1a 1 {m}\n")
    return d


@pytest.fixture
def fake_env(tmp_path):
    proc = tmp_path / "proc"
    shm = tmp_path / "shm"
    proc.mkdir()
    shm.mkdir()
    return str(proc), str(shm)


def touch_segment(shm_root, name, age_s):
    p = os.path.join(shm_root, name)
    with open(p, "wb") as fh:
        fh.write(b"x" * 64)
    t = time.time() - age_s
    os.utime(p, (t, t))
    return p
