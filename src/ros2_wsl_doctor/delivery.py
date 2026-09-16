"""Prove delivery instead of inferring it.

`ros2 topic info` listing a publisher proves nothing about arrival. Count
messages that ARRIVE over a window. Two tools: a minimal pub/sub round trip on
a chosen domain, and a QoS check for the RELIABLE-subscriber-vs-BEST_EFFORT-
publisher mismatch, which DDS answers with silence and one easily missed
warning line ("incompatible QoS ... RELIABILITY").
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import uuid

from .report import Finding, Status


def _stop(proc: subprocess.Popen, grace_s: float = 3.0) -> None:
    """SIGINT, wait, then SIGKILL. The ros2 CLI shuts its participant down
    cleanly on SIGINT; anything harsher leaves the segments this tool exists to
    find, and a child that ignores SIGTERM would keep publishing after we exit."""
    import signal
    if proc.poll() is not None:
        return
    try:
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=grace_s)
    except (subprocess.TimeoutExpired, OSError):
        try:
            proc.kill()
            proc.wait(timeout=grace_s)
        except (subprocess.TimeoutExpired, OSError):
            pass


def delivery_test(domain: int | None = None, expected: int = 10, rate_hz: float = 10.0,
                  timeout_s: float = 20.0) -> Finding:
    if not shutil.which("ros2"):
        return Finding("delivery", Status.SKIP, "ros2 not on PATH")
    env = dict(os.environ)
    # the ros2 CLI is Python: when its stdout is a pipe it block-buffers, and
    # the echo lines never reach us inside the window. Unbuffer it.
    env["PYTHONUNBUFFERED"] = "1"
    if domain is not None:
        env["ROS_DOMAIN_ID"] = str(domain)
    topic = "/ros2_wsl_doctor_%s" % uuid.uuid4().hex[:8]
    pub = subprocess.Popen(
        ["ros2", "topic", "pub", "-r", str(rate_hz), topic, "std_msgs/msg/Int32", "{data: 1}"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    got = 0
    t0 = time.monotonic()
    try:
        # one echo process, count lines with "data:" until expected or timeout
        echo = subprocess.Popen(["ros2", "topic", "echo", topic, "std_msgs/msg/Int32"],
                                env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True)
        deadline = t0 + timeout_s
        import selectors
        sel = selectors.DefaultSelector()
        sel.register(echo.stdout, selectors.EVENT_READ)
        while time.monotonic() < deadline and got < expected:
            for _ in sel.select(timeout=0.5):
                line = echo.stdout.readline()
                if not line:
                    break
                if line.startswith("data:"):
                    got += 1
        _stop(echo)
    finally:
        _stop(pub)
    dom = env.get("ROS_DOMAIN_ID", "0")
    el = time.monotonic() - t0
    if got >= expected:
        return Finding("delivery", Status.PASS,
                       "domain %s delivered %d/%d in %.1f s" % (dom, got, expected, el))
    if got == 0:
        return Finding("delivery", Status.FAIL,
                       "domain %s delivered 0/%d in %.0f s: pub/sub on this host cannot see each "
                       "other" % (dom, expected, el),
                       fix="ros2-wsl-doctor shm; ros2-wsl-doctor env-split; check "
                           "FASTDDS_BUILTIN_TRANSPORTS matches everywhere")
    return Finding("delivery", Status.WARN, "domain %s delivered %d/%d in %.0f s (partial)"
                   % (dom, got, expected, el))


def parse_topic_info(text: str) -> dict:
    """Publishers/subscribers with their reliability from `ros2 topic info -v`."""
    out = {"publishers": [], "subscribers": []}
    cur = None
    node = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("Publisher count"):
            cur = "publishers"
        elif s.startswith("Subscription count"):
            cur = "subscribers"
        m = re.match(r"Node name:\s*(\S+)", s)
        if m:
            node = m.group(1)
        m = re.match(r"Reliability:\s*(\S+)", s)
        if m and cur:
            out[cur].append({"node": node, "reliability": m.group(1).upper()})
    return out


def qos_check(topic: str, runner=None) -> Finding:
    if runner is None:
        if not shutil.which("ros2"):
            return Finding("qos", Status.SKIP, "ros2 not on PATH")

        def runner(cmd):
            try:
                return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout
            except (OSError, subprocess.TimeoutExpired):
                return ""
    text = runner(["ros2", "topic", "info", "-v", topic])
    if not text.strip():
        return Finding("qos", Status.FAIL, "no answer for %s (topic absent or discovery wedged)"
                       % topic, fix="ros2-wsl-doctor daemon; ros2-wsl-doctor shm")
    info = parse_topic_info(text)
    pubs = info["publishers"]
    subs = info["subscribers"]
    be_pubs = [p for p in pubs if p["reliability"].startswith("BEST")]
    rel_subs = [s for s in subs if s["reliability"].startswith("RELIABLE")]
    details = ["publishers: %s" % ", ".join("%s(%s)" % (p["node"], p["reliability"]) for p in pubs)
               or "publishers: none",
               "subscribers: %s" % ", ".join("%s(%s)" % (s["node"], s["reliability"]) for s in subs)
               or "subscribers: none"]
    if be_pubs and rel_subs:
        return Finding("qos", Status.FAIL,
                       "%s: BEST_EFFORT publisher with %d RELIABLE subscriber(s); DDS delivers "
                       "nothing to them" % (topic, len(rel_subs)),
                       fix="subscribe with qos_profile_sensor_data; on the CLI: ros2 topic hz "
                           "%s --qos-reliability best_effort" % topic,
                       details=details)
    if be_pubs:
        return Finding("qos", Status.WARN,
                       "%s publisher is BEST_EFFORT: a plain create_subscription or `ros2 topic hz` "
                       "(RELIABLE by default) receives nothing" % topic,
                       fix="ros2 topic hz %s --qos-reliability best_effort" % topic,
                       details=details)
    if not pubs:
        return Finding("qos", Status.WARN, "%s has no publisher" % topic, details=details)
    return Finding("qos", Status.PASS, "%s: reliability compatible" % topic, details=details)
