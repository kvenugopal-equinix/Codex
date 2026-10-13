"""The join watcher: poll, diff, grace, re-check, escalate. No Zoom, no sleeping, no real calls."""
from pathlib import Path

import pytest

from warroom.config import Settings
from warroom.dialer import DialResult
from warroom.roster import Shift, parse_days, parse_time
from warroom.ui_backend import UiParticipant, UiUnavailable
from warroom.watcher import CONTACT_ARRIVAL_WAIT, QUIET_AFTER_BAD, Watcher

ME = UiParticipant("Bot (me)", "Bot (me)", True, False)


def P(name, phone=""):
    return UiParticipant(name, name, False, False, phone)


def mk(**k):
    d = dict(dry_run=False, live_calling=True, target_mode="test", test_number="+6511111111",
             allow_roster_calls=False, roster_path=Path("x"), join_log_path=Path("y"),
             grace_seconds=10.0, poll_seconds=3.0, max_calls_per_hour=3)
    d.update(k)
    return Settings(**d)


def shift(name="Ann", phone="+6590000001"):
    return Shift(name, "", phone, "Asia/Singapore", parse_days("Mon-Fri"), parse_time("00:00"),
                 parse_time("23:59"), 1, True)


DIALLED = DialResult("DIALLED +6511111111 (TEST): answered", True, True, "t0")
DRY = DialResult("DRY-RUN: would call")
NOANSWER = DialResult("CALL PLACED, timeout: no answer", True, False, "t0")
UNSURE = DialResult("UNKNOWN, Call may have been placed", True, False, "", True)


class Room:
    """Scripted reads. An Exception is raised; the last item repeats once the script runs out."""

    def __init__(self, *script):
        self.script, self.reads = list(script), 0

    def __call__(self):
        item = self.script[min(self.reads, len(self.script) - 1)]
        self.reads += 1
        if isinstance(item, Exception):
            raise item
        return item


class Rig:
    def __init__(self, *script, shifts=(), result=DIALLED, **settings):
        self.room = Room(*script)
        self.escalated, self.skipped, self.sleeps, self.lines, self.voices = [], [], [], [], 0
        self.now = 0.0
        self.result = result

        def escalate(name, voice, people):
            self.escalated.append(name)
            return self.result, "+6511111111"

        def start_voice():
            self.voices += 1
            return object()

        self.w = Watcher(mk(**settings), list(shifts), self.room, escalate,
                         lambda n, v, why: self.skipped.append((n, why)), start_voice,
                         sleep=lambda s: (self.sleeps.append(s), setattr(self, "now", self.now + s)),
                         clock=lambda: self.now, out=self.lines.append)

    def polls(self, n):
        for _ in range(n):
            self.w.poll()

    def show(self, *names):
        """From now on every read returns the bot plus these people."""
        self.room.script, self.room.reads = [[ME, *[P(n) for n in names]]], 0
        self.w.poll()


def test_people_already_there_are_not_greeted():
    r = Rig([ME, P("Alice")], [ME, P("Alice")])
    r.polls(2)
    assert r.escalated == [] and r.voices == 0


def test_a_new_visitor_gets_voice_grace_recheck_and_one_call():
    r = Rig([ME], [ME, P("Bob")])
    r.polls(2)
    assert r.escalated == ["Bob"] and r.voices == 1 and r.skipped == []
    assert 10.0 in r.sleeps          # the grace period happened before the call


def test_a_visitor_who_leaves_during_the_grace_period_is_not_called_for():
    r = Rig([ME], [ME, P("Bob")], [ME])      # third read is the re-check
    r.polls(2)
    assert r.escalated == [] and r.skipped == [("Bob", "left during the grace period")]


def test_an_engineer_already_present_by_phone_number_suppresses_the_call():
    r = Rig([ME], [ME, P("Bob")], [ME, P("Bob"), P("+65 9000 0001", "+6590000001")], shifts=[shift()])
    r.polls(2)
    assert r.escalated == [] and "engineer is already" in r.skipped[0][1]


def test_skip_if_support_can_be_turned_off():
    r = Rig([ME], [ME, P("Bob")], [ME, P("Bob"), P("x", "+6590000001")], shifts=[shift()], skip_if_support=False)
    r.polls(2)
    assert r.escalated == ["Bob"]


