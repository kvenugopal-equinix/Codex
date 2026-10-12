"""python -m warroom.cli oncall | dial | join NAME | watch | voice-test | ui-probe | selftest"""
import argparse
import signal
import sys
from datetime import datetime, timezone
from .config import ConfigError, Settings
from .dialer import DialResult, choose_target, dial, invite
from .joinlog import log_join
from .voice import DEFAULT_MESSAGE, speak, speak_in_meeting
from .roster import load_roster, on_duty


NOT_TRUSTED = ("NOT TRUSTED: give the app that runs this (War Room Bot, Terminal, iTerm or Claude) Accessibility "
               "permission in System Settings > Privacy & Security > Accessibility, then retry")


def main(argv=None):
    p = argparse.ArgumentParser(prog="warroom")
    p.add_argument("cmd", choices=["oncall", "dial", "join", "watch", "voice-test", "ui-probe", "selftest"])
    p.add_argument("name", nargs="?", default="Visitor")
    p.add_argument("--include-placeholders", action="store_true")
    p.add_argument("--hold", type=float, default=0.0, help="selftest: seconds to leave the typed number visible")
    a = p.parse_args(argv)
    try:
        s = Settings.from_env()
    except ConfigError as e:
        print(f"CONFIG: {e}", file=sys.stderr)
        return 2
    if a.cmd in ("dial", "join", "watch"):
        # Shows the values that actually won (a real environment variable beats .env; the first duplicate wins).
        print(f"gates: {s.gates()}", file=sys.stderr)
    if a.cmd in ("ui-probe", "selftest"):
        return ui_commands(a.cmd, a.hold)
    if a.cmd == "voice-test":
        return voice_test(s)
    if a.cmd == "watch":
        return watch_command(s, a.include_placeholders)
    duty = on_duty(load_roster(s.roster_path), datetime.now(timezone.utc), a.include_placeholders)
    if a.cmd == "oncall":
        for x in duty:
            print(f"P{x.priority} {x.name} {x.phone} {x.timezone} {x.start}-{x.end}")
        if not duty:
            print("nobody on duty (placeholder rows are ignored unless --include-placeholders)")
    elif a.cmd == "dial":
        d = choose_target(s, duty)
        inv = invite(s, d)
        if inv.text:
            print(inv.text)
        if inv.interrupted:
            return 1
        text = dial(s, d).text
        print(text)
        return _exit_code(text)
    else:
        # Start the voice first (non-blocking), then dial straight away so both run in parallel.
        result, _ = _escalate(s, a.name, duty, _start_voice(s))
        return _exit_code(result.text)


def _start_voice(s):
    """Starts the spoken welcome without waiting for it. Returns a handle (truthy, with wait()) or None."""
    if s.voice_enabled and (not s.dry_run or s.voice_in_dry_run):
        play = speak if s.voice_route == "local" else speak_in_meeting
        return play(s.voice_message or DEFAULT_MESSAGE, s.voice_name or None)
    return None


def _welcome(voice) -> str:
    """What the join log records for the welcome: 'no', 'yes', or the shared-audio outcome ('FAILED: ...')."""
    if not voice:
        return "no"
    return " ".join(str(getattr(voice, "outcome", "yes")).split())[:200]


def voice_test(s):
    """Plays the welcome into the meeting once, as Zoom shared computer sound. Places no call and writes no log; it
    ignores WARROOM_DRY_RUN and WARROOM_VOICE because the point is to hear it."""
    from . import ui_backend as ui
    try:
        if not ui.input_available():
            print(NOT_TRUSTED)
            return 1
        ui.prepare_meeting()
    except ui.UiError as e:
        print(f"UI: {e}")
        return 1
    voice = speak_in_meeting(s.voice_message or DEFAULT_MESSAGE, s.voice_name or None)
    print("starting a computer-audio share and playing the welcome into the meeting ...")
    try:
        outcome = voice.wait()
    except KeyboardInterrupt:
        print("interrupted: stopping the share", file=sys.stderr)
        return 1
    print(f"welcome voice: {outcome}")
    return 0 if outcome == "yes" else 1


