"""The optional Zoom-contact invite: config, target choice, the gates in dialer.invite, the order in _escalate,
and the join-log column it adds. The Zoom layer is always replaced; nothing here touches a real meeting."""
import csv
from dataclasses import replace
from pathlib import Path

import pytest

import warroom.cli as cli
import warroom.dialer as dialer
import warroom.ui_backend as ui
from warroom.config import ConfigError, Settings
from warroom.dialer import DialDecision, DialResult, InviteOutcome, choose_target, invite
from warroom.joinlog import FIELDS, log_join
from warroom.roster import Shift, parse_days, parse_time

MAIL = "test.engineer@example.com"
OTHER = "someone.else@example.com"


def mk(tmp_path=None, **k):
    d = dict(dry_run=True, live_calling=False, target_mode="test", test_number="+6511111111",
             allow_roster_calls=False, roster_path=Path("x"),
             join_log_path=(tmp_path / "j.csv") if tmp_path else Path("y"))
    d.update(k)
    return Settings(**d)


def live(tmp_path, **k):
    d = dict(dry_run=False, live_calling=True, zoom_invite=True, test_zoom_email=MAIL)
    d.update(k)
    return mk(tmp_path, **d)


def shift(zoom_email=MAIL, phone="+6590000001"):
    return Shift("Eng One", zoom_email, phone, "Asia/Singapore", parse_days("Mon-Fri"),
                 parse_time("00:00"), parse_time("23:59"), 1, True)


@pytest.fixture
def fake_invite(monkeypatch):
    """Replaces ui_backend.invite_contact; records the calls and returns/raises what the test sets."""
    calls = []
    box = {"result": ui.InviteResult("invited", True, "chip added, Invite pressed", True), "raise": None}

    def invite_contact(email, *, press_invite=False):
        calls.append((email, press_invite))
        if box["raise"]:
            raise box["raise"]
        return box["result"]

    monkeypatch.setattr(ui, "invite_contact", invite_contact)
    return calls, box


# ---- config -------------------------------------------------------------------------------------

def test_invite_is_off_by_default_and_shown_in_the_gates():
    s = Settings.from_env()
    assert s.zoom_invite is False and s.test_zoom_email == ""
    assert "zoom_invite=False" in s.gates()


def test_invite_flag_and_address_are_read(monkeypatch):
    monkeypatch.setenv("WARROOM_ZOOM_INVITE", "true")
    monkeypatch.setenv("WARROOM_TEST_ZOOM_EMAIL", f' "{MAIL}" ')
    s = Settings.from_env()
    assert s.zoom_invite is True and s.test_zoom_email == MAIL and "zoom_invite=True" in s.gates()


@pytest.mark.parametrize("raw", ["nope", "a@b", "two words@example.com", "@example.com", "x@y@example.com"])
def test_bad_zoom_email_is_an_error_that_does_not_echo_it(monkeypatch, raw):
    monkeypatch.setenv("WARROOM_TEST_ZOOM_EMAIL", raw)
    with pytest.raises(ConfigError) as e:
        Settings.from_env()
    assert raw not in str(e.value)


def test_blank_zoom_email_is_fine(monkeypatch):
    monkeypatch.setenv("WARROOM_TEST_ZOOM_EMAIL", "  ")
    assert Settings.from_env().test_zoom_email == ""


# ---- choose_target ------------------------------------------------------------------------------

def test_test_mode_uses_only_the_test_address_and_only_when_the_feature_is_on():
    s = mk(test_zoom_email=MAIL)
    assert choose_target(s, [shift(OTHER)]).zoom_email == ""
    s = mk(zoom_invite=True, test_zoom_email=MAIL)
    assert choose_target(s, [shift(OTHER)]).zoom_email == MAIL        # the roster address is discarded


def test_roster_mode_uses_the_roster_address_only_when_the_feature_is_on():
    s = mk(target_mode="roster", allow_roster_calls=True)
    assert choose_target(s, [shift(OTHER)]).zoom_email == ""
    s = mk(target_mode="roster", allow_roster_calls=True, zoom_invite=True)
    d = choose_target(s, [shift(OTHER)])
    assert d.zoom_email == OTHER and d.will_place


# ---- dialer.invite gates ------------------------------------------------------------------------

def decision(email=MAIL, will_place=True):
    return DialDecision("+6511111111", "TEST", will_place, "test mode", email)


