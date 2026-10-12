"""The computer-audio share that carries the spoken welcome into the meeting: the Zoom UI steps (against a fake that
mimics axctl and the share picker) and the voice thread around it. Nothing here reaches Zoom, say or afplay."""
import os
import re
import threading
import time

import pytest

import warroom.ui_backend as ui
import warroom.voice as voice
from conftest import REAL_OPEN_ZOOM, REAL_PLAY, REAL_RENDER


class ShareAx:
    """The share UI as mapped on a live Zoom: toolbar Share -> picker window -> Other Tab -> Computer audio (arms)
    -> 'Share - Computer audio' (starts). While sharing, the meeting window has a 'My computer sound' tab whose
    close button exists only once the tab has been selected (clicked)."""

    def __init__(self):
        self.meeting = True
        self.picker = False
        self.other = False
        self.armed = False
        self.sharing = False
        self.tab_selected = False
        self.presses, self.clicks, self.closed = [], [], []
        self.picker_never_opens = False
        self.go_never_starts = False
        self.close_never_stops = False
        self.click_never_selects = False
        self.stop_after_clicks = 1
        self.foreground = True
        self.opened = 0                     # times Zoom was brought forward (open -a zoom.us)
        self.open_brings_meeting_back = True

    def open_zoom(self):
        self.opened += 1
        if self.open_brings_meeting_back:
            self.meeting = True

    def trusted(self):
        return True

    def call(self, cmd, *a, **k):
        o = {a[i][2:]: a[i + 1] for i in range(0, len(a) - 1, 2) if a[i].startswith("--")}
        win, m = o.get("window", ""), o.get("match", "")
        if cmd == "windows":
            return {"ok": True, "windows": (["Zoom Meeting"] if self.meeting else [])
                    + (["Share screen window"] if self.picker else [])}
        if cmd == "activate":
            return {"ok": True}
        if cmd == "find":
            if win == ui.MEETING_WIN and m == ui.SHARE_LIVE_RX:
                return {"ok": True, "matches": [{"desc": "My computer sound"}] if self.sharing else []}
            if win == ui.MEETING_WIN and m == ui.SHARE_CLOSE_RX:
                return {"ok": True, "matches": [{}] if self.sharing and self.tab_selected else []}
            if win == ui.SHARE_WIN and m == ui.SHARE_GO_RX:
                return {"ok": True, "matches": [{"desc": "Share - Computer audio"}] if self.picker and self.armed else []}
        if cmd == "press":
            self.presses.append((win, m))
            if win == ui.MEETING_WIN and m == "^Share$":
                if not self.sharing and not self.picker_never_opens:
                    self.picker = True
                return {"ok": True}
            if win == ui.SHARE_WIN and m == "^Other Tab" and self.picker:
                self.other = True
                return {"ok": True}
            if win == ui.SHARE_WIN and m == "^Computer audio, Share audio" and self.picker and self.other:
                self.armed = True
                return {"ok": True}
            if win == ui.SHARE_WIN and re.search(m, "Share - Computer audio") and self.picker and self.armed:
                self.picker = self.armed = self.other = False
                self.sharing = not self.go_never_starts
                return {"ok": True}
            if win == ui.MEETING_WIN and m == ui.SHARE_CLOSE_RX and self.sharing and self.tab_selected:
                if not self.close_never_stops:
                    self.sharing = self.tab_selected = False
                return {"ok": True}
            return {"ok": False, "error": "not found (0 matches)"}
        if cmd == "click":
            self.clicks.append(m)
            if m == ui.SHARE_TAB_RX and self.sharing and not self.click_never_selects:
                self.tab_selected = True
                return {"ok": True}
            return {"ok": False, "error": "not found (0 matches)"}
        if cmd == "close":
            self.closed.append(win)
            self.picker = self.armed = self.other = False
            return {"ok": True}
        raise AssertionError(f"unexpected {cmd} {a}")


@pytest.fixture
def share(monkeypatch):
    f = ShareAx()
    monkeypatch.setattr(ui, "ax", f)
    monkeypatch.setattr(ui, "_open_zoom", f.open_zoom)
    for name in ("SHARE_PICKER_WAIT", "SHARE_START_WAIT", "SHARE_STOP_WAIT", "SURFACE_WAIT"):
        monkeypatch.setattr(ui, name, 0.05)
    monkeypatch.setattr(ui.time, "sleep", lambda s: None)
    return f


