"""Mac UI layer: drives the Zoom client through tools/axctl (Accessibility API).

Places the call from inside the meeting: Invite -> Zoom Phone -> type number -> Call -> wait for the
callee to answer -> "Complete meeting invite". Nothing here presses Call unless the caller passes
press_call=True; the safety gates live in dialer.py. Contract: MAC_SETUP.md section 4.

invite_contact() does the other half: Invite -> Contacts -> filter by the engineer's Zoom e-mail -> select
that one contact -> Invite. Likewise it presses Invite only when asked to.
"""
import json
import os
import re
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import E164, EMAIL

BASE = Path(__file__).resolve().parent.parent
AXCTL = BASE / "tools" / "axctl"
DEBUG_PATH = BASE / "logs" / "ui_debug.json"

MEETING_WIN = r"^Zoom Meeting(?:\s+\d+[- ]minutes?)?$"  # Zoom may append a duration, e.g. "  40-minutes".
# The Participants panel is docked inside the meeting window normally, but gets its own "Participants (N)"
# window when the meeting is full screen or the panel is popped out. Its Invite button goes with it.
PANEL_WINS = r"^(?:Zoom Meeting(?:\s+\d+[- ]minutes?)?|Participants(?: \(\d+\))?)$"
INVITE_WIN = "^Invite people to join meeting"
TAB_COUNT = 7                       # tabs in the Invite window; the Switch button steps to the next one
CONTACT_SETTLE = 4.0                # seconds to let the contact list finish filtering
ANYWHERE = "."                      # matches every window title, including Zoom Workplace
COMPLETE_RX = re.compile(r"Complete meeting invite", re.I)
# Elapsed-time label: "00:34" drawn, "34 seconds" / "1 minute 5 seconds" in the tree. Anchored, so
# call-history rows such as "Duration:32 seconds" are not mistaken for a live call.
DEFAULT_ANSWER = r"^(\d{1,2}:\d{2}|\d+ seconds?|\d+ minutes?( \d+ seconds?)?)$"


def _answer_rx() -> "re.Pattern":
    """WARROOM_ANSWER_PATTERN overrides the answered label, but a blank, invalid or match-everything
    override is ignored: it would make the tool press 'Complete meeting invite' while still ringing."""
    raw = os.environ.get("WARROOM_ANSWER_PATTERN", "").strip()
    try:
        rx = re.compile(raw, re.I) if raw else None
    except re.error:
        rx = None
    if rx is None or rx.match("") or rx.match("Calling...") or rx.match("Complete meeting invite"):
        rx = re.compile(DEFAULT_ANSWER, re.I)
    return rx


ANSWERED_RX = _answer_rx()
COMPLETE_WAIT = 10.0                # seconds to wait for "Complete meeting invite" to disappear
SETTLE_GAP = 1.5                    # seconds the screen must stay clean before the call counts as completed
NOT_FRONTMOST = "-25200"            # AX refuses a press while Zoom is in the background: nothing happened
KNOWN_TAGS = {"me", "host", "co-host", "guest"}
ID_TAG = re.compile(r"participant id:\s*\w+")       # Zoom 7.2 appends "(Host, me, Participant ID:355195)" to a row
POLL = 0.7

# Zoom asks "You have a meeting in progress. If you continue to make a call, your audio will be switched
# from the meeting to your phone call." (Cancel / Continue). Continue is what lets the callee join.
WORKPLACE_WIN = "^Zoom Workplace$"
PROMPT_RX = re.compile(r"meeting in progress", re.I)
CONTINUE_RX = re.compile(r"^Continue$", re.I)
CANCEL_RX = re.compile(r"^Cancel$", re.I)
MAX_CONTINUE = 3                    # Continue presses per call, so a prompt that keeps coming back cannot loop


class UiError(RuntimeError):
    """The Zoom UI is not in the state we expected."""


class UiUnavailable(UiError):
    """No Zoom, no meeting, or no Accessibility permission."""


class UiMeetingHidden(UiUnavailable):
    """Zoom is running, but no meeting window is currently exposed to Accessibility."""


@dataclass
class UiParticipant:
    display_name: str
    participant_id: str      # the Mac tree exposes no id, so this is the display name
    is_me: bool
    is_host: bool
    phone_number: str = ""


@dataclass
class InviteResult:
    state: str               # rehearsed | invited | no_match | ambiguous | not_selected | unknown
    ok: bool
    detail: str
    pressed: bool = False    # the Invite press was attempted (so a person may already have been invited)


@dataclass
class CalloutResult:
    state: str               # rehearsed | mismatch | completed | timeout | aborted | complete_failed | unknown
    ok: bool
    detail: str
    call_pressed: bool = False
    answered: bool = False
    started_utc: str = ""
    read_back: str = ""


