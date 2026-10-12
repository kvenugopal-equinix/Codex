"""ui_backend against a simulated Zoom (no real UI is touched)."""
import json
import re
import pytest
import warroom.ui_backend as ui
from warroom.config import Settings
from warroom.dialer import DialDecision, dial
from pathlib import Path


WORKPLACE = "Zoom Workplace"
INVITE_T = "Invite people to join meeting 9"


def node(window, role, value="", title="", desc=""):
    return {"window": window, "role": role, "title": title, "desc": desc, "value": value}


class FakeAx:
    """Just enough of axctl's behaviour, driven by a tiny state machine.

    Window scoping mirrors axctl: no --window = every window except Zoom Workplace (untitled ones included);
    --window RE = titled windows whose title matches (Workplace included).
    prompt_at: None | "call" (prompt right after Call, blocks the answer) | "complete" (after the Complete
    press; the button stays until Continue) | "late" (button already gone, prompt shows up one read later).
    """

    def __init__(self, tab="Zoom Phone, 7 of 7", typed_ok=True, answers_after=None, trusted=True):
        self.invite = False
        self.number = ""
        self.tab = tab
        self.typed_ok = typed_ok
        self.call_pressed = 0
        self.polls = 0
        self.answers_after = answers_after      # None = never answers
        self.complete_pressed = False
        self.closed = 0
        self.is_trusted = trusted
        self.wipe_on_get = False
        self.needs_activate = False
        self.activated = 0
        self.call_attempts = 0
        self.refuse_call = False
        self.rows = ["Bridge Bot (me)", "Alice (Host)", "+6512345678"]
        self.panel_open = True
        self.fail_after_call = None         # axctl command that raises once Call has been pressed
        self.call_press_raises = False      # the Call press takes effect, then axctl times out
        self.fail_complete = False
        self.empty_after_complete = False
        self.wipe_on_activate = False
        self.prompt_at = None
        self.prompt_window = ""             # "" = an untitled window, like a system alert
        self.prompt_visible = False
        self.reappear = 0                   # times the prompt comes straight back after Continue
        self.continue_pressed = 0
        self.continue_scopes = []
        self.stray_continue = False         # a Continue button in some other, titled window
        self.prompt_needs_activate = False  # Zoom drops to the background when the prompt opens
        self.fail_texts_after_complete = False
        self.continue_error = None          # error string returned by the Continue press instead of pressing it
        self.vanish_on_activate = False     # the prompt is gone by the time Zoom has been brought forward
        self.activate_scopes = []
        self.joined = False
        self._late_reads = 0
        self.invite_home = None             # None = Invite always pressable; else the one window holding it, and
        self.invite_error = None            # only while the panel is open. A "Participants (N)" home is a detached window.
        self.presses = []                   # (match, --window) of every press
        self.workplace_listed = False       # is "Zoom Workplace" among the windows (not when full screen)
        # Invite window: the Switch cycler and the Contacts tab
        self.switch_mode = "ok"             # ok | applies_but_refuses (-25200 yet it moved) | dead (ok, never moves)
        self.directory = {"eng@example.com": ["Eng One"], "dup@example.com": ["Dup A", "Dup B"]}
        self.filter = ""
        self.filter_ignores_set = False
        self.filter_set_refuses = False     # the set lands but axctl answers -25200
        self.selected = None
        self.clicks = []
        self.click_selects = True
        self.invite_pressed = 0
        self.invite_press_error = None      # error string returned by the Invite-button press
        self.invite_press_applies = True    # does that press take effect even when it reports the error
        self.invite_closes_window = False   # does Zoom close the Invite window once the invitation is sent

    def trusted(self):
        return self.is_trusted

    TABS = ["Contacts", "Email", "Calendar", "Chat", "Rooms", "Phone", "Zoom Phone"]

    def _on_contacts(self):
        return self.invite and self.tab.startswith("Contacts")

    def _listed(self):
        if self.filter == "":
            return [n for names in self.directory.values() for n in names]
        return list(self.directory.get(self.filter, []))

    def _step_switch(self):
        i = int(re.search(r", (\d+) of", self.tab).group(1)) % len(self.TABS)
        self.tab = f"{self.TABS[i]}, {i + 1} of {len(self.TABS)}"

    def _show_prompt(self):
        self.prompt_visible = True
        if self.prompt_needs_activate:
            self.needs_activate = True

    @staticmethod
    def _scoped(nodes, rx):
        return [n for n in nodes if (re.search(rx, n["window"], re.I) if rx else n["window"] != WORKPLACE)]

    def _screen(self):
        nodes = []
        if self.call_pressed and not self.joined:
            answered = (self.answers_after is not None and self.polls > self.answers_after
                        and not (self.prompt_at == "call" and self.prompt_visible))
            if answered:
                nodes += [node(WORKPLACE, "AXStaticText", "00:03"),
                          node(WORKPLACE, "AXButton", title="Complete meeting invite")]
            else:
                nodes += [node(INVITE_T, "AXStaticText", "Calling...")]
        nodes += [node(WORKPLACE, "AXStaticText", "Duration:32 seconds")]
        if self._on_contacts():
            nodes += [node(INVITE_T, "AXStaticText", "Add contacts"), node(INVITE_T, "AXStaticText", "Recent")]
            for who in self._listed():
                nodes += [node(INVITE_T, "AXStaticText", who), node(INVITE_T, "AXButton", desc=f"Profile, {who}")]
        if self.prompt_visible:
            w = self.prompt_window
            nodes += [node(w, "AXStaticText", "You have a meeting in progress"),
                      node(w, "AXStaticText", "If you continue to make a call, your audio will be switched "
                                              "from the meeting to your phone call."),
                      node(w, "AXButton", desc="Cancel"), node(w, "AXButton", title="Continue")]
        if self.stray_continue:
            nodes += [node("Some Wizard", "AXButton", title="Continue")]
        return nodes

    def _continue_buttons(self, rx):
        return [n for n in self._scoped(self._screen(), rx)
                if n["role"] == "AXButton" and "Continue" in (n["title"], n["desc"], n["value"])]

    def call(self, cmd, *a, **k):
        o = {a[i][2:]: a[i + 1] for i in range(0, len(a) - 1, 2) if a[i].startswith("--")}
        if self.call_pressed and cmd == self.fail_after_call:
            raise ui.UiError(f"axctl {cmd} timed out")
        if cmd == "windows":
            detached = [self.invite_home] if (self.invite_home or "").startswith("Participants") and self.panel_open else []
            return {"ok": True, "windows": ["Zoom Meeting"] + detached + ([WORKPLACE] if self.workplace_listed else [])
                    + (["Invite people to join meeting 9"] if self.invite else [])}
        if cmd == "participants":
            if not self.panel_open:
                return {"ok": False, "error": "participants list not visible", "panel_button": "Open participants panel"}
            return {"ok": True, "participants": self.rows}
        if cmd == "find":
            if self._on_contacts() and o.get("role") == "AXStaticText" and o.get("field") == "value":
                return {"ok": True, "matches": [n for n in self._screen()
                        if n["role"] == "AXStaticText" and re.search(o["match"], n["value"], re.I)]}
            if o["match"] == "^Switch$":
                return {"ok": True, "matches": [{"value": self.tab}]}
            if o["match"] == "^Call$":
                return {"ok": True, "matches": [{"enabled": bool(self.number)}]}
            if o["match"] == "^Invite$" and o.get("window") == ui.INVITE_WIN:
                return {"ok": True, "matches": [{"enabled": self.selected is not None}]}
            if o["match"] == "^Continue$":
                return {"ok": True, "matches": self._continue_buttons(o.get("window"))}
        if cmd == "get" and o.get("role") == "AXTextArea":
            return {"ok": True, "value": self.filter}
        if cmd == "get":
            return {"ok": True, "value": self.number if not self.wipe_on_get else ""}
        if cmd == "set" and o.get("role") == "AXTextArea":
            if not self.filter_ignores_set:
                self.filter = o["value"]
                self.selected = None
            if self.filter_set_refuses:
                return {"ok": False, "error": "set failed: -25200"}
            return {"ok": True, "value": self.filter}
        if cmd == "click":
            who = re.sub(r"^\^|\$$", "", o["match"]).replace("\\", "")
            if o["role"] != "AXStaticText" or who not in self._listed():
                return {"ok": False, "error": "not found (0 matches)"}
            self.clicks.append(who)
            if self.click_selects:
                self.selected = who
            return {"ok": True}
        if cmd == "set":
            self.number = o["value"] if self.typed_ok or not o["value"] else "+65"
            return {"ok": True, "value": self.number}
        if cmd == "activate":
            self.activated += 1
            self.activate_scopes.append(o.get("window"))
            self.needs_activate = False
            if self.vanish_on_activate:
                self.prompt_visible = False
            if self.wipe_on_activate:
                self.number = ""
            return {"ok": True}
        if cmd == "press":
            m = o["match"]
            self.presses.append((m, o.get("window")))
            if self.needs_activate:
                return {"ok": False, "error": "press failed: -25200"}
            if m == "^Switch$":
                if self.switch_mode == "dead":
                    return {"ok": True}
                self._step_switch()
                if self.switch_mode == "applies_but_refuses":
                    return {"ok": False, "error": "press failed: -25200"}
                return {"ok": True}
            if m == "^Invite$" and o["window"] == ui.INVITE_WIN:
                self.invite_pressed += 1
                if self.invite_press_error and not self.invite_press_applies:
                    return {"ok": False, "error": self.invite_press_error}
                self.selected = None
                if self.invite_closes_window:
                    self.invite = False
                if self.invite_press_error:
                    return {"ok": False, "error": self.invite_press_error}
                return {"ok": True}
            if m == "^Invite$":
                if self.invite_error:
                    return {"ok": False, "error": self.invite_error}
                if self.invite_home and not (self.panel_open and re.search(o["window"], self.invite_home, re.I)):
                    return {"ok": False, "error": "not found (0 matches)"}
                self.invite = True
            elif m == "^Call$":
                self.call_attempts += 1
                if self.refuse_call:
                    return {"ok": False, "error": "press failed: -25200"}
                self.call_pressed += 1
                self.invite = False
                if self.prompt_at == "call":
                    self._show_prompt()
                if self.call_press_raises:
                    raise ui.UiError("axctl press timed out")
            elif m.startswith("^Open participants"):
                self.panel_open = True
            elif "Complete meeting invite" in m:
                if self.fail_complete:
                    return {"ok": False, "error": "press failed: -25204"}
                self.complete_pressed = True
                if self.prompt_at == "complete":
                    self._show_prompt()
                else:
                    self.joined = True
                    if self.prompt_at == "late":
                        self._late_reads = 2
            elif m == "^Continue$":
                hits = self._continue_buttons(o.get("window"))
                if not hits:
                    return {"ok": False, "error": "not found (0 matches)"}
                if self.continue_error:
                    return {"ok": False, "error": self.continue_error}
                self.continue_pressed += 1
                self.continue_scopes.append(o.get("window"))
                if self.reappear > 0:
                    self.reappear -= 1
                else:
                    self.prompt_visible = False
                    if self.prompt_at == "complete":
                        self.joined = True
            return {"ok": True}
        if cmd == "close":
            self.invite = False
            self.closed += 1
            return {"ok": True}
        if cmd == "texts":
            rx = o.get("window")
            if rx is None:
                self.polls += 1                  # one poll = one default-scope read
                if self._late_reads:
                    self._late_reads -= 1
                    if not self._late_reads:
                        self._show_prompt()
            if self.fail_texts_after_complete and self.complete_pressed:
                raise ui.UiError("axctl texts timed out")
            if self.complete_pressed and self.empty_after_complete:
                return {"ok": True, "nodes": []}
            return {"ok": True, "nodes": self._scoped(self._screen(), rx)}
        raise AssertionError(f"unexpected {cmd} {a}")