# ---------------------------------------------------------------- the Zoom UI steps

def test_start_walks_the_picker_and_ends_with_the_share_running(share):
    ui.start_audio_share()
    assert share.sharing and not share.picker
    assert [m for _, m in share.presses] == ["^Share$", "^Other Tab", "^Computer audio, Share audio", ui.SHARE_GO_RX]


def test_start_never_presses_a_screen_share_button(share):
    ui.start_audio_share()
    assert not any(re.search("Desktop|Screen", m, re.I) for _, m in share.presses)
    assert re.search(ui.SHARE_GO_RX, "Share - Computer audio")
    assert not re.search(ui.SHARE_GO_RX, "Share - Desktop 1")


def test_start_is_a_no_op_when_the_share_is_already_running(share):
    share.sharing = True
    ui.start_audio_share()
    assert share.presses == []


def test_start_needs_a_meeting_even_after_bringing_zoom_forward(share):
    share.meeting, share.open_brings_meeting_back = False, False
    with pytest.raises(ui.UiUnavailable):
        ui.start_audio_share()
    assert share.presses == [] and share.opened == 1


def test_start_that_never_opens_the_picker_fails_cleanly(share):
    share.picker_never_opens = True
    with pytest.raises(ui.UiError, match="did not open"):
        ui.start_audio_share()
    assert not share.sharing


def test_start_that_does_not_take_effect_closes_the_picker_and_reports(share):
    share.go_never_starts = True
    with pytest.raises(ui.UiError, match="did not start sharing"):
        ui.start_audio_share()
    assert not share.sharing and not share.picker


def test_a_failed_start_still_stops_a_share_that_appeared_late(share, monkeypatch):
    real = ui._wait
    calls = []

    def late(pred, seconds, msg):
        calls.append(msg)
        if "did not start" in msg:                    # the share turns up after the wait gave up
            share.sharing, share.tab_selected = True, True
        return real(lambda: False, 0, msg)

    monkeypatch.setattr(ui, "_wait", late)
    with pytest.raises(ui.UiError):
        ui.start_audio_share()
    assert not share.sharing


def test_stop_clicks_an_unselected_tab_first_then_presses_its_close_button(share):
    share.sharing, share.tab_selected = True, False
    ui.stop_audio_share()
    assert not share.sharing
    assert share.clicks == [ui.SHARE_TAB_RX]
    assert share.presses == [(ui.MEETING_WIN, ui.SHARE_CLOSE_RX)]


def test_stop_with_the_tab_already_selected_does_not_click(share):
    share.sharing, share.tab_selected = True, True
    ui.stop_audio_share()
    assert not share.sharing and share.clicks == []


def test_stop_when_nothing_is_shared_does_nothing(share):
    ui.stop_audio_share()
    assert share.presses == [] and share.clicks == []


def test_stop_that_cannot_end_the_share_says_what_to_click(share):
    share.sharing, share.tab_selected, share.close_never_stops = True, True, True
    with pytest.raises(ui.UiError, match="click the x on the 'My computer sound' tab"):
        ui.stop_audio_share()


def test_stop_when_the_tab_cannot_be_selected_reports_why(share):
    share.sharing, share.click_never_selects = True, True
    with pytest.raises(ui.UiError, match="click the x"):
        ui.stop_audio_share()


def test_stop_reports_a_hidden_meeting_instead_of_assuming_the_share_is_gone(share):
    share.sharing, share.meeting, share.open_brings_meeting_back = True, False, False
    with pytest.raises(ui.UiUnavailable):
        ui.stop_audio_share()
    assert share.sharing                    # still reported as running: nothing was assumed


# ---------------------------------------------------------------- a call that hides the meeting window

def test_a_visible_meeting_is_never_brought_forward(share):
    share.sharing, share.tab_selected = True, True
    ui.start_audio_share()                  # already running: a no-op
    ui.stop_audio_share()
    assert share.opened == 0


def test_stop_brings_zoom_forward_when_the_call_hid_the_meeting_window(share):
    # Live 2026-10-09: the dial brought Zoom Workplace forward, the meeting window dropped out of Accessibility and
    # the share could not be stopped.
    share.sharing, share.tab_selected, share.meeting = True, False, False
    ui.stop_audio_share()
    assert share.opened == 1 and not share.sharing


