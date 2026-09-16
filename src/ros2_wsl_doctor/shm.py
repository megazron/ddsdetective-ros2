"""Orphaned FastDDS shared-memory segments.

THE FAULT. Every node is up and publishing to each other perfectly, and a
FRESH process sees an empty graph: `ros2 topic list` hangs, `ros2 topic hz`
reports nothing on a topic that is plainly flowing. FastDDS creates a segment
per participant in /dev/shm; a process that dies without cleaning up (SIGKILL,
a crash, a killed launch) leaves it behind. They accumulate and discovery for
a NEW participant has to wade through all of them.

WHY THE CHECK IS SAFE. A segment is ORPHANED only if no live process
references it. Both /proc/<pid>/fd and /proc/<pid>/maps are consulted, because
FastDDS mmaps its segments and can close the descriptor afterwards; an
fd-only check would delete a segment a running node is mapping, which breaks
the working half of the stack while fixing the broken half. On top of that an
AGE FLOOR applies: a process that is still starting has segments it has not
mapped yet, and they look unowned for a few seconds. Measured on the rig that
motivated this: a sweep without the floor destroyed a starting simulation.

WHY NOT `rm -f /dev/shm/fastrtps_*`. The ros2 daemon is a participant and its
segments are in there too. Sweep them and the daemon does not die, it goes
DEAF: `ros2 node list` returns nothing against a healthy stack and the next
preflight blames the simulation. That cost an afternoon.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass

from .report import Finding, Status

SEGMENT_RE = re.compile(r"^(sem\.)?(fastrtps|fastdds)[A-Za-z0-9_.\-]*$")
DEFAULT_AGE_FLOOR_S = 20.0


@dataclass
class ShmSurvey:
    total: list[str]
    in_use: list[str]
    orphaned: list[str]
    too_young: list[str]

    def as_details(self) -> list[str]:
        return [f"total segments      {len(self.total)}",
                f"in use (live proc)  {len(self.in_use)}",
                f"too young to judge  {len(self.too_young)}",
                f"ORPHANED            {len(self.orphaned)}"]


def referenced_names(proc_root: str = "/proc") -> set[str]:
    """Every /dev/shm object name a live process has open OR mapped."""
    names: set[str] = set()
    try:
        pids = [p for p in os.listdir(proc_root) if p.isdigit()]
    except OSError:
        return names
    for pid in pids:
        fd_dir = os.path.join(proc_root, pid, "fd")
        try:
            for fd in os.listdir(fd_dir):
                try:
                    t = os.readlink(os.path.join(fd_dir, fd))
                except OSError:
                    continue
                if "/dev/shm/" in t:
                    names.add(os.path.basename(t.split(" (deleted)")[0]))
        except OSError:
            pass
        try:
            with open(os.path.join(proc_root, pid, "maps")) as fh:
                for line in fh:
                    i = line.find("/dev/shm/")
                    if i != -1:
                        names.add(os.path.basename(
                            line[i:].strip().split(" (deleted)")[0]))
        except OSError:
            pass
    return names


def survey(shm_root: str = "/dev/shm", proc_root: str = "/proc",
           age_floor_s: float = DEFAULT_AGE_FLOOR_S,
           now: float | None = None) -> ShmSurvey:
    now = time.time() if now is None else now
    try:
        names = sorted(n for n in os.listdir(shm_root) if SEGMENT_RE.match(n))
    except OSError:
        return ShmSurvey([], [], [], [])
    live = referenced_names(proc_root)
    in_use, orphaned, young = [], [], []
    for n in names:
        if n in live:
            in_use.append(n)
            continue
        try:
            age = now - os.stat(os.path.join(shm_root, n)).st_mtime
        except OSError:
            continue
        (young if age < age_floor_s else orphaned).append(n)
    return ShmSurvey(names, in_use, orphaned, young)


def daemon_running() -> bool:
    try:
        out = subprocess.run(["pgrep", "-f", "ros2cli.daemon"], capture_output=True,
                             text=True, timeout=5)
        return out.returncode == 0 and out.stdout.strip() != ""
    except (OSError, subprocess.TimeoutExpired):
        return False


def _ancestors() -> set[int]:
    """This process and everything above it; never a kill target."""
    out, pid = set(), os.getpid()
    while pid > 1:
        out.add(pid)
        try:
            with open("/proc/%d/stat" % pid) as fh:
                pid = int(fh.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return out


def kill_daemon_processes(proc_root: str = "/proc") -> list[int]:
    """SIGINT the ros2 daemon processes by PID. Own rule: never `pkill -f` a
    broad pattern, because the pattern can match the shell that called us."""
    import signal
    killed = []
    skip = _ancestors()
    try:
        pids = [int(p) for p in os.listdir(proc_root) if p.isdigit()]
    except OSError:
        return killed
    for pid in pids:
        if pid in skip:
            continue
        try:
            with open(os.path.join(proc_root, str(pid), "cmdline"), "rb") as fh:
                cmd = fh.read()
        except OSError:
            continue
        # the daemon's argv is `python3 -c from ros2cli.daemon.daemonize import main; ...`
        if b"ros2cli" in cmd and b"daemonize import main" in cmd:
            try:
                os.kill(pid, signal.SIGINT)
                killed.append(pid)
            except OSError:
                pass
    return killed


def restart_daemon() -> str:
    """Stop, then start, the ros2 daemon; each step under timeout."""
    if not shutil.which("ros2"):
        return "ros2 not on PATH; daemon not restarted"
    subprocess.run(["timeout", "-s", "INT", "10", "ros2", "daemon", "stop"],
                   capture_output=True)
    kill_daemon_processes()
    time.sleep(2)
    subprocess.run(["timeout", "-s", "INT", "25", "ros2", "daemon", "start"],
                   capture_output=True)
    return "ros2 daemon restarted"


def delete_orphans(s: ShmSurvey, shm_root: str = "/dev/shm") -> tuple[int, int, float]:
    removed = failed = 0
    freed = 0.0
    for n in s.orphaned:
        p = os.path.join(shm_root, n)
        try:
            freed += os.path.getsize(p)
        except OSError:
            pass
        try:
            os.unlink(p)
            removed += 1
        except OSError:
            failed += 1
    return removed, failed, freed / (1024.0 * 1024.0)


def check(fix: bool = False, restart: bool = False, shm_root: str = "/dev/shm",
          proc_root: str = "/proc", age_floor_s: float = DEFAULT_AGE_FLOOR_S) -> Finding:
    s = survey(shm_root, proc_root, age_floor_s)
    details = s.as_details()
    if not s.total:
        return Finding("shm", Status.PASS, "no FastDDS segments in %s" % shm_root,
                       details=details)
    if not s.orphaned:
        msg = "%d FastDDS segment(s), all referenced by a live process" % len(s.total)
        if s.too_young:
            msg += " (%d younger than %.0f s, left alone)" % (len(s.too_young), age_floor_s)
        return Finding("shm", Status.PASS, msg, details=details)
    if not fix:
        return Finding(
            "shm", Status.FAIL,
            "%d orphaned FastDDS segment(s) in %s; new participants must wade through them"
            % (len(s.orphaned), shm_root),
            fix="ros2-wsl-doctor shm --fix   (deletes only the orphans; add --restart-daemon "
                "if a ros2 daemon is running)",
            details=details + ["  " + n for n in s.orphaned[:8]]
            + (["  ... and %d more" % (len(s.orphaned) - 8)] if len(s.orphaned) > 8 else [])
            + ["do NOT `rm -f /dev/shm/fastrtps_*`: that deletes the running ros2 daemon's "
               "own segments and it goes deaf rather than dying"])
    had_daemon = daemon_running()
    note = []
    if had_daemon and restart:
        subprocess.run(["timeout", "-s", "INT", "10", "ros2", "daemon", "stop"],
                       capture_output=True)
        kill_daemon_processes()
        # what the daemon owned is now unreferenced: re-survey after it is gone
        time.sleep(1)
        s = survey(shm_root, proc_root, age_floor_s=0.0)
    removed, failed, mib = delete_orphans(s, shm_root)
    if had_daemon and restart:
        time.sleep(2)
        note.append(restart_daemon())
    elif had_daemon:
        note.append("a ros2 daemon is running and was left alone (its segments were "
                    "referenced, so they were kept); pass --restart-daemon to cycle it")
    status = Status.PASS if failed == 0 else Status.WARN
    return Finding("shm", status,
                   "removed %d orphan(s), %.1f MiB freed%s"
                   % (removed, mib, (", %d failed" % failed) if failed else ""),
                   details=details + note + ["already-running nodes are untouched; discovery "
                                             "for NEW processes recovers immediately"])
