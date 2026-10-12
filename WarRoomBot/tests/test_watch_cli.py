"""The `watch` command and the new watcher settings, end to end with the Zoom layer replaced."""
import signal

import pytest

import warroom.cli as cli
import warroom.ui_backend as ui
from warroom.config import ConfigError, Settings
from warroom.dialer import DialResult
from warroom.ui_backend import UiParticipant


def P(name, me=False):
    return UiParticipant(name, name, me, False)


ME = P("Bot (me)", True)


def room(monkeypatch, *states, trusted=True, in_meeting=True):
    """Each read returns the next state; when they run out the user presses Ctrl-C."""
    it = iter(states)

    def read():
        try:
            return next(it)
        except StopIteration:
            raise KeyboardInterrupt from None

    monkeypatch.setattr(ui, "input_available", lambda: trusted)
    monkeypatch.setattr(ui, "meeting_window",
                        lambda: "Zoom Meeting" if in_meeting else (_ for _ in ()).throw(ui.UiUnavailable("no meeting")))
    monkeypatch.setattr(ui, "read_participants", read)
    monkeypatch.setattr(cli, "load_roster", lambda p: [])
    monkeypatch.setattr("time.sleep", lambda s: None)


def env(monkeypatch, tmp_path, **extra):
    base = dict(WARROOM_TEST_NUMBER="+6511111111", WARROOM_JOIN_LOG=str(tmp_path / "j.csv"),
                WARROOM_GRACE_SECONDS="0")
    base.update(extra)
    for k, v in base.items():
        monkeypatch.setenv(k, v)


def test_watch_in_dry_run_logs_a_dry_run_row_and_never_calls(monkeypatch, tmp_path, capsys):
    env(monkeypatch, tmp_path)
    room(monkeypatch, [ME], [ME, P("Bob")], [ME, P("Bob")])
    monkeypatch.setattr(cli, "speak", lambda *a, **k: pytest.fail("no voice in a dry run"))
    monkeypatch.setattr(cli, "speak_in_meeting", lambda *a, **k: pytest.fail("no voice in a dry run"))
    assert cli.main(["watch"]) == 0
    out = capsys.readouterr().out
    assert "VISITOR JOINED: 'Bob'" in out and "DRY-RUN: would call +6511111111" in out
    rows = (tmp_path / "j.csv").read_text().splitlines()
    assert len(rows) == 2 and "Bob" in rows[1] and "dry-run" in rows[1]


def test_watch_rearms_sigint_so_stop_works_for_a_background_launch(monkeypatch, tmp_path):
    # A background child of a non-interactive shell starts with SIGINT ignored; 'watch.sh stop' relies on SIGINT.
    env(monkeypatch, tmp_path)
    room(monkeypatch, [ME])
    before = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        cli.main(["watch"])
        assert signal.getsignal(signal.SIGINT) is signal.default_int_handler
    finally:
        signal.signal(signal.SIGINT, before)


def test_managed_watch_keeps_ownership_during_audio_exit_cleanup(monkeypatch, tmp_path):
    from contextlib import nullcontext
    import warroom.config as config
    import warroom.voice as voice
    env(monkeypatch, tmp_path)
    room(monkeypatch, [ME])
    monkeypatch.setattr(config, "BASE", tmp_path)
    monkeypatch.setattr(cli, "_keep_awake", nullcontext)
    # Keep the suite's original atexit hook; this test checks explicit worker cleanup.
    monkeypatch.setattr(cli.atexit, "unregister", lambda f: None)
    cleaned = []

    def cleanup():
        assert (tmp_path / "logs" / "watcher.pid.json").is_file()
        assert signal.getsignal(signal.SIGINT) is signal.SIG_IGN
        cleaned.append(True)

    monkeypatch.setattr(voice, "finish_welcomes", cleanup)
    assert cli.main(["watch", "--watch-token", "a" * 32]) == 0
    assert cleaned == [True]
    assert not (tmp_path / "logs" / "watcher.pid.json").exists()