def test_a_roster_name_is_not_trusted_unless_asked():
    base = ([ME], [ME, P("Bob")], [ME, P("Bob"), P("Ann")])
    r = Rig(*base, shifts=[shift()])
    r.polls(2)
    assert r.escalated == ["Bob"]            # "Ann" is just a display name anyone can type
    r = Rig(*base, shifts=[shift()], trust_display_names=True)
    r.polls(2)
    assert r.escalated == [] and "Ann" in r.skipped[0][1]


def test_the_test_number_counts_as_support_and_so_does_a_number_without_country_code():
    r = Rig([ME], [ME, P("Bob")], [ME, P("Bob"), P("11111111", "11111111")])
    r.polls(2)
    assert r.escalated == [] and r.skipped


def test_ignored_names_and_the_bot_itself_are_never_visitors():
    r = Rig([ME], [ME, P("Fireflies Notetaker"), P("Bot")], ignore_names=("fireflies notetaker",))
    r.polls(2)
    # "Bot" is not the (me) row, so it is a visitor; the note-taker is ignored
    assert r.escalated == ["Bot"]
    assert r.skipped == [] and not any("Fireflies" in l for l in r.lines)


def test_a_note_taker_alone_never_triggers_anything():
    r = Rig([ME], [ME, P("Fireflies Notetaker")], ignore_names=("fireflies notetaker",))
    r.polls(2)
    assert r.escalated == [] and r.voices == 0


def test_a_failed_read_is_a_glitch_not_a_departure():
    r = Rig([ME, P("Alice")], UiUnavailable("own row missing"), [ME, P("Alice")], [ME, P("Alice")])
    r.polls(4)
    assert r.escalated == [] and r.w.bad == 0


def test_one_good_read_without_a_person_does_not_make_them_new_when_they_return():
    r = Rig([ME, P("Alice")], [ME], [ME, P("Alice")])
    r.polls(3)
    assert r.escalated == []


def test_someone_who_really_left_is_greeted_again_when_they_come_back():
    r = Rig([ME, P("Alice")], [ME], [ME], [ME, P("Alice")])
    r.polls(4)
    assert r.escalated == ["Alice"]


def test_the_watcher_never_gives_up_when_the_meeting_is_out_of_sight():
    # Live 2026-10-09: it stopped itself after a minute of "no Zoom meeting window", and a visitor who joined while
    # the window was hidden was never greeted. Now it waits, however long, and greets them when the window is back.
    r = Rig([ME], *([UiUnavailable("no meeting")] * 500), [ME, P("Bob")], [ME, P("Bob")])
    r.polls(502)
    assert r.w.bad == 0 and r.escalated == ["Bob"]


def test_a_long_outage_is_reported_rarely_and_its_end_once():
    r = Rig([ME], *([UiUnavailable("no meeting")] * 250), [ME])
    r.polls(252)
    failed = [x for x in r.lines if x.startswith("read failed")]
    assert len(failed) == 4                     # at 1, 10, 100 and 200 in a row
    assert all("still watching" in x for x in failed)
    assert r.lines[-1] == "reading the meeting again after 250 failed reads"


def test_a_single_glitch_is_not_announced_as_an_outage_ending():
    r = Rig([ME], UiUnavailable("x"), [ME])
    r.polls(3)
    assert not any(x.startswith("reading the meeting again") for x in r.lines)


def test_the_quiet_threshold_is_what_the_reports_use():
    r = Rig([ME], *([UiUnavailable("x")] * QUIET_AFTER_BAD), [ME])
    r.polls(QUIET_AFTER_BAD + 2)
    assert sum(x.startswith("read failed") for x in r.lines) == 2


def test_two_visitors_in_one_poll_share_one_call():
    r = Rig([ME], [ME, P("Bob"), P("Cy")])
    r.polls(2)
    assert r.escalated == ["Bob"] and r.voices == 1
    assert r.skipped == [("Cy", "covered by the call placed for 'Bob'")]


def test_two_guests_with_the_same_name_are_both_counted():
    r = Rig([ME, P("Guest")], [ME, P("Guest"), P("Guest")])
    r.polls(2)
    assert r.escalated == ["Guest"]


