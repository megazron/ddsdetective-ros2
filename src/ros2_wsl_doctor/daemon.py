"""A stale ros2 daemon.

THE FAULT. After switching WSL to mirrored networking, one terminal reported
"No ROS 2 nodes at all" while another ran a healthy stack. There was no
discovery partition: `ros2 node list --no-daemon` saw all 28 nodes the whole
time. The ros2 daemon caches network state, did not survive the interface
change, and HUNG rather than failing, so `timeout 20 ros2 node list` returned
an empty string, which reads as "nothing is running".
"""
from __future__ import annotations

import shutil
import subprocess

from .report import Finding, Status


def _run(cmd: list[str], timeout: float) -> tuple[str, bool]:
    """(stdout, timed_out)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout, False
    except subprocess.TimeoutExpired:
        return "", True
    except OSError:
        return "", True


def daemon_pids() -> list[str]:
    try:
        r = subprocess.run(["pgrep", "-f", "ros2cli.daemon"], capture_output=True,
                           text=True, timeout=5)
        return [p for p in r.stdout.split() if p.strip()]
    except (OSError, subprocess.TimeoutExpired):
        return []


def check(daemon_timeout: float = 8.0, nodaemon_timeout: float = 25.0,
          runner=_run, have_ros2: bool | None = None, pids=None) -> Finding:
    have = shutil.which("ros2") is not None if have_ros2 is None else have_ros2
    if not have:
        return Finding("daemon", Status.SKIP, "ros2 not on PATH (source your ROS 2 setup first)")
    pids = daemon_pids() if pids is None else pids
    via_daemon, d_to = runner(["ros2", "node", "list"], daemon_timeout)
    truth, t_to = runner(["ros2", "node", "list", "--no-daemon"], nodaemon_timeout)
    n_d = [l for l in via_daemon.split("\n") if l.strip()]
    n_t = [l for l in truth.split("\n") if l.strip()]
    details = ["daemon process(es): %s" % (", ".join(pids) if pids else "none"),
               "via daemon:  %s" % ("TIMED OUT after %.0f s" % daemon_timeout if d_to
                                     else "%d node(s)" % len(n_d)),
               "--no-daemon: %s" % ("TIMED OUT after %.0f s" % nodaemon_timeout if t_to
                                     else "%d node(s)" % len(n_t))]
    if (d_to or not n_d) and n_t:
        return Finding("daemon", Status.FAIL,
                       "stale ros2 daemon: it %s while --no-daemon sees %d node(s)"
                       % ("hung" if d_to else "returned nothing", len(n_t)),
                       fix="ros2 daemon stop && ros2 daemon start   "
                           "(ground truth: ros2 node list --no-daemon)",
                       details=details)
    if d_to and t_to:
        return Finding("daemon", Status.FAIL,
                       "both the daemon and --no-daemon hung: discovery itself is wedged",
                       fix="ddsdetective-ros2 shm; then check env-split; then "
                           "FASTDDS_BUILTIN_TRANSPORTS", details=details)
    if not n_d and not n_t:
        return Finding("daemon", Status.PASS, "no nodes running (daemon and --no-daemon agree)",
                       details=details)
    if len(n_d) != len(n_t):
        return Finding("daemon", Status.WARN,
                       "daemon sees %d node(s), --no-daemon sees %d" % (len(n_d), len(n_t)),
                       fix="ros2 daemon stop && ros2 daemon start", details=details)
    return Finding("daemon", Status.PASS, "ros2 daemon agrees with --no-daemon: %d node(s)"
                   % len(n_d), details=details)
