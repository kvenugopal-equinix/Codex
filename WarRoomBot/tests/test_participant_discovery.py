"""Participant reads survive hidden main windows without inventing departures or placing calls."""
from pathlib import Path
import re

import pytest

from warroom.config import Settings
from warroom.dialer import DialResult
import warroom.ui_backend as ui
from warroom.watcher import Watcher


class ParticipantAx:
    def __init__(self):
        self.main = None
        self.panel = True
        self.rows = ["Bot (Host, me, Participant ID:1)"]
        self.error = None
        self.opens, self.presses = 0, []
        self.recover = False
        self.panel_open = True

    def trusted(self):
        return True

    def call(self, command, *args, **kwargs):
        if command == "windows":
            return {"ok": True, "windows": ["Zoom Workplace"]
                    + ([self.main] if self.main else [])
                    + (["Participants ({})".format(len(self.rows))] if self.panel else [])}
        if command == "participants":
            if self.error:
                return {"ok": False, "error": self.error}
            if not self.main and not self.panel:
                return {"ok": False, "error": "no meeting or Participants window"}
            if not self.panel_open:
                return {"ok": False, "error": "participants list not visible",
                        "panel_button": "Open participants panel"}
            return {"ok": True, "participants": self.rows,
                    "source_window": "Participants ({})".format(len(self.rows)) if self.panel else self.main}
        if command == "press":
            options = dict(zip(args[::2], args[1::2]))
            assert options["--match"] == "^Open participants"
            assert re.search(options["--window"], self.main, re.I)
            self.presses.append(options)
            self.panel_open = True
            return {"ok": True}
        raise AssertionError("unexpected UI operation: " + command)

    def open_zoom(self):
        self.opens += 1
        if self.recover:
            self.panel = True  # A detached list can reappear while the main window stays hidden.