def _helper_path() -> Path:
    """The native host supplies its signed helper; Terminal uses the data-folder helper."""
    override = os.environ.get("WARROOM_AXCTL")
    if override is None:
        helper = AXCTL
        remedy = "run tools/build_axctl.sh on macOS"
    else:
        if not override.strip() or "\0" in override or not Path(override).is_absolute():
            raise UiUnavailable("WARROOM_AXCTL must be an absolute path to an executable Accessibility helper; "
                                "correct it or rebuild and reinstall War Room Bot.app")
        helper = Path(override)
        remedy = "correct WARROOM_AXCTL or rebuild and reinstall War Room Bot.app"
    if not helper.is_file():
        raise UiUnavailable(f"{helper} is missing or is not a file; {remedy}")
    if not os.access(helper, os.X_OK):
        raise UiUnavailable(f"{helper} is not executable; {remedy}")
    return helper


class Ax:
    """Thin wrapper around the selected Accessibility helper. One JSON object per call."""

    def call(self, *args: str, timeout: float = 20) -> dict:
        helper = _helper_path()
        try:
            p = subprocess.run([str(helper), *args], capture_output=True, text=True, timeout=timeout)
        except OSError as e:
            raise UiUnavailable(f"cannot run axctl at {helper}: {e}; rebuild the helper on macOS") from None
        except subprocess.TimeoutExpired:
            raise UiError(f"axctl {args[0]} timed out") from None
        try:
            d = json.loads(p.stdout)
        except ValueError:
            raise UiError(f"axctl {args[0]} gave no JSON: {(p.stdout + p.stderr).strip()[:200]}") from None
        if not isinstance(d, dict) or type(d.get("ok")) is not bool:
            raise UiError(f"axctl {args[0]} did not return a JSON object with a top-level Boolean ok")
        if d["ok"] and p.returncode != 0:
            raise UiError(f"axctl {args[0]} reported success but exited with status {p.returncode}")
        err = d.get("error", "")
        if not isinstance(err, str):
            raise UiError(f"axctl {args[0]} returned an invalid error message")
        if not d.get("ok") and ("not trusted" in err or "not running" in err):
            raise UiUnavailable(err)
        return d

    def trusted(self) -> bool:
        try:
            return self.call("trusted").get("ok") is True
        except UiError:
            return False


ax = Ax()
_lock = threading.Lock()


@contextmanager
def exclusive():
    """Hold only while acting; waiting for the callee is read-only (lesson 9)."""
    with _lock:
        yield


def busy() -> bool:
    return _lock.locked()


def input_available() -> bool:
    return ax.trusted()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _need(d: dict, what: str) -> dict:
    if not d.get("ok"):
        raise UiError(f"{what}: {d.get('error', 'failed')}")
    return d


def _titles() -> list:
    return _need(ax.call("windows"), "list windows")["windows"]


def _has_window(rx: str) -> bool:
    return any(re.search(rx, t, re.I) for t in _titles())


def _find(window: str, role: str, field: str, match: str) -> list:
    return _need(ax.call("find", "--window", window, "--role", role, "--field", field, "--match", match),
                 f"find {match}")["matches"]


def _activate(window: str = "") -> None:
    """Bring Zoom forward and raise `window` (no window: raise whichever Zoom window is first). AXPress is
    refused (-25200) while Zoom is in the background. axctl may report zoom_frontmost:false and the press
    still works, so the flag is not checked."""
    ax.call("activate", *(("--window", window) if window else ()))
    time.sleep(0.5)


def _press(window: str, role: str, field: str, match: str, *, retry: bool = True) -> None:
    """Press one control. With retry, a refused press is retried once after activating Zoom: only for
    idempotent controls (Invite, panel toggles). Never for Call: it activates first and presses once."""
    args = ("press", "--window", window, "--role", role, "--field", field, "--match", match)
    d = ax.call(*args)
    if retry and not d.get("ok") and "press failed" in d.get("error", ""):
        _activate(window)
        d = ax.call(*args)
    _need(d, f"press {match}")


def _wait(pred, seconds: float, msg: str) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if pred():
            return
        time.sleep(0.2)
    raise UiError(msg)


def in_meeting() -> bool:
    return _has_window(MEETING_WIN)


def meeting_window() -> str:
    titles = _titles()
    matches = [title for title in titles if re.search(MEETING_WIN, title, re.I)]
    if not matches:
        seen = ", ".join(repr(t) for t in titles) or "none"
        raise UiMeetingHidden(f"Zoom is running, but no meeting window is exposed to Accessibility. Visible windows: "
                            f"{seen}. If you are already in a full-screen meeting, it may be on another desktop. "
                            f"The watcher also reads detached Participants panels and occasionally tries to restore visibility")
    return matches[0]


