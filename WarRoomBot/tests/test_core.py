from datetime import datetime, timezone
from warroom.roster import Shift, on_duty, parse_days, parse_time
from warroom.config import Settings
from warroom.dialer import DialResult, choose_target, dial
from pathlib import Path

def S(name, start, end, days="Mon-Fri", prio=1, tz="Asia/Singapore", phone="+6590000001"):
    return Shift(name, "", phone, tz, parse_days(days), parse_time(start), parse_time(end), prio, True)

def utc(*a): return datetime(*a, tzinfo=timezone.utc)

def test_day_shift():
    # Mon 2026-10-05 03:00 UTC = 11:00 SGT
    assert [s.name for s in on_duty([S("a","09:00","18:00")], utc(2026,10,5,3))] == ["a"]
    assert on_duty([S("a","09:00","18:00")], utc(2026,10,5,12)) == []

def test_overnight_spills_to_next_day():
    s = S("n","18:00","03:00","Mon-Fri")
    assert on_duty([s], utc(2026,10,9,18))  # Sat 02:00 SGT, shift began Fri
    assert not on_duty([s], utc(2026,10,10,18))  # Sun 02:00 SGT, began Sat (not in days)

def test_priority_order():
    r = on_duty([S("b","00:00","23:59",prio=2), S("a","00:00","23:59",prio=1)], utc(2026,10,5,3))
    assert [s.name for s in r] == ["a","b"]

def test_placeholders_ignored():
    p = S("<Eng>","00:00","23:59",phone="+65XXXXXXXX")
    assert on_duty([p], utc(2026,10,5,3)) == []

def mk(**k):
    d = dict(dry_run=True, live_calling=False, target_mode="test", test_number="+6511111111",
             allow_roster_calls=False, roster_path=Path("x"), join_log_path=Path("y")); d.update(k)
    return Settings(**d)

def test_test_mode_discards_roster_numbers():
    d = choose_target(mk(), [S("a","00:00","23:59")])
    assert d.number == "+6511111111"

def test_roster_mode_needs_allow():
    assert not choose_target(mk(target_mode="roster"), [S("a","00:00","23:59")]).will_place

def test_dry_run_never_opens(monkeypatch):
    import warroom.dialer as m
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert dial(mk(), choose_target(mk(), [])).text.startswith("DRY-RUN")
    assert dial(mk(dry_run=False), choose_target(mk(dry_run=False), [])).text.startswith("DRY-RUN")  # live flag off

def test_voice_does_not_block_dial(monkeypatch, tmp_path):
    import time, warroom.cli as cli, warroom.voice as v
    order = []
    class P:
        def wait(self): order.append("wait")
    monkeypatch.setattr(cli, "speak", lambda *a, **k: order.append("speak") or P())
    monkeypatch.setattr(cli, "dial", lambda *a, **k: order.append("dial") or DialResult("DRY-RUN: x"))
    monkeypatch.setattr(cli, "load_roster", lambda p: [])
    monkeypatch.setenv("WARROOM_DRY_RUN", "true"); monkeypatch.setenv("WARROOM_VOICE_IN_DRY_RUN", "true")
    monkeypatch.setenv("WARROOM_VOICE_ROUTE", "local")
    monkeypatch.setenv("WARROOM_TEST_NUMBER", "+6511111111"); monkeypatch.setenv("WARROOM_JOIN_LOG", str(tmp_path/"j.csv"))
    cli.main(["join", "V"])
    assert order == ["speak", "dial", "wait"]

def test_say_returns_immediately(monkeypatch):
    import warroom.voice as v
    handle = object()
    monkeypatch.setattr(v.subprocess, "Popen", lambda *a, **k: handle)
    assert v.speak("Welcome") is handle


import pytest
from warroom.config import ConfigError


@pytest.mark.parametrize("raw", ["", "  ", "ture", "flase", "2", "\"false\"x", "nope"])
def test_unrecognised_dry_run_stays_in_dry_run(monkeypatch, raw):
    monkeypatch.setenv("WARROOM_DRY_RUN", raw)
    assert Settings.from_env().dry_run is True


@pytest.mark.parametrize("raw", ["", "ture", "yess", "tru", "enabled"])
def test_unrecognised_live_calling_stays_off(monkeypatch, raw):
    monkeypatch.setenv("WARROOM_LIVE_CALLING", raw)
    assert Settings.from_env().live_calling is False


@pytest.mark.parametrize("raw,want", [("false", False), ("FALSE", False), ("0", False), ("\"false\"", False),
                                      ("true", True), ("On", True), ("1", True)])
def test_recognised_dry_run_values(monkeypatch, raw, want):
    monkeypatch.setenv("WARROOM_DRY_RUN", raw)
    assert Settings.from_env().dry_run is want


def test_defaults_are_the_closed_state():
    s = Settings.from_env()
    assert s.dry_run and not s.live_calling and s.target_mode == "test" and not s.allow_roster_calls


@pytest.mark.parametrize("raw", ["tset", "prod", "ROSTER2", "live"])
def test_unknown_target_mode_is_an_error_not_roster(monkeypatch, raw):
    monkeypatch.setenv("WARROOM_TARGET_MODE", raw)
    with pytest.raises(ConfigError):
        Settings.from_env()