def test_the_hourly_ceiling_counts_placed_calls():
    r = Rig(result=NOANSWER, max_calls_per_hour=2)
    r.show()
    r.show("A")
    r.show("A", "B")
    r.show("A", "B", "C")
    assert r.escalated == ["A", "B"] and "call limit" in r.skipped[0][1]


def test_the_ceiling_releases_after_an_hour():
    r = Rig(result=NOANSWER, max_calls_per_hour=1)
    r.show()
    r.show("A")
    r.show("A", "B")
    assert r.escalated == ["A"] and len(r.skipped) == 1
    r.now += 3601
    r.show("A", "B", "C")
    assert r.escalated == ["A", "C"]


def test_a_dry_run_does_not_use_up_the_hourly_ceiling():
    r = Rig(result=DRY, max_calls_per_hour=1)
    r.show()
    r.show("A")
    r.show("A", "B")
    assert r.escalated == ["A", "B"]


def test_the_engineer_who_joins_after_the_call_is_not_greeted_as_a_visitor():
    r = Rig([ME], [ME, P("Bob")], [ME, P("Bob")], [ME, P("Bob"), P("Dev Eng", "+6511111111")],
            [ME, P("Bob"), P("Dev Eng", "+6511111111"), P("Cy")])
    r.polls(2)                                   # baseline, then Bob; the call is answered, then Dev Eng appears
    assert r.escalated == ["Bob"]
    r.polls(1)
    assert r.escalated == ["Bob"]                # Dev Eng was absorbed, not greeted
    r.polls(1)
    assert r.escalated == ["Bob"] and "Dev Eng" in r.skipped[0][1]     # Cy: an engineer is already here


def test_an_unanswered_call_does_not_wait_for_an_engineer():
    r = Rig([ME], [ME, P("Bob")], result=NOANSWER)
    r.polls(2)
    assert not any("engineer joined" in l for l in r.lines)
    assert r.sleeps == [10.0]


def test_an_uncertain_call_still_counts_and_still_looks_for_the_engineer():
    r = Rig([ME], [ME, P("Bob")], [ME, P("Bob")], [ME, P("Bob"), P("Dev", "+6511111111")], result=UNSURE)
    r.polls(2)
    assert len(r.w.calls) == 1
    assert any("Dev" in l and "support arrival recognized" in l for l in r.lines)


def test_ctrl_c_during_a_call_stops_the_watcher():
    r = Rig([ME], [ME, P("Bob")], result=DialResult("UNKNOWN", False, False, "", True, True))
    r.polls(1)
    with pytest.raises(KeyboardInterrupt):
        r.polls(1)
    assert r.w.interrupted


def test_a_failed_recheck_still_calls_and_does_not_mistake_the_visitor_for_the_engineer():
    err = UiUnavailable("glitch")
    r = Rig([ME], [ME, P("Bob")], err, err, err, [ME, P("Bob")])
    r.polls(2)
    assert r.escalated == ["Bob"]
    assert not any("engineer joined" in l for l in r.lines)


def test_a_bug_while_escalating_is_reported_and_the_watch_continues():
    r = Rig([ME], [ME, P("Bob")], [ME, P("Bob"), P("Cy")])
    r.w.escalate = lambda n, v, people: (_ for _ in ()).throw(RuntimeError("boom"))
    r.polls(3)
    assert any("ERROR: RuntimeError: boom" in l and "'Bob'" in l for l in r.lines)
    assert r.w.known["Bob"] == 1             # not retried forever


def test_names_are_shown_escaped():
    r = Rig([ME], [ME, P("Bob\x1b[2J")])
    r.polls(2)
    assert not any("\x1b" in l for l in r.lines)


def test_run_polls_and_sleeps_between_reads():
    r = Rig([ME], [ME])
    r.w.run(max_polls=3)
    assert r.room.reads == 3 and r.sleeps == [3.0, 3.0, 3.0]


def test_the_bot_being_renamed_mid_meeting_is_not_a_new_visitor():
    r = Rig([UiParticipant("Bot A (me)", "x", True, False)], [UiParticipant("Bot B (me)", "x", True, False)])
    r.polls(2)
    assert r.escalated == []


def contacts_result(*, sent=True, attempted=True, name="Ann", **kwargs):
    return DialResult("NOT PLACED: phone route unavailable", invite_contact_name=name,
                      invite_attempted=attempted, invite_sent=sent, **kwargs)


