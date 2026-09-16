from conftest import make_proc
from ros2_wsl_doctor import env_split
from ros2_wsl_doctor.report import Status

SHELL = {"ROS_DOMAIN_ID": "0", "RMW_IMPLEMENTATION": "rmw_fastrtps_cpp",
         "FASTDDS_BUILTIN_TRANSPORTS": "SHM"}


def test_domain_split_is_a_fail_and_names_the_majority(fake_env):
    proc, _ = fake_env
    base = {"RMW_IMPLEMENTATION": "rmw_fastrtps_cpp", "FASTDDS_BUILTIN_TRANSPORTS": "SHM"}
    make_proc(proc, 10, "/opt/ros/jazzy/lib/moveit_ros_move_group/move_group", {**base, "ROS_DOMAIN_ID": "0"})
    make_proc(proc, 11, "python3 -m srl_teleop.srl_gui --ros-args", {**base, "ROS_DOMAIN_ID": "0"})
    make_proc(proc, 12, "python3 -m srl_teleop.kortex_highlevel_bridge --ros-args", {**base, "ROS_DOMAIN_ID": "7"})
    f = env_split.check(proc_root=proc, shell_env=SHELL)
    assert f.status == Status.FAIL
    assert "domain split" in f.finding
    assert "export ROS_DOMAIN_ID=0" in f.fix
    assert any("pid 12" in d for d in f.details)


def test_unset_domain_means_zero(fake_env):
    proc, _ = fake_env
    make_proc(proc, 20, "ros2 launch pkg a.launch.py", {"RMW_IMPLEMENTATION": "rmw_fastrtps_cpp", "FASTDDS_BUILTIN_TRANSPORTS": "SHM"})
    make_proc(proc, 21, "rviz2", {**SHELL})
    f = env_split.check(proc_root=proc, shell_env=SHELL)
    assert f.status == Status.PASS, f


def test_transport_split_without_domain_split(fake_env):
    proc, _ = fake_env
    make_proc(proc, 30, "move_group", {**SHELL})
    make_proc(proc, 31, "controller_manager/ros2_control_node", {**SHELL, "FASTDDS_BUILTIN_TRANSPORTS": "UDPv4"})
    f = env_split.check(proc_root=proc, shell_env=SHELL)
    assert f.status == Status.FAIL and "transport" in f.finding


def test_shell_differing_from_stack_is_a_warn(fake_env):
    proc, _ = fake_env
    make_proc(proc, 40, "move_group", {**SHELL, "ROS_DOMAIN_ID": "7"})
    f = env_split.check(proc_root=proc, shell_env=SHELL)
    assert f.status == Status.WARN and "export ROS_DOMAIN_ID=7" in f.fix


def test_localhost_only_is_flagged(fake_env):
    proc, _ = fake_env
    make_proc(proc, 50, "move_group", {**SHELL, "ROS_LOCALHOST_ONLY": "1"})
    f = env_split.check(proc_root=proc, shell_env={**SHELL, "ROS_LOCALHOST_ONLY": "1"})
    assert f.status == Status.WARN and "ROS_LOCALHOST_ONLY" in f.finding


def test_non_ros_processes_are_ignored(fake_env):
    proc, _ = fake_env
    make_proc(proc, 60, "/usr/bin/bash", {"ROS_DOMAIN_ID": "3"})
    make_proc(proc, 61, "firefox", {"ROS_DOMAIN_ID": "4"})
    assert env_split.check(proc_root=proc, shell_env=SHELL).status == Status.SKIP


def test_custom_match_regex(fake_env):
    proc, _ = fake_env
    make_proc(proc, 70, "/home/me/bin/my_bridge", {**SHELL, "ROS_DOMAIN_ID": "2"})
    make_proc(proc, 71, "/home/me/bin/my_gui", {**SHELL, "ROS_DOMAIN_ID": "0"})
    assert env_split.check(proc_root=proc, shell_env=SHELL).status == Status.SKIP
    f = env_split.check(proc_root=proc, match=r"my_", shell_env=SHELL)
    assert f.status == Status.FAIL


def test_ros2_daemons_are_not_a_split(fake_env):
    proc, _ = fake_env
    make_proc(proc, 80, "/usr/bin/python3 -c from ros2cli.daemon.daemonize import main; main() --name ros2-daemon --ros-domain-id 0", {**SHELL})
    make_proc(proc, 81, "/usr/bin/python3 -c from ros2cli.daemon.daemonize import main; main() --name ros2-daemon --ros-domain-id 7", {**SHELL, "ROS_DOMAIN_ID": "7"})
    make_proc(proc, 82, "move_group", {**SHELL})
    f = env_split.check(proc_root=proc, shell_env=SHELL)
    assert f.status == Status.PASS, f
    assert any("ros2 daemon(s)" in d for d in f.details)
