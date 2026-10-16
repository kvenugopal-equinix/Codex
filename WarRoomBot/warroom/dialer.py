"""Mac dialer. Default method "ui" calls out from inside the meeting (Invite > Zoom Phone > Call >
Complete meeting invite) through Accessibility. Method "uri" (zoomphonecall://) dials a separate
outbound call and is off unless WARROOM_DIAL_METHOD=uri. Gated; dry-run by default.

With WARROOM_ZOOM_INVITE=true the same engineer is also invited as a Zoom contact (Invite > Contacts). That
invite goes through the same gates as the call and is off by default."""
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from .config import ConfigError, E164, EMAIL, Settings, contact_name
from .roster import Shift

GUARD_SECONDS = 180      # a started call blocks the next live dial this long (at least) unless it ended cleanly


@dataclass
class DialDecision:
    number: str
    engineer: str
    will_place: bool
    reason: str
    zoom_email: str = ""        # the Zoom account to invite as a contact; "" = no invite (feature off, or no address)
    zoom_contact: str = ""      # name lookup only; never fall back between the two selectors


@dataclass
class InviteOutcome:
    text: str                   # "" when the feature is off, so nothing is printed or logged
    log: str = ""               # the join-log value: "", dry-run, yes, no, unknown
    interrupted: bool = False   # Ctrl-C landed mid-invite; a caller that loops must stop
    contact_name: str = ""      # actual Contacts row selected, when known
    attempted: bool = False     # Invite was pressed or may have been pressed
    sent: bool = False          # UI reported that the invitation was sent


@dataclass
class DialResult:
    text: str
    pressed: bool = False       # Call was actually pressed / the link opened
    answered: bool = False
    started_utc: str = ""
    uncertain: bool = False     # Call may have been placed but this run cannot tell: look at Zoom
    interrupted: bool = False   # Ctrl-C landed mid-call; a caller that loops must stop instead of carrying on
    invite_contact_name: str = ""
    invite_attempted: bool = False
    invite_sent: bool = False

    def __str__(self) -> str:
        return self.text


def choose_target(settings: Settings, duty: list) -> DialDecision:
    """test mode discards roster numbers and addresses and uses only WARROOM_TEST_NUMBER and
    WARROOM_TEST_ZOOM_EMAIL."""
    if settings.target_mode == "test":
        if not settings.test_number:
            return DialDecision("", "", False, "test mode but WARROOM_TEST_NUMBER is not set")
        return DialDecision(settings.test_number, "TEST", True, "test mode",
                            settings.test_zoom_email if settings.zoom_invite and settings.zoom_contact_lookup == "email" else "",
                            settings.test_zoom_contact if settings.zoom_invite and settings.zoom_contact_lookup == "name" else "")
    if not settings.allow_roster_calls:
        return DialDecision("", "", False, "roster mode needs WARROOM_ALLOW_ROSTER_CALLS=true")
    if not duty:
        return DialDecision("", "", False, "nobody on duty")
    s: Shift = duty[0]
    return DialDecision(s.phone, s.name, True, f"roster priority {s.priority}",
                        s.zoom_email if settings.zoom_invite and settings.zoom_contact_lookup == "email" else "",
                        s.name if settings.zoom_invite and settings.zoom_contact_lookup == "name" else "")


def _guard_path(settings: Settings) -> Path:
    return Path(settings.join_log_path).parent / "call_guard.json"


def _guard_blocks(path: Path) -> str:
    """Why a new live call must wait, or "". Written before Call is pressed, so it also covers a run that
    was killed mid-call. Only a call that ended cleanly (or never started) releases it early."""
    try:
        g = json.loads(path.read_text())
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(g["at"])).total_seconds()
        hold = float(g.get("hold", GUARD_SECONDS))
    except FileNotFoundError:
        return ""
    except Exception:
        return "logs/call_guard.json is unreadable; check Zoom, then delete it"
    if g.get("state") != "ended" and age < hold:
        return (f"a call to {g.get('number')} was started {age:.0f}s ago (state: {g.get('state')}). Check Zoom "
                f"and your phone; a new call is allowed after {hold:.0f}s, or delete {path.name}")
    return ""


