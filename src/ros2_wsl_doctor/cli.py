"""ddsdetective-ros2 command line.

    ddsdetective-ros2                 # every check
    ddsdetective-ros2 shm [--fix] [--restart-daemon]
    ddsdetective-ros2 env-split [--match REGEX]
    ddsdetective-ros2 daemon
    ddsdetective-ros2 wsl
    ddsdetective-ros2 delivery [--domain N] [--expected 10]
    ddsdetective-ros2 qos TOPIC
    add --json to any of them for machine-readable output
"""
from __future__ import annotations

import argparse
import sys

from . import daemon, delivery, env_split, shm, wsl
from .report import Finding, exit_code, render_json, render_table


def run_all(args) -> list[Finding]:
    out: list[Finding] = []
    out.append(shm.check(fix=False, age_floor_s=args.age_floor))
    out.append(env_split.check(match=args.match))
    out.append(daemon.check())
    out.extend(wsl.checks())
    if args.delivery_test:
        out.append(delivery.delivery_test(domain=args.domain, expected=args.expected))
    if args.qos_check:
        out.append(delivery.qos_check(args.qos_check))
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ddsdetective-ros2", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--quiet", action="store_true", help="hide detail lines")
    p.add_argument("--age-floor", type=float, default=shm.DEFAULT_AGE_FLOOR_S,
                   help="seconds a segment must be unreferenced before it counts as orphaned")
    p.add_argument("--match", default=None, help="regex for which processes count as ROS")
    p.add_argument("--delivery-test", action="store_true",
                   help="also run a pub/sub round trip (needs ros2 on PATH)")
    p.add_argument("--domain", type=int, default=None, help="ROS_DOMAIN_ID for --delivery-test")
    p.add_argument("--expected", type=int, default=10, help="messages expected by --delivery-test")
    p.add_argument("--qos-check", metavar="TOPIC", default=None,
                   help="also check a topic for a BEST_EFFORT/RELIABLE mismatch")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("shm", help="orphaned FastDDS shared-memory segments")
    s.add_argument("--fix", action="store_true", help="delete the orphans (only the orphans)")
    s.add_argument("--restart-daemon", action="store_true",
                   help="with --fix: cycle a running ros2 daemon so its segments are swept too")
    s.add_argument("--shm-root", default="/dev/shm")
    s.add_argument("--proc-root", default="/proc")
    e = sub.add_parser("env-split", help="domain/transport split between running ROS processes")
    e.add_argument("--proc-root", default="/proc")
    sub.add_parser("daemon", help="stale ros2 daemon")
    sub.add_parser("wsl", help="WSL2 traps: NAT, usb modules, /mnt/c, transports, clock")
    d = sub.add_parser("delivery", help="pub/sub round trip on a domain")
    d.add_argument("--domain", type=int, default=None, dest="d_domain")
    d.add_argument("--expected", type=int, default=10, dest="d_expected")
    q = sub.add_parser("qos", help="reliability mismatch on a topic")
    q.add_argument("topic")
    return p


def main(argv=None) -> int:
    p = build_parser()
    args = p.parse_args(argv)
    if args.cmd == "shm":
        findings = [shm.check(fix=args.fix, restart=args.restart_daemon, shm_root=args.shm_root,
                              proc_root=args.proc_root, age_floor_s=args.age_floor)]
    elif args.cmd == "env-split":
        findings = [env_split.check(proc_root=args.proc_root, match=args.match)]
    elif args.cmd == "daemon":
        findings = [daemon.check()]
    elif args.cmd == "wsl":
        findings = wsl.checks()
    elif args.cmd == "delivery":
        findings = [delivery.delivery_test(domain=args.d_domain if args.d_domain is not None else args.domain,
                                           expected=args.d_expected)]
    elif args.cmd == "qos":
        findings = [delivery.qos_check(args.topic)]
    else:
        findings = run_all(args)
    print(render_json(findings) if args.json else render_table(findings, verbose=not args.quiet))
    return exit_code(findings)


if __name__ == "__main__":
    sys.exit(main())
