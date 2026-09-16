"""DDS domain / transport splits between running ROS processes.

THE FAULT. Healthy bridges, arms answering, a window showing nothing: "bridge
up but no data". A per-arm CONNECT script did `export ROS_DOMAIN_ID=7`
unconditionally while the GUI ran on domain 0, so every connect put the bridge
on a graph the window could never see. DDS has no way to say so. The pin was
justified by a comment claiming domain 0 was "polluted"; re-measured, domain 0
and domain 7 both delivered 27/27. The workaround outlived its cause and split
the system in half for weeks.

The check reads the environment each ROS process is ACTUALLY using, from
/proc/<pid>/environ, not from a config file that may since have been edited.
"""
from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass

from .report import Finding, Status

KEYS = ("ROS_DOMAIN_ID", "RMW_IMPLEMENTATION", "FASTDDS_BUILTIN_TRANSPORTS",
        "ROS_LOCALHOST_ONLY", "ROS_AUTOMATIC_DISCOVERY_RANGE")
DEFAULT_MATCH = re.compile(
    r"ros2|--ros-args|rclpy|rclcpp|rmw|/opt/ros/|install/|move_group|controller_manager|"
    r"robot_state_publisher|ros2_control_node|rviz|gazebo|gz sim|ign gazebo", re.I)
SELF_MATCH = re.compile(r"ros2_wsl_doctor|ddsdetective-ros2")
# The ros2 CLI starts one daemon PER DOMAIN it has been asked about, so two
# daemons on two domains are not a split; they are reported separately.
DAEMON_MATCH = re.compile(r"ros2cli\.daemon")


@dataclass
class RosProc:
    pid: int
    name: str
    env: dict

    def key(self) -> tuple:
        e = self.env
        return (e.get("ROS_DOMAIN_ID", "0") or "0",
                e.get("RMW_IMPLEMENTATION", "(default)"),
                e.get("FASTDDS_BUILTIN_TRANSPORTS", "(default)"),
                e.get("ROS_LOCALHOST_ONLY", "(unset)"),
                e.get("ROS_AUTOMATIC_DISCOVERY_RANGE", "(default)"))


def read_environ(path: str) -> dict:
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return {}
    env = {}
    for item in raw.split(b"\0"):
        if b"=" in item:
            k, v = item.split(b"=", 1)
            env[k.decode(errors="replace")] = v.decode(errors="replace")
    return env


def read_cmdline(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            return fh.read().replace(b"\0", b" ").decode(errors="replace").strip()
    except OSError:
        return ""


def scan(proc_root: str = "/proc", match: re.Pattern | None = None,
         skip_pids: set[int] | None = None, include_daemons: bool = False) -> list[RosProc]:
    match = match or DEFAULT_MATCH
    skip = skip_pids if skip_pids is not None else {os.getpid(), os.getppid()}
    out = []
    try:
        pids = sorted(int(p) for p in os.listdir(proc_root) if p.isdigit())
    except OSError:
        return out
    for pid in pids:
        if pid in skip:
            continue
        cmd = read_cmdline(os.path.join(proc_root, str(pid), "cmdline"))
        if not cmd or not match.search(cmd) or SELF_MATCH.search(cmd):
            continue
        if (DAEMON_MATCH.search(cmd) is not None) != include_daemons:
            continue
        env = read_environ(os.path.join(proc_root, str(pid), "environ"))
        if not env:
            continue  # not ours to read (permission) or gone
        name = cmd.split()[0].rsplit("/", 1)[-1]
        # python launchers: show the module/script instead of "python3"
        parts = cmd.split()
        if name.startswith("python") and len(parts) > 1:
            name = parts[1].rsplit("/", 1)[-1] if parts[1] != "-m" else parts[2]
        out.append(RosProc(pid, name[:40], {k: env[k] for k in KEYS if k in env}))
    return out


def group(procs: list[RosProc]) -> dict[tuple, list[RosProc]]:
    g: dict[tuple, list[RosProc]] = defaultdict(list)
    for p in procs:
        g[p.key()].append(p)
    return dict(g)


def shell_key(environ: dict | None = None) -> tuple:
    e = os.environ if environ is None else environ
    return RosProc(0, "shell", {k: e[k] for k in KEYS if k in e}).key()


def describe(key: tuple) -> str:
    dom, rmw, tr, lo, rng = key
    return f"domain {dom}, rmw {rmw}, transports {tr}, localhost_only {lo}, range {rng}"


def check(proc_root: str = "/proc", match: str | None = None,
          shell_env: dict | None = None) -> Finding:
    pat = re.compile(match, re.I) if match else None
    procs = scan(proc_root, pat)
    daemons = scan(proc_root, pat, include_daemons=True)
    daemon_note = (["ros2 daemon(s): " + ", ".join(
        "pid %d on domain %s" % (d.pid, d.env.get("ROS_DOMAIN_ID", "0") or "0") for d in daemons)
        + "  (one per domain queried; not counted as a split)"] if daemons else [])
    if not procs:
        return Finding("env-split", Status.SKIP,
                       "no running ROS processes found (nothing to compare)",
                       details=daemon_note)
    groups = group(procs)
    details = list(daemon_note)
    for k, ps in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        details.append("%d proc(s): %s" % (len(ps), describe(k)))
        for p in ps[:6]:
            details.append("    pid %-7d %s" % (p.pid, p.name))
        if len(ps) > 6:
            details.append("    ... and %d more" % (len(ps) - 6))
    lo = [p for p in procs if p.env.get("ROS_LOCALHOST_ONLY") not in (None, "", "0")]
    majority = max(groups.items(), key=lambda kv: len(kv[1]))[0]
    sk = shell_key(shell_env)
    shell_note = []
    if sk != majority:
        shell_note.append("THIS SHELL differs from the running stack: shell is %s"
                          % describe(sk))
        shell_note.append("  a node started from here will not see the stack")
    if len(groups) > 1:
        doms = sorted({k[0] for k in groups})
        what = "DDS domain split" if len(doms) > 1 else "DDS transport/discovery split"
        return Finding(
            "env-split", Status.FAIL,
            "%s: %d running ROS process groups cannot see each other" % (what, len(groups)),
            fix="export ROS_DOMAIN_ID=%s RMW_IMPLEMENTATION=%s FASTDDS_BUILTIN_TRANSPORTS=%s"
                "  # the majority group; restart the minority under it"
                % (majority[0],
                   majority[1] if majority[1] != "(default)" else "rmw_fastrtps_cpp",
                   majority[2] if majority[2] != "(default)" else "UDPv4"),
            details=details + shell_note
            + (["ROS_LOCALHOST_ONLY is set on %d process(es): deprecated in Jazzy, and "
                "applied to only some processes it causes the very partition it is meant "
                "to prevent" % len(lo)] if lo else []))
    if lo:
        return Finding("env-split", Status.WARN,
                       "one group, but ROS_LOCALHOST_ONLY is set on %d process(es)" % len(lo),
                       fix="unset ROS_LOCALHOST_ONLY  (deprecated in Jazzy; half-applied it "
                           "partitions the graph; use ROS_AUTOMATIC_DISCOVERY_RANGE)",
                       details=details + shell_note)
    if shell_note:
        return Finding("env-split", Status.WARN,
                       "%d ROS process(es) agree (%s) but this shell does not"
                       % (len(procs), describe(majority)),
                       fix="export ROS_DOMAIN_ID=%s   # join the running stack" % majority[0],
                       details=details + shell_note)
    return Finding("env-split", Status.PASS,
                   "%d ROS process(es) and this shell agree: %s" % (len(procs), describe(majority)),
                   details=details)