@pytest.fixture
def fake(monkeypatch, tmp_path):
    f = FakeAx()
    monkeypatch.setattr(ui, "ax", f)
    monkeypatch.setattr(ui, "POLL", 0)
    monkeypatch.setattr(ui, "COMPLETE_WAIT", 0.05)
    monkeypatch.setattr(ui, "CONTACT_SETTLE", 0.05)       # sleep is a no-op here, so keep the real-time wait tiny
    monkeypatch.setattr(ui, "SETTLE_GAP", 0)            # sleep is a no-op here, so the clock would never reach it
    monkeypatch.setattr(ui, "DEBUG_PATH", tmp_path / "ui_debug.json")
    monkeypatch.setattr(ui.time, "sleep", lambda s: None)
    return f


def test_rehearse_never_presses_call_and_clears_field(fake):
    r = ui.rehearse()
    assert r.ok and r.state == "rehearsed" and fake.call_pressed == 0
    assert fake.number == "" and not fake.invite and fake.closed == 1


def test_invite_is_found_in_the_detached_participants_window_of_a_full_screen_meeting(fake):
    fake.invite_home = "Participants (3)"
    r = ui.rehearse()
    assert r.ok and fake.call_pressed == 0 and fake.closed == 1
    assert ("^Invite$", ui.PANEL_WINS) in fake.presses
    assert not any(m.startswith("^Open participants") for m, _ in fake.presses)   # no needless panel toggling