def prepare_meeting() -> str:
    """At explicit startup, accept a readable detached panel or recover a hidden meeting.

    Exposed meeting windows and detached participant lists need no activation.
    No Call or sharing controls are pressed.
    A missing Zoom process or denied Accessibility access is reported before any activation.
    """
    try:
        return meeting_window()
    except UiMeetingHidden:
        data = _participant_snapshot()
        if not data.get("ok") and _visibility_failure(data):
            data = _recover_participant_snapshot(force=True) or data
        _decode_participants(data)
        source = data.get("source_window")
        if isinstance(source, str) and source:
            return source
        try:
            return meeting_window()
        except UiMeetingHidden:
            return "Participants panel"


# ---------------------------------------------------------------- participants

def _split_tags(raw: str):
    name, tags = raw.strip(), []
    while True:
        m = re.search(r"\s*\(([^()]*)\)\s*$", name)
        found = [t.strip().lower() for t in m.group(1).split(",")] if m else []
        if not m or not all(t in KNOWN_TAGS or ID_TAG.fullmatch(t) for t in found):
            return name, tags
        tags += [t for t in found if t in KNOWN_TAGS]
        name = name[:m.start()]


PARTICIPANT_RECOVERY_GAP = 30.0
_participant_recover_at = 0.0


def _participant_snapshot() -> dict:
    """Ask the helper for the meeting or detached list before consulting window titles."""
    d = ax.call("participants")
    if not d.get("ok") and "not visible" in d.get("error", ""):
        if d.get("panel_button", "").lower().startswith("open participants"):
            if not _lock.acquire(blocking=False):
                return d
            try:
                _press(MEETING_WIN, "AXButton", "desc", "^Open participants")
            except UiUnavailable:
                raise
            except UiError:
                # The window may have changed since the helper found the panel button.
                # Keep this as a failed visibility read so bounded recovery can try again.
                return d
            finally:
                _lock.release()
            time.sleep(0.6)
            d = ax.call("participants")
    return d


def _visibility_failure(data: dict) -> bool:
    error = data.get("error", "").lower()
    return not data.get("ok") and (error.startswith("no meeting") or error == "participants list not visible")


def _recover_participant_snapshot(*, force=False):
    """Try one bounded recovery, with a cooldown and without interrupting another UI action."""
    global _participant_recover_at
    if not _lock.acquire(blocking=False):
        return None
    try:
        now = time.monotonic()
        if not force and now < _participant_recover_at:
            return None
        _participant_recover_at = now + PARTICIPANT_RECOVERY_GAP
        _open_zoom()
    finally:
        _lock.release()
    end = time.monotonic() + SURFACE_WAIT
    while True:
        data = _participant_snapshot()
        if data.get("ok") or not _visibility_failure(data) or time.monotonic() >= end:
            return data
        time.sleep(0.3)


def _decode_participants(d: dict) -> list:
    _need(d, "read participants")
    rows = d.get("participants")
    if not isinstance(rows, list) or any(not isinstance(row, str) for row in rows):
        raise UiError("read participants: helper returned an invalid participant list")
    out = []
    for raw in rows:
        name, tags = _split_tags(raw)
        digits = re.sub(r"[\s\-()]", "", name)
        out.append(UiParticipant(name, name, "me" in tags, "host" in tags or "co-host" in tags,
                                 digits if re.fullmatch(r"\+?\d{7,15}", digits) else ""))
    if not any(p.is_me for p in out):
        raise UiUnavailable("own row missing from the participant list (a glitch, not an empty room)")
    return out


def read_participants() -> list:
    """Read the validated participant list; recover hidden UI at most once per cooldown."""
    data = _participant_snapshot()
    if _visibility_failure(data):
        data = _recover_participant_snapshot() or data
    return _decode_participants(data)


# ---------------------------------------------------------------- invite dialog

def _invite_open() -> bool:
    return _has_window(INVITE_WIN)


def _press_invite() -> None:
    """Invite lives in the Participants panel, wherever that is showing (docked or its own window). A closed
    panel has no Invite button, so open it once and look again; any other failure is not retried."""
    try:
        _press(PANEL_WINS, "AXButton", "desc", "^Invite$")
    except UiError as e:
        if "not found" not in str(e):
            raise
        _press(MEETING_WIN, "AXButton", "desc", "^Open participants")
        time.sleep(0.6)
        _press(PANEL_WINS, "AXButton", "desc", "^Invite$")


def _tab_shown() -> str:
    """The Invite window's current tab as Zoom words it on the Switch button, e.g. 'Zoom Phone, 7 of 7'."""
    m = _find(INVITE_WIN, "AXButton", "desc", "^Switch$")
    return m[0]["value"] if m else ""