def test_sent_contact_join_is_not_another_visitor_when_the_phone_failed():
    r = Rig(result=contacts_result(), shifts=[shift()])
    r.show()
    r.show("Bob")
    r.show("Bob", "Ann")
    assert r.escalated == ["Bob"] and r.voices == 1
    assert r.w.kind(P("Ann")) == "support"
    assert not r.w.support_names  # no global trust-display-names opt-in
    assert any("arrival inferred" in line and "not account verification" in line for line in r.lines)


def test_sent_contact_presence_honors_skip_if_support_for_other_visitors():
    r = Rig(result=contacts_result())
    r.show()
    r.show("Bob")
    r.show("Bob", "Ann")
    r.show("Bob", "Ann", "Cy")
    assert r.escalated == ["Bob"]
    assert r.skipped[-1][0] == "Cy" and "engineer is already" in r.skipped[-1][1]


def test_unrelated_visitor_still_escalates_when_support_skip_is_disabled():
    r = Rig(result=contacts_result(), skip_if_support=False)
    r.show()
    r.show("Bob")
    r.show("Bob", "Ann")
    r.show("Bob", "Ann", "Cy")
    assert r.escalated == ["Bob", "Cy"]


def test_unknown_invitation_prevents_self_trigger_but_never_claims_support():
    r = Rig(result=contacts_result(sent=False))
    r.show()
    r.show("Bob")
    r.show("Bob", "Ann")
    assert r.escalated == ["Bob"] and r.w.kind(P("Ann")) == "invited"
    r.show("Bob", "Ann", "Cy")
    assert r.escalated == ["Bob", "Cy"]
    assert any("invitation delivery is unconfirmed" in line for line in r.lines)


def test_existing_baseline_contact_name_is_never_promoted_by_an_invitation():
    r = Rig(result=contacts_result(), shifts=[shift()])
    r.show("Ann")
    r.show("Ann", "Bob")
    r.show("Ann", "Bob", "Cy")
    assert r.escalated == ["Bob", "Cy"]
    assert r.w.kind(P("Ann")) == "visitor" and not r.w._pending_contacts


def test_one_missing_snapshot_does_not_make_baseline_contact_a_fresh_invitee():
    r = Rig([ME, P("Ann")], [ME, P("Bob")], [ME, P("Bob")], result=contacts_result())
    r.polls(2)
    r.show("Bob", "Ann")
    assert r.escalated == ["Bob"]
    assert r.w.kind(P("Ann")) == "visitor" and not r.w._pending_contacts


def test_pending_contact_match_expires_at_its_deadline():
    r = Rig(result=contacts_result())
    r.show()
    r.show("Bob")
    r.now += CONTACT_ARRIVAL_WAIT
    r.show("Bob", "Ann")
    assert r.escalated == ["Bob", "Ann"]
    assert r.w.kind(P("Ann")) == "visitor"


def test_bound_contact_does_not_become_new_visitor_when_arrival_deadline_passes():
    r = Rig(result=contacts_result())
    r.show()
    r.show("Bob")
    r.show("Bob", "Ann")
    r.now += CONTACT_ARRIVAL_WAIT + 1
    r.show("Bob", "Ann")
    r.show("Bob", "Ann", "Cy")
    assert r.escalated == ["Bob"] and r.w.kind(P("Ann")) == "support"


def test_contact_correlation_expires_after_two_good_absences_and_rejoin_is_a_visitor():
    r = Rig(result=contacts_result())
    r.show()
    r.show("Bob")
    r.show("Bob", "Ann")
    r.show("Bob")
    r.show("Bob")
    r.show("Bob", "Ann")
    assert r.escalated == ["Bob", "Ann"]
    assert r.w.kind(P("Ann")) == "visitor"


def test_bad_read_and_single_absence_do_not_drop_contact_correlation():
    r = Rig(result=contacts_result())
    r.show()
    r.show("Bob")
    r.show("Bob", "Ann")
    r.show("Bob")
    r.room.script, r.room.reads = [UiUnavailable("no list")], 0
    r.polls(2)
    r.show("Bob", "Ann")
    assert r.escalated == ["Bob"] and r.w.kind(P("Ann")) == "support"


