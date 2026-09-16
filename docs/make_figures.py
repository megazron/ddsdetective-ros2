#!/usr/bin/env python3
"""Regenerate the figures in docs/img/ for ddsdetective-ros2.

    python3 docs/make_figures.py

Diagrams are written as hand-built SVG so they need nothing but the standard
library; the one rendered-output panel uses matplotlib if it is available and
is skipped with a message otherwise. Every figure is captioned in README.md.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
IMG = os.path.join(HERE, "img")
os.makedirs(IMG, exist_ok=True)

# palette -- one accent, matches the other toolkits
INK = "#1f2933"
MUTE = "#6b7580"
LINE = "#c3cbd3"
ACCENT = "#0b7285"          # teal
ACCENT_BG = "#e3f2f4"
WARN = "#b25a00"
WARN_BG = "#fdf0e2"
FAIL = "#b02a37"
FAIL_BG = "#fbe9eb"
OK = "#2b8a3e"
OK_BG = "#e8f5ec"
PAPER = "#ffffff"
FONT = "'Segoe UI',Helvetica,Arial,sans-serif"
MONO = "'Cascadia Code','Consolas','DejaVu Sans Mono',monospace"


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


class SVG:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.b = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" font-family="{FONT}">',
            f'<rect width="{w}" height="{h}" fill="{PAPER}"/>',
        ]

    def rect(self, x, y, w, h, fill=PAPER, stroke=LINE, sw=1.5, rx=8):
        self.b.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')

    def text(self, x, y, s, size=15, fill=INK, anchor="start", weight="400",
             mono=False, italic=False):
        fam = f' font-family="{MONO}"' if mono else ""
        it = ' font-style="italic"' if italic else ""
        self.b.append(
            f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}" font-weight="{weight}"{fam}{it}>{esc(s)}</text>')

    def wrap(self, x, y, s, size=13, fill=MUTE, width=40, lh=17, mono=False):
        words, line, yy = s.split(), "", y
        for wd in words:
            t = (line + " " + wd).strip()
            if len(t) > width and line:
                self.text(x, yy, line, size, fill, mono=mono)
                line, yy = wd, yy + lh
            else:
                line = t
        if line:
            self.text(x, yy, line, size, fill, mono=mono)
        return yy

    def line(self, x1, y1, x2, y2, stroke=MUTE, sw=1.6, dash=None, arrow=False):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        a = ' marker-end="url(#arw)"' if arrow else ""
        self.b.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" '
            f'stroke-width="{sw}"{d}{a}/>')

    def defs_arrow(self):
        self.b.append(
            f'<defs><marker id="arw" markerWidth="10" markerHeight="10" '
            f'refX="8" refY="3" orient="auto" markerUnits="strokeWidth">'
            f'<path d="M0,0 L8,3 L0,6 z" fill="{MUTE}"/></marker></defs>')

    def save(self, name):
        self.b.append("</svg>")
        open(os.path.join(IMG, name), "w").write("\n".join(self.b))
        print("wrote", name)


# --------------------------------------------------------------------- 1
def silent_delivery():
    s = SVG(1000, 560)
    s.defs_arrow()
    s.text(30, 40, "One symptom, six causes", size=24, weight="700")
    s.wrap(30, 66,
           "The publisher is up, the topic is listed, Publisher count is 1 -- "
           "and the subscriber receives nothing.", size=14, width=95)
    # symptom box
    s.rect(340, 96, 320, 70, fill=FAIL_BG, stroke=FAIL, sw=2)
    s.text(500, 124, "topic flows, nobody receives", size=15, fill=FAIL,
           anchor="middle", weight="700")
    s.text(500, 146, "Publisher count: 1   subscriber: 0 bytes", size=12,
           fill=FAIL, anchor="middle", mono=True)
    causes = [
        ("shm", "orphaned /dev/shm segments", "a killed process leaks its FastDDS segment; discovery wades through the pile", OK),
        ("env-split", "domain / transport split", "two process groups on different ROS_DOMAIN_ID or RMW never see each other", OK),
        ("daemon", "hung ros2 daemon", "caches stale graph state and hangs; --no-daemon still sees every node", OK),
        ("qos", "RELIABLE vs BEST_EFFORT", "DDS delivers nothing and warns once; ros2 topic hz gets zero", OK),
        ("wsl/network", "NAT breaks UDP realtime", "TCP and ping are perfect; the UDP cyclic channel times out", WARN),
        ("wsl/usb", "modules not loaded", "usbipd says Attached while Linux has no /dev/video*", WARN),
    ]
    x0, y0, bw, bh, gx, gy = 30, 210, 300, 100, 20, 20
    for i, (chk, title, why, col) in enumerate(causes):
        cx = x0 + (i % 3) * (bw + gx)
        cy = y0 + (i // 3) * (bh + gy)
        s.line(500, 166, cx + bw / 2, cy, stroke=LINE, sw=1.2)
        s.rect(cx, cy, bw, bh, fill=PAPER, stroke=col, sw=2)
        s.text(cx + 14, cy + 26, title, size=14, weight="700")
        s.text(cx + bw - 12, cy + 26, chk, size=11, fill=col, anchor="end", mono=True)
        s.wrap(cx + 14, cy + 48, why, size=11.5, width=42, lh=15)
    s.text(30, 548, "The doctor checks each one and names the fix; the two amber rows are WSL-only.",
           size=12, fill=MUTE, italic=True)
    s.save("silent_delivery.svg")


# --------------------------------------------------------------------- 2
def domain_split():
    s = SVG(1000, 500)
    s.defs_arrow()
    s.text(30, 40, "A DDS domain split", size=24, weight="700")
    s.wrap(30, 66, "Two groups of processes on different ROS_DOMAIN_ID are two "
           "graphs that cannot see each other. Nothing errors.", size=14, width=95)
    # bus 7
    s.rect(60, 110, 360, 150, fill=ACCENT_BG, stroke=ACCENT, sw=2)
    s.text(80, 138, "ROS_DOMAIN_ID = 7", size=15, weight="700", fill=ACCENT, mono=True)
    for i, n in enumerate(["arm_driver_left", "arm_driver_right"]):
        s.text(80, 170 + i * 26, "• " + n, size=13, mono=True)
    s.text(80, 240, "the arm bridges", size=12, fill=MUTE, italic=True)
    # bus 0
    s.rect(580, 110, 360, 150, fill="#eef1f4", stroke=MUTE, sw=2)
    s.text(600, 138, "ROS_DOMAIN_ID = 0", size=15, weight="700", fill=INK, mono=True)
    for i, n in enumerate(["robot_gui", "move_group", "ros2_control_node"]):
        s.text(600, 170 + i * 26, "• " + n, size=13, mono=True)
    s.text(600, 248, "the window, the sim", size=12, fill=MUTE, italic=True)
    # gap
    s.line(430, 185, 570, 185, stroke=FAIL, sw=2, dash="6 6")
    s.text(500, 176, "no", size=13, fill=FAIL, anchor="middle", weight="700")
    s.text(500, 205, "discovery", size=12, fill=FAIL, anchor="middle")
    # diagnosis
    s.rect(60, 300, 880, 96, fill=PAPER, stroke=LINE)
    s.text(80, 328, "how the doctor finds it", size=14, weight="700")
    s.text(80, 354, "diff ROS_DOMAIN_ID / RMW_IMPLEMENTATION / FASTDDS_BUILTIN_TRANSPORTS "
           "across /proc/<pid>/environ of every ROS process", size=12.5, mono=True)
    s.text(80, 378, "fix: export ROS_DOMAIN_ID=<the majority group> in the stranded shell",
           size=12.5, mono=True, fill=ACCENT)
    s.wrap(60, 430,
           "On the rig this stranded the arm bridges for weeks. The workaround "
           "that pinned them to domain 7 was justified by a comment claiming "
           "domain 0 was 'polluted' -- re-measured, both domains delivered 27 of "
           "27. Re-measure a claim before preserving a workaround for it.",
           size=13, width=110, fill=MUTE)
    s.save("domain_split.svg")


# --------------------------------------------------------------------- 3
def shm_ownership():
    s = SVG(1000, 540)
    s.defs_arrow()
    s.text(30, 40, "When is a shared-memory segment safe to delete", size=23, weight="700")
    # decision chain
    steps = [
        ("a file in /dev/shm", "name matches  fastrtps* / fastdds* / sem.fastrtps*", ACCENT),
        ("referenced by a live process?", "checked in BOTH /proc/<pid>/fd and /proc/<pid>/maps -- FastDDS mmaps and may close the fd", ACCENT),
        ("older than the age floor?", "default 20 s; a process still starting has segments it has not mapped yet", ACCENT),
        ("ORPHAN -- safe to delete", "with --fix; already-running nodes are untouched", OK),
    ]
    y = 90
    for i, (t, why, col) in enumerate(steps):
        s.rect(60, y, 520, 70, fill=ACCENT_BG if col == ACCENT else OK_BG, stroke=col, sw=2)
        s.text(80, y + 28, t, size=15, weight="700", fill=col if col == OK else INK)
        s.wrap(80, y + 50, why, size=12, width=66, lh=15)
        if i < len(steps) - 1:
            s.line(320, y + 70, 320, y + 90, stroke=MUTE, sw=1.6, arrow=True)
            s.text(335, y + 86, "yes, and", size=11, fill=MUTE)
        y += 90
    # traps panel
    s.rect(620, 90, 340, 330, fill=FAIL_BG, stroke=FAIL, sw=2)
    s.text(640, 118, "two traps this avoids", size=15, weight="700", fill=FAIL)
    s.wrap(640, 148,
           "1. rm -f /dev/shm/fastrtps_* deletes the running ros2 daemon's own "
           "segments too. It does not die -- it goes DEAF, and every node list "
           "returns nothing against a healthy stack.", size=12.5, width=42, lh=17, fill=INK)
    s.wrap(640, 250,
           "2. Sweeping while a stack is starting destroys a process whose "
           "segments are not mapped yet. Hence the age floor.", size=12.5,
           width=42, lh=17, fill=INK)
    s.text(640, 350, "order: stop daemon -> sweep -> start daemon", size=12,
           mono=True, fill=FAIL)
    s.wrap(60, 470,
           "Measured on the rig: 116 segments, 37 live, 79 orphaned; a fresh "
           "pub/sub still exchanged 27 of 27 messages while ros2 topic list "
           "timed out at 25 s, because the pair only had to find each other, "
           "not the polluted graph.", size=13, width=118, fill=MUTE)
    s.save("shm_ownership.svg")


# --------------------------------------------------------------------- 4
def doctor_output():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import FancyBboxPatch
    except Exception as e:                                    # noqa: BLE001
        print("matplotlib not available, skipping doctor_output.png:", e)
        return
    # capture a real run
    env = dict(os.environ, PYTHONPATH=os.path.join(os.path.dirname(HERE), "src"))
    try:
        out = subprocess.run([sys.executable, "-m", "ros2_wsl_doctor.cli"],
                             capture_output=True, text=True, timeout=120,
                             env=env).stdout
    except Exception as e:                                    # noqa: BLE001
        out = "(could not run the doctor: %s)" % e
    lines = [ln.rstrip() for ln in out.splitlines() if ln.strip()]
    colmap = {"PASS": OK, "WARN": WARN, "FAIL": FAIL, "SKIP": MUTE, "INFO": ACCENT}
    fig, ax = plt.subplots(figsize=(11, 0.34 * len(lines) + 1.2), dpi=150)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, len(lines) + 1)
    ax.axis("off")
    fig.patch.set_facecolor("#0d1420")
    ax.set_facecolor("#0d1420")
    ax.text(0.015, len(lines) + 0.4, "$ ddsdetective-ros2", family="monospace",
            fontsize=12, color="#8dd5e0", weight="bold")
    for i, ln in enumerate(lines):
        y = len(lines) - i - 0.2
        col = "#c7d0da"
        for k, c in colmap.items():
            if (" " + k + " ") in ("  " + ln + " ") or ln.strip().split()[:1] == [k]:
                pass
        for k, c in colmap.items():
            if k in ln.split():
                col = {"PASS": "#6bcf7f", "WARN": "#f0a24b", "FAIL": "#ef6b78",
                       "SKIP": "#8a94a0", "INFO": "#6fd0e0"}[k]
                break
        ax.text(0.015, y, ln, family="monospace", fontsize=10.5, color=col)
    fig.tight_layout(pad=0.6)
    fig.savefig(os.path.join(IMG, "doctor_output.png"),
                facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    print("wrote doctor_output.png")


if __name__ == "__main__":
    silent_delivery()
    domain_split()
    shm_ownership()
    doctor_output()