def _guard_write(path: Path, state: str, number: str, hold: float = GUARD_SECONDS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "state": state, "number": number,
                                "hold": hold}))


def _guard_update(path: Path, state: str, number: str, hold: float) -> None:
    """Best effort, for use once Call may have been pressed: a failed write must not hide the result. The
    earlier 'in_flight' record then keeps blocking for `hold` seconds, which is the safe direction."""
    try:
        _guard_write(path, state, number, hold)
    except Exception:
        pass


def dial(settings: Settings, d: DialDecision) -> DialResult:
    if not d.will_place:
        return DialResult(f"SKIPPED: {d.reason}")
    if settings.target_mode not in ("test", "roster"):
        return DialResult("REFUSED: unknown target mode")
    if settings.target_mode == "roster" and not settings.allow_roster_calls:
        return DialResult("REFUSED: roster mode needs WARROOM_ALLOW_ROSTER_CALLS=true")
    if not E164.fullmatch(d.number):
        return DialResult(f"REFUSED: '{d.number}' is not E.164")
    if settings.target_mode == "test" and d.number != settings.test_number:
        return DialResult(f"REFUSED: test mode may only call WARROOM_TEST_NUMBER, not {d.number}")
    method = os.environ.get("WARROOM_DIAL_METHOD", "ui")
    if method not in ("ui", "uri"):
        return DialResult("REFUSED: WARROOM_DIAL_METHOD must be ui or uri")
    how = "zoomphonecall:// (separate call)" if method == "uri" else "Zoom Invite > Zoom Phone in the meeting"
    if settings.dry_run or not settings.live_calling:
        return DialResult(f"DRY-RUN: would call {d.number} ({d.engineer}) via {how}")
    guard = _guard_path(settings)
    blocked = _guard_blocks(guard)
    if blocked:
        return DialResult(f"REFUSED: {blocked}")
    if method == "uri":
        try:
            _guard_write(guard, "link_opened", d.number)
        except Exception as e:
            return DialResult(f"NOT PLACED: could not write the call guard ({e})")
        try:
            subprocess.run(["open", f"zoomphonecall://{d.number}"], check=True, timeout=20)
        except (Exception, KeyboardInterrupt) as e:
            return DialResult(f"UNKNOWN: opening the call link failed ({e}); check Zoom before retrying",
                              uncertain=True, interrupted=isinstance(e, KeyboardInterrupt))
        return DialResult(f"LINK OPENED for {d.number} ({d.engineer}); Zoom has not confirmed a call. Press "
                          "'Complete meeting invite' in Zoom once answered.", True, False,
                          datetime.now(timezone.utc).isoformat(timespec="seconds"))
    from . import ui_backend
    # The guard must outlast the longest call this run can make (the wait for an answer, then the settle).
    hold = max(GUARD_SECONDS, settings.call_timeout + 120)
    try:
        _guard_write(guard, "in_flight", d.number, hold)
    except Exception as e:
        return DialResult(f"NOT PLACED: could not write the call guard ({e}); no call was attempted")
    try:
        r = ui_backend.callout(d.number, settings.call_timeout, press_call=True)
    except KeyboardInterrupt:
        # Stopped part-way: Call may or may not have been pressed, so say so instead of guessing.
        _guard_update(guard, "unknown", d.number, hold)
        return DialResult("UNKNOWN, Call may have been placed: interrupted (Ctrl-C) while dialling. Look at "
                          "Zoom and your phone before trying again", False, False, "", True, True)
    except Exception as e:
        # callout raises only before Call is pressed; once pressed it returns a result instead.
        _guard_update(guard, "ended", d.number, hold)
        return DialResult(f"NOT PLACED: {e}")
    if r.state == "unknown":
        _guard_update(guard, "unknown", d.number, hold)
        return DialResult(f"UNKNOWN, Call may have been placed: {r.detail}", True, False, r.started_utc, True)
    _guard_update(guard, "ended" if r.ok or not r.call_pressed else r.state, d.number, hold)
    if r.ok:
        return DialResult(f"DIALLED {d.number} ({d.engineer}): {r.detail}", True, True, r.started_utc)
    return DialResult(f"{'CALL PLACED' if r.call_pressed else 'NOT PLACED'}, {r.state}: {r.detail}",
                      r.call_pressed, r.answered, r.started_utc)


