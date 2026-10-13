"""Only the selected roster target's fresh, unambiguous presence avoids another invite and call."""
import csv
from dataclasses import replace
from datetime import time

import pytest

from warroom import cli, ui_backend as ui
from warroom.config import Settings
from warroom.dialer import DialResult, InviteOutcome
from warroom.roster import Shift
from warroom.watcher import Watcher


def P(name, me=False):
    return ui.UiParticipant(name, name, me, False)


ME = P("Bot", True)


def shift(name="Ann", priority=1):
    return Shift(name, "", "+14155550123", "UTC", frozenset(range(7)), time(), time(), priority, True)


def settings(tmp_path, **changes):
    s = Settings(dry_run=False, live_calling=True, target_mode="roster", test_number="+14155550124",
                 allow_roster_calls=True, roster_path=tmp_path / "roster.csv",
                 join_log_path=tmp_path / "joins.csv", voice_enabled=False, grace_seconds=0,
                 zoom_invite=True, zoom_contact_lookup="name")
    return replace(s, **changes)


def routes(monkeypatch):
    calls = []

    def invite(s, d):
        calls.append(("invite", d))
        return InviteOutcome("ZOOM INVITE SENT: fixture", "yes", contact_name=d.engineer,
                             attempted=True, sent=True)

    def dial(s, d):
        calls.append(("dial", d))
        return DialResult("NOT PLACED: fixture")

    monkeypatch.setattr(cli, "invite", invite)
    monkeypatch.setattr(cli, "dial", dial)
    return calls


def watch(monkeypatch, s, states, rosters):
    states, rosters = iter(states), iter(rosters)

    def read():
        try:
            value = next(states)
        except StopIteration:
            raise KeyboardInterrupt from None
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(ui, "input_available", lambda: True)
    monkeypatch.setattr(ui, "prepare_meeting", lambda: None)
    monkeypatch.setattr(ui, "read_participants", read)
    monkeypatch.setattr(cli, "load_roster", lambda path: next(rosters))
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    assert cli._watch_command(s, False) == 0


def rows(s):
    with s.join_log_path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def test_baseline_selected_engineer_avoids_both_routes_without_trusting_roster_names(monkeypatch, tmp_path):
    s = settings(tmp_path)
    calls = routes(monkeypatch)
    baseline, visitors = [ME, P("Ann")], [ME, P("Ann"), P("Bob")]
    watch(monkeypatch, s, [baseline, visitors, visitors], [[shift()], [shift()]])
    assert not s.trust_display_names and not calls
    row, = rows(s)
    assert row["participant_name"] == "Bob" and row["engineer_name"] == "Ann"
    assert row["engineer_called"] == "no" and row["zoom_invited"] == "no"
    assert "selected roster engineer 'Ann' is already in the meeting (exact display-name match)" in row["notes"]


def test_simultaneous_visitors_log_the_presence_skip_without_claiming_a_call(monkeypatch, tmp_path):
    s = settings(tmp_path)
    calls = routes(monkeypatch)
    baseline, visitors = [ME, P("Ann")], [ME, P("Ann"), P("Bob"), P("Cy")]
    watch(monkeypatch, s, [baseline, visitors, visitors], [[shift()], [shift()]])
    assert not calls
    logged = rows(s)
    assert [row["participant_name"] for row in logged] == ["Bob", "Cy"]
    assert all(row["engineer_called"] == "no" and "already in the meeting" in row["notes"] for row in logged)
    assert all("call placed" not in row["notes"] for row in logged)