def test_start_brings_zoom_forward_when_the_meeting_window_is_hidden(share):
    share.meeting = False
    ui.start_audio_share()
    assert share.opened == 1 and share.sharing


def test_a_meeting_window_that_comes_back_late_is_waited_for(share, monkeypatch):
    share.sharing, share.tab_selected, share.meeting, share.open_brings_meeting_back = True, True, False, False
    polls = []
    real = ui.in_meeting

    def slow():
        polls.append(1)
        if len(polls) == 3:
            share.meeting = True
        return real()

    monkeypatch.setattr(ui, "in_meeting", slow)
    ui.stop_audio_share()
    assert len(polls) == 3 and not share.sharing


def test_open_zoom_runs_open_a_zoom_us_and_survives_a_failure(monkeypatch):
    seen = []
    monkeypatch.setattr(ui.subprocess, "run", lambda cmd, **k: seen.append(cmd))
    REAL_OPEN_ZOOM()
    assert seen == [["open", "-a", "zoom.us"]]

    def boom(cmd, **k):
        raise OSError("no open")

    monkeypatch.setattr(ui.subprocess, "run", boom)
    REAL_OPEN_ZOOM()                        # the caller looks for the window anyway


def test_zoom_that_is_not_running_is_reported_not_launched(share, monkeypatch):
    monkeypatch.setattr(share, "call", lambda cmd, *a, **k: {"ok": False, "error": "Zoom is not running"})
    with pytest.raises(ui.UiError, match="not running"):
        ui.stop_audio_share()
    assert share.opened == 0


def test_audio_sharing_reflects_the_indicator(share):
    assert not ui.audio_sharing()
    share.sharing = True
    assert ui.audio_sharing()


# ---------------------------------------------------------------- the voice thread

class FakeZoom:
    def __init__(self, log, start_error=None, stop_error=None):
        self.log, self.start_error, self.stop_error = log, start_error, stop_error

    def start_audio_share(self):
        self.log.append("start")
        if self.start_error:
            raise ui.UiError(self.start_error)

    def stop_audio_share(self):
        self.log.append("stop")
        if self.stop_error:
            raise ui.UiError(self.stop_error)


def greet(tmp_path, log, *, start_error=None, stop_error=None, render_error=None, play_error=None, text="hello"):
    path = tmp_path / "w.aiff"

    def render(*a):
        log.append("render")
        if render_error:
            raise RuntimeError(render_error)
        path.write_bytes(b"x")
        return str(path)

    def play(p):
        log.append("play")
        if play_error:
            raise RuntimeError(play_error)

    h = voice.speak_in_meeting(text, ui=FakeZoom(log, start_error, stop_error), render_fn=render, play_fn=play,
                               sleep=lambda s: log.append(f"sleep {s:g}"), lead_in=0.5, tail=0.25)
    return h, path


def test_greeting_renders_shares_plays_and_stops_in_that_order(tmp_path):
    log = []
    h, path = greet(tmp_path, log)
    assert h and h.wait() == "yes" and h.outcome == "yes"
    assert log == ["render", "start", "sleep 0.5", "play", "sleep 0.25", "stop"]
    assert not path.exists()


def test_the_handle_says_unfinished_until_the_greeting_is_over(tmp_path):
    gate, log = threading.Event(), []

    def play(p):
        gate.wait(5)

    h = voice.speak_in_meeting("hi", ui=FakeZoom(log), render_fn=lambda *a: str(tmp_path / "x"), play_fn=play,
                               sleep=lambda s: None)
    time.sleep(0.05)
    assert h.outcome == "unfinished" and bool(h)
    gate.set()
    assert h.wait(5) == "yes"


def test_a_failed_share_start_is_reported_not_played_locally(tmp_path):
    log = []
    h, path = greet(tmp_path, log, start_error="Zoom did not start sharing computer sound")
    assert h.wait() == "FAILED: Zoom did not start sharing computer sound"
    assert "play" not in log and log[-1] == "stop"        # the start is verified stopped too: it may have half-started
    assert not path.exists()