def test_feature_off_means_no_text_no_log_and_no_ui(fake_invite):
    calls, _ = fake_invite
    out = invite(mk(test_zoom_email=MAIL), decision())
    assert out == InviteOutcome("") and calls == []


def test_nothing_is_invited_when_no_call_will_be_placed(fake_invite):
    calls, _ = fake_invite
    assert invite(live(Path("/nonexistent")), decision(will_place=False)).text == "" and calls == []


def test_missing_address_is_skipped_with_a_hint(fake_invite):
    calls, _ = fake_invite
    out = invite(live(Path("/nonexistent")), decision(email=""))
    assert out.text.startswith("ZOOM INVITE SKIPPED") and "WARROOM_TEST_ZOOM_EMAIL" in out.text
    assert out.log == "no" and calls == []
    out = invite(live(Path("/nonexistent"), target_mode="roster", allow_roster_calls=True), decision(email=""))
    assert "zoom_email in the roster" in out.text and calls == []


def test_a_malformed_address_is_refused_and_not_echoed(fake_invite):
    calls, _ = fake_invite
    out = invite(live(Path("/nonexistent")), decision(email="not an address"))
    assert out.text.startswith("ZOOM INVITE REFUSED") and "not an address" not in out.text and calls == []


def test_test_mode_refuses_any_address_but_the_test_one(fake_invite):
    calls, _ = fake_invite
    out = invite(live(Path("/nonexistent")), decision(email=OTHER))
    assert out.text.startswith("ZOOM INVITE REFUSED") and OTHER not in out.text and out.log == "no" and calls == []


def test_the_uri_dial_method_cannot_invite(monkeypatch, fake_invite):
    calls, _ = fake_invite
    monkeypatch.setenv("WARROOM_DIAL_METHOD", "uri")
    out = invite(live(Path("/nonexistent")), decision())
    assert out.text.startswith("ZOOM INVITE SKIPPED") and calls == []


@pytest.mark.parametrize("k", [dict(dry_run=True), dict(live_calling=False)])
def test_dry_run_or_live_flag_off_only_rehearses(fake_invite, k, tmp_path):
    calls, _ = fake_invite
    out = invite(live(tmp_path, **k), decision())
    assert out.text.startswith("DRY-RUN: would invite") and out.log == "dry-run"
    assert MAIL not in out.text and calls == []


def test_a_live_call_guard_blocks_the_invite_too(tmp_path, fake_invite):
    calls, _ = fake_invite
    dialer._guard_write(dialer._guard_path(live(tmp_path)), "in_flight", "+6511111111", 600)
    out = invite(live(tmp_path), decision())
    assert out.text.startswith("ZOOM INVITE REFUSED") and out.log == "no" and calls == []


def test_a_clean_invite_presses_invite_once_and_says_so(tmp_path, fake_invite):
    calls, _ = fake_invite
    out = invite(live(tmp_path), decision())
    assert calls == [(MAIL, True)]
    assert out.text.startswith("ZOOM INVITE SENT") and out.log == "yes" and not out.interrupted
    assert MAIL not in out.text


@pytest.mark.parametrize("state,ok,log,prefix", [
    ("unknown", False, "unknown", "ZOOM INVITE UNKNOWN"),
    ("no_match", False, "no", "ZOOM INVITE NOT SENT, no_match"),
    ("ambiguous", False, "no", "ZOOM INVITE NOT SENT, ambiguous"),
    ("not_selected", False, "no", "ZOOM INVITE NOT SENT, not_selected"),
])
def test_each_result_state_maps_to_a_log_value(tmp_path, fake_invite, state, ok, log, prefix):
    _, box = fake_invite
    box["result"] = ui.InviteResult(state, ok, "detail here", state == "unknown")
    out = invite(live(tmp_path), decision())
    assert out.text.startswith(prefix) and out.log == log and "detail here" in out.text


def test_an_exception_means_invite_was_not_pressed(tmp_path, fake_invite):
    _, box = fake_invite
    box["raise"] = ui.UiError("Invite window did not open")
    out = invite(live(tmp_path), decision())
    assert out.text.startswith("ZOOM INVITE NOT SENT: ") and out.log == "no" and not out.interrupted


