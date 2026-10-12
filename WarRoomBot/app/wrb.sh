#!/bin/bash
# War Room Bot control script. The app (WarRoomBot.applescript) calls this for every action, and it works by hand too:
#
#   wrb.sh state            NOT_INSTALLED | SETTING_UP | UPDATE_AVAILABLE | READY
#   wrb.sh setup            copy the files to the install folder and run install.sh (idempotent; also "update/repair")
#   wrb.sh setup-bg         the same, detached (what the app uses; follow it with "progress")
#   wrb.sh progress         "N/6 what it is doing" while setup runs, then "DONE <exit code>"
#   wrb.sh log | error      the last lines of the setup log | why the last setup failed
#   wrb.sh start | dry      run the watcher in the background: live in TEST MODE (calls only the test number) | dry run
#   wrb.sh stop | status | check | recent
#   wrb.sh number | has-number | set-number N
#   wrb.sh trusted | permission-status | accessibility | open-data | version
#
# WARROOM_HOME overrides the install folder (default ~/WarRoomBot). Tests set it to stay out of the real home.
# Exit codes: 0 ok; 10 developer tools requested; 11 Nexus unreachable; 13 watcher is running; 20 not set up;
# 21 another watcher is running; 22 no test number; 23 Accessibility not allowed; 24 watcher did not stay up; 2 usage.
set -uo pipefail

SELF="$(cd "$(dirname "$0")" && pwd -P)"
PAYLOAD="$(cd "$SELF/.." && pwd -P)"          # the app's payload, or the install itself when run from there
WR_HOME="${WARROOM_HOME:-$HOME/WarRoomBot}"
INDEX="${WARROOM_PIP_INDEX:-https://nexus.equinix.com/repository/pypi-mirror/simple/}"
LOGS="$WR_HOME/logs"

installed() { [ -x "$WR_HOME/.venv/bin/python" ] && [ -x "$WR_HOME/tools/axctl" ] && [ -f "$WR_HOME/.env" ] && [ -f "$WR_HOME/VERSION" ]; }
need_installed() { installed || { echo "War Room Bot is not set up yet: open the app to set it up (or run: wrb.sh setup)."; exit 20; }; }
payload_version() { cat "$PAYLOAD/VERSION" 2>/dev/null || echo dev; }
installed_version() { cat "$WR_HOME/VERSION" 2>/dev/null || echo none; }
py() { if [ -x "$WR_HOME/.venv/bin/python" ]; then echo "$WR_HOME/.venv/bin/python"; else echo python3; fi; }

# Setup writes its pid here while it runs; a pid that no longer runs wrb.sh is a leftover. (Not our own pid: setup-bg
# writes the pid of the process it starts, which then asks "is setup already running?".)
setup_running() {
  local pid
  pid=$(cat "$LOGS/setup.pid" 2>/dev/null) || return 1
  [ -n "$pid" ] && [ "$pid" != "$$" ] && ps -p "$pid" -o command= 2>/dev/null | grep -q 'wrb\.sh'
}
# Captured, not piped: with pipefail a pipe closed early by head/grep can fail the whole test.
watcher_on() { local out; out=$("$WR_HOME/watch.sh" status 2>/dev/null); case "$out" in ON*) return 0 ;; *) return 1 ;; esac; }
same_dir() { [ -d "$1" ] && [ -d "$2" ] && [ "$1" -ef "$2" ]; }
# Any warroom watcher on this Mac, started by this app or not (one Zoom per Mac, so two would fight).
other_watcher_pids() { pgrep -f 'warroom\.cli watch' | tr '\n' ' '; }

cmd_state() {
  if setup_running; then echo SETTING_UP
  elif ! installed; then echo NOT_INSTALLED
  elif ! same_dir "$PAYLOAD" "$WR_HOME" && [ "$(payload_version)" != "$(installed_version)" ]; then echo UPDATE_AVAILABLE
  else echo READY
  fi
}

# ---- setup -------------------------------------------------------------------------------------------------

setup_fail() { echo "ERROR: $2"; exit "$1"; }