def _goto_tab(name: str) -> None:
    """Switch is a cycler, not a menu: each press moves to the next tab (Zoom Phone -> Contacts is one press,
    Contacts -> Zoom Phone is six). A press is never repeated blindly, because Zoom often reports -25200 for a
    press that DID land and a repeat would step past the tab. The tab is read again after every press, and
    Zoom is only brought forward when the last press visibly changed nothing."""
    want, prev, shown = name.lower(), None, ""
    for _ in range(2 * TAB_COUNT):
        shown = _tab_shown()
        if shown.lower().startswith(want):
            return
        if shown == prev:
            _activate(INVITE_WIN)
        prev = shown
        d = ax.call("press", "--window", INVITE_WIN, "--role", "AXButton", "--field", "desc", "--match", "^Switch$")
        if not d.get("ok") and "press failed" not in d.get("error", ""):
            _need(d, "press Switch")            # not found / disabled: not the refusal quirk, so give up
        time.sleep(POLL)
    raise UiError(f"could not reach the {name} tab of the Invite window (it shows {shown or 'an unknown tab'!r})")


def _open_invite(tab: str = "Zoom Phone") -> None:
    try:
        meeting_window()
    except UiMeetingHidden:
        # A fullscreen meeting may expose only its detached Participants panel.
        # This runs inside exclusive(): validate the read without toggling panels or taking another lock.
        _decode_participants(ax.call("participants"))
    if not _invite_open():
        _press_invite()
        _wait(_invite_open, 6, "the Invite window did not open")
    _goto_tab(tab)


def _close_invite() -> None:
    if _invite_open():
        _need(ax.call("close", "--window", INVITE_WIN), "close Invite window")


def _call_enabled() -> bool:
    m = _find(INVITE_WIN, "AXButton", "title", "^Call$")
    return bool(m and m[0]["enabled"])


def _set_number(value: str) -> str:
    d = _need(ax.call("set", "--window", INVITE_WIN, "--role", "AXTextField", "--not", "Caller ID",
                      "--value", value), "set number")
    return d.get("value", "")


def _get_number() -> str:
    return _need(ax.call("get", "--window", INVITE_WIN, "--role", "AXTextField", "--not", "Caller ID"),
                 "read number").get("value", "")


def _norm(s: str) -> str:
    return re.sub(r"[\s\-()]", "", s)


def _tidy() -> None:
    """Best effort after a failure before Call: empty the number field and close Invite. Never raises."""
    try:
        if _invite_open():
            _set_number("")
            _close_invite()
    except Exception:
        pass


# ---------------------------------------------------------------- invite a Zoom contact

def _set_filter(text: str) -> None:
    """Type into 'Add contacts' (it filters the list). Zoom often answers -25200 although the text landed, so
    that refusal is tolerated here and the caller reads the box back instead of trusting the return."""
    d = ax.call("set", "--window", INVITE_WIN, "--role", "AXTextArea", "--field", "desc", "--match", "^Add contacts",
                "--value", text)
    if not d.get("ok") and "set failed" not in d.get("error", ""):
        raise UiError(f"set contact filter: {d.get('error', 'failed')}")


def _filter_text() -> str:
    d = _need(ax.call("get", "--window", INVITE_WIN, "--role", "AXTextArea", "--field", "desc",
                      "--match", "^Add contacts"), "read contact filter")
    return d.get("value", "")


def _contact_rows() -> list:
    """Display names of the contacts now listed. A row is a static text followed by a 'Profile,' button; the
    list shows names only (no e-mail), so the e-mail can only be matched by Zoom's own filter."""
    nodes = _need(ax.call("texts", "--window", INVITE_WIN), "read contacts")["nodes"]
    return [a["value"] for a, b in zip(nodes, nodes[1:])
            if a["role"] == "AXStaticText" and a["value"].strip()
            and b["role"] == "AXButton" and "Profile," in b["desc"]]


def _settled_rows() -> list:
    """The filtered list once two reads in a row agree (it shrinks over a moment), or the last read."""
    end, last = time.monotonic() + CONTACT_SETTLE, None
    while True:
        rows = _contact_rows()
        if rows and rows == last:
            return rows
        last = rows
        if time.monotonic() >= end:
            return rows
        time.sleep(0.4)


def _invite_enabled() -> bool:
    m = _find(INVITE_WIN, "AXButton", "desc", "^Invite$")
    return bool(m and m[0]["enabled"])


def _restore_invite() -> None:
    """Best effort, never raises: empty the filter, put the tab back on Zoom Phone (where callout expects it)
    and close the Invite window."""
    try:
        if not _invite_open():
            return
        for step in (lambda: _set_filter(""), lambda: _goto_tab("Zoom Phone")):
            try:
                step()
            except Exception:
                pass
        _close_invite()
    except Exception:
        pass