def test_rehearsal_uses_validated_detached_panel_when_main_window_is_hidden(fake, monkeypatch):
    fake.invite_home = "Participants (3)"
    original = fake.call

    def detached_only(command, *args, **kwargs):
        if command == "windows":
            return {"ok": True, "windows": ["Participants (3)", "Zoom Workplace"]
                    + ([INVITE_T] if fake.invite else [])}
        return original(command, *args, **kwargs)

    monkeypatch.setattr(fake, "call", detached_only)
    result = ui.rehearse()
    assert result.ok and result.state == "rehearsed"
    assert fake.call_pressed == 0 and fake.closed == 1
    assert ("^Invite$", ui.PANEL_WINS) in fake.presses


def test_hidden_main_and_unvalidated_detached_list_cannot_open_invite(fake, monkeypatch):
    fake.rows = ["Visitor"]
    original = fake.call

    def detached_only(command, *args, **kwargs):
        if command == "windows":
            return {"ok": True, "windows": ["Participants (1)", "Zoom Workplace"]}
        return original(command, *args, **kwargs)

    monkeypatch.setattr(fake, "call", detached_only)
    with pytest.raises(ui.UiUnavailable, match="own row missing"):
        ui.rehearse()
    assert fake.presses == [] and fake.call_pressed == 0


@pytest.mark.parametrize("home", ["Participants (3)", "Zoom Meeting"])
def test_invite_opens_a_closed_panel_once_then_presses_it(fake, home):
    fake.invite_home, fake.panel_open = home, False
    r = ui.rehearse()
    assert r.ok and fake.panel_open and fake.call_pressed == 0
    assert [m for m, _ in fake.presses].count("^Open participants") == 1
    assert [m for m, _ in fake.presses].count("^Invite$") == 2          # not found, panel opened, found


def test_invite_failure_other_than_not_found_is_not_retried_by_toggling_the_panel(fake):
    fake.invite_home, fake.panel_open = "Participants (3)", False
    fake.invite_error = "press failed: -25204"
    with pytest.raises(ui.UiError, match="press failed"):
        ui.rehearse()
    assert not fake.panel_open and not any(m.startswith("^Open participants") for m, _ in fake.presses)


def test_hold_rechecks_field_and_flags_a_revert(fake):
    r = ui.rehearse(hold=3)
    assert r.ok and "still there after 3s" in r.detail
    fake.wipe_on_get = True
    r = ui.rehearse(hold=3)
    assert r.state == "reverted" and not r.ok and fake.call_pressed == 0


def test_background_zoom_press_is_retried_once_after_activate(fake):
    fake.needs_activate = True
    r = ui.rehearse()
    assert r.ok and fake.activated == 1 and fake.call_pressed == 0


def test_press_that_still_fails_is_reported(fake):
    fake.needs_activate = True
    fake.call = (lambda orig: lambda cmd, *a, **k: ({"ok": True} if cmd == "activate" else orig(cmd, *a, **k)))(fake.call)
    with pytest.raises(ui.UiError, match="press failed"):
        ui.rehearse()


def test_call_activates_zoom_first_and_is_never_retried(fake):
    fake.answers_after = 1
    ui.callout("+6590000002", timeout=30, press_call=True)
    assert fake.activated >= 1 and fake.call_attempts == 1
    fake.refuse_call = True
    fake.invite = False
    r = ui.callout("+6590000002", timeout=30, press_call=True)
    assert r.state == "unknown" and r.call_pressed      # a failed Call press is never "not placed"
    assert fake.call_attempts == 2          # one attempt per callout, no retry inside the second


def test_mismatch_refuses_to_call(fake):
    fake.typed_ok = False
    r = ui.callout("+6590000002", press_call=True)
    assert r.state == "mismatch" and not r.ok and fake.call_pressed == 0


def test_callout_cycles_back_to_zoom_phone_from_another_tab(fake):
    fake.tab = "Contacts, 1 of 7"
    fake.answers_after = 1
    r = ui.callout("+6590000002", timeout=30, press_call=True)
    assert r.ok and fake.call_pressed == 1 and fake.tab.startswith("Zoom Phone")
    assert [m for m, _ in fake.presses].count("^Switch$") == 6      # Contacts -> Zoom Phone is six steps, no more


def test_callout_reports_a_tab_it_cannot_leave_and_does_not_call(fake):
    fake.tab, fake.switch_mode = "Contacts, 1 of 7", "dead"
    with pytest.raises(ui.UiError, match="could not reach the Zoom Phone tab"):
        ui.callout("+6590000002", press_call=True)
    assert fake.call_pressed == 0


def test_answered_then_complete_pressed(fake):
    fake.answers_after = 2
    r = ui.callout("+6590000002", timeout=30, press_call=True)
    assert r.ok and r.state == "completed" and fake.call_pressed == 1 and fake.complete_pressed


def test_unanswered_times_out_without_completing(fake):
    r = ui.callout("+6590000002", timeout=0.05, press_call=True)
    assert r.state == "timeout" and r.call_pressed and not fake.complete_pressed
    assert fake.call_pressed == 1


