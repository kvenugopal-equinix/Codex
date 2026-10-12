"""Regressions found while reviewing the uploaded distribution."""
import csv
import re
from pathlib import Path

import pytest

from warroom.config import Settings, ConfigError
from warroom.dialer import DialDecision, dial, invite
from warroom.joinlog import log_join
from warroom.roster import _row_to_shift
from test_watcher import Rig, ME, P


def settings(tmp_path, **over):
    args = dict(dry_run=False, live_calling=True, target_mode="roster", test_number="",
                allow_roster_calls=False, roster_path=tmp_path / "r.xlsx",
                join_log_path=tmp_path / "logs" / "join.csv", zoom_invite=True)
    return Settings(**dict(args, **over))


def test_direct_dial_and_invite_cannot_bypass_roster_gate(tmp_path):
    s = settings(tmp_path)
    d = DialDecision("+14155550123", "Engineer", True, "manual", "eng@example.com")
    assert dial(s, d).text.startswith("REFUSED")
    assert invite(s, d).log == "no"
    assert not s.join_log_path.parent.exists()


def test_unknown_dial_method_never_drives_zoom(tmp_path, monkeypatch):
    monkeypatch.setenv("WARROOM_DIAL_METHOD", "uui")
    s = settings(tmp_path, allow_roster_calls=True)
    assert "WARROOM_DIAL_METHOD" in dial(s, DialDecision("+14155550123", "E", True, "x")).text


def test_uri_launch_failure_is_uncertain_and_retains_guard(tmp_path, monkeypatch):
    import warroom.dialer as d
    monkeypatch.setenv("WARROOM_DIAL_METHOD", "uri")
    monkeypatch.setattr(d.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("failed")))
    s = settings(tmp_path, allow_roster_calls=True)
    decision = DialDecision("+14155550123", "E", True, "x")
    assert dial(s, decision).uncertain
    assert dial(s, decision).text.startswith("REFUSED")


def test_log_creates_nested_parent(tmp_path):
    p = tmp_path / "new" / "logs" / "join.csv"
    log_join(p, participant_name="Visitor")
    with p.open(newline="") as f:
        assert list(csv.DictReader(f))[0]["participant_name"] == "Visitor"


def test_quoted_dotenv_preserves_hash_and_spaces(tmp_path, real_load_dotenv, monkeypatch):
    import os
    p = tmp_path / ".env"
    p.write_text('WARROOM_VOICE_MESSAGE="Room #1 is open" # comment\n')
    real_load_dotenv(p)
    assert os.environ["WARROOM_VOICE_MESSAGE"] == "Room #1 is open"


def test_bad_quote_is_configuration_error(tmp_path, real_load_dotenv):
    p = tmp_path / ".env"
    p.write_text('WARROOM_VOICE_MESSAGE="broken\n')
    with pytest.raises(ConfigError):
        real_load_dotenv(p)


def test_zero_priority_is_not_replaced_by_99():
    row = dict(name="E", phone="+14155550123", shift_start="00:00", shift_end="00:00", priority=0)
    assert _row_to_shift(row).priority == 0


def test_unrelated_arrival_after_answer_is_still_a_visitor():
    r = Rig([ME], [ME, P("Bob")], [ME, P("Bob")], [ME, P("Bob"), P("Visitor")])
    r.polls(2)
    assert r.w.kind(P("Visitor")) == "visitor"
    r.polls(1)
    assert r.escalated == ["Bob", "Visitor"]


def test_applescript_handler_names_match():
    source = (Path(__file__).resolve().parents[1] / "app" / "WarRoomBot.applescript").read_text()
    starts = re.findall(r"^on (\w+)(?:\(|$)", source, re.M)
    ends = re.findall(r"^end (\w+)$", source, re.M)
    assert starts == ends


def test_dry_wrapper_disables_optional_speech():
    source = (Path(__file__).resolve().parents[1] / "watch.sh").read_text()
    dry = source.split("  dry)", 1)[1].split("  check)", 1)[0]
    assert "WARROOM_VOICE_IN_DRY_RUN=false" in dry


def test_app_control_tests_work_while_installer_hides_version(tmp_path):
    import os
    import shutil
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    copied = tmp_path / "installing"
    shutil.copytree(root, copied, ignore=shutil.ignore_patterns(
        ".git", ".venv", "__pycache__", ".pytest_cache", ".env", "roster.xlsx", "logs", "dist"))
    (copied / "VERSION").unlink(missing_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("WARROOM_")}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_wrb.py::test_state_follows_the_install"],
        cwd=copied, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (copied / "VERSION").exists()