def test_ctrl_c_is_reported_as_unknown_and_flags_the_caller_to_stop(tmp_path, fake_invite):
    _, box = fake_invite
    box["raise"] = KeyboardInterrupt()
    out = invite(live(tmp_path), decision())
    assert out.log == "unknown" and out.interrupted and out.text.startswith("ZOOM INVITE UNKNOWN")


# ---- cli._escalate ------------------------------------------------------------------------------

def _escalate_env(monkeypatch, tmp_path, order, **k):
    s = live(tmp_path, **k)
    monkeypatch.setattr(cli, "invite", lambda st, d: order.append("invite") or InviteOutcome("ZOOM INVITE SENT: ok", "yes"))
    monkeypatch.setattr(cli, "dial", lambda st, d: order.append("dial") or
                        DialResult("DIALLED +6511111111 (TEST): connected", True, True, "2026-10-09T01:00:00+00:00"))
    return s


def test_the_contact_is_invited_before_the_phone_is_dialled_and_both_are_logged(monkeypatch, tmp_path):
    order = []
    s = _escalate_env(monkeypatch, tmp_path, order)
    result, d = cli._escalate(s, "Bob", [], None)
    assert order == ["invite", "dial"] and result.answered and d.number == "+6511111111"
    rows = list(csv.DictReader((tmp_path / "j.csv").open()))
    assert rows[0]["zoom_invited"] == "yes" and rows[0]["engineer_called"] == "yes"
    assert rows[0]["notes"].startswith("ZOOM INVITE SENT: ok | DIALLED")


def test_an_interrupted_invite_skips_the_dial_and_stops_the_watcher(monkeypatch, tmp_path, capsys):
    order = []
    s = live(tmp_path)
    monkeypatch.setattr(cli, "invite", lambda st, d: InviteOutcome("ZOOM INVITE UNKNOWN: interrupted", "unknown", True))
    monkeypatch.setattr(cli, "dial", lambda st, d: order.append("dial") or DialResult("DIALLED"))
    result, _ = cli._escalate(s, "Bob", [], None)
    assert order == [] and result.interrupted and result.text.startswith("NOT CALLED")
    row = list(csv.DictReader((tmp_path / "j.csv").open()))[0]
    assert row["zoom_invited"] == "unknown" and row["engineer_called"] == "no"


def test_a_failed_invite_does_not_stop_the_call(monkeypatch, tmp_path):
    order = []
    s = live(tmp_path)
    monkeypatch.setattr(cli, "invite", lambda st, d: InviteOutcome("ZOOM INVITE NOT SENT: no window", "no"))
    monkeypatch.setattr(cli, "dial", lambda st, d: order.append("dial") or DialResult("DIALLED x", True, True))
    result, _ = cli._escalate(s, "Bob", [], None)
    assert order == ["dial"] and result.answered
    assert list(csv.DictReader((tmp_path / "j.csv").open()))[0]["zoom_invited"] == "no"


def test_with_the_feature_off_the_notes_are_just_the_call_text(monkeypatch, tmp_path):
    s = mk(tmp_path)
    result, _ = cli._escalate(s, "Bob", [], None)
    row = list(csv.DictReader((tmp_path / "j.csv").open()))[0]
    assert row["notes"] == result.text and row["zoom_invited"] == ""