def invite_contact(email: str, *, press_invite: bool = False) -> InviteResult:
    """Invite one existing Zoom contact: Invite > Contacts > filter by `email` > select that one row > Invite.

    Fails closed: it presses Invite only when Zoom's filter leaves exactly one contact. Contract the caller
    relies on: an exception means Invite was NOT pressed. From the moment the press is attempted this returns
    an InviteResult (state "unknown" if it cannot tell whether the invitation went out). The Invite window is
    always put back on Zoom Phone and closed."""
    if not EMAIL.fullmatch(email):
        raise UiError("the contact address is not an e-mail address")
    with exclusive():
        try:
            _open_invite("Contacts")
            _set_filter(email)
            if _filter_text() != email:
                raise UiError("the contact filter box did not take the address")
            rows = _settled_rows()
            if not rows:
                return InviteResult("no_match", False, "Zoom lists no contact for that address (is the engineer in "
                                    "your Zoom contacts, and does the filter search by e-mail?); nobody was invited")
            if len(rows) > 1:
                return InviteResult("ambiguous", False, f"{len(rows)} contacts match that address; nobody was "
                                    "invited, because only an exact single match is trusted")
            who = rows[0]
            _activate(INVITE_WIN)
            _need(ax.call("click", "--window", INVITE_WIN, "--role", "AXStaticText", "--field", "value",
                          "--match", "^" + re.escape(who) + "$"), "select contact")
            time.sleep(0.8)
            if not _invite_enabled():
                return InviteResult("not_selected", False, f"clicked {who!r} but Zoom's Invite button stayed "
                                    "disabled, so the contact is not selected; nobody was invited")
            if not press_invite:
                return InviteResult("rehearsed", True, f"{who!r} is the only match and is selected; Invite was "
                                    "not pressed")
            _activate(INVITE_WIN)
            refused = ""
            try:
                _press(INVITE_WIN, "AXButton", "desc", "^Invite$", retry=False)
            except Exception as e:
                # Zoom reports -25200 for presses that took effect; an applied Invite shows as the window gone
                # or the button disabled again. Anything else cannot be told apart from "nothing happened".
                try:
                    time.sleep(1.0)
                    if _invite_open() and _invite_enabled():
                        return InviteResult("unknown", False, f"the Invite press raised ({e}) and nothing on screen "
                                            f"changed. {who!r} MAY have been invited: look at Zoom", True)
                except Exception:
                    return InviteResult("unknown", False, f"the Invite press raised ({e}). {who!r} MAY have been "
                                        "invited: look at Zoom", True)
                refused = f" (the press reported: {e})"
            time.sleep(1.5)
            return InviteResult("invited", True, f"invited {who!r} as a Zoom contact{refused}", True)
        finally:
            _restore_invite()


def callout(number: str, timeout: float = 60.0, should_abort=None,
            *, press_call: bool = False, hold: float = 0.0) -> CalloutResult:
    """Type `number`, read it back, and only then (press_call=True) press Call and wait for the answer.

    Contract the caller relies on: an exception means Call was NOT pressed. From the moment the Call
    press is attempted, this function always returns a CalloutResult. If it lost track of the call it
    returns state "unknown", which means the phone may be ringing or connected."""
    if not E164.fullmatch(number):
        raise UiError(f"'{number}' is not E.164")

    with exclusive():
        try:
            _open_invite()
            before = _call_enabled()
            read = _set_number(number)
            if _norm(read) != number:
                _tidy()
                return CalloutResult("mismatch", False,
                                     f"typed {number!r} but the field reads {read!r}; Call was not pressed",
                                     read_back=read)
            after = _call_enabled()
            if not press_call:
                kept = ""
                if hold > 0:                      # leave it on screen so a person can see Zoom shows it
                    time.sleep(hold)
                    again = _get_number()
                    kept = (f"; still there after {hold:g}s" if _norm(again) == number
                            else f"; CHANGED after {hold:g}s to {again!r}")
                _set_number("")
                _close_invite()
                ok = not kept.startswith("; CHANGED")
                return CalloutResult("rehearsed" if ok else "reverted", ok,
                                     f"number typed and read back OK{kept}; Call enabled {before} -> {after} "
                                     "(it is enabled even when empty, so that proves nothing); Call was not pressed",
                                     read_back=read)
            # Bringing Zoom forward can disturb the field, so read the number again right before Call.
            _activate(INVITE_WIN)
            last = _get_number()
            if _norm(last) != number:
                _tidy()
                return CalloutResult("mismatch", False,
                                     f"after bringing Zoom forward the field reads {last!r}, not {number!r}; "
                                     "Call was not pressed", read_back=last)
        except Exception:
            _tidy()
            raise
        started = _now()
        try:
            _press(INVITE_WIN, "AXButton", "title", "^Call$", retry=False)
        except Exception as e:
            # A refused press (-25200) and a timeout (-25204) look alike from here, and a timed-out press
            # can still have taken effect, so this is never reported as "not placed".
            return CalloutResult("unknown", False,
                                 f"the Call press raised ({e}). The call MAY have been placed: look at Zoom "
                                 "and your phone before trying again", True, False, started, read)
        time.sleep(1.5)

    # Waiting for the callee is read-only, so the UI lock is released. Call has been pressed, so nothing
    # below may raise: any failure becomes state "unknown". (The Invite window normally stays open showing
    # "Calling..." while the phone rings, so its being open says nothing about whether Call registered.)
    snap: list = []
    switch = _AudioSwitch()
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if should_abort and should_abort():
                return CalloutResult("aborted", False,
                                     "aborted while ringing; the call was already placed" + switch.note(),
                                     True, False, started, read)
            snap = _read_screen()
            if switch.handle(snap):         # a modal prompt blocks everything else: look again first
                time.sleep(POLL)
                continue
            has_btn = any(n["role"] == "AXButton" and COMPLETE_RX.search(_text(n)) for n in snap)
            answered = any(n["role"] == "AXStaticText" and ANSWERED_RX.match(n["value"].strip()) for n in snap)
            if has_btn and answered:
                refused = ""
                try:
                    with exclusive():
                        _press(ANYWHERE, "AXButton", "any", COMPLETE_RX.pattern)
                except UiError as e:
                    # The callee answered, so this is not "unknown". A timed-out press can still take
                    # effect, so look at the screen instead of guessing.
                    refused = f" (the press reported: {e})"
                if _settle(switch):
                    return CalloutResult("completed", True,
                                         "answered and added to the meeting" + refused + switch.note(),
                                         True, True, started, read)
                try:
                    snap = _read_screen()
                except UiError:
                    pass
                saved = _save_debug(snap)
                return CalloutResult("complete_failed", False,
                                     "pressed 'Complete meeting invite' but it is still showing"
                                     + refused + switch.note() + saved, True, True, started, read)
            time.sleep(POLL)
        saved = _save_debug(snap)
        return CalloutResult("timeout", False,
                             f"no answer detected within {timeout:.0f}s; the phone may still be ringing"
                             f"{switch.note()}{_workplace_hint()}{saved}", True, False, started, read)
    except Exception as e:
        _save_debug(snap)
        return CalloutResult("unknown", False,
                             f"lost track of the call after Call was pressed ({e}){switch.note()}. It may be "
                             "ringing or connected: look at Zoom and your phone before trying again",
                             True, False, started, read)


