"""WARROOM_VOICE_ROUTE, the welcome handle in the CLI, how its outcome reaches the join log, and `voice-test`."""
import csv

import pytest

import warroom.cli as cli
import warroom.ui_backend as ui
from warroom.config import ConfigError, Settings
from warroom.dialer import DialResult
from warroom.voice import DEFAULT_MESSAGE

from test_watch_cli import ME, P, env, room


class Handle:
    """Stands in for SharedSpeech: truthy, with an outcome and a wait()."""

    def __init__(self, outcome="yes", raises=None):
        self.outcome, self.raises, self.waited = outcome, raises, False

    def __bool__(self):
        return True

    def wait(self, timeout=None):
        self.waited = True
        if self.raises:
            raise self.raises
        return self.outcome


def rows(tmp_path):
    return list(csv.DictReader(open(tmp_path / "j.csv", newline="")))


# ---------------------------------------------------------------- settings

def test_route_defaults_to_the_meeting(monkeypatch, tmp_path):
    env(monkeypatch, tmp_path)
    assert Settings.from_env().voice_route == "share"


@pytest.mark.parametrize("raw,expected", [("share", "share"), ("local", "local"), (" LOCAL ", "local"),
                                          ('"local"', "local"), ("'Share'", "share"), ("", "share")])
def test_route_accepts_the_two_routes(monkeypatch, tmp_path, raw, expected):
    env(monkeypatch, tmp_path, WARROOM_VOICE_ROUTE=raw)
    assert Settings.from_env().voice_route == expected


@pytest.mark.parametrize("raw", ["blackhole", "meeting", "none", "true"])
def test_an_unknown_route_is_refused_not_defaulted(monkeypatch, tmp_path, raw):
    env(monkeypatch, tmp_path, WARROOM_VOICE_ROUTE=raw)
    with pytest.raises(ConfigError, match="WARROOM_VOICE_ROUTE"):
        Settings.from_env()


def test_a_bad_route_stops_the_cli_before_anything_runs(monkeypatch, tmp_path, capsys):
    env(monkeypatch, tmp_path, WARROOM_VOICE_ROUTE="nonsense")
    assert cli.main(["watch"]) == 2
    assert "CONFIG:" in capsys.readouterr().err


# ---------------------------------------------------------------- which voice is started

def settings(monkeypatch, tmp_path, **extra):
    env(monkeypatch, tmp_path, **extra)
    return Settings.from_env()


def fakes(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "speak", lambda *a, **k: seen.append(("local", a)) or "L")
    monkeypatch.setattr(cli, "speak_in_meeting", lambda *a, **k: seen.append(("share", a)) or "S")
    return seen


def test_live_run_plays_into_the_meeting_by_default(monkeypatch, tmp_path):
    seen = fakes(monkeypatch)
    s = settings(monkeypatch, tmp_path, WARROOM_DRY_RUN="false")
    assert cli._start_voice(s) == "S"
    assert seen == [("share", (DEFAULT_MESSAGE, None))]


def test_local_route_uses_this_macs_speakers(monkeypatch, tmp_path):
    seen = fakes(monkeypatch)
    s = settings(monkeypatch, tmp_path, WARROOM_DRY_RUN="false", WARROOM_VOICE_ROUTE="local",
                 WARROOM_VOICE_NAME="Samantha", WARROOM_VOICE_MESSAGE="Hello there")
    assert cli._start_voice(s) == "L"
    assert seen == [("local", ("Hello there", "Samantha"))]


def test_no_voice_in_a_dry_run_unless_asked(monkeypatch, tmp_path):
    seen = fakes(monkeypatch)
    assert cli._start_voice(settings(monkeypatch, tmp_path)) is None
    assert cli._start_voice(settings(monkeypatch, tmp_path, WARROOM_VOICE_IN_DRY_RUN="true")) == "S"
    assert [k for k, _ in seen] == ["share"]