@pytest.mark.parametrize("engineer,people,present", [
    ("Ann", [P(" aNN ")], True),
    ("  Straße  ", [P("STRASSE")], True),
    ("Ann", [P("Ann Guest")], False),
    ("Ann", [P("An")], False),
    ("Ann", [P("Ann"), P(" aNN ")], False),
    ("Ann", [P("Ann", True)], False),
    ("Ann", [P("Ann", True), P("Ann")], False),
    ("Ann", [], False),
    ("Ann", None, False),
    ("", [P("")], False),
    ("<Engineer>", [P("<Engineer>")], False),
])
def test_only_exact_unique_nonbot_real_target_presence_skips(monkeypatch, tmp_path, engineer, people, present):
    calls = routes(monkeypatch)
    result, decision = cli._escalate(settings(tmp_path), "Bob", [shift(engineer)], None, people)
    assert (not calls) is present
    if present:
        assert not result.pressed and not result.invite_attempted and not result.invite_sent
    else:
        assert calls == [("invite", decision), ("dial", decision)]
        assert calls[0][1] is calls[1][1] is decision


@pytest.mark.parametrize("changes,duty,person", [
    ({"skip_if_support": False}, [shift()], "Ann"),
    ({"target_mode": "test"}, [shift()], "Ann"),
    ({"target_mode": "test"}, [shift()], "TEST"),
    ({"allow_roster_calls": False}, [shift()], "Ann"),
    ({}, [], "Ann"),
    ({}, [shift(), shift("Backup", 2)], "Backup"),
])
def test_presence_guard_respects_settings_and_selected_target(monkeypatch, tmp_path, changes, duty, person):
    calls = routes(monkeypatch)
    cli._escalate(settings(tmp_path, **changes), "Bob", duty, None, [ME, P(person), P("Bob")])
    assert [route for route, _ in calls] == ["invite", "dial"]


@pytest.mark.parametrize("present,expected_routes", [("New engineer", []), ("Old engineer", ["invite", "dial"])])
def test_presence_uses_refreshed_roster_and_the_same_single_decision(monkeypatch, tmp_path, present, expected_routes):
    s = settings(tmp_path)
    calls, selections = routes(monkeypatch), []
    choose = cli.choose_target

    def choose_once(settings, duty):
        decision = choose(settings, duty)
        selections.append(decision)
        return decision

    monkeypatch.setattr(cli, "choose_target", choose_once)
    baseline, visitors = [ME, P(present)], [ME, P(present), P("Bob")]
    watch(monkeypatch, s, [baseline, visitors, visitors], [[shift("Old engineer")], [shift("New engineer")]])
    assert len(selections) == 1 and selections[0].engineer == "New engineer"
    assert [route for route, _ in calls] == expected_routes
    assert all(decision is selections[0] for _, decision in calls)


@pytest.mark.parametrize("recheck", [[ME, P("Bob")], ui.UiUnavailable("unreadable list")])
def test_departed_target_or_failed_recheck_cannot_use_stale_presence(monkeypatch, tmp_path, recheck):
    s = settings(tmp_path)
    calls = routes(monkeypatch)
    reads = [recheck] * 3 if isinstance(recheck, Exception) else [recheck]
    watch(monkeypatch, s, [[ME, P("Ann")], [ME, P("Ann"), P("Bob")], *reads], [[shift()], [shift()]])
    assert [route for route, _ in calls] == ["invite", "dial"]


def test_presence_skip_finishes_welcome_without_consuming_call_limit_or_promoting_name(monkeypatch, tmp_path):
    s = settings(tmp_path, max_calls_per_hour=1)
    calls, welcomed = routes(monkeypatch), []

    class Voice:
        def wait(self):
            welcomed.append(True)

    people = [ME, P("Ann"), P("Bob")]

    def escalate(name, voice, fresh):
        result, decision = cli._escalate(s, name, [shift()], voice, fresh)
        return result, decision.number

    w = Watcher(s, [shift()], lambda: people, escalate, lambda *args: None,
                lambda: Voice(), sleep=lambda seconds: None)
    w.step([ME, P("Ann")])
    w.poll()
    assert welcomed == [True] and not calls and not w.calls
    assert w.kind(P("Ann")) == "visitor" and not w.support_names
    people = [ME, P("Bob"), P("Cy")]
    w.poll()
    assert [route for route, _ in calls] == ["invite", "dial"]
    assert len(w.calls) == 1