def _workplace_hint() -> str:
    """The call controls (answer time, 'Complete meeting invite') live in the Zoom Workplace window. A full
    screen meeting sits on its own desktop and Accessibility cannot see Workplace from there."""
    try:
        if not _has_window(WORKPLACE_WIN):
            return (" [the Zoom Workplace window is not visible to Accessibility (is the meeting full screen?), "
                    "so an answer could not be seen]")
    except Exception:
        pass
    return ""


def _text(n: dict) -> str:
    return " ".join((n.get("title", ""), n.get("desc", ""), n.get("value", "")))


def _read_screen() -> list:
    """Every text node Zoom shows: the default scope (all windows except Zoom Workplace, untitled ones
    included, which is where a dialog may live) plus Workplace, where the call controls are. Raises UiError
    if either read fails: half a screen must not be mistaken for the whole."""
    base = _need(ax.call("texts"), "read screen")["nodes"]
    return base + _need(ax.call("texts", "--window", WORKPLACE_WIN), "read call state")["nodes"]


def _prompt_windows(nodes: list) -> list:
    """Titles of the windows that show the audio-switch prompt: the 'meeting in progress' heading, a Cancel
    button and exactly one Continue button, all in the same window. A stray 'Continue' elsewhere never
    qualifies."""
    by: dict = {}
    for n in nodes:
        by.setdefault(n.get("window", ""), []).append(n)
    found = []
    for title, ns in by.items():
        buttons = [n for n in ns if n.get("role") == "AXButton"]
        labels = [[x.strip() for x in (b.get("title", ""), b.get("desc", ""), b.get("value", "")) if x.strip()]
                  for b in buttons]
        if (any(PROMPT_RX.search(_text(n)) for n in ns)
                and any(CANCEL_RX.match(x) for ls in labels for x in ls)
                and sum(any(CONTINUE_RX.match(x) for x in ls) for ls in labels) == 1):
            found.append(title)
    return found


def _prompt_text_showing(nodes: list) -> bool:
    """The prompt's heading anywhere on screen, whatever window or role carries it."""
    return any(PROMPT_RX.search(_text(n)) for n in nodes)