def test_no_voice_when_voice_is_off(monkeypatch, tmp_path):
    seen = fakes(monkeypatch)
    assert cli._start_voice(settings(monkeypatch, tmp_path, WARROOM_DRY_RUN="false", WARROOM_VOICE="false")) is None
    assert seen == []


# ---------------------------------------------------------------- what the log records

def test_welcome_values():
    assert cli._welcome(None) == "no"
    assert cli._welcome(Handle("yes")) == "yes"
    assert cli._welcome(Handle("FAILED: Zoom\ndid not   start")) == "FAILED: Zoom did not start"
    assert cli._welcome(Handle("FAILED: " + "x" * 500)) == ("FAILED: " + "x" * 500)[:200]
    assert cli._welcome(object()) == "yes"           # the local `say` Popen has no outcome


def watch(monkeypatch, tmp_path, handle, **extra):
    env(monkeypatch, tmp_path, WARROOM_DRY_RUN="false", WARROOM_LIVE_CALLING="true", **extra)
    room(monkeypatch, [ME], [ME, P("Bob")], [ME, P("Bob")])
    monkeypatch.setattr(cli, "speak_in_meeting", lambda *a, **k: handle)
    monkeypatch.setattr(cli, "dial", lambda *a, **k: DialResult("DIALLED +6511111111 (TEST): answered", True, True, "", False, False))
    return cli.main(["watch"])


def test_the_join_log_records_how_the_shared_welcome_went(monkeypatch, tmp_path):
    h = Handle("yes")
    watch(monkeypatch, tmp_path, h)
    assert h.waited and rows(tmp_path)[0]["welcome_voice"] == "yes"


def sequence(monkeypatch, tmp_path, handle, **extra):
    """Runs one visitor through the watcher and returns the order of 'wait for the voice' and 'dial'."""
    events = []
    real_wait = handle.wait
    handle.wait = lambda timeout=None: events.append(("wait", timeout)) or real_wait(timeout)
    env(monkeypatch, tmp_path, WARROOM_DRY_RUN="false", WARROOM_LIVE_CALLING="true", **extra)
    room(monkeypatch, [ME], [ME, P("Bob")], [ME, P("Bob")])
    monkeypatch.setattr(cli, "speak_in_meeting", lambda *a, **k: handle)
    monkeypatch.setattr(cli, "speak", lambda *a, **k: handle)
    monkeypatch.setattr(cli, "dial", lambda *a, **k: events.append("dial") or
                        DialResult("DIALLED +6511111111 (TEST): answered", True, True, "", False, False))
    cli.main(["watch"])
    return events


def test_the_call_does_not_wait_for_the_shared_welcome(monkeypatch, tmp_path):
    # The welcome and the call run in parallel: the dial is issued first, and only afterwards does the CLI wait for the
    # welcome (so the join log can say how it went).
    assert sequence(monkeypatch, tmp_path, Handle("yes")) == ["dial", ("wait", None)]


def test_the_call_does_not_wait_for_the_local_welcome_either(monkeypatch, tmp_path):
    assert sequence(monkeypatch, tmp_path, Handle("yes"), WARROOM_VOICE_ROUTE="local") == ["dial", ("wait", None)]


def test_a_welcome_that_is_still_playing_does_not_hold_the_call_back(monkeypatch, tmp_path):
    h = Handle("unfinished")
    assert sequence(monkeypatch, tmp_path, h)[0] == "dial"
    assert rows(tmp_path)[0]["engineer_called"] == "yes"


def test_a_failed_shared_welcome_is_logged_and_does_not_stop_the_call(monkeypatch, tmp_path):
    watch(monkeypatch, tmp_path, Handle("FAILED: Zoom did not start sharing computer sound"))
    r = rows(tmp_path)[0]
    assert r["welcome_voice"].startswith("FAILED: Zoom did not start sharing")
    assert r["engineer_called"] == "yes"             # the call was placed regardless