def test_duplicate_contact_names_never_create_an_inferred_support_presence():
    r = Rig(result=contacts_result())
    r.show()
    r.show("Bob")
    r.show("Bob", "Ann", " aNN ")
    assert r.w.kind(P("Ann")) == "visitor" and r.w.kind(P(" aNN ")) == "visitor"
    assert not r.w._pending_contacts and not r.w._invited_presence
    assert len(r.escalated) == 2  # one escalation for the ambiguous arrival batch


def test_second_duplicate_name_invalidates_an_existing_contact_correlation():
    r = Rig(result=contacts_result())
    r.show()
    r.show("Bob")
    r.show("Bob", "Ann")
    r.show("Bob", "Ann", "Ann")
    assert r.w.kind(P("Ann")) == "visitor"
    assert not r.w._invited_presence
    assert any("duplicate display names" in line for line in r.lines)


@pytest.mark.parametrize("already_arrived", [False, True])
def test_bot_rename_cannot_acquire_or_transfer_contact_correlation(already_arrived):
    r = Rig(result=contacts_result())
    r.show()
    r.show("Bob")
    if already_arrived:
        r.show("Bob", "Ann")
    renamed_bot = UiParticipant("Ann", "Ann (me)", True, False)
    r.room.script, r.room.reads = [[renamed_bot, P("Bob")]], 0
    r.polls(1)
    assert not r.w._invited_presence and not r.w._pending_contacts
    assert r.w.kind(renamed_bot) == "me"
    # Even without an empty intervening snapshot, that name must not transfer from the bot to a guest.
    r.show("Bob", "Ann")
    assert r.escalated == ["Bob", "Ann"] and r.w.kind(P("Ann")) == "visitor"


def test_contact_match_is_casefold_and_trim_exact_not_substring():
    r = Rig(result=contacts_result(name="  Straße  "), skip_if_support=False)
    r.show()
    r.show("Bob")
    r.show("Bob", "STRASSE")
    r.show("Bob", "STRASSE", "STRASSE Guest")
    assert r.escalated == ["Bob", "STRASSE Guest"]
    assert r.w.kind(P("STRASSE")) == "support"


@pytest.mark.parametrize("result", [DRY, contacts_result(attempted=False), contacts_result(name="")])
def test_unattempted_or_unnamed_invite_does_not_infer_a_contact(result):
    r = Rig(result=result)
    r.show()
    r.show("Bob")
    r.show("Bob", "Ann")
    assert r.escalated == ["Bob", "Ann"] and r.w.kind(P("Ann")) == "visitor"


def test_actual_dry_run_never_registers_contact_correlation():
    r = Rig(result=contacts_result(), dry_run=True)
    r.show()
    r.show("Bob")
    r.show("Bob", "Ann")
    assert r.escalated == ["Bob", "Ann"] and not r.w._invited_presence


def test_contact_attempt_counts_toward_hourly_ceiling_when_phone_fails():
    r = Rig(result=contacts_result(sent=False), max_calls_per_hour=1)
    r.show()
    r.show("Bob")
    r.show("Bob", "Cy")
    assert r.escalated == ["Bob"] and len(r.w.calls) == 1
    assert "call limit" in r.skipped[-1][1]


def test_interrupted_invite_stops_before_registering_or_reading_contact_arrivals():
    r = Rig([ME], [ME, P("Bob")], result=contacts_result(interrupted=True))
    r.polls(1)
    with pytest.raises(KeyboardInterrupt):
        r.polls(1)
    assert r.w.interrupted and not r.w._pending_contacts
    assert r.room.reads == 3


def test_cli_preserves_contacts_outcome_when_phone_fails(monkeypatch, tmp_path):
    from warroom import cli
    from warroom.dialer import InviteOutcome

    monkeypatch.setattr(cli, "invite", lambda *args: InviteOutcome(
        "ZOOM INVITE SENT", "yes", contact_name="Directory Name", attempted=True, sent=True))
    monkeypatch.setattr(cli, "dial", lambda *args: DialResult("NOT PLACED: phone unavailable"))
    monkeypatch.setattr(cli, "log_join", lambda *args, **kwargs: None)
    result, _ = cli._escalate(mk(join_log_path=tmp_path / "joins.csv"), "Bob", [], None)
    assert result.invite_contact_name == "Directory Name"
    assert result.invite_attempted and result.invite_sent and not result.pressed