def _press_continue(window: str) -> None:
    """Press the one Continue button in `window` (an untitled window is reached with the default scope).
    Refuses unless exactly one button matches, and that button sits in `window`. Only a -25200 refusal (Zoom
    was in the background, so nothing happened) is retried: Zoom is brought forward and the button is
    looked for again first. Any other failure, a timeout included, is not retried because the press may
    already have taken effect."""
    rx = "^" + re.escape(window) + "$"
    scope = ("--window", rx) if window else ()
    sel = ("--role", "AXButton", "--field", "any", "--match", CONTINUE_RX.pattern)

    def one_button() -> None:
        found = _need(ax.call("find", *scope, *sel), "find Continue")["matches"]
        if len(found) != 1:
            raise UiError(f"expected one Continue button, found {len(found)}")
        if found[0].get("window", "") != window:        # the default scope spans windows
            raise UiError(f"the Continue button is in {found[0].get('window', '')!r}, not {window!r}")

    with exclusive():
        one_button()
        d = ax.call("press", *scope, *sel)
        if not d.get("ok") and NOT_FRONTMOST in d.get("error", ""):
            _activate(rx if window else "")
            one_button()
            d = ax.call("press", *scope, *sel)
        _need(d, "press Continue")


class _AudioSwitch:
    """Answers Zoom's 'You have a meeting in progress ... audio will be switched' prompt with Continue.
    Only used after the Call press. Every attempt counts toward MAX_CONTINUE, whether or not it worked."""

    def __init__(self):
        self.tries = 0
        self.pressed = 0
        self.problems: list = []

    def _problem(self, msg: str) -> None:
        if msg not in self.problems:
            self.problems.append(msg)

    def handle(self, nodes: list) -> bool:
        """True if Continue was pressed, so the caller should read the screen again."""
        wins = _prompt_windows(nodes)
        if not wins:
            if _prompt_text_showing(nodes):
                self._problem("text like Zoom's audio-switch prompt is on screen but its Cancel / Continue "
                              "buttons were not recognised, so Continue was not pressed")
            return False
        if len(wins) != 1:
            self._problem(f"{len(wins)} windows look like the audio-switch prompt, so Continue was not pressed")
            return False
        if self.tries >= MAX_CONTINUE:
            self._problem(f"the audio-switch prompt came back after {MAX_CONTINUE} Continue presses")
            return False
        self.tries += 1
        try:
            _press_continue(wins[0])
        except UiError as e:
            self._problem(f"could not press Continue on the audio-switch prompt ({e})")
            return False
        self.pressed += 1
        return True

    def note(self) -> str:
        bits = ([f"pressed Continue on Zoom's audio-switch prompt x{self.pressed}"] if self.pressed else []) + self.problems
        return f" [{'; '.join(bits)}]" if bits else ""


def _settle(switch: "_AudioSwitch") -> bool:
    """After 'Complete meeting invite' was pressed: True once the button has been gone, with no sign of the
    audio-switch prompt anywhere (its heading text in any window counts, even if its buttons are not
    recognised), on clean reads that span SETTLE_GAP seconds, because the prompt can show up a moment
    after the button goes. Continue is pressed if the prompt appears meanwhile. A failed or empty read
    never counts as 'gone'."""
    end = time.monotonic() + COMPLETE_WAIT
    clean_since = None
    while True:
        try:
            nodes = _read_screen()
        except UiError:
            nodes = []
        if nodes and switch.handle(nodes):
            clean_since = None
            end = time.monotonic() + COMPLETE_WAIT      # give Zoom time to act on the press
        elif nodes and not any(COMPLETE_RX.search(_text(n)) for n in nodes) and not _prompt_text_showing(nodes):
            now = time.monotonic()
            if clean_since is None:
                clean_since = now
            elif now - clean_since >= SETTLE_GAP:
                return True
        else:
            clean_since = None
        if time.monotonic() >= end:
            return False
        time.sleep(0.2)


def _save_debug(snap: list) -> str:
    """Saves the last full screen read (every window, untitled ones included) plus the window list. Returns
    the sentence to append to a result's detail, true whether or not the file could be written."""
    try:
        titles = _titles()
    except Exception:
        titles = []
    try:                                # a diagnostic aid: never let it change or hide the call's outcome
        DEBUG_PATH.parent.mkdir(exist_ok=True)
        DEBUG_PATH.write_text(json.dumps({"at": _now(), "windows": titles, "nodes": snap}, indent=1))
        return f". Screen text saved to {DEBUG_PATH}"
    except Exception:
        return ". (The screen text could not be saved.)"


def rehearse(dummy: str = "+6500000000", hold: float = 0.0) -> CalloutResult:
    """Opens Invite, types a dummy number, reads it back, clears it. Never presses Call."""
    return callout(dummy, press_call=False, hold=hold)


# ---------------------------------------------------------------- computer-audio share (the spoken welcome)
#
# The welcome is played into the meeting as Zoom shared "Computer audio" (an audio-only share, no screen), the
# same idea as the Windows bot. Mapped live on the Mac: toolbar Share -> "Share screen window" -> "Other Tab"
# -> "Computer audio, Share audio" (arms it) -> "Share - Computer audio" (starts it). While it runs the meeting
# window shows a "My computer sound" tab and the text "Computer audio is being shared". The tab offers a
# "close My computer sound" button only while it is the selected tab.