def test_the_log_row_is_written_even_if_waiting_for_the_voice_is_interrupted(monkeypatch, tmp_path):
    h = Handle("unfinished", raises=KeyboardInterrupt())
    watch(monkeypatch, tmp_path, h)
    assert rows(tmp_path)[0]["welcome_voice"] == "unfinished"


def test_a_visitor_who_left_still_gets_the_welcome_outcome_logged(monkeypatch, tmp_path):
    env(monkeypatch, tmp_path, WARROOM_DRY_RUN="false", WARROOM_LIVE_CALLING="true")
    room(monkeypatch, [ME], [ME, P("Bob")], [ME])
    h = Handle("yes")
    monkeypatch.setattr(cli, "speak_in_meeting", lambda *a, **k: h)
    monkeypatch.setattr(cli, "dial", lambda *a, **k: pytest.fail("must not dial"))
    assert cli.main(["watch"]) == 0
    r = rows(tmp_path)[0]
    assert h.waited and r["welcome_voice"] == "yes" and r["notes"].startswith("NOT CALLED")


# ---------------------------------------------------------------- voice-test

def vt(monkeypatch, tmp_path, outcome="yes", trusted=True, in_meeting=True, **extra):
    env(monkeypatch, tmp_path, **extra)                 # dry-run stays on: voice-test must ignore it
    monkeypatch.setattr(ui, "input_available", lambda: trusted)
    monkeypatch.setattr(ui, "meeting_window",
                        lambda: "Zoom Meeting" if in_meeting else (_ for _ in ()).throw(ui.UiUnavailable("no meeting")))
    h = Handle(outcome)
    calls = []
    monkeypatch.setattr(cli, "speak_in_meeting", lambda *a, **k: calls.append(a) or h)
    monkeypatch.setattr(cli, "speak", lambda *a, **k: pytest.fail("voice-test never uses the local speakers"))
    monkeypatch.setattr(cli, "dial", lambda *a, **k: pytest.fail("voice-test never dials"))
    return h, calls


def test_voice_test_plays_the_welcome_and_reports(monkeypatch, tmp_path, capsys):
    h, calls = vt(monkeypatch, tmp_path)
    assert cli.main(["voice-test"]) == 0
    assert h.waited and calls == [(DEFAULT_MESSAGE, None)]
    assert "welcome voice: yes" in capsys.readouterr().out
    assert not (tmp_path / "j.csv").exists()            # no log row


def test_voice_test_ignores_dry_run_and_the_voice_switch(monkeypatch, tmp_path):
    h, calls = vt(monkeypatch, tmp_path, WARROOM_VOICE="false", WARROOM_DRY_RUN="true")
    assert cli.main(["voice-test"]) == 0 and len(calls) == 1


def test_voice_test_fails_when_the_share_fails(monkeypatch, tmp_path, capsys):
    vt(monkeypatch, tmp_path, outcome="FAILED: picker never opened")
    assert cli.main(["voice-test"]) == 1
    assert "welcome voice: FAILED: picker never opened" in capsys.readouterr().out


def test_voice_test_needs_accessibility_and_a_meeting(monkeypatch, tmp_path, capsys):
    _, calls = vt(monkeypatch, tmp_path, trusted=False)
    assert cli.main(["voice-test"]) == 1 and "NOT TRUSTED" in capsys.readouterr().out
    _, calls2 = vt(monkeypatch, tmp_path, in_meeting=False)
    assert cli.main(["voice-test"]) == 1 and "UI:" in capsys.readouterr().out
    assert calls == [] and calls2 == []                  # nothing was shared


def test_voice_test_ctrl_c_returns_nonzero(monkeypatch, tmp_path, capsys):
    h, _ = vt(monkeypatch, tmp_path)
    h.raises = KeyboardInterrupt()
    assert cli.main(["voice-test"]) == 1
    assert "stopping the share" in capsys.readouterr().err


def test_voice_test_does_not_print_the_call_gates(monkeypatch, tmp_path, capsys):
    vt(monkeypatch, tmp_path)
    cli.main(["voice-test"])
    assert "gates:" not in capsys.readouterr().err