def test_timeout_says_when_workplace_is_hidden_as_in_a_full_screen_meeting(fake):
    r = ui.callout("+6590000002", timeout=0.05, press_call=True)
    assert r.state == "timeout" and "Zoom Workplace window is not visible" in r.detail
    fake.workplace_listed, fake.invite, fake.call_pressed = True, False, 0
    r = ui.callout("+6590000002", timeout=0.05, press_call=True)
    assert r.state == "timeout" and "not visible" not in r.detail


def test_abort_stops_polling(fake):
    r = ui.callout("+6590000002", timeout=30, should_abort=lambda: True, press_call=True)
    assert r.state == "aborted" and not fake.complete_pressed


def test_history_duration_row_is_not_an_answer():
    assert not ui.ANSWERED_RX.match("Duration:32 seconds")
    for ok in ("00:34", "34 seconds", "1 minute 5 seconds"):
        assert ui.ANSWERED_RX.match(ok)


def test_rejects_non_e164(fake):
    with pytest.raises(ui.UiError):
        ui.callout("6590000002")
    with pytest.raises(TypeError):
        ui.callout("+6590000002", zoom_email="a@b.c")          # the contact invite has its own function now


def test_participants_tags_and_own_row(fake):
    ps = ui.read_participants()
    assert [(p.display_name, p.is_me, p.is_host) for p in ps] == [
        ("Bridge Bot", True, False), ("Alice", False, True), ("+6512345678", False, False)]
    assert ps[2].phone_number == "+6512345678"
    fake.rows = ["Alice (Host)"]
    with pytest.raises(ui.UiUnavailable):
        ui.read_participants()


def test_unknown_parenthetical_stays_in_name():
    assert ui._split_tags("John (Equinix) (me)") == ("John (Equinix)", ["me"])


def test_zoom_participant_id_is_not_part_of_the_name_and_does_not_hide_the_tags():
    # Seen live on Zoom 7.2.1: without this the bot's own row was "missing" and the watcher read nothing.
    assert ui._split_tags("Karthikeyan Venugopal (Host, me, Participant ID:355195)") == (
        "Karthikeyan Venugopal", ["host", "me"])
    assert ui._split_tags("Alex Vince (Participant ID:12)") == ("Alex Vince", [])
    assert ui._split_tags("Alex (Participant ID: 7) (guest)") == ("Alex", ["guest"])
    assert ui._split_tags("Alex (Participant ID:1, Equinix)") == ("Alex (Participant ID:1, Equinix)", [])


def test_own_row_with_a_participant_id_is_found(fake):
    fake.rows = ["Bridge Bot (Host, me, Participant ID:355195)"]
    ps = ui.read_participants()
    assert [(p.display_name, p.is_me, p.is_host) for p in ps] == [("Bridge Bot", True, True)]


def test_closed_participant_panel_is_opened(fake):
    fake.panel_open = False
    assert ui.read_participants()[0].is_me and fake.panel_open


def test_number_is_read_again_after_zoom_is_brought_forward(fake):
    fake.wipe_on_activate = True
    r = ui.callout("+6590000002", press_call=True)
    assert r.state == "mismatch" and not r.ok and fake.call_attempts == 0
    assert not fake.invite


def test_unreadable_screen_after_call_press_is_unknown_not_an_exception(fake):
    fake.fail_after_call = "texts"
    fake.answers_after = 1
    r = ui.callout("+6590000002", timeout=30, press_call=True)
    assert r.state == "unknown" and r.call_pressed and not r.ok and fake.call_pressed == 1


def test_window_list_failing_after_call_press_does_not_matter(fake):
    # After Call only `texts` is read to follow the call; the window list is not needed.
    fake.fail_after_call = "windows"
    fake.answers_after = 1
    r = ui.callout("+6590000002", timeout=30, press_call=True)
    assert r.state == "completed" and r.ok and fake.call_pressed == 1


def test_call_press_that_times_out_but_took_effect_is_unknown(fake):
    fake.call_press_raises = True
    r = ui.callout("+6590000002", press_call=True)
    assert r.state == "unknown" and r.call_pressed and fake.call_attempts == 1


def test_complete_press_failing_after_answer_is_complete_failed_not_unknown(fake):
    # The callee answered, so the call is known: connected but not added to the meeting. The screen is
    # re-read after the press rather than guessed at.
    fake.answers_after = 1
    fake.fail_complete = True
    r = ui.callout("+6590000002", timeout=30, press_call=True)
    assert r.state == "complete_failed" and r.call_pressed and r.answered and not fake.complete_pressed
    assert "the press reported" in r.detail


def test_empty_screen_read_does_not_count_as_complete_gone(fake):
    fake.answers_after = 1
    fake.empty_after_complete = True
    r = ui.callout("+6590000002", timeout=30, press_call=True)
    assert r.state == "complete_failed" and not r.ok and fake.complete_pressed


def test_label_without_button_or_button_without_label_is_not_an_answer(fake):
    fake.answers_after = 0
    orig = fake.call

    def only(keep_role):
        def call(cmd, *a, **k):
            d = orig(cmd, *a, **k)
            if cmd == "texts":
                d["nodes"] = [n for n in d["nodes"] if n["role"] == keep_role or n["value"].startswith("Duration")]
            return d
        return call
    for role in ("AXStaticText", "AXButton"):
        fake.call_pressed = 0
        fake.invite = False
        fake.polls = 0
        fake.call = only(role)
        r = ui.callout("+6590000002", timeout=0.05, press_call=True)
        assert r.state == "timeout" and not fake.complete_pressed


def test_failure_before_call_raises_and_tidies_up(fake):
    fake.tab, fake.switch_mode = "Contacts, 1 of 7", "dead"
    with pytest.raises(ui.UiError):
        ui.callout("+6590000002", press_call=True)
    assert fake.call_attempts == 0 and not fake.invite


@pytest.mark.parametrize("raw", ["", "   ", ".*", "^$", "[unclosed", "Calling.*"])
def test_unsafe_answer_pattern_override_is_ignored(monkeypatch, raw):
    monkeypatch.setenv("WARROOM_ANSWER_PATTERN", raw)
    rx = ui._answer_rx()
    assert rx.pattern == ui.DEFAULT_ANSWER and not rx.match("Calling...") and rx.match("00:12")