setup_body() {
  echo "==> 0/6 Checking this Mac and the network"
  [ "$(uname -s)" = "Darwin" ] || setup_fail 1 "this runs on macOS only"
  if ! xcode-select -p >/dev/null 2>&1; then
    xcode-select --install >/dev/null 2>&1
    setup_fail 10 "the Apple developer tools are needed (Python and the Accessibility helper). macOS has opened its installer: let it finish, then open War Room Bot again."
  fi
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$INDEX" 2>/dev/null || true)
  [ -n "$code" ] && [ "$code" != "000" ] \
    || setup_fail 11 "cannot reach $INDEX. Connect to the Equinix network or VPN and try again. Public package sites are deliberately not used."
  # Replacing the helper while a watcher runs could break the call it is making.
  if [ -x "$WR_HOME/watch.sh" ] && watcher_on; then
    setup_fail 13 "the watcher is running. Stop it first, then update."
  fi

  if ! same_dir "$PAYLOAD" "$WR_HOME"; then
    echo "==> 0/6 Copying the files to $WR_HOME"
    # ditto merges into an existing folder: files the payload does not hold (.env, roster.xlsx, logs, .venv, tools/axctl)
    # are never touched. --noqtn keeps the download's "quarantine" mark off the installed copy.
    ditto --noqtn "$PAYLOAD" "$WR_HOME" || setup_fail 1 "could not copy the files to $WR_HOME"
    rm -f "$WR_HOME/VERSION"        # put back only once the install has worked, so a half-done setup is retried
  fi
  xattr -dr com.apple.quarantine "$WR_HOME" 2>/dev/null || true
  chmod +x "$WR_HOME/install.sh" "$WR_HOME/watch.sh" "$WR_HOME/app/wrb.sh" "$WR_HOME"/tools/*.sh 2>/dev/null || true

  ( cd "$WR_HOME" && ./install.sh ) \
    || setup_fail 1 "the install did not finish (see the lines above, or $LOGS/setup.log)"
  if ! same_dir "$PAYLOAD" "$WR_HOME"; then payload_version > "$WR_HOME/VERSION"; fi   # written, not copied: a copy keeps the download's quarantine mark
  chmod 600 "$WR_HOME/.env" "$WR_HOME/roster.xlsx" 2>/dev/null || true     # a phone number and the on-call roster: owner only
  echo "==> 6/6 Done"
}

cmd_setup() {
  mkdir -p "$LOGS" || { echo "ERROR: cannot create $LOGS"; exit 1; }
  if setup_running; then echo "Set-up is already running."; exit 0; fi
  rm -f "$LOGS/setup.done"
  echo $$ > "$LOGS/setup.pid"
  { echo; echo "---- setup $(date '+%Y-%m-%d %H:%M:%S') (version $(payload_version)) ----"; } >> "$LOGS/setup.log"
  ( setup_body ) >> "$LOGS/setup.log" 2>&1
  local rc=$?
  echo "$rc" > "$LOGS/setup.done"       # before the pid file goes, so "not running and no result" can only mean a crash
  rm -f "$LOGS/setup.pid"
  if [ "$rc" -eq 0 ]; then echo "Set-up finished."; else tail -n 6 "$LOGS/setup.log"; fi
  exit "$rc"
}

# Starts setup detached and returns at once, so the app can show a progress bar while it runs.
cmd_setup_bg() {
  mkdir -p "$LOGS" || { echo "ERROR: cannot create $LOGS"; exit 1; }
  if setup_running; then echo "already running"; return 0; fi
  rm -f "$LOGS/setup.done"
  nohup /bin/bash "$SELF/wrb.sh" setup < /dev/null > /dev/null 2>&1 &
  echo $! > "$LOGS/setup.pid"
  disown 2>/dev/null
  echo started
}

cmd_progress() {
  if [ -f "$LOGS/setup.done" ]; then echo "DONE $(cat "$LOGS/setup.done")"; return 0; fi
  if ! setup_running; then echo "DONE 1"; return 0; fi      # it died without leaving a result
  local last
  last=$(grep -E '^==> ' "$LOGS/setup.log" 2>/dev/null | tail -n 1)
  echo "${last#==> }"
}

cmd_log() { tail -n "${1:-12}" "$LOGS/setup.log" 2>/dev/null || echo "(no setup log yet)"; }

# Show the cause from the latest setup attempt, rather than the outer install wrapper.
# If a compiler or test process exited without an ERROR line, preserve its last diagnostics.
cmd_error() {
  [ -f "$LOGS/setup.log" ] || { echo "No setup log yet."; return 0; }
  awk '
    /^---- setup / { count = 0; cause = ""; delete lines }
    /^ERROR: the install did not finish/ { next }
    /^[[:space:]]*$/ { next }
    { lines[++count] = $0 }
    /^ERROR:/ { cause = substr($0, 8) }
    END {
      if (cause != "") print cause
      else if (count == 0) print "No diagnostic was recorded. Run the installer in Terminal."
      else {
        first = count > 12 ? count - 11 : 1
        for (i = first; i <= count; i++) print lines[i]
      }
    }
  ' "$LOGS/setup.log"
}

# ---- the watcher -------------------------------------------------------------------------------------------

mode_file() { echo "$LOGS/watcher.mode"; }

cmd_status() {
  need_installed
  if watcher_on; then
    local mode pid
    mode=$(cat "$(mode_file)" 2>/dev/null || echo unknown)
    pid=$(pgrep -f "$WR_HOME/.venv/bin/python -m warroom.cli watch" | head -n 1)
    case "$mode" in
      live) echo "ON, live in test mode: a new visitor places a call to your test number." ;;
      dry)  echo "ON, dry run: nothing is dialled and nothing is played." ;;
      *)    echo "ON (started outside this app)." ;;
    esac
    [ -n "$pid" ] && echo "Running for $(ps -p "$pid" -o etime= 2>/dev/null | tr -d ' ')."
  else
    rm -f "$(mode_file)"
    echo "OFF"
    "$WR_HOME/watch.sh" status | sed 1d      # the note about a watcher this app did not start, if any
  fi
}

launch() {          # $1 = start | dry
  need_installed
  if watcher_on; then echo "The watcher is already running."; exit 0; fi
  if [ "$1" = "start" ] && ! cmd_has_number >/dev/null; then
    echo "Set your test phone number first (Change test phone number)."
    exit 22
  fi
  local others
  others=$(other_watcher_pids)
  if [ -n "$others" ]; then
    echo "Another watcher that this app did not start is running (pid $others). Stop it first (Ctrl-C in the window it runs in)."
    exit 21
  fi
  if ! cmd_trusted >/dev/null; then
    echo "Accessibility is not allowed for War Room Bot yet. Allow it in System Settings > Privacy & Security > Accessibility, then try again."
    exit 23
  fi
  mkdir -p "$LOGS"
  local log="$LOGS/watcher.log"
  [ "$(stat -f %z "$log" 2>/dev/null || echo 0)" -gt 5000000 ] && mv -f "$log" "$log.1"
  echo "---- $1 $(date '+%Y-%m-%d %H:%M:%S') ----" >> "$log"
  [ "$1" = "start" ] && echo live > "$(mode_file)" || echo dry > "$(mode_file)"
  # Job control gives the background job a normal SIGINT. Without it a non-interactive shell starts it with SIGINT
  # ignored, and Stop (which sends SIGINT) would do nothing.
  set -m
  nohup "$WR_HOME/watch.sh" "$1" < /dev/null >> "$log" 2>&1 &
  disown 2>/dev/null
  set +m
  local i
  for i in 1 2 3 4 5 6 7 8; do sleep 1; watcher_on && break; done
  sleep 2       # it exits at once if Zoom shows no meeting, or Accessibility is refused
  if watcher_on; then
    cmd_status
  else
    rm -f "$(mode_file)"
    echo "The watcher did not stay running:"
    awk -v h="---- $1 " 'index($0, h) == 1 { buf = "" } { buf = buf $0 "\n" } END { printf "%s", buf }' "$log" | tail -n 8
    exit 24
  fi
}

cmd_stop() {
  need_installed
  if ! watcher_on; then echo "The watcher is not running."; rm -f "$(mode_file)"; "$WR_HOME/watch.sh" status | sed 1d; return 0; fi
  "$WR_HOME/watch.sh" stop >/dev/null
  local i
  for i in $(seq 1 20); do watcher_on || break; sleep 1; done
  if watcher_on; then
    echo "Stop was requested but the watcher is still finishing something (a call in progress). Check Status in a minute."
  else
    rm -f "$(mode_file)"
    echo "OFF"
  fi
}

cmd_check() {
  need_installed
  local out rc
  out=$("$WR_HOME/watch.sh" check 2>&1); rc=$?
  printf '%s\n' "$out" | head -n 25
  exit "$rc"
}

cmd_recent() {
  need_installed
  "$(py)" - "$LOGS/join_log.csv" <<'PY'
import csv, sys
try:
    with open(sys.argv[1], newline="") as f:
        rows = list(csv.DictReader(f))
except FileNotFoundError:
    rows = []
if not rows:
    print("No visitors logged yet.")
for r in reversed(rows[-5:]):
    print(f"{r.get('joined_at_local', '')}  {r.get('participant_name', '')}")
    print(f"   welcome: {r.get('welcome_voice', '')}   call: {r.get('engineer_called', '')}   zoom invite: {r.get('zoom_invited', '') or '-'}")
    if r.get("notes"):
        print(f"   {r['notes'][:110]}")
PY
}

# ---- settings and permission -------------------------------------------------------------------------------

cmd_number() {
  need_installed
  ( cd "$WR_HOME" && "$(py)" -c 'from warroom.config import Settings; print(Settings.from_env().test_number)' 2>/dev/null )
}

cmd_has_number() { local n; n=$(cmd_number); [[ "$n" =~ ^\+[1-9][0-9]{6,14}$ ]]; }

cmd_set_number() {
  need_installed
  [ $# -ge 1 ] || { echo "usage: wrb.sh set-number +<country code><number>"; exit 2; }
  "$(py)" "$WR_HOME/tools/set_env.py" --env "$WR_HOME/.env" WARROOM_TEST_NUMBER "$*"
}

# Parse the top-level Boolean, never a quoted word or a nested field.
trust_value() {
  "$(py)" -c '
import json, sys
try:
    data = json.loads(sys.argv[1])
except (ValueError, TypeError):
    data = None
value = data.get("ok") if isinstance(data, dict) else None
print("true" if value is True else "false" if value is False else "invalid")
' "$1" 2>/dev/null
}

cmd_trusted() {
  local out
  out=$("$WR_HOME/tools/axctl" trusted 2>/dev/null) || return 1
  [ "$(trust_value "$out")" = true ]
}

# Call this through the app to diagnose the same process chain as its permission check.
cmd_permission_status() {
  local out rc value
  out=$("$WR_HOME/tools/axctl" trusted 2>&1); rc=$?
  value=$(trust_value "$out")
  printf 'Control payload: %s\nAccessibility helper: %s\nExit code: %s\nResult: %s\n' "$PAYLOAD" "$WR_HOME/tools/axctl" "$rc" "${out:-(no output)}"
  if [ "$rc" -eq 0 ] && [ "$value" = true ]; then
    echo "Permission is granted to the helper in this launch context."
  elif { [ "$rc" -eq 0 ] || [ "$rc" -eq 2 ]; } && [ "$value" = false ]; then
    echo "macOS reports that the helper lacks Accessibility permission in this launch context."
    echo "Quit the app, remove its old Accessibility entry, add /Applications/War Room Bot.app, enable it, then reopen it."
    echo "A check run from Terminal tests Terminal access, not access through the app."
  else
    echo "The helper check failed; this result does not establish whether Accessibility permission is granted."
  fi
}

# Registers this app in the Accessibility list (the system prompt) and opens that Settings pane.
cmd_accessibility() {
  need_installed
  "$WR_HOME/tools/axctl" prompt >/dev/null 2>&1
  open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility" 2>/dev/null || true
}

case "${1:-}" in
  state)         cmd_state ;;
  setup)         cmd_setup ;;
  setup-bg)      cmd_setup_bg ;;
  progress)      cmd_progress ;;
  log)           shift; cmd_log "$@" ;;
  error)         cmd_error ;;
  start)         launch start ;;
  dry)           launch dry ;;
  stop)          cmd_stop ;;
  status)        cmd_status ;;
  check)         cmd_check ;;
  recent)        cmd_recent ;;
  number)        cmd_number ;;
  has-number)    cmd_has_number ;;
  set-number)    shift; cmd_set_number "$@" ;;
  trusted)       need_installed; cmd_trusted && echo yes || { echo no; exit 1; } ;;
  permission-status) cmd_permission_status ;;
  accessibility) cmd_accessibility ;;
  open-data)     need_installed; open "$WR_HOME" ;;
  version)       echo "$(payload_version)" ;;
  *)             awk 'NR > 1 && /^#/ { print; next } NR > 1 { exit }' "$0"; exit 2 ;;
esac