def _safe_cell(text: str) -> str:
    """A display name is somebody else's text: stop a spreadsheet reading it as a formula."""
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _escalate(s, name, duty, voice):
    """Dial for one visitor and log it. Returns (result, decision)."""
    d = choose_target(s, duty)
    # The welcome keeps playing while the engineer is invited and called. All of it drives Zoom, but ui_backend lets
    # only one act at a time, and the share's stop brings the meeting window back if the call hid it
    # (ui_backend.surface_meeting). The contact invite goes first: it is quick, and it leaves Zoom Phone showing.
    inv = invite(s, d)
    if inv.text:
        print(inv.text)
    if inv.interrupted:
        # Ctrl-C landed mid-invite. Do not carry on and dial: stop, and let the watcher stop too.
        result = DialResult("NOT CALLED: interrupted (Ctrl-C) during the Zoom invite", interrupted=True)
    else:
        result = dial(s, d)
    text = result.text
    print(text)         # first, so a logging failure can never hide that a call was placed
    try:
        if voice:
            voice.wait()  # only after dialling has been issued; the log then records how the welcome went
    finally:
        try:
            log_join(s.join_log_path, participant_name=_safe_cell(name), role="visitor",
                     welcome_voice=_welcome(voice),
                     engineer_called=("dry-run" if text.startswith("DRY") else "unknown" if result.uncertain
                                      else "yes" if result.pressed else "no"),
                     engineer_name=d.engineer, call_started_utc=result.started_utc,
                     call_answered=("" if result.uncertain else "yes" if result.answered
                                    else "no" if result.pressed else ""),
                     notes=(inv.text + " | " + text) if inv.text else text, zoom_invited=inv.log)
        except Exception as e:
            print(f"LOG FAILED: {e}. The result above is still valid.", file=sys.stderr)
    return result, d


def watch_command(s, include_placeholders=False):
    """Watch the meeting and escalate for each new visitor. Stops on Ctrl-C."""
    from . import ui_backend as ui
    from .watcher import Watcher
    try:
        # A watcher started in the background by a non-interactive shell inherits SIGINT as "ignored", and then
        # Ctrl-C / './watch.sh stop' (which sends SIGINT) would do nothing. Stop must always work.
        signal.signal(signal.SIGINT, signal.default_int_handler)
    except ValueError:      # not the main thread
        pass
    try:
        if not ui.input_available():
            print(NOT_TRUSTED)
            return 1
        ui.prepare_meeting()
    except ui.UiError as e:
        print(f"UI: {e}")
        return 1
    shifts = load_roster(s.roster_path)

    def escalate(name, voice):
        # Re-read the roster each time: the shift may have changed, and a roster edit takes effect without a restart.
        try:
            duty = on_duty(load_roster(s.roster_path), datetime.now(timezone.utc), include_placeholders)
        except Exception as e:
            print(f"ROSTER: {e}; treating nobody as on duty", file=sys.stderr)
            duty = []
        result, d = _escalate(s, name, duty, voice)
        return result, d.number

    def log_skip(name, voice, why):
        try:
            if voice:
                voice.wait()
        finally:
            try:
                log_join(s.join_log_path, participant_name=_safe_cell(name), role="visitor",
                         welcome_voice=_welcome(voice), engineer_called="no", notes=f"NOT CALLED: {why}")
            except Exception as e:
                print(f"LOG FAILED: {e}", file=sys.stderr)

    w = Watcher(s, shifts, ui.read_participants, escalate, log_skip, lambda: _start_voice(s))
    print(f"watching the meeting every {s.poll_seconds:g}s; Ctrl-C to stop")
    try:
        w.run()
    except KeyboardInterrupt:
        print("stopped" + (" while a call was being placed: look at Zoom and your phone" if w.interrupted else ""))
        return 1 if w.interrupted else 0


def _exit_code(text: str) -> int:
    """0 for a dry run or a call that connected; 1 for everything else, including 'unknown'."""
    return 0 if text.startswith(("DRY-RUN", "DIALLED")) else 1


def ui_commands(cmd, hold=0.0):
    """Checks of the Zoom UI layer. May bring a hidden meeting forward; never presses Call."""
    from . import ui_backend as ui
    try:
        if not ui.input_available():
            print(NOT_TRUSTED)
            return 1
        meeting = ui.prepare_meeting()
        if cmd == "ui-probe":
            print("meeting window:", meeting)
            for p in ui.read_participants():
                print(f"  {p.display_name}{' (me)' if p.is_me else ''}{' [host]' if p.is_host else ''}"
                      f"{' ' + p.phone_number if p.phone_number else ''}")
        else:
            r = ui.rehearse(hold=hold)
            print(f"{r.state}: {r.detail}")
            return 0 if r.ok else 1
    except ui.UiError as e:
        print(f"UI: {e}")
        return 1
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