def invite(settings: Settings, d: DialDecision) -> InviteOutcome:
    """Invite the engineer into the meeting as a Zoom contact, behind the same gates as the call. Never raises
    for a UI problem: the phone call is the main route, so a failed invite is reported and the call goes on.
    The address is never printed or logged (it is somebody's account)."""
    if not settings.zoom_invite or not d.will_place:
        return InviteOutcome("")
    if settings.target_mode not in ("test", "roster") or (
            settings.target_mode == "roster" and not settings.allow_roster_calls):
        return InviteOutcome("ZOOM INVITE REFUSED: roster calling is not authorized", "no")
    who = "the test account" if settings.target_mode == "test" else d.engineer
    name = ""
    if settings.zoom_contact_lookup == "name":
        try:
            name = contact_name(d.zoom_contact)
        except ConfigError:
            return InviteOutcome("ZOOM INVITE REFUSED: invalid Contacts display name", "no")
        if not name:
            hint = "set WARROOM_TEST_ZOOM_CONTACT" if settings.target_mode == "test" else "fill in the roster name"
            return InviteOutcome(f"ZOOM INVITE SKIPPED: no Contacts display name ({hint})", "no")
        if settings.target_mode == "test" and name != settings.test_zoom_contact.strip():
            return InviteOutcome("ZOOM INVITE REFUSED: test mode may only invite WARROOM_TEST_ZOOM_CONTACT", "no")
    elif settings.zoom_contact_lookup == "email":
        if not d.zoom_email:
            hint = " (set WARROOM_TEST_ZOOM_EMAIL)" if settings.target_mode == "test" else " (no zoom_email in the roster)"
            return InviteOutcome(f"ZOOM INVITE SKIPPED: no Zoom address for {who}{hint}", "no")
        if not EMAIL.fullmatch(d.zoom_email):
            return InviteOutcome(f"ZOOM INVITE REFUSED: the Zoom address for {who} is not an e-mail address", "no")
        if settings.target_mode == "test" and d.zoom_email != settings.test_zoom_email:
            return InviteOutcome("ZOOM INVITE REFUSED: test mode may only invite WARROOM_TEST_ZOOM_EMAIL", "no")
    else:
        return InviteOutcome("ZOOM INVITE REFUSED: unknown Contacts lookup mode", "no")
    if os.environ.get("WARROOM_DIAL_METHOD", "ui") == "uri":
        return InviteOutcome("ZOOM INVITE SKIPPED: contact invites need WARROOM_DIAL_METHOD=ui", "no")
    if settings.dry_run or not settings.live_calling:
        return InviteOutcome(f"DRY-RUN: would invite {who} as a Zoom contact (Invite > Contacts)", "dry-run")
    blocked = _guard_blocks(_guard_path(settings))
    if blocked:
        return InviteOutcome(f"ZOOM INVITE REFUSED: {blocked}", "no")
    from . import ui_backend
    try:
        r = (ui_backend.invite_contact(contact_name=name, press_invite=True) if name else
             ui_backend.invite_contact(d.zoom_email, press_invite=True))
    except KeyboardInterrupt:
        return InviteOutcome("ZOOM INVITE UNKNOWN: interrupted (Ctrl-C) while inviting. Look at Zoom before "
                             "trying again", "unknown", True, attempted=True)
    except Exception as e:
        return InviteOutcome(f"ZOOM INVITE NOT SENT: {e}", "no")      # raised before Invite was pressed
    if r.ok:
        return InviteOutcome(f"ZOOM INVITE SENT: {r.detail}", "yes", contact_name=r.contact_name,
                             attempted=r.pressed, sent=True)
    if r.state == "unknown":
        return InviteOutcome(f"ZOOM INVITE UNKNOWN: {r.detail}", "unknown", contact_name=r.contact_name,
                             attempted=r.pressed)
    return InviteOutcome(f"ZOOM INVITE NOT SENT, {r.state}: {r.detail}", "no")
