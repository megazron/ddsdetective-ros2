import os

from conftest import make_proc, touch_segment
from ros2_wsl_doctor import shm
from ros2_wsl_doctor.report import Status


def test_orphan_vs_referenced_by_fd(fake_env):
    proc, shmr = fake_env
    touch_segment(shmr, "fastrtps_port7412", 120)
    touch_segment(shmr, "fastrtps_port7413", 120)
    make_proc(proc, 100, "/opt/ros/jazzy/lib/x/node", fds=["/dev/shm/fastrtps_port7412"])
    s = shm.survey(shmr, proc, age_floor_s=20)
    assert s.in_use == ["fastrtps_port7412"]
    assert s.orphaned == ["fastrtps_port7413"]


def test_mmapped_but_fd_closed_counts_as_referenced(fake_env):
    proc, shmr = fake_env
    touch_segment(shmr, "fastrtps_abc_el", 120)
    make_proc(proc, 101, "python3 node.py", maps=["/dev/shm/fastrtps_abc_el"])
    s = shm.survey(shmr, proc)
    assert s.orphaned == [] and s.in_use == ["fastrtps_abc_el"]


def test_age_floor_protects_a_starting_process(fake_env):
    proc, shmr = fake_env
    touch_segment(shmr, "fastrtps_young", 3)
    touch_segment(shmr, "fastrtps_old", 300)
    s = shm.survey(shmr, proc, age_floor_s=20)
    assert s.too_young == ["fastrtps_young"]
    assert s.orphaned == ["fastrtps_old"]


def test_semaphores_and_fastdds_prefix_are_included(fake_env):
    proc, shmr = fake_env
    touch_segment(shmr, "sem.fastrtps_port7412_el", 300)
    touch_segment(shmr, "fastdds_shared_mem", 300)
    touch_segment(shmr, "unrelated_segment", 300)
    s = shm.survey(shmr, proc)
    assert sorted(s.total) == ["fastdds_shared_mem", "sem.fastrtps_port7412_el"]


def test_deleted_suffix_in_maps_is_stripped(fake_env):
    proc, shmr = fake_env
    touch_segment(shmr, "fastrtps_x", 300)
    make_proc(proc, 7, "ros2 run a b", maps=["/dev/shm/fastrtps_x (deleted)"])
    assert shm.survey(shmr, proc).in_use == ["fastrtps_x"]


def test_check_reports_fail_without_fix_and_deletes_only_orphans(fake_env, monkeypatch):
    proc, shmr = fake_env
    touch_segment(shmr, "fastrtps_live", 300)
    touch_segment(shmr, "fastrtps_dead", 300)
    make_proc(proc, 5, "move_group", fds=["/dev/shm/fastrtps_live"])
    f = shm.check(shm_root=shmr, proc_root=proc)
    assert f.status == Status.FAIL and "1 orphaned" in f.finding
    assert "rm -f" in " ".join(f.details)  # the warning against the broad sweep
    monkeypatch.setattr(shm, "daemon_running", lambda: False)
    f = shm.check(fix=True, shm_root=shmr, proc_root=proc)
    assert f.status == Status.PASS and "removed 1" in f.finding
    assert os.path.exists(os.path.join(shmr, "fastrtps_live"))
    assert not os.path.exists(os.path.join(shmr, "fastrtps_dead"))


def test_check_passes_when_clean(fake_env):
    proc, shmr = fake_env
    assert shm.check(shm_root=shmr, proc_root=proc).status == Status.PASS
    touch_segment(shmr, "fastrtps_a", 300)
    make_proc(proc, 9, "rviz2", fds=["/dev/shm/fastrtps_a"])
    assert shm.check(shm_root=shmr, proc_root=proc).status == Status.PASS