def test_the_dial_command_invites_first_and_stops_if_interrupted(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("WARROOM_TEST_NUMBER", "+6511111111")
    monkeypatch.setenv("WARROOM_JOIN_LOG", str(tmp_path / "j.csv"))
    monkeypatch.setattr(cli, "load_roster", lambda p: [])
    monkeypatch.setattr(cli, "invite", lambda st, d: InviteOutcome("ZOOM INVITE UNKNOWN: interrupted", "unknown", True))
    monkeypatch.setattr(cli, "dial", lambda *a: pytest.fail("must not dial after an interrupted invite"))
    assert cli.main(["dial"]) == 1
    assert "ZOOM INVITE UNKNOWN" in capsys.readouterr().out


# ---- join log -----------------------------------------------------------------------------------

OLD = FIELDS[:-1]


def test_a_new_log_gets_the_full_header(tmp_path):
    p = tmp_path / "j.csv"
    log_join(p, participant_name="A", zoom_invited="yes")
    assert p.read_text().splitlines()[0].split(",") == FIELDS
    assert list(csv.DictReader(p.open()))[0]["zoom_invited"] == "yes"


def test_an_old_log_is_rewritten_with_padded_rows_and_new_rows_line_up(tmp_path):
    p = tmp_path / "j.csv"
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(OLD)
        w.writerow(["u", "l", "tz", "", "Old Visitor"] + [""] * (len(OLD) - 5))
    log_join(p, participant_name="New Visitor", zoom_invited="dry-run")
    rows = list(csv.DictReader(p.open()))
    assert [r["participant_name"] for r in rows] == ["Old Visitor", "New Visitor"]
    assert rows[0]["zoom_invited"] == "" and rows[1]["zoom_invited"] == "dry-run"
    assert not (tmp_path / "j.csv.migrating").exists()


def test_a_current_log_is_left_alone(tmp_path):
    p = tmp_path / "j.csv"
    log_join(p, participant_name="A")
    before = p.stat().st_mtime_ns
    import warroom.joinlog as jl
    assert jl._migrate(p) == FIELDS and p.stat().st_mtime_ns == before


def test_failed_id_migration_does_not_append_an_event_without_its_id(tmp_path, monkeypatch):
    p = tmp_path / "j.csv"
    with p.open("w", newline="") as f:
        csv.writer(f).writerow(OLD)
    import warroom.joinlog as jl
    before = p.read_bytes()
    monkeypatch.setattr(jl.os, "replace", lambda *a: (_ for _ in ()).throw(PermissionError("busy")))
    with pytest.raises(OSError, match="could not upgrade the join log with event IDs"):
        log_join(p, participant_name="A", zoom_invited="yes")
    assert p.read_bytes() == before
    assert not list(tmp_path.glob("j.csv.migrating*"))


def test_an_unrelated_header_is_never_rewritten(tmp_path):
    p = tmp_path / "j.csv"
    p.write_text("a,b,c\n1,2,3\n")
    import warroom.joinlog as jl
    assert jl._migrate(p) == ["a", "b", "c"] and p.read_text() == "a,b,c\n1,2,3\n"


# Exact-name Contacts lookup is opt-in; the old email lookup remains compatible.

def test_contact_lookup_configuration_defaults_and_explicit_name(monkeypatch):
    assert Settings.from_env().zoom_contact_lookup == "email"
    assert Settings.from_env().test_zoom_contact == ""
    monkeypatch.setenv("WARROOM_ZOOM_CONTACT_LOOKUP", " NAME ")
    monkeypatch.setenv("WARROOM_TEST_ZOOM_CONTACT", "  Engineer O'Neil  ")
    settings = Settings.from_env()
    assert settings.zoom_contact_lookup == "name"
    assert settings.test_zoom_contact == "Engineer O'Neil"


@pytest.mark.parametrize("lookup", ["", "fuzzy", "auto"])
def test_unknown_contact_lookup_is_a_configuration_error(monkeypatch, lookup):
    monkeypatch.setenv("WARROOM_ZOOM_CONTACT_LOOKUP", lookup)
    with pytest.raises(ConfigError, match="WARROOM_ZOOM_CONTACT_LOOKUP"):
        Settings.from_env()


@pytest.mark.parametrize("name", ["Eng\nOne", "Eng\tOne", "Eng\x85One", "x" * 201])
def test_invalid_test_contact_name_is_a_configuration_error(monkeypatch, name):
    monkeypatch.setenv("WARROOM_TEST_ZOOM_CONTACT", name)
    with pytest.raises(ConfigError):
        Settings.from_env()


def test_name_mode_selects_phone_and_name_from_same_roster_row():
    settings = mk(target_mode="roster", allow_roster_calls=True, zoom_invite=True, zoom_contact_lookup="name")
    selected = choose_target(settings, [shift(phone="+6590000001"),
                                        replace(shift(phone="+6590000002"), name="Other Engineer")])
    assert selected.zoom_contact == "Eng One" and selected.number == "+6590000001"
    assert selected.zoom_email == ""     # no email fallback in name mode


@pytest.mark.parametrize("test_name", ["", "Explicit Test Contact"])
def test_name_mode_never_uses_roster_contact_in_test_mode(test_name):
    settings = mk(zoom_invite=True, zoom_contact_lookup="name", test_zoom_contact=test_name)
    selected = choose_target(settings, [shift()])
    assert selected.zoom_contact == test_name and selected.engineer == "TEST"
    assert selected.number == settings.test_number and selected.zoom_email == ""


def test_name_selector_is_empty_when_invites_are_off():
    settings = mk(zoom_invite=False, zoom_contact_lookup="name", test_zoom_contact="Test Contact")
    assert choose_target(settings, [shift()]).zoom_contact == ""


def test_live_name_invite_uses_contacts_name_selector_and_reports_actual_row(monkeypatch, tmp_path):
    calls = []
    def contact(*args, **kwargs):
        calls.append((args, kwargs))
        return ui.InviteResult("invited", True, "sent", True, "ENG ONE")
    monkeypatch.setattr(ui, "invite_contact", contact)
    settings = live(tmp_path, target_mode="roster", allow_roster_calls=True, zoom_contact_lookup="name")
    outcome = invite(settings, choose_target(settings, [shift()]))
    assert calls == [((), {"contact_name": "Eng One", "press_invite": True})]
    assert outcome.log == "yes" and outcome.contact_name == "ENG ONE"
    assert outcome.attempted and outcome.sent


@pytest.mark.parametrize("dry,live_flag", [(True, True), (False, False)])
def test_name_invite_rehearsal_never_drives_zoom(monkeypatch, tmp_path, dry, live_flag):
    monkeypatch.setattr(ui, "invite_contact", lambda **kwargs: pytest.fail("dry run drove Zoom"))
    settings = live(tmp_path, dry_run=dry, live_calling=live_flag, zoom_contact_lookup="name",
                    test_zoom_contact="Test Contact")
    outcome = invite(settings, choose_target(settings, []))
    assert outcome.log == "dry-run" and not outcome.attempted and not outcome.sent
    assert not outcome.contact_name


def test_name_test_mode_refuses_unconfigured_and_foreign_contacts(monkeypatch, tmp_path):
    monkeypatch.setattr(ui, "invite_contact", lambda **kwargs: pytest.fail("wrong contact reached Zoom"))
    settings = live(tmp_path, zoom_contact_lookup="name", test_zoom_contact="Test Contact")
    for name in ("", "Eng One", "Test Contact Extra", "Test Contact\n"):
        outcome = invite(settings, DialDecision(settings.test_number, "TEST", True, "test", zoom_contact=name))
        assert outcome.log == "no" and not outcome.attempted and not outcome.sent


@pytest.mark.parametrize("state,pressed,sent", [("invited", True, True), ("unknown", True, False),
                                               ("no_match", False, False), ("ambiguous", False, False)])
def test_name_invitation_metadata_tracks_attempt_and_success(monkeypatch, tmp_path, state, pressed, sent):
    monkeypatch.setattr(ui, "invite_contact", lambda **kwargs:
                        ui.InviteResult(state, sent, "result", pressed, "Eng One" if pressed else ""))
    settings = live(tmp_path, zoom_contact_lookup="name", test_zoom_contact="Eng One")
    outcome = invite(settings, choose_target(settings, []))
    assert outcome.attempted == pressed and outcome.sent == sent
    assert outcome.contact_name == ("Eng One" if pressed else "")


def test_interrupted_name_lookup_does_not_infer_selected_contact(monkeypatch, tmp_path):
    def interrupted(**kwargs):
        raise KeyboardInterrupt
    monkeypatch.setattr(ui, "invite_contact", interrupted)
    settings = live(tmp_path, zoom_contact_lookup="name", test_zoom_contact="Eng One")
    outcome = invite(settings, choose_target(settings, []))
    assert outcome.interrupted and outcome.attempted and not outcome.sent
    assert outcome.contact_name == ""  # interruption may have happened before a row was selected


def test_name_invites_still_respect_call_guard_and_roster_gate(monkeypatch, tmp_path):
    monkeypatch.setattr(ui, "invite_contact", lambda **kwargs: pytest.fail("blocked invite reached Zoom"))
    settings = live(tmp_path, zoom_contact_lookup="name", target_mode="roster", allow_roster_calls=False)
    selected = DialDecision("+6590000001", "Eng One", True, "roster", zoom_contact="Eng One")
    assert invite(settings, selected).log == "no"
    settings = live(tmp_path, zoom_contact_lookup="name", target_mode="roster", allow_roster_calls=True)
    dialer._guard_write(dialer._guard_path(settings), "in_flight", selected.number, 600)
    assert invite(settings, selected).log == "no"
