#!/bin/bash
# Switch the war-room watcher on and off:   ./watch.sh [start|stop|status|dry|check]
#   check   read-only: shows the Zoom meeting window and its participants. Places no call, plays nothing.
#   dry     watches and logs what it WOULD do. Places no call, plays nothing.
#   start   live, in TEST MODE: the only number it can dial is WARROOM_TEST_NUMBER (a visitor really triggers a call).
#   stop / status   act on the watcher started from THIS folder only.
# Run it from a terminal that has Accessibility permission, with the bot in the Zoom meeting.
cd "$(dirname "$0")" || exit 1
ROOT="$PWD"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || { echo "no .venv yet: run ./install.sh first"; exit 1; }

# Mine = started from this folder (absolute interpreter path in its command line), so installs do not see each other.
MINE=$(printf '%s' "$PY -m warroom.cli watch" | sed 's/[][\.*^$+?(){}|/]/\\&/g')
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

case "${1:-start}" in
  start)
    already_on && exit 1
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
    exec caffeinate -dis "$PY" -m warroom.cli watch ;;
  dry)
    already_on && exit 1
    export WARROOM_DRY_RUN=true WARROOM_LIVE_CALLING=false WARROOM_TARGET_MODE=test WARROOM_VOICE_IN_DRY_RUN=false
    echo "starting the watcher in DRY RUN: nothing is dialled and nothing is played. Ctrl-C to stop"
    exec caffeinate -dis "$PY" -m warroom.cli watch ;;
  check)
    exec "$PY" -m warroom.cli ui-probe ;;
  stop)
    if pkill -INT -f "$MINE"; then echo "OFF: stop signal sent"; else echo "was not running"; others_note; fi ;;
  status)
    if pgrep -f "$MINE" >/dev/null; then echo "ON (pid $(pids "$MINE"))"; else echo "OFF"; others_note; fi ;;
  *)
    echo "usage: ./watch.sh [start|stop|status|dry|check]"; exit 2 ;;
esac