def test_target_mode_is_case_insensitive_and_blank_means_test(monkeypatch):
    monkeypatch.setenv("WARROOM_TARGET_MODE", " ROSTER ")
    assert Settings.from_env().target_mode == "roster"
    monkeypatch.setenv("WARROOM_TARGET_MODE", "")
    assert Settings.from_env().target_mode == "test"


@pytest.mark.parametrize("raw", ["0", "-5", "nan", "inf", "abc", "4"])
def test_bad_call_timeout_is_an_error(monkeypatch, raw):
    monkeypatch.setenv("WARROOM_CALL_TIMEOUT", raw)
    with pytest.raises(ConfigError):
        Settings.from_env()


def test_call_timeout_default_and_override(monkeypatch):
    assert Settings.from_env().call_timeout == 60
    monkeypatch.setenv("WARROOM_CALL_TIMEOUT", "90")
    assert Settings.from_env().call_timeout == 90


def test_dotenv_real_env_wins_first_duplicate_wins_and_quotes_stripped(tmp_path, monkeypatch, real_load_dotenv):
    env = tmp_path / ".env"
    env.write_text('WARROOM_DRY_RUN="false"\nWARROOM_DRY_RUN=true\nWARROOM_TEST_NUMBER=+6511111111  # mine\n'
                   'WARROOM_VOICE=false\n')
    monkeypatch.setenv("WARROOM_VOICE", "true")
    real_load_dotenv(env)
    import os
    assert os.environ["WARROOM_DRY_RUN"] == "false"            # first duplicate wins, quotes stripped
    assert os.environ["WARROOM_TEST_NUMBER"] == "+6511111111"
    assert os.environ["WARROOM_VOICE"] == "true"                # the real environment beats .env


def test_roster_mode_never_reached_by_default_dial_refusal():
    d = choose_target(mk(target_mode="roster", allow_roster_calls=True), [S("a", "00:00", "23:59")])
    assert d.will_place and d.number == "+6590000001"


def test_cli_prints_gates_and_exit_codes(monkeypatch, tmp_path, capsys):
    import warroom.cli as cli
    monkeypatch.setattr(cli, "load_roster", lambda p: [])
    monkeypatch.setenv("WARROOM_TEST_NUMBER", "+6511111111")
    monkeypatch.setenv("WARROOM_JOIN_LOG", str(tmp_path / "j.csv"))
    assert cli.main(["dial"]) == 0
    out = capsys.readouterr()
    assert "dry_run=True live_calling=False target_mode=test" in out.err and out.out.startswith("DRY-RUN")
    monkeypatch.setenv("WARROOM_TARGET_MODE", "typo")
    assert cli.main(["dial"]) == 2
    assert "CONFIG" in capsys.readouterr().err


def test_join_prints_result_even_if_logging_fails(monkeypatch, tmp_path, capsys):
    import warroom.cli as cli
    monkeypatch.setattr(cli, "load_roster", lambda p: [])
    monkeypatch.setattr(cli, "log_join", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    monkeypatch.setattr(cli, "dial", lambda *a, **k: DialResult("UNKNOWN, Call may have been placed: x", True, uncertain=True))
    monkeypatch.setenv("WARROOM_VOICE", "false")
    monkeypatch.setenv("WARROOM_TEST_NUMBER", "+6511111111")
    rc = cli.main(["join", "V"])
    o = capsys.readouterr()
    assert rc == 1 and "UNKNOWN" in o.out and "LOG FAILED" in o.err


def test_join_logs_unknown_as_unknown_not_no(monkeypatch, tmp_path):
    import csv
    import warroom.cli as cli
    monkeypatch.setattr(cli, "load_roster", lambda p: [])
    monkeypatch.setattr(cli, "dial", lambda *a, **k: DialResult("UNKNOWN, Call may have been placed: x", False, uncertain=True))
    monkeypatch.setenv("WARROOM_VOICE", "false")
    monkeypatch.setenv("WARROOM_TEST_NUMBER", "+6511111111")
    monkeypatch.setenv("WARROOM_JOIN_LOG", str(tmp_path / "j.csv"))
    cli.main(["join", "V"])
    row = list(csv.DictReader(open(tmp_path / "j.csv")))[0]
    assert row["engineer_called"] == "unknown"


def test_join_logs_an_uncertain_result_as_unknown_even_if_it_says_pressed(monkeypatch, tmp_path):
    import csv
    import warroom.cli as cli
    monkeypatch.setattr(cli, "load_roster", lambda p: [])
    monkeypatch.setattr(cli, "dial", lambda *a, **k: DialResult("UNKNOWN, Call may have been placed: x", True, False, "", True))
    monkeypatch.setenv("WARROOM_VOICE", "false")
    monkeypatch.setenv("WARROOM_TEST_NUMBER", "+6511111111")
    monkeypatch.setenv("WARROOM_JOIN_LOG", str(tmp_path / "j.csv"))
    cli.main(["join", "V"])
    row = list(csv.DictReader(open(tmp_path / "j.csv")))[0]
    assert row["engineer_called"] == "unknown" and row["call_answered"] == ""
