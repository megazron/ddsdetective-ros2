import json

from ros2_wsl_doctor import cli
from ros2_wsl_doctor.report import Finding, Status, exit_code, render_json, render_table, worst


def test_render_table_and_worst():
    fs = [Finding("a", Status.PASS, "fine"),
          Finding("b", Status.FAIL, "broken", fix="do this", details=["why"])]
    t = render_table(fs)
    assert "FAIL" in t and "fix: do this" in t and "why" in t and "overall: FAIL" in t
    assert worst(fs) == Status.FAIL and exit_code(fs) == 1
    assert exit_code([Finding("a", Status.WARN, "meh")]) == 0
    assert "no findings" in render_table([])


def test_render_json_roundtrip():
    d = json.loads(render_json([Finding("a", Status.SKIP, "x")]))
    assert d["overall"] == "SKIP" and d["findings"][0]["status"] == "SKIP"


def test_cli_shm_json_on_fake_roots(fake_env, capsys):
    proc, shmr = fake_env
    rc = cli.main(["--json", "shm", "--shm-root", shmr, "--proc-root", proc])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["findings"][0]["check"] == "shm"


def test_cli_env_split_on_empty_proc(fake_env, capsys):
    proc, _ = fake_env
    rc = cli.main(["env-split", "--proc-root", proc])
    assert rc == 0 and "SKIP" in capsys.readouterr().out


def test_cli_help(capsys):
    try:
        cli.main(["--help"])
    except SystemExit as e:
        assert e.code == 0
    assert "ros2-wsl-doctor" in capsys.readouterr().out