@pytest.fixture
def room(monkeypatch):
    ax = ParticipantAx()
    clock = {"now": 100.0}
    monkeypatch.setattr(ui, "ax", ax)
    monkeypatch.setattr(ui, "_open_zoom", ax.open_zoom)
    monkeypatch.setattr(ui, "_participant_recover_at", 0.0)
    monkeypatch.setattr(ui, "SURFACE_WAIT", 0.6)
    monkeypatch.setattr(ui.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(ui.time, "sleep", lambda seconds: clock.update(now=clock["now"] + seconds))
    return ax, clock


def test_startup_and_reads_use_detached_panel_without_main_window_or_activation(room):
    ax, _ = room
    assert ui.prepare_meeting() == "Participants (1)"
    for _ in range(5):
        people = ui.read_participants()
        assert len(people) == 1 and people[0].is_me
    assert ax.opens == 0 and ax.presses == []


def test_join_is_detected_from_detached_panel_and_failed_read_does_not_create_rejoin(room):
    ax, _ = room
    called = []
    settings = Settings(
        dry_run=True, live_calling=False, target_mode="test", test_number="+6510000000",
        allow_roster_calls=False, roster_path=Path("unused"), join_log_path=Path("unused"), grace_seconds=0)

    def escalate(name, voice, people):
        called.append(name)
        return DialResult("DRY-RUN: would call"), ""

    watcher = Watcher(settings, [], ui.read_participants, escalate, lambda *args: None,
                      lambda: None, sleep=lambda seconds: None, out=lambda line: None)
    watcher.poll()
    ax.rows.append("Visitor (Participant ID:2)")
    watcher.poll()
    assert called == ["Visitor"]
    ax.rows = []  # Missing the bot's own row is a failed read, never an empty meeting.
    for _ in range(5):
        watcher.poll()
    ax.rows = ["Bot (Host, me, Participant ID:1)", "Visitor (Participant ID:2)"]
    watcher.poll()
    assert called == ["Visitor"]
    assert ax.opens == 0 and ax.presses == []


def test_detached_list_missing_own_row_fails_without_focus_recovery(room):
    ax, _ = room
    ax.rows = ["Visitor"]
    with pytest.raises(ui.UiUnavailable, match="own row missing"):
        ui.read_participants()
    with pytest.raises(ui.UiUnavailable, match="own row missing"):
        ui.prepare_meeting()
    assert ax.opens == 0


def test_ambiguous_participant_lists_fail_without_selecting_one_or_activating(room):
    ax, _ = room
    ax.error = "multiple Participants lists are visible; close the extra meeting panels"
    with pytest.raises(ui.UiError, match="multiple Participants lists"):
        ui.read_participants()
    assert ax.opens == 0 and ax.presses == []


def test_caption_suffix_is_detected_and_panel_action_uses_matching_scope(room):
    ax, _ = room
    ax.main, ax.panel = "Zoom Meeting  40-minutes", False
    ax.panel_open = False
    assert ui.meeting_window() == ax.main and ui.in_meeting()
    assert re.search(ui.PANEL_WINS, ax.main)
    assert not re.search(ui.MEETING_WIN, "Invite people to join meeting")
    for unrelated in ("Zoom Meeting Settings", "Zoom Meeting History"):
        assert not re.search(ui.MEETING_WIN, unrelated)
        assert not re.search(ui.PANEL_WINS, unrelated)
    assert ui.read_participants()[0].is_me
    assert len(ax.presses) == 1 and ax.opens == 0


def test_read_recovery_accepts_detached_panel_without_waiting_for_main_window(room):
    ax, _ = room
    ax.panel, ax.recover = False, True
    assert ui.read_participants()[0].is_me
    assert ax.main is None and ax.opens == 1
    for _ in range(5):
        assert ui.read_participants()[0].is_me
    assert ax.opens == 1


def test_failed_visibility_recovery_is_bounded_and_throttled(room):
    ax, clock = room
    ax.panel = False
    with pytest.raises(ui.UiError, match="no meeting or Participants window"):
        ui.read_participants()
    assert ax.opens == 1 and clock["now"] >= 100.6
    for _ in range(5):
        with pytest.raises(ui.UiError):
            ui.read_participants()
    assert ax.opens == 1
    clock["now"] = 100.0 + ui.PARTICIPANT_RECOVERY_GAP
    with pytest.raises(ui.UiError):
        ui.read_participants()
    assert ax.opens == 2


def test_read_recovery_does_not_interrupt_another_ui_action(room):
    ax, _ = room
    ax.panel, ax.recover = False, True
    with ui.exclusive():
        with pytest.raises(ui.UiError):
            ui.read_participants()
    assert ax.opens == 0


def test_closed_panel_is_not_toggled_while_another_ui_action_holds_lock(room):
    ax, _ = room
    ax.main, ax.panel, ax.panel_open = "Zoom Meeting", False, False
    with ui.exclusive():
        with pytest.raises(ui.UiError, match="participants list not visible"):
            ui.read_participants()
    assert ax.presses == [] and ax.opens == 0


def test_panel_press_failure_allows_one_visibility_recovery(room, monkeypatch):
    ax, _ = room
    ax.main, ax.panel, ax.panel_open = "Zoom Meeting", False, False
    original = ax.call

    def changed_window(command, *args, **kwargs):
        if command == "press":
            return {"ok": False, "error": "not found (0 matches)"}
        return original(command, *args, **kwargs)

    def recover():
        ax.opens += 1
        ax.panel, ax.panel_open = True, True

    monkeypatch.setattr(ax, "call", changed_window)
    monkeypatch.setattr(ui, "_open_zoom", recover)
    assert ui.read_participants()[0].is_me
    assert ax.opens == 1
    assert ui.read_participants()[0].is_me
    assert ax.opens == 1


def test_panel_press_permission_failure_does_not_attempt_visibility_recovery(room, monkeypatch):
    ax, _ = room
    ax.main, ax.panel, ax.panel_open = "Zoom Meeting", False, False
    original = ax.call

    def denied(command, *args, **kwargs):
        if command == "press":
            raise ui.UiUnavailable("not trusted: denied")
        return original(command, *args, **kwargs)

    monkeypatch.setattr(ax, "call", denied)
    with pytest.raises(ui.UiUnavailable, match="not trusted"):
        ui.read_participants()
    assert ax.opens == 0


def test_genuine_process_or_permission_failure_does_not_launch_zoom(room, monkeypatch):
    ax, _ = room

    def denied(*args, **kwargs):
        raise ui.UiUnavailable("not trusted: denied")

    monkeypatch.setattr(ax, "call", denied)
    with pytest.raises(ui.UiUnavailable, match="not trusted"):
        ui.read_participants()
    assert ax.opens == 0