def test_watch_needs_accessibility_and_a_meeting(monkeypatch, tmp_path, capsys):
    env(monkeypatch, tmp_path)
    room(monkeypatch, [ME], trusted=False)
    assert cli.main(["watch"]) == 1 and "NOT TRUSTED" in capsys.readouterr().out
    room(monkeypatch, [ME], in_meeting=False)
    assert cli.main(["watch"]) == 1 and "no meeting" in capsys.readouterr().out


def test_watch_logs_a_visitor_who_left_and_does_not_call(monkeypatch, tmp_path, capsys):
    env(monkeypatch, tmp_path)
    room(monkeypatch, [ME], [ME, P("Bob")], [ME])
    monkeypatch.setattr(cli, "dial", lambda *a, **k: pytest.fail("must not dial"))
    assert cli.main(["watch"]) == 0
    assert "NOT CALLED: left during the grace period" in (tmp_path / "j.csv").read_text()


def test_ctrl_c_while_a_call_is_being_placed_exits_nonzero(monkeypatch, tmp_path, capsys):
    env(monkeypatch, tmp_path, WARROOM_DRY_RUN="false", WARROOM_LIVE_CALLING="true")
    room(monkeypatch, [ME], [ME, P("Bob")], [ME, P("Bob")])
    monkeypatch.setattr(cli, "speak_in_meeting", lambda *a, **k: type("V", (), {"wait": lambda self: None})())
    monkeypatch.setattr(cli, "dial", lambda *a, **k: DialResult("UNKNOWN, Call may have been placed", False, False, "", True, True))
    assert cli.main(["watch"]) == 1
    assert "look at Zoom and your phone" in capsys.readouterr().out


def test_a_display_name_cannot_become_a_spreadsheet_formula(monkeypatch, tmp_path):
    env(monkeypatch, tmp_path)
    room(monkeypatch, [ME], [ME, P("=HYPERLINK(\"http://x\")")], [ME, P("=HYPERLINK(\"http://x\")")])
    cli.main(["watch"])
    import csv
    rows = list(csv.DictReader(open(tmp_path / "j.csv", newline="")))
    assert rows[0]["participant_name"] == "'=HYPERLINK(\"http://x\")"


def test_watcher_settings_defaults_and_overrides(monkeypatch, tmp_path):
    env(monkeypatch, tmp_path)
    s = Settings.from_env()
    assert (s.poll_seconds, s.grace_seconds, s.max_calls_per_hour) == (3.0, 0.0, 3)
    assert s.skip_if_support and not s.trust_display_names and s.ignore_names == ()
    env(monkeypatch, tmp_path, WARROOM_POLL_SECONDS="5", WARROOM_MAX_CALLS_PER_HOUR="2",
        WARROOM_TRUST_DISPLAY_NAMES="true", WARROOM_SKIP_IF_SUPPORT_PRESENT="false",
        WARROOM_IGNORE_NAMES=" Fireflies Notetaker , Otter.ai,, ")
    s = Settings.from_env()
    assert (s.poll_seconds, s.max_calls_per_hour) == (5.0, 2)
    assert s.trust_display_names and not s.skip_if_support
    assert s.ignore_names == ("fireflies notetaker", "otter.ai")


@pytest.mark.parametrize("name,value", [("WARROOM_POLL_SECONDS", "0.5"), ("WARROOM_POLL_SECONDS", "abc"),
                                        ("WARROOM_POLL_SECONDS", "nan"), ("WARROOM_GRACE_SECONDS", "-1"),
                                        ("WARROOM_GRACE_SECONDS", "inf"), ("WARROOM_MAX_CALLS_PER_HOUR", "0"),
                                        ("WARROOM_MAX_CALLS_PER_HOUR", "2.5")])
def test_bad_watcher_settings_are_refused_not_defaulted(monkeypatch, tmp_path, name, value):
    env(monkeypatch, tmp_path, **{name: value})
    with pytest.raises(ConfigError):
        Settings.from_env()