def test_safe_answer_pattern_override_is_used(monkeypatch):
    monkeypatch.setenv("WARROOM_ANSWER_PATTERN", r"^Connected \d+s$")
    assert ui._answer_rx().match("Connected 4s")


def test_e164_is_ascii_only():
    assert ui.E164.fullmatch("+6590000002")
    assert not ui.E164.fullmatch("+\u0669\u0668\u0667\u0666\u0665\u0664\u0663\u0662")


# ---------------------------------------------------------------- "You have a meeting in progress" prompt

def answered_call(fake, **k):
    fake.answers_after = 1
    for key, val in k.items():
        setattr(fake, key, val)
    return ui.callout("+6590000002", timeout=30, press_call=True)


def test_prompt_after_complete_in_an_untitled_window_is_continued(fake):
    r = answered_call(fake, prompt_at="complete", prompt_window="")
    assert r.state == "completed" and r.ok and fake.continue_pressed == 1
    assert fake.continue_scopes == [None]                 # untitled: reached with the default scope
    assert "pressed Continue" in r.detail and fake.complete_pressed


def test_prompt_right_after_call_is_continued_before_the_answer_is_acted_on(fake):
    r = answered_call(fake, prompt_at="call", prompt_window="")
    assert r.state == "completed" and fake.continue_pressed == 1 and fake.complete_pressed


def test_prompt_while_ringing_and_never_answered_is_still_continued_once(fake):
    fake.prompt_at = "call"
    r = ui.callout("+6590000002", timeout=0.05, press_call=True)
    assert r.state == "timeout" and fake.continue_pressed == 1 and "pressed Continue" in r.detail


def test_prompt_in_a_titled_window_is_reached_by_its_escaped_anchored_title(fake):
    title = "Zoom (Audio) Alert"
    r = answered_call(fake, prompt_at="complete", prompt_window=title)
    assert r.state == "completed" and fake.continue_scopes == ["^" + re.escape(title) + "$"]


def test_prompt_inside_the_workplace_window_is_continued(fake):
    r = answered_call(fake, prompt_at="complete", prompt_window=WORKPLACE)
    assert r.state == "completed" and fake.continue_pressed == 1
    assert fake.continue_scopes == ["^" + re.escape(WORKPLACE) + "$"]


def test_prompt_that_appears_after_the_button_is_gone_is_still_handled(fake):
    r = answered_call(fake, prompt_at="late", prompt_window="")
    assert r.state == "completed" and fake.continue_pressed == 1 and not fake.prompt_visible


def test_a_stray_continue_button_elsewhere_is_never_pressed(fake):
    r = answered_call(fake, stray_continue=True)
    assert r.state == "completed" and fake.continue_pressed == 0


def test_ambiguous_continue_buttons_are_not_pressed(fake):
    r = answered_call(fake, prompt_at="complete", prompt_window="", stray_continue=True)
    assert r.state == "complete_failed" and not r.ok and fake.continue_pressed == 0
    assert "found 2" in r.detail


def test_a_prompt_that_keeps_coming_back_is_pressed_at_most_three_times(fake):
    r = answered_call(fake, prompt_at="complete", prompt_window="", reappear=99)
    assert r.state == "complete_failed" and fake.continue_pressed == ui.MAX_CONTINUE
    assert "came back" in r.detail
    dump = json.loads(ui.DEBUG_PATH.read_text())
    assert dump["windows"] == ["Zoom Meeting"] and any(n["window"] == "" for n in dump["nodes"])


def test_continue_refused_while_zoom_is_in_the_background_is_retried_after_activate(fake):
    r = answered_call(fake, prompt_at="complete", prompt_window="", prompt_needs_activate=True)
    assert r.state == "completed" and fake.continue_pressed == 1 and fake.activated >= 2


def test_retry_after_activate_uses_the_escaped_anchored_title(fake):
    title = "Zoom (Audio) Alert"
    r = answered_call(fake, prompt_at="complete", prompt_window=title, prompt_needs_activate=True)
    assert r.state == "completed" and fake.continue_pressed == 1
    assert "^" + re.escape(title) + "$" in fake.activate_scopes


def test_only_a_background_refusal_of_continue_is_retried(fake):
    # -25204 is a timeout: the press may already have worked, so pressing again could hit something else.
    r = answered_call(fake, prompt_at="complete", prompt_window="", continue_error="press failed: -25204")
    assert r.state == "complete_failed" and fake.continue_pressed == 0
    assert fake.activated == 1 and "-25204" in r.detail      # 1 = the activate before Call; none for Continue


def test_retry_looks_for_the_button_again_after_activate(fake):
    # The prompt is gone once Zoom is forward (the person clicked it): the retry must find nothing, not press.
    r = answered_call(fake, prompt_at="complete", prompt_window="", prompt_needs_activate=True,
                      vanish_on_activate=True)
    assert fake.continue_pressed == 0 and fake.activated >= 2
    assert "found 0" in r.detail


def test_continue_is_refused_when_the_only_match_is_in_another_window(fake):
    # The prompt vanished between reading the screen and pressing: the one Continue left is a stray elsewhere.
    fake.stray_continue = True
    with pytest.raises(ui.UiError, match="not ''"):
        ui._press_continue("")
    assert fake.continue_pressed == 0


def test_prompt_text_with_unrecognised_buttons_is_never_called_completed(fake):
    orig = fake._screen

    def screen():
        nodes = orig()
        if fake.complete_pressed:
            nodes += [node("", "AXStaticText", "You have a meeting in progress")]   # buttons not recognisable
        return nodes
    fake._screen = screen
    r = answered_call(fake)
    assert r.state == "complete_failed" and not r.ok and fake.continue_pressed == 0
    assert "not recognised" in r.detail


