#!/bin/bash
# Switch the war-room watcher on and off:   ./watch.sh [start|roster|stop|status|dry|roster-dry|check|roster-preview]
#   check   read-only: shows the Zoom meeting window and its participants. Places no call, plays nothing.
#   dry     watches and logs what it WOULD do. Places no call, plays nothing.
#   start   live, in TEST MODE: the only number it can dial is WARROOM_TEST_NUMBER (a visitor really triggers a call).
#   roster-preview   read-only: reports the current on-duty engineer selected for roster calls.
#   roster / roster-dry   live roster calling / roster rehearsal. Live roster calling requires this explicit command.
#   stop / status   act on the watcher started from THIS folder only.
# Run it from a terminal that has Accessibility permission, with the bot in the Zoom meeting.
cd "$(dirname "$0")" || exit 1
ROOT="$PWD"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || { echo "no .venv yet: run ./install.sh first"; exit 1; }

# Any watcher on this Mac, whichever folder. Two of them would fight over the one Zoom window, so start refuses.
ANY="warroom\\.cli watch"

pids() { pgrep -f "$1" | tr '\n' ' '; }

already_on() {
  if pgrep -f "$ANY" >/dev/null; then
    echo "a watcher is already running (pid $(pids "$ANY")); './watch.sh stop' first (or Ctrl-C it) to restart it"
    return 0
  fi
  return 1
}

# Said by status/stop when nothing of this folder's is running but some other watcher is.
others_note() {
  if pgrep -f "$ANY" >/dev/null; then
    echo "note: a watcher that was not started by this script is running (pid $(pids "$ANY")); this script does not touch it. Press Ctrl-C in the window it runs in."
  fi
}

# Select through the production roster rules without entering the dialer or driving Zoom.
# Temporary overrides do not change .env or the settings inherited by a later watcher.
roster_preview() (
  export WARROOM_DRY_RUN=true WARROOM_LIVE_CALLING=false WARROOM_TARGET_MODE=roster WARROOM_ALLOW_ROSTER_CALLS=true
  "$PY" - <<'PY'
import sys
from datetime import datetime, timezone
from warroom.config import E164, Settings
from warroom.dialer import choose_target
from warroom.roster import load_roster, on_duty

try:
    settings = Settings.from_env()
    duty = on_duty(load_roster(settings.roster_path), datetime.now(timezone.utc))
    target = choose_target(settings, duty)
    if not target.will_place:
        print("SKIPPED: " + target.reason)
        sys.exit(1)
    if not E164.fullmatch(target.number):
        print("ROSTER: the selected engineer's phone is not an international number (+country code and digits)")
        sys.exit(2)
    shift = duty[0]
    print("Selected on-duty engineer: " + target.engineer)
    print("Phone: " + target.number)
    print(f"Priority: {shift.priority}; shift: {shift.start:%H:%M}-{shift.end:%H:%M} ({shift.timezone})")
    print("No call has been placed. The watcher selects the current on-duty engineer for each new visitor.")
except Exception as error:
    print("ROSTER: could not select an on-duty engineer: " + str(error))
    sys.exit(2)
PY
)

managed_watch() {
  local mode="$1" token
  token=$("$PY" -c 'import uuid; print(uuid.uuid4().hex)') || return 1
  mkdir -p "$ROOT/logs" || return 1
  printf '%s\n' "$mode" > "$ROOT/logs/watcher.mode" || return 1
  exec "$PY" -m warroom.cli watch --watch-token "$token"
}

case "${1:-start}" in
  start)
    already_on && exit 1
    export PYTHONUNBUFFERED=1
    # Fail before anything runs: test mode with no test number could never place a call, and says so late.
    TEST_NUMBER=$("$PY" -c 'from warroom.config import Settings; print(Settings.from_env().test_number)' 2>/dev/null)
    if [ -z "$TEST_NUMBER" ]; then
      echo "WARROOM_TEST_NUMBER is not set. Put your own phone number in .env (WARROOM_TEST_NUMBER=+<country code><number>), then retry."
      echo "Use './watch.sh dry' to rehearse without a number."
      exit 1
    fi
    export WARROOM_DRY_RUN=false WARROOM_LIVE_CALLING=true WARROOM_TARGET_MODE=test
    echo "starting the watcher LIVE in test mode; a new visitor will call ${TEST_NUMBER}"
    echo "Ctrl-C in this window (or './watch.sh stop' elsewhere) switches it off"
    managed_watch live ;;
  dry)
    already_on && exit 1
    export PYTHONUNBUFFERED=1
    export WARROOM_DRY_RUN=true WARROOM_LIVE_CALLING=false WARROOM_TARGET_MODE=test WARROOM_VOICE_IN_DRY_RUN=false
    echo "starting the watcher in DRY RUN: nothing is dialled and nothing is played. Ctrl-C to stop"
    managed_watch dry ;;
  roster)
    already_on && exit 1
    PREVIEW=$(roster_preview); PREVIEW_RC=$?
    printf '%s\n' "$PREVIEW"
    [ "$PREVIEW_RC" -eq 0 ] || exit "$PREVIEW_RC"
    export PYTHONUNBUFFERED=1
    export WARROOM_DRY_RUN=false WARROOM_LIVE_CALLING=true WARROOM_TARGET_MODE=roster WARROOM_ALLOW_ROSTER_CALLS=true
    echo "starting the watcher LIVE in roster mode; new visitors trigger a call to the current on-duty engineer"
    echo "Ctrl-C in this window (or './watch.sh stop' elsewhere) switches it off"
    managed_watch roster-live ;;
  roster-dry)
    already_on && exit 1
    export PYTHONUNBUFFERED=1
    export WARROOM_DRY_RUN=true WARROOM_LIVE_CALLING=false WARROOM_TARGET_MODE=roster WARROOM_ALLOW_ROSTER_CALLS=true WARROOM_VOICE_IN_DRY_RUN=false
    echo "starting the watcher in roster DRY RUN: logs the selected engineer; nothing is dialled and nothing is played. Ctrl-C to stop"
    managed_watch roster-dry ;;
  roster-preview)
    roster_preview ;;
  check)
    exec "$PY" -m warroom.cli ui-probe ;;
  stop)
    RESULT=$("$PY" -m warroom.process stop --root "$ROOT") || exit $?
    printf '%s\n' "$RESULT"
    [ "$RESULT" = "was not running" ] && others_note
    exit 0 ;;
  status)
    STATUS=$("$PY" -m warroom.process status --root "$ROOT") || exit $?
    printf '%s\n' "$STATUS"
    [ "$STATUS" = "OFF" ] && others_note
    exit 0 ;;
  *)
    echo "usage: ./watch.sh [start|roster|stop|status|dry|roster-dry|check|roster-preview]"; exit 2 ;;
esac
