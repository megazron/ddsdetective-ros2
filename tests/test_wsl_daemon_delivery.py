import os

from ros2_wsl_doctor import daemon, delivery, wsl
from ros2_wsl_doctor.report import Status


def test_wslconfig_parsing_is_section_aware():
    assert wsl.networking_mode("[wsl2]\nnetworkingMode=mirrored\n") == "mirrored"
    assert wsl.networking_mode("[experimental]\nnetworkingMode=mirrored\n") is None
    assert wsl.networking_mode("[wsl2]\n# networkingMode=mirrored\nmemory=8GB\n") is None
    assert wsl.networking_mode('[WSL2]\nNetworkingMode = "Mirrored"  # comment\n') == "mirrored"


def test_wsl_checks_skip_off_wsl(tmp_path):
    pv = tmp_path / "version"
    pv.write_text("Linux version 6.8.0-generic (buildd@x) ...")
    out = wsl.checks(proc_version=str(pv))
    assert len(out) == 1 and out[0].status == Status.SKIP


def test_wsl_checks_nat_and_missing_modules(tmp_path):
    pv = tmp_path / "version"
    pv.write_text("Linux version 6.6.87.2-microsoft-standard-WSL2")
    users = tmp_path / "Users" / "me"
    users.mkdir(parents=True)
    (users / ".wslconfig").write_text("[wsl2]\nmemory=8GB\n")
    mods = tmp_path / "modules"
    mods.write_text("uvcvideo 1 0 - Live 0x0\n")
    mnt = tmp_path / "mnt_c"
    mnt.mkdir()
    dev = tmp_path / "dev"
    dev.mkdir()
    out = {f.check: f for f in wsl.checks(proc_version=str(pv), users_root=str(tmp_path / "Users"),
                                          proc_modules=str(mods), mnt_c=str(mnt),
                                          dev_root=str(dev), environ={}, live_mode_runner=False)}
    assert out["wsl/network"].status == Status.WARN and "NAT" in out["wsl/network"].finding
    assert out["wsl/usb"].status == Status.WARN and "vhci_hcd" in out["wsl/usb"].finding
    assert out["wsl/mnt-c"].status == Status.PASS
    assert out["wsl/transport"].status == Status.INFO


def test_wsl_checks_mirrored_and_shm(tmp_path):
    pv = tmp_path / "version"
    pv.write_text("microsoft")
    users = tmp_path / "Users" / "me"
    users.mkdir(parents=True)
    (users / ".wslconfig").write_text("[wsl2]\nnetworkingMode=mirrored\n")
    mods = tmp_path / "modules"
    mods.write_text("vhci_hcd 1 0 - Live 0x0\nuvcvideo 1 0 - Live 0x0\n")
    mnt = tmp_path / "mnt_c"
    mnt.mkdir()
    out = {f.check: f for f in wsl.checks(proc_version=str(pv), users_root=str(tmp_path / "Users"),
                                          proc_modules=str(mods), mnt_c=str(mnt),
                                          dev_root=str(tmp_path), environ={"FASTDDS_BUILTIN_TRANSPORTS": "SHM"}, live_mode_runner=False)}
    assert out["wsl/network"].status == Status.PASS
    assert out["wsl/usb"].status == Status.PASS
    assert out["wsl/transport"].status == Status.PASS


def test_daemon_stale_detected():
    def runner(cmd, timeout):
        return ("", True) if "--no-daemon" not in cmd else ("/a\n/b\n/c\n", False)
    f = daemon.check(runner=runner, have_ros2=True, pids=["123"])
    assert f.status == Status.FAIL and "stale" in f.finding and "ros2 daemon stop" in f.fix


def test_daemon_agrees():
    def runner(cmd, timeout):
        return ("/a\n/b\n", False)
    assert daemon.check(runner=runner, have_ros2=True, pids=[]).status == Status.PASS


def test_daemon_skips_without_ros2():
    assert daemon.check(have_ros2=False).status == Status.SKIP


TOPIC_INFO = """Type: sensor_msgs/msg/Image

Publisher count: 1

Node name: scene_camera_node
Node namespace: /
Topic type: sensor_msgs/msg/Image
Endpoint type: PUBLISHER
GID: 01.0f
QoS profile:
  Reliability: BEST_EFFORT
  History (Depth): UNKNOWN
  Durability: VOLATILE

Subscription count: 1

Node name: _ros2cli_hz
Node namespace: /
Topic type: sensor_msgs/msg/Image
Endpoint type: SUBSCRIPTION
GID: 01.10
QoS profile:
  Reliability: RELIABLE
  Durability: VOLATILE
"""


def test_qos_mismatch_detected():
    f = delivery.qos_check("/scene_camera/image_raw", runner=lambda cmd: TOPIC_INFO)
    assert f.status == Status.FAIL and "BEST_EFFORT" in f.finding
    assert "best_effort" in f.fix


def test_qos_parse():
    info = delivery.parse_topic_info(TOPIC_INFO)
    assert info["publishers"] == [{"node": "scene_camera_node", "reliability": "BEST_EFFORT"}]
    assert info["subscribers"][0]["reliability"] == "RELIABLE"


def test_qos_absent_topic():
    assert delivery.qos_check("/nope", runner=lambda cmd: "").status == Status.FAIL


def test_live_networking_mode_wins_over_file(tmp_path):
    pv = tmp_path / "version"
    pv.write_text("microsoft")
    users = tmp_path / "Users" / "me"
    users.mkdir(parents=True)
    (users / ".wslconfig").write_text("[wsl2]\n#networkingMode=mirrored\n")
    mods = tmp_path / "modules"
    mods.write_text("")
    out = {f.check: f for f in wsl.checks(proc_version=str(pv), users_root=str(tmp_path / "Users"),
                                          proc_modules=str(mods), mnt_c=str(tmp_path),
                                          dev_root=str(tmp_path), environ={},
                                          live_mode_runner=lambda: "nat\n")}
    assert out["wsl/network"].status == Status.WARN and "wslinfo" in out["wsl/network"].finding
    out = {f.check: f for f in wsl.checks(proc_version=str(pv), users_root=str(tmp_path / "Users"),
                                          proc_modules=str(mods), mnt_c=str(tmp_path),
                                          dev_root=str(tmp_path), environ={},
                                          live_mode_runner=lambda: "mirrored")}
    assert out["wsl/network"].status == Status.PASS