def test_settle_waits_for_a_prompt_that_shows_up_a_little_late(fake, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(ui.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(ui.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    monkeypatch.setattr(ui, "SETTLE_GAP", 1.5)
    monkeypatch.setattr(ui, "COMPLETE_WAIT", 10.0)
    fake.call_pressed, fake.complete_pressed, fake.joined = 1, True, True
    fake._late_reads = 4                                  # the prompt appears on the 4th read, about 0.6s in
    assert ui._settle(ui._AudioSwitch()) is True
    assert fake.continue_pressed == 1 and not fake.prompt_visible


def test_failing_to_save_the_debug_file_never_changes_the_outcome(fake, tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory")
    monkeypatch.setattr(ui, "DEBUG_PATH", blocker / "ui_debug.json")
    r = ui.callout("+6590000002", timeout=0.05, press_call=True)
    assert r.state == "timeout" and r.call_pressed and "could not be saved" in r.detail


def test_unreadable_screen_after_complete_is_not_counted_as_gone(fake):
    r = answered_call(fake, fail_texts_after_complete=True)
    assert r.state == "complete_failed" and not r.ok and fake.complete_pressed


def test_rehearsal_never_touches_a_prompt(fake):
    fake.prompt_at, fake.prompt_visible = "complete", True
    assert ui.rehearse().state == "rehearsed" and fake.continue_pressed == 0


def _n(window, role, value="", title="", desc=""):
    return node(window, role, value, title, desc)


def test_prompt_needs_heading_cancel_and_one_continue_in_the_same_window():
    head = _n("", "AXStaticText", "You have a meeting in progress")
    cancel, cont = _n("", "AXButton", desc="Cancel"), _n("", "AXButton", title="Continue")
    assert ui._prompt_windows([head, cancel, cont]) == [""]
    assert ui._prompt_windows([head, cont]) == []                              # no Cancel
    assert ui._prompt_windows([cancel, cont]) == []                            # no heading
    assert ui._prompt_windows([head, cancel, cont, _n("", "AXButton", title="Continue")]) == []
    assert ui._prompt_windows([head, _n("A", "AXButton", desc="Cancel"), _n("B", "AXButton", title="Continue")]) == []
    assert ui._prompt_windows([head, cancel, _n("", "AXStaticText", "Continue")]) == []   # text, not a button


def mks(tmp, **k):
    d = dict(dry_run=False, live_calling=True, target_mode="test", test_number="+6511111111",
             allow_roster_calls=False, roster_path=Path("x"), join_log_path=tmp / "join_log.csv", call_timeout=0.05)
    d.update(k)
    return Settings(**d)


D = DialDecision("+6511111111", "TEST", True, "test mode")


def test_dial_live_uses_ui_not_uri(fake, monkeypatch, tmp_path):
    import warroom.dialer as m
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("uri used")))
    monkeypatch.delenv("WARROOM_DIAL_METHOD", raising=False)
    fake.answers_after = 1
    r = dial(mks(tmp_path), D)
    assert r.text.startswith("DIALLED") and r.pressed and r.answered and fake.call_pressed == 1
    assert json.loads((tmp_path / "call_guard.json").read_text())["state"] == "ended"


def test_dial_dry_run_never_touches_ui(tmp_path):
    assert dial(mks(tmp_path, dry_run=True), D).text.startswith("DRY-RUN")
    assert dial(mks(tmp_path, live_calling=False), D).text.startswith("DRY-RUN")
    assert not (tmp_path / "call_guard.json").exists()


def test_dial_reports_untrusted_without_placing(monkeypatch, tmp_path):
    class Denied:
        def call(self, *a, **k):
            raise ui.UiUnavailable("not trusted: this app has no Accessibility permission")
    monkeypatch.setattr(ui, "ax", Denied())
    r = dial(mks(tmp_path), D)
    assert r.text.startswith("NOT PLACED") and not r.pressed and not r.uncertain
    assert json.loads((tmp_path / "call_guard.json").read_text())["state"] == "ended"


@pytest.mark.parametrize("setup", ["call_press_raises", "texts_fail"])
def test_dial_never_says_not_placed_after_the_press(fake, tmp_path, setup):
    fake.answers_after = 1
    if setup == "call_press_raises":
        fake.call_press_raises = True
    else:
        fake.fail_after_call = "texts"
    r = dial(mks(tmp_path, call_timeout=30), D)
    assert r.text.startswith("UNKNOWN") and r.pressed and r.uncertain and not r.answered
    assert "NOT PLACED" not in r.text and fake.call_attempts == 1
    assert json.loads((tmp_path / "call_guard.json").read_text())["state"] == "unknown"


def test_dial_reports_an_answered_call_that_was_not_completed_as_placed(fake, tmp_path):
    fake.answers_after = 1
    fake.fail_complete = True
    r = dial(mks(tmp_path, call_timeout=30), D)
    assert r.text.startswith("CALL PLACED, complete_failed") and r.pressed and r.answered and not r.uncertain
    assert json.loads((tmp_path / "call_guard.json").read_text())["state"] == "complete_failed"


def test_second_dial_is_refused_while_a_call_is_in_flight(fake, tmp_path):
    r1 = dial(mks(tmp_path), D)                       # nobody answers: timeout, call may still be ringing
    assert r1.text.startswith("CALL PLACED, timeout") and fake.call_attempts == 1
    r2 = dial(mks(tmp_path), D)
    assert r2.text.startswith("REFUSED") and fake.call_attempts == 1


def test_guard_expires_and_a_clean_end_releases_it(fake, tmp_path):
    from datetime import datetime, timedelta, timezone
    g = tmp_path / "call_guard.json"
    old = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
    g.write_text(json.dumps({"at": old, "state": "in_flight", "number": "+6511111111"}))
    fake.answers_after = 1
    assert dial(mks(tmp_path), D).text.startswith("DIALLED")
    fake.call_pressed = fake.complete_pressed = 0
    fake.joined = False
    fake.invite = False
    fake.polls = 0
    assert dial(mks(tmp_path), D).text.startswith("DIALLED")       # state "ended": next visitor not blocked


def test_corrupt_guard_blocks_rather_than_allows(fake, tmp_path):
    (tmp_path / "call_guard.json").write_text("{not json")
    assert dial(mks(tmp_path), D).text.startswith("REFUSED") and fake.call_attempts == 0


def test_test_mode_refuses_any_number_but_the_test_number(fake, tmp_path):
    other = DialDecision("+6522222222", "Alice", True, "roster priority 1")
    r = dial(mks(tmp_path), other)
    assert r.text.startswith("REFUSED") and fake.call_attempts == 0


def test_guard_write_failing_after_the_call_does_not_hide_the_result(fake, tmp_path, monkeypatch):
    import warroom.dialer as m
    real, calls = m._guard_write, []

    def flaky(*a, **k):
        calls.append(a[1])
        if a[1] != "in_flight":
            raise OSError("disk full")
        return real(*a, **k)
    monkeypatch.setattr(m, "_guard_write", flaky)
    fake.answers_after = 1
    r = dial(mks(tmp_path, call_timeout=30), D)
    assert r.text.startswith("DIALLED") and r.pressed and calls == ["in_flight", "ended"]
    assert json.loads((tmp_path / "call_guard.json").read_text())["state"] == "in_flight"   # keeps blocking


def test_no_call_is_made_if_the_guard_cannot_be_written(fake, tmp_path, monkeypatch):
    import warroom.dialer as m
    monkeypatch.setattr(m, "_guard_write", lambda *a, **k: (_ for _ in ()).throw(OSError("read-only")))
    r = dial(mks(tmp_path), D)
    assert r.text.startswith("NOT PLACED") and not r.pressed and fake.call_attempts == 0


def test_ctrl_c_during_the_call_is_reported_as_unknown_not_a_traceback(fake, tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "callout", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    r = dial(mks(tmp_path), D)
    assert r.text.startswith("UNKNOWN") and r.uncertain and "interrupted" in r.text
    assert json.loads((tmp_path / "call_guard.json").read_text())["state"] == "unknown"


def test_guard_outlasts_a_long_call_timeout(fake, tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    monkeypatch.setattr(ui, "callout", lambda *a, **k: ui.CalloutResult("timeout", False, "no answer", True, False, "", ""))
    dial(mks(tmp_path, call_timeout=300), D)                       # nobody answers: state "timeout"
    g = tmp_path / "call_guard.json"
    rec = json.loads(g.read_text())
    assert rec["hold"] >= 420
    rec["at"] = (datetime.now(timezone.utc) - timedelta(seconds=250)).isoformat()    # past the old fixed 180s
    g.write_text(json.dumps(rec))
    assert dial(mks(tmp_path, call_timeout=300), D).text.startswith("REFUSED")


# ---------------------------------------------------------------- the Invite window's tab cycler


def _open_dialog(fake, tab="Zoom Phone, 7 of 7"):
    fake.invite, fake.tab = True, tab


def test_goto_tab_presses_once_when_one_step_away(fake):
    _open_dialog(fake)
    ui._goto_tab("Contacts")
    assert fake.tab == "Contacts, 1 of 7" and [m for m, _ in fake.presses] == ["^Switch$"]


def test_goto_tab_does_nothing_when_already_there(fake):
    _open_dialog(fake)
    ui._goto_tab("Zoom Phone")
    assert fake.presses == [] and fake.activated == 0


def test_goto_tab_does_not_repeat_a_press_that_landed_but_reported_a_refusal(fake):
    _open_dialog(fake)
    fake.switch_mode = "applies_but_refuses"
    ui._goto_tab("Contacts")
    assert fake.tab == "Contacts, 1 of 7" and len(fake.presses) == 1 and fake.activated == 0


def test_goto_tab_brings_zoom_forward_only_when_a_press_changed_nothing(fake):
    _open_dialog(fake)
    fake.needs_activate = True          # the first press is refused and does nothing
    ui._goto_tab("Contacts")
    assert fake.tab == "Contacts, 1 of 7" and fake.activated == 1 and len(fake.presses) == 2


def test_goto_tab_gives_up_instead_of_cycling_forever(fake):
    _open_dialog(fake)
    fake.switch_mode = "dead"
    with pytest.raises(ui.UiError, match="could not reach the Contacts tab"):
        ui._goto_tab("Contacts")
    assert len(fake.presses) == 2 * ui.TAB_COUNT


# ---------------------------------------------------------------- invite a Zoom contact


def _restored(fake):
    assert not fake.invite and fake.filter == "" and fake.tab.startswith("Zoom Phone")


def test_invite_contact_happy_path_selects_the_one_match_and_presses_invite(fake):
    r = ui.invite_contact("eng@example.com", press_invite=True)
    assert (r.state, r.ok, r.pressed) == ("invited", True, True)
    assert fake.clicks == ["Eng One"] and fake.invite_pressed == 1
    _restored(fake)


def test_invite_contact_rehearsal_selects_but_never_presses_invite(fake):
    r = ui.invite_contact("eng@example.com")
    assert (r.state, r.ok, r.pressed) == ("rehearsed", True, False)
    assert fake.clicks == ["Eng One"] and fake.invite_pressed == 0
    _restored(fake)


def test_invite_contact_survives_zoom_closing_the_dialog_after_the_invite(fake):
    fake.invite_closes_window = True
    r = ui.invite_contact("eng@example.com", press_invite=True)
    assert r.state == "invited" and fake.invite_pressed == 1 and not fake.invite


def test_invite_contact_with_no_match_invites_nobody(fake):
    r = ui.invite_contact("nobody@example.com", press_invite=True)
    assert (r.state, r.ok, r.pressed) == ("no_match", False, False)
    assert fake.clicks == [] and fake.invite_pressed == 0
    _restored(fake)


def test_invite_contact_with_several_matches_invites_nobody(fake):
    r = ui.invite_contact("dup@example.com", press_invite=True)
    assert (r.state, r.ok, r.pressed) == ("ambiguous", False, False)
    assert fake.clicks == [] and fake.invite_pressed == 0
    _restored(fake)


def test_invite_contact_that_did_not_select_does_not_press_invite(fake):
    fake.click_selects = False
    r = ui.invite_contact("eng@example.com", press_invite=True)
    assert (r.state, r.ok, r.pressed) == ("not_selected", False, False)
    assert fake.invite_pressed == 0
    _restored(fake)


def test_invite_contact_refuses_when_the_filter_box_did_not_take_the_address(fake):
    fake.filter_ignores_set = True
    with pytest.raises(ui.UiError, match="did not take the address"):
        ui.invite_contact("eng@example.com", press_invite=True)
    assert fake.clicks == [] and fake.invite_pressed == 0
    _restored(fake)


def test_invite_contact_tolerates_a_set_that_landed_but_reported_a_refusal(fake):
    fake.filter_set_refuses = True
    r = ui.invite_contact("eng@example.com", press_invite=True)
    assert r.state == "invited" and fake.invite_pressed == 1


@pytest.mark.parametrize("bad", ["", "not an address", "a@b", "eng@example.com extra", "Eng One"])
def test_invite_contact_rejects_a_non_address_before_touching_zoom(fake, bad):
    with pytest.raises(ui.UiError):
        ui.invite_contact(bad, press_invite=True)
    assert fake.presses == [] and fake.clicks == []


def test_invite_press_refused_after_it_took_effect_counts_as_invited(fake):
    fake.invite_closes_window = True
    fake.invite_press_error, fake.invite_press_applies = "press failed: -25200", True
    r = ui.invite_contact("eng@example.com", press_invite=True)
    assert r.state == "invited" and r.ok and "press reported" in r.detail and fake.invite_pressed == 1


def test_invite_press_refused_and_nothing_changed_is_unknown_never_retried(fake):
    fake.invite_press_error, fake.invite_press_applies = "press failed: -25200", False
    fake.selected = None
    original = fake.call

    def keep_selected(cmd, *a, **k):
        d = original(cmd, *a, **k)
        if cmd == "press" and fake.invite_pressed:
            fake.selected = "Eng One"            # the button is still enabled: the press visibly did nothing
        return d
    fake.call = keep_selected
    r = ui.invite_contact("eng@example.com", press_invite=True)
    assert (r.state, r.ok, r.pressed) == ("unknown", False, True)
    assert fake.invite_pressed == 1             # one attempt only: a repeat could invite twice
    _restored(fake)


def test_invite_press_that_raises_and_cannot_be_checked_is_unknown(fake):
    fake.invite_press_error = "press failed: -25200"
    original = fake.call

    def dies(cmd, *a, **k):
        if cmd == "windows" and fake.invite_pressed:
            raise ui.UiError("axctl windows timed out")
        return original(cmd, *a, **k)
    fake.call = dies
    r = ui.invite_contact("eng@example.com", press_invite=True)
    assert (r.state, r.ok, r.pressed) == ("unknown", False, True)


def test_invite_contact_restores_the_dialog_even_when_a_step_blows_up(fake):
    original = fake.call

    def boom(cmd, *a, **k):
        if cmd == "texts" and fake.filter:
            raise ui.UiError("axctl texts timed out")
        return original(cmd, *a, **k)
    fake.call = boom
    with pytest.raises(ui.UiError, match="timed out"):
        ui.invite_contact("eng@example.com", press_invite=True)
    assert fake.invite_pressed == 0
    _restored(fake)


def test_invite_contact_waits_for_the_list_to_finish_filtering(fake):
    original, reads = fake.call, []

    def slow(cmd, *a, **k):
        if cmd == "texts":
            reads.append(1)
            if len(reads) == 1:                  # the first read still shows the unfiltered list
                saved, fake.filter = fake.filter, ""
                try:
                    return original(cmd, *a, **k)
                finally:
                    fake.filter = saved
        return original(cmd, *a, **k)
    fake.call = slow
    r = ui.invite_contact("eng@example.com", press_invite=True)
    assert r.state == "invited" and fake.clicks == ["Eng One"] and len(reads) >= 3


def test_contact_name_selects_exact_result_among_fuzzy_matches(fake):
    fake.directory["Eng One"] = ["Eng One Two", "ENG ONE", "Other Eng One"]
    result = ui.invite_contact(contact_name="  Eng One  ", press_invite=True)
    assert result.state == "invited" and result.contact_name == "ENG ONE"
    assert fake.clicks == ["ENG ONE"] and fake.invite_pressed == 1
    _restored(fake)


@pytest.mark.parametrize("rows,state", [([], "no_match"), (["Eng One Two"], "no_match"),
                                        (["Eng One", "Eng One"], "ambiguous"),
                                        (["Eng One", "  eng one  "], "ambiguous")])
def test_contact_name_rejects_missing_fuzzy_only_or_duplicate_names(fake, rows, state):
    fake.directory["Eng One"] = rows
    result = ui.invite_contact(contact_name="Eng One", press_invite=True)
    assert result.state == state and not result.pressed
    assert not fake.clicks and fake.invite_pressed == 0
    _restored(fake)


@pytest.mark.parametrize("name", [".*", "Eng (One)+", "Engineer O'Neil", "张伟", "A #1"])
def test_contact_name_regex_characters_are_literal(fake, name):
    fake.directory[name] = [name]
    result = ui.invite_contact(contact_name=name, press_invite=True)
    assert result.state == "invited" and result.contact_name == name
    assert fake.invite_pressed == 1


@pytest.mark.parametrize("name", [" ", "Eng\nOne", "Eng\tOne", "Eng\x00One", "x" * 201])
def test_invalid_contact_name_does_not_touch_zoom(fake, name):
    with pytest.raises(ui.UiError):
        ui.invite_contact(contact_name=name, press_invite=True)
    assert not fake.presses and not fake.clicks


def test_email_and_name_are_never_combined_or_used_as_fallback(fake):
    with pytest.raises(ui.UiError, match="either"):
        ui.invite_contact("eng@example.com", contact_name="Eng One", press_invite=True)
    assert not fake.presses and not fake.clicks


@pytest.mark.parametrize("matches", [0, 2])
def test_unique_contact_row_with_ambiguous_or_stale_ax_target_does_not_click(fake, matches):
    fake.directory["Eng One"] = ["Eng One"]
    original = fake.call
    def target(cmd, *args, **kwargs):
        result = original(cmd, *args, **kwargs)
        if cmd == "find" and "AXStaticText" in args:
            result["matches"] = result["matches"] * matches
        return result
    fake.call = target
    result = ui.invite_contact(contact_name="Eng One", press_invite=True)
    assert result.state == "ambiguous" and not fake.clicks and fake.invite_pressed == 0
    _restored(fake)


def test_name_invite_unknown_press_keeps_actual_contact_and_never_retries(fake):
    fake.directory["Eng One"] = ["ENG ONE"]
    fake.invite_press_error, fake.invite_press_applies = "press failed: -25200", False
    result = ui.invite_contact(contact_name="Eng One", press_invite=True)
    assert result.state == "unknown" and result.pressed and result.contact_name == "ENG ONE"
    assert fake.invite_pressed == 1
    _restored(fake)