def test_a_render_failure_never_touches_zoom(tmp_path):
    log = []
    h, _ = greet(tmp_path, log, render_error="say not found")
    assert h.wait() == "FAILED: say not found"
    assert log == ["render"]


def test_a_playback_failure_still_stops_the_share(tmp_path):
    log = []
    h, path = greet(tmp_path, log, play_error="afplay failed")
    assert h.wait() == "FAILED: afplay failed"
    assert log[-1] == "stop" and not path.exists()


def test_a_share_that_cannot_be_stopped_is_a_loud_failure(tmp_path, capsys):
    log = []
    h, _ = greet(tmp_path, log, stop_error="could not stop the computer-audio share")
    assert h.wait() == "FAILED: share left running: could not stop the computer-audio share"
    assert "WELCOME SHARE STILL RUNNING" in capsys.readouterr().err
    assert h in voice._may_be_sharing                      # so the exit hook retries


def test_a_failed_start_and_a_failed_stop_keep_both_reasons(tmp_path):
    log = []
    h, _ = greet(tmp_path, log, start_error="picker never opened", stop_error="meeting hidden")
    out = h.wait()
    assert "picker never opened" in out and "meeting hidden" in out


def test_two_greetings_never_share_at_the_same_time(tmp_path):
    log, gate = [], threading.Event()

    def play_first(p):
        log.append("play 1")
        gate.wait(5)

    zoom = FakeZoom(log)
    h1 = voice.speak_in_meeting("a", ui=zoom, render_fn=lambda *a: str(tmp_path / "1"), play_fn=play_first, sleep=lambda s: None)
    deadline = time.monotonic() + 5
    while "play 1" not in log and time.monotonic() < deadline:
        time.sleep(0.01)
    h2 = voice.speak_in_meeting("b", ui=zoom, render_fn=lambda *a: str(tmp_path / "2"), play_fn=lambda p: log.append("play 2"),
                                sleep=lambda s: None)
    time.sleep(0.1)
    assert log.count("start") == 1                         # the second waits for the first to stop
    gate.set()
    assert h1.wait(5) == "yes" and h2.wait(5) == "yes"
    assert log == ["start", "play 1", "stop", "start", "play 2", "stop"]


def test_exit_hook_stops_a_share_that_may_still_be_running(monkeypatch):
    log = []
    monkeypatch.setattr(voice, "_zoom", lambda: FakeZoom(log))
    voice._stop_leftovers()
    assert log == []                                       # nothing open: Zoom is not touched
    voice._may_be_sharing.add(object())
    voice._stop_leftovers()
    assert log == ["stop"]


def test_exit_hook_shouts_when_it_cannot_stop(monkeypatch, capsys):
    monkeypatch.setattr(voice, "_zoom", lambda: FakeZoom([], stop_error="meeting hidden"))
    voice._may_be_sharing.add(object())
    voice._stop_leftovers()
    assert "WELCOME SHARE STILL RUNNING" in capsys.readouterr().err


def test_render_builds_a_safe_say_command(monkeypatch):
    seen = {}

    def run(cmd, **k):
        seen.update(cmd=cmd, input=k.get("input"))

    monkeypatch.setattr(voice.subprocess, "run", run)
    path = REAL_RENDER("-v bogus", "Samantha", 180)         # a message that looks like an option
    try:
        assert seen["cmd"][:3] == ["say", "-o", path]
        assert seen["cmd"][3:] == ["-v", "Samantha", "-r", "180", "-f", "-"]
        assert seen["input"] == "-v bogus"                  # on stdin, never on the command line
    finally:
        voice._remove(path)


def test_render_removes_its_file_when_say_fails(monkeypatch):
    made = []

    def run(cmd, **k):
        made.append(cmd[2])
        raise voice.subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(voice.subprocess, "run", run)
    with pytest.raises(voice.subprocess.CalledProcessError):
        REAL_RENDER("hi")
    assert made and not os.path.exists(made[0])


def test_play_uses_afplay_and_waits(monkeypatch):
    seen = {}
    monkeypatch.setattr(voice.subprocess, "run", lambda cmd, **k: seen.update(cmd=cmd, k=k))
    REAL_PLAY("/tmp/x.aiff")
    assert seen["cmd"] == ["afplay", "/tmp/x.aiff"] and seen["k"]["check"] is True
