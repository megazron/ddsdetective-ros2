"""WSL2-specific traps that read as driver faults."""
from __future__ import annotations

import glob
import os
import re

from .report import Finding, Status


def is_wsl(proc_version: str = "/proc/version") -> bool:
    try:
        with open(proc_version) as fh:
            return "microsoft" in fh.read().lower()
    except OSError:
        return False


def wslconfig_paths(users_root: str = "/mnt/c/Users") -> list[str]:
    try:
        return sorted(glob.glob(os.path.join(users_root, "*", ".wslconfig")))
    except OSError:
        return []


def networking_mode(text: str) -> str | None:
    """networkingMode from a .wslconfig body; None if absent. Section-aware."""
    section = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].split(";", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"^\[(.+)\]$", line)
        if m:
            section = m.group(1).strip().lower()
            continue
        if section == "wsl2" and "=" in line:
            k, v = (s.strip() for s in line.split("=", 1))
            if k.lower() == "networkingmode":
                return v.strip().strip('"').lower()
    return None


def live_networking_mode(runner=None) -> str | None:
    """What WSL is ACTUALLY running, from `wslinfo --networking-mode` (WSL 2.x).

    The .wslconfig file says what the next `wsl --shutdown` will apply; this
    says what applies now. On the rig that motivated this the file had the
    mirrored line commented out and wslinfo said `nat`.
    """
    import shutil
    import subprocess
    if runner is None:
        if not shutil.which("wslinfo"):
            return None

        def runner():
            try:
                return subprocess.run(["wslinfo", "--networking-mode"], capture_output=True,
                                      text=True, timeout=5).stdout
            except (OSError, subprocess.TimeoutExpired):
                return ""
    out = (runner() or "").strip().lower()
    return out or None


def loaded_modules(proc_modules: str = "/proc/modules") -> set[str]:
    try:
        with open(proc_modules) as fh:
            return {l.split()[0] for l in fh if l.strip()}
    except OSError:
        return set()


def mnt_c_state(path: str = "/mnt/c") -> str:
    """'ok', 'absent' or 'EIO' (dead 9p mount)."""
    if not os.path.exists(path):
        return "absent"
    try:
        os.listdir(path)
        return "ok"
    except OSError as e:
        return "EIO" if e.errno == 5 else "error: %s" % e


def checks(proc_version="/proc/version", users_root="/mnt/c/Users",
           proc_modules="/proc/modules", mnt_c="/mnt/c", dev_root="/dev",
           environ=None, live_mode_runner=None) -> list[Finding]:
    env = os.environ if environ is None else environ
    out = []
    if not is_wsl(proc_version):
        out.append(Finding("wsl", Status.SKIP, "not running under WSL"))
        return out
    out.append(Finding("wsl", Status.INFO, "running under WSL2"))

    # networking mode
    cfgs = wslconfig_paths(users_root)
    mode = None
    for c in cfgs:
        try:
            with open(c, encoding="utf-8-sig", errors="replace") as fh:
                mode = networking_mode(fh.read()) or mode
        except OSError:
            pass
    live = live_networking_mode(live_mode_runner) if live_mode_runner is not False else None
    src = "wslinfo" if live else ".wslconfig"
    eff = live or mode
    if eff == "mirrored":
        out.append(Finding("wsl/network", Status.PASS, "networkingMode=mirrored (per %s)" % src,
                           details=(["note: .wslconfig says %s; the running mode wins until the "
                                     "next wsl --shutdown" % (mode or "unset")]
                                    if live and mode != live else [])))
    else:
        out.append(Finding(
            "wsl/network", Status.WARN,
            "networkingMode is %s (NAT, per %s): UDP realtime channels break; TCP looks fine"
            % (eff or "unset", src),
            fix="add [wsl2] networkingMode=mirrored to %%UserProfile%%\\.wslconfig, then "
                "`wsl --shutdown` from PowerShell",
            details=["symptom: the Kinova cyclic (UDP 10001) path times out 3-6 s per write "
                     "while TCP 10000 and ping are perfect; the arm serves live feedback and "
                     "never moves"]))

    # usb modules
    mods = loaded_modules(proc_modules)
    missing = [m for m in ("vhci_hcd", "uvcvideo") if m not in mods and m.replace("_", "-") not in mods]
    videos = sorted(glob.glob(os.path.join(dev_root, "video*")))
    if missing:
        out.append(Finding(
            "wsl/usb", Status.WARN,
            "kernel module(s) not loaded: %s; usbipd will say Attached while Linux has no /dev/video*"
            % ", ".join(missing),
            fix="sudo modprobe %s" % " ".join(missing),
            details=["/dev/video* present now: %s" % (", ".join(videos) if videos else "none")]))
    else:
        out.append(Finding("wsl/usb", Status.PASS,
                           "vhci_hcd and uvcvideo loaded; /dev/video*: %s"
                           % (", ".join(os.path.basename(v) for v in videos) if videos else "none")))

    # /mnt/c
    st = mnt_c_state(mnt_c)
    if st == "ok":
        out.append(Finding("wsl/mnt-c", Status.PASS, "/mnt/c readable"))
    elif st == "EIO":
        out.append(Finding("wsl/mnt-c", Status.FAIL,
                           "/mnt/c returns EIO: the 9p mount is dead and cannot be fixed from inside WSL",
                           fix="wsl --shutdown   (from Windows PowerShell), then reopen the terminal"))
    else:
        out.append(Finding("wsl/mnt-c", Status.WARN, "/mnt/c: %s" % st))

    # transports
    tr = env.get("FASTDDS_BUILTIN_TRANSPORTS")
    if tr and tr.upper().startswith("SHM"):
        out.append(Finding(
            "wsl/transport", Status.PASS, "FASTDDS_BUILTIN_TRANSPORTS=%s in this shell" % tr,
            details=["caveat: a 1280x720 raw Image exceeds the default SHM segment; the node "
                     "captures, reports live, and no subscriber ever gets a frame. 640x480 flows."]))
    else:
        out.append(Finding(
            "wsl/transport", Status.INFO,
            "FASTDDS_BUILTIN_TRANSPORTS is %s" % (tr or "unset (UDPv4 default)"),
            fix="export FASTDDS_BUILTIN_TRANSPORTS=SHM   # if UDP discovery is dead on this host; "
                "set it in EVERY shell and launch, a half-applied transport is a split",
            details=["with SHM, keep raw images at 640x480 or under; 720p silently never arrives"]))

    out.append(Finding("wsl/clock", Status.INFO,
                       "time.time() steps backwards on host resync; measure intervals with "
                       "time.monotonic()",
                       details=["seen: a send latency of -2321 ms, and robot_state_publisher "
                                "logging 'Moved backwards in time' every ~30 s. Clock artefact, "
                                "not a driver fault."]))
    return out