SHARE_WIN = "^Share screen window$"
SHARE_LIVE_RX = r"^My computer sound|^Computer audio is being shared"
SHARE_GO_RX = r"^Share - Computer audio$"       # anchored: a "Share - Desktop 1" button must never match
SHARE_CLOSE_RX = r"^close My computer sound$"
SHARE_TAB_RX = r"^My computer sound$"
SHARE_PICKER_WAIT = 8.0
SHARE_START_WAIT = 10.0
SHARE_STOP_WAIT = 5.0


SURFACE_WAIT = 8.0


def _open_zoom() -> None:
    """Brings Zoom to the front, like its Dock icon. Zoom switches to the desktop its meeting is on."""
    try:
        subprocess.run(["open", "-b", "us.zoom.xos"], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass                                # the caller looks for the window anyway and reports if it is still missing


def surface_meeting() -> None:
    """meeting_window() for the share's own steps. While the bot is presenting, the call's Zoom Workplace window
    pushes the meeting window out of Accessibility's sight (seen live 2026-10-09), so the share could not be stopped
    and the bot stayed "Presenting". Bringing Zoom forward brings the window back. The share requires the main
    window; participant polling has its own detached-panel path and throttled recovery. A missing or untrusted
    Zoom process raises before any activation here."""
    if any(re.search(MEETING_WIN, t, re.I) for t in _titles()):
        return
    _open_zoom()
    end = time.monotonic() + SURFACE_WAIT
    while time.monotonic() < end:
        if in_meeting():
            return
        time.sleep(0.3)
    meeting_window()                        # still hidden: the usual error, listing the windows that are visible


def audio_sharing() -> bool:
    """True while the meeting window shows the computer-audio share's tab or its 'being shared' text."""
    d = _need(ax.call("find", "--window", MEETING_WIN, "--field", "any", "--match", SHARE_LIVE_RX), "look for the share")
    return bool(d["matches"])


def _share_go_ready() -> bool:
    return bool(_find(SHARE_WIN, "AXButton", "desc", SHARE_GO_RX))


def start_audio_share() -> None:
    """Starts an audio-only 'Computer audio' share. Returns once Zoom shows it running; raises UiError otherwise
    (after closing the picker and stopping anything that did start). No-op if one is already running."""
    with exclusive():
        surface_meeting()
        if audio_sharing():
            return
        try:
            _press(MEETING_WIN, "AXButton", "desc", "^Share$")
            _wait(lambda: _has_window(SHARE_WIN), SHARE_PICKER_WAIT, "the Share screen window did not open")
            _press(SHARE_WIN, "AXRadioButton", "desc", "^Other Tab")
            _press(SHARE_WIN, "AXButton", "desc", "^Computer audio, Share audio")
            _wait(_share_go_ready, 5, "Zoom did not arm the computer-audio share ('Share - Computer audio' never appeared)")
            _press(SHARE_WIN, "AXButton", "desc", SHARE_GO_RX)
            _wait(audio_sharing, SHARE_START_WAIT, "Zoom did not start sharing computer sound")
        except UiError:
            _abandon_share()
            raise


def _abandon_share() -> None:
    """Best effort after a failed start: close the picker if it is still open, stop whatever did start."""
    try:
        if _has_window(SHARE_WIN):
            ax.call("close", "--window", SHARE_WIN)
    except UiError:
        pass
    try:
        _stop_locked()
    except UiError:
        pass


def _stop_locked() -> None:
    """Ends the share and verifies it. The close button exists only while the share's tab is selected, so an
    unselected tab is clicked first (it has no AXPress). Raises UiError if the share is still showing."""
    last = ""
    for _ in range(3):
        if not audio_sharing():
            return
        try:
            if _find(MEETING_WIN, "AXButton", "desc", SHARE_CLOSE_RX):
                _press(MEETING_WIN, "AXButton", "desc", SHARE_CLOSE_RX)
                end = time.monotonic() + SHARE_STOP_WAIT
                while time.monotonic() < end and audio_sharing():
                    time.sleep(0.2)
            else:
                _activate(MEETING_WIN)
                _need(ax.call("click", "--window", MEETING_WIN, "--field", "desc", "--match", SHARE_TAB_RX),
                      "select the 'My computer sound' tab")
                time.sleep(1.0)
        except UiError as e:
            last = f" ({e})"
    if audio_sharing():
        raise UiError("could not stop the computer-audio share: click the x on the 'My computer sound' tab in Zoom"
                      + last)


def stop_audio_share() -> None:
    """Stops the computer-audio share and verifies it is gone. Brings Zoom forward if the call hid the meeting
    window; a window that still cannot be found is reported rather than assumed to be clean."""
    with exclusive():
        surface_meeting()
        _stop_locked()


def send_chat(message: str) -> None:
    raise UiUnavailable("chat panel not mapped on the Mac yet; the spoken welcome replaces the chat message")
