#!/bin/bash
# War Room Bot control script. The native app calls this for every action, and it works by hand too:
#
#   wrb.sh state            NOT_INSTALLED | SETTING_UP | UPDATE_AVAILABLE | READY
#   wrb.sh setup            copy the files to the install folder and run install.sh (idempotent; also "update/repair")
#   wrb.sh setup-bg         the same, detached (what the app uses; follow it with "progress")
#   wrb.sh progress         "N/6 what it is doing" while setup runs, then "DONE <exit code>"
#   wrb.sh log | error      the last lines of the setup log | why the last setup failed
#   wrb.sh start NUMBER | dry   start a test run with this explicit phone number | dry run
#   wrb.sh roster-preview | roster-dry | roster-start   show the current roster target | rehearse | start live roster calling
#   wrb.sh stop | status | check | recent
#   wrb.sh number | has-number | set-number N | clear-number
#   wrb.sh calling-options | set-calling-options phone|contacts-phone [TEST_CONTACT_NAME] | test-preview NUMBER
#   wrb.sh trusted | permission-status | accessibility | open-data | version
#
# WARROOM_HOME overrides the install folder (default ~/WarRoomBot). Tests set it to stay out of the real home.
# Exit codes: 0 ok; 10 developer tools requested; 11 Nexus unreachable; 13 watcher is running; 20 not set up;
# 21 another watcher is running; 22 no test number; 23 Accessibility not allowed; 24 watcher did not stay up;
# 25 watcher is still stopping; 26 no valid on-duty roster target; 27 runtime update required; 2 usage.
set -uo pipefail

SELF="$(cd "$(dirname "$0")" && pwd -P)"
PAYLOAD="$(cd "$SELF/.." && pwd -P)"          # the app's payload, or the install itself when run from there
WR_HOME="${WARROOM_HOME:-$HOME/WarRoomBot}"
INDEX="${WARROOM_PIP_INDEX:-https://nexus.equinix.com/repository/pypi-mirror/simple/}"
LOGS="$WR_HOME/logs"
AX_HELPER="${WARROOM_AXCTL:-$WR_HOME/tools/axctl}"

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
watcher_on() {
  local out
  out=$("$WR_HOME/watch.sh" status) || { echo "Could not check watcher status." >&2; return 2; }
  case "$out" in ON*) return 0 ;; *) return 1 ;; esac
}
same_dir() { [ -d "$1" ] && [ -d "$2" ] && [ "$1" -ef "$2" ]; }
# Replacing the app bundle does not replace the user's installed runtime. Stop
# and Status must remain usable while an update is pending.
runtime_update_needed() {
  ! same_dir "$PAYLOAD" "$WR_HOME" && [ "$(payload_version)" != "$(installed_version)" ]
}
need_current_runtime() {
  need_installed
  if runtime_update_needed; then
    echo "The app contains version $(payload_version), but the installed program files are version $(installed_version)."
    echo "Choose Stop if the watcher is running, then Update / Repair in War Room Bot. Wait for setup to finish and try again."
    echo "Your roster, settings and logs are preserved."
    exit 27
  fi
}
# Any warroom watcher on this Mac, started by this app or not (one Zoom per Mac, so two would fight).
other_watcher_pids() { pgrep -f 'warroom\.cli watch' | tr '\n' ' '; }

cmd_state() {
  if setup_running; then echo SETTING_UP
  elif ! installed; then echo NOT_INSTALLED
  elif runtime_update_needed; then echo UPDATE_AVAILABLE
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
  local watcher_state others
  if [ -x "$WR_HOME/watch.sh" ]; then
    watcher_on; watcher_state=$?
    [ "$watcher_state" -eq 2 ] && setup_fail 13 "could not check watcher status. Stop it in its Terminal window before updating."
    [ "$watcher_state" -eq 0 ] && setup_fail 13 "the watcher is running. Stop it first, then update."
  fi
  # Older releases can miss framework Python when matching the venv executable path.
  others=$(other_watcher_pids)
  [ -n "$others" ] && setup_fail 13 "a watcher is running (pid $others). Stop it first, then update."

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
  local status
  status=$("$WR_HOME/watch.sh" status) || return $?
  if [[ "$status" == ON* ]]; then
    local mode pid
    mode=$(cat "$(mode_file)" 2>/dev/null || echo unknown)
    pid=$(printf '%s\n' "$status" | sed -n 's/^ON (pid \([0-9][0-9]*\))$/\1/p')
    case "$mode" in
      live) echo "ON, live in test mode: a new visitor places a call to your test number." ;;
      dry)  echo "ON, dry run: nothing is dialled and nothing is played." ;;
      roster-live) echo "ON, live in roster mode: a new visitor places a call to the current on-duty engineer." ;;
      roster-dry) echo "ON, roster dry run: logs the selected on-duty engineer; nothing is dialled and nothing is played." ;;
      *)    echo "ON (started outside this app)." ;;
    esac
    # This is the saved configuration; a watcher launched elsewhere can override it.
    cmd_calling_summary "${mode%%-*}" || true
    [ -n "$pid" ] && echo "Running for $(ps -p "$pid" -o etime= 2>/dev/null | tr -d ' ')."
  else
    rm -f "$(mode_file)"
    echo "OFF"
    printf '%s\n' "$status" | sed 1d      # the note about a watcher this app did not start, if any
  fi
}

cmd_roster_preview() {
  need_current_runtime
  "$WR_HOME/watch.sh" roster-preview
}

launch() {          # $1 = start | dry | roster-start | roster-dry
  need_current_runtime
  local watcher_state
  watcher_on; watcher_state=$?
  [ "$watcher_state" -eq 2 ] && exit 1
  if [ "$watcher_state" -eq 0 ]; then echo "The watcher is already running."; exit 0; fi
  local others
  others=$(other_watcher_pids)
  if [ -n "$others" ]; then
    echo "Another watcher that this app did not start is running (pid $others). Stop it first (Ctrl-C in the window it runs in)."
    exit 21
  fi
  if [ "$1" = "roster-start" ]; then
    local preview
    preview=$(cmd_roster_preview 2>&1) || { printf '%s\n' "$preview"; exit 26; }
    printf '%s\n' "$preview"
  fi
  if ! cmd_trusted >/dev/null; then
    echo "Accessibility is not allowed for War Room Bot yet. Allow it in System Settings > Privacy & Security > Accessibility, then try again."
    exit 23
  fi
  mkdir -p "$LOGS"
  local log="$LOGS/watcher.log"
  [ "$(stat -f %z "$log" 2>/dev/null || echo 0)" -gt 5000000 ] && mv -f "$log" "$log.1"
  echo "---- $1 $(date '+%Y-%m-%d %H:%M:%S') ----" >> "$log"
  local watch_cmd
  case "$1" in
    start) watch_cmd=start; echo live > "$(mode_file)" ;;
    dry) watch_cmd=dry; echo dry > "$(mode_file)" ;;
    roster-start) watch_cmd=roster; echo roster-live > "$(mode_file)" ;;
    roster-dry) watch_cmd=roster-dry; echo roster-dry > "$(mode_file)" ;;
  esac
  # The native app keeps this Process as its child so macOS can attribute Accessibility to the app. Detaching
  # through nohup/disown can lose that attribution. Status and Stop still target the managed Python worker.
  if [ "${WARROOM_APP_FOREGROUND:-}" = 1 ]; then
    exec "$WR_HOME/watch.sh" "$watch_cmd" < /dev/null >> "$log" 2>&1
  fi
  # Job control gives the background job a normal SIGINT. Without it a non-interactive shell starts it with SIGINT
  # ignored, and Stop (which sends SIGINT) would do nothing.
  set -m
  nohup "$WR_HOME/watch.sh" "$watch_cmd" < /dev/null >> "$log" 2>&1 &
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
  local state
  watcher_on; state=$?
  [ "$state" -eq 2 ] && return 1
  if [ "$state" -eq 1 ]; then echo "The watcher is not running."; rm -f "$(mode_file)"; "$WR_HOME/watch.sh" status | sed 1d; return 0; fi
  "$WR_HOME/watch.sh" stop || return $?
  local i
  for i in $(seq 1 20); do
    watcher_on; state=$?
    [ "$state" -eq 2 ] && return 1
    [ "$state" -eq 1 ] && break
    sleep 1
  done
  if [ "$state" -eq 0 ]; then
    echo "The watcher is still stopping. Check Status again shortly. Details: $LOGS/watcher.log"
    return 25
  else
    rm -f "$(mode_file)"
    echo "OFF"
  fi
}

cmd_check() {
  need_current_runtime
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

use_test_number_for_run() {
  need_current_runtime
  [ $# -le 1 ] || { echo "Pass the test phone number as one argument."; return 2; }
  [ $# -eq 1 ] || { echo "Enter a test phone number for this run, using + and the country code."; return 22; }
  local number rc
  number=$(cd "$WR_HOME" && "$(py)" - "$1" <<'PY'
import sys
from tools.set_env import Refused, _number
try:
    number = _number(sys.argv[1])
    if not number:
        raise Refused("enter a number using + and the country code")
except Refused:
    print("Enter a valid test phone number for this run, using + followed by the country code and number.")
    raise SystemExit(22)
print(number)
PY
  ); rc=$?
  [ "$rc" -eq 0 ] || { printf '%s\n' "$number"; return "$rc"; }
  # This one controller process and its worker use the explicit input. Saved settings and inherited
  # numbers are never a fallback, and no .env file is written by preview or Start.
  export WARROOM_TEST_NUMBER="$number"
}

cmd_start() {
  use_test_number_for_run "$@" || return $?
  launch start
}

cmd_set_number() {
  need_installed
  [ $# -ge 1 ] || { echo "usage: wrb.sh set-number +<country code><number>"; exit 2; }
  [[ "$*" =~ [^[:space:]] ]] || { echo "Enter a number using + and the country code. To remove a saved number, choose Clear saved number."; exit 2; }
  "$(py)" "$WR_HOME/tools/set_env.py" --env "$WR_HOME/.env" WARROOM_TEST_NUMBER "$*"
}

cmd_clear_number() {
  need_current_runtime
  local watcher_state
  watcher_on; watcher_state=$?
  [ "$watcher_state" -eq 2 ] && exit 1
  if [ "$watcher_state" -eq 0 ]; then
    echo "Stop the watcher before clearing its saved test number. A running watcher keeps the number it started with."
    exit 13
  fi
  "$(py)" "$WR_HOME/tools/set_env.py" --env "$WR_HOME/.env" WARROOM_TEST_NUMBER "" || return $?
  echo "Saved test number cleared. Enter your own number before starting another test run."
}

cmd_calling_options() {
  need_current_runtime
  ( cd "$WR_HOME" && "$(py)" - <<'PY'
import json
from warroom.config import Settings
s = Settings.from_env()
print(json.dumps({"zoom_invite": s.zoom_invite, "zoom_contact_lookup": s.zoom_contact_lookup,
                  "test_zoom_contact": s.test_zoom_contact}))
PY
  )
}

cmd_calling_summary() {
  ( cd "$WR_HOME" && "$(py)" - "$1" <<'PY'
import sys
from warroom.config import Settings
s = Settings.from_env()
lookup = getattr(s, "zoom_contact_lookup", "email")
if not s.zoom_invite:
    route = "Phone only."
elif lookup == "name":
    if sys.argv[1] == "roster":
        route = "Zoom Contacts by the selected engineer's roster name, plus their phone."
    elif getattr(s, "test_zoom_contact", ""):
        route = "Zoom Contacts by the saved test contact name, plus your test phone."
    else:
        route = "Phone only in test mode; no test Zoom contact name is saved."
else:
    route = "Zoom Contacts using the legacy account-email lookup, plus phone. Use Calling options to select contact-name lookup."
print("Configured calling: " + route)
PY
  )
}

cmd_test_preview() {
  use_test_number_for_run "$@" || return $?
  ( cd "$WR_HOME" && "$(py)" - <<'PY'
from warroom.config import E164, Settings
s = Settings.from_env()
if not E164.fullmatch(s.test_number):
    print("Enter a valid test phone number for this run.")
    raise SystemExit(22)
print("Test phone for this run: " + s.test_number)
if s.zoom_invite and s.zoom_contact_lookup == "name" and s.test_zoom_contact:
    print("Also invite through Zoom's Contacts tab: " + s.test_zoom_contact)
elif s.zoom_invite and s.zoom_contact_lookup == "email" and s.test_zoom_email:
    print("Also invite through Zoom Contacts using the legacy account-email lookup: " + s.test_zoom_email)
elif s.zoom_invite:
    print("Phone only: no test Zoom contact is configured. Set a test contact name in Calling options to use both.")
else:
    print("Phone only. Choose Zoom Contacts + phone in Calling options to use both.")
print("No call or invitation has been placed.")
PY
  )
}

cmd_set_calling_options() {
  need_current_runtime
  [ $# -ge 1 ] && [ $# -le 2 ] || { echo "usage: wrb.sh set-calling-options phone|contacts-phone [TEST_CONTACT_NAME]"; return 2; }
  case "$1" in phone|contacts-phone) ;; *) echo "Choose phone or contacts-phone."; return 2 ;; esac
  local status others rc
  status=$("$WR_HOME/watch.sh" status) || { echo "Could not check watcher status. Calling options were not changed."; return 1; }
  case "$status" in
    ON*) echo "Stop the watcher before changing calling options. A running watcher keeps the options it started with."; return 13 ;;
    OFF*) ;;
    *) echo "Watcher status is unknown. Calling options were not changed."; return 1 ;;
  esac
  others=$(pgrep -f 'warroom\.cli watch'); rc=$?
  if [ "$rc" -ne 0 ] && [ "$rc" -ne 1 ]; then
    echo "Could not check for other watchers. Calling options were not changed."; return 1
  fi
  if [ -n "$others" ]; then
    echo "Another watcher is running. Stop it before changing calling options."; return 21
  fi
  ( cd "$WR_HOME" && "$(py)" - "$1" "${2:-}" <<'PY'
from pathlib import Path
import sys
from tools.set_env import Refused, set_values
try:
    set_values(Path('.env'), {"WARROOM_ZOOM_INVITE": "true" if sys.argv[1] == "contacts-phone" else "false",
                             "WARROOM_ZOOM_CONTACT_LOOKUP": "name", "WARROOM_TEST_ZOOM_CONTACT": sys.argv[2]})
except Refused as error:
    print("REFUSED: " + str(error))
    raise SystemExit(2)
if sys.argv[1] == "contacts-phone":
    print("Calling options saved: Zoom Contacts + phone. Roster mode uses the selected engineer's name for Zoom Contacts.")
    print("Test mode uses only the saved test contact name and the phone entered for each run; a blank test contact means phone-only tests.")
else:
    print("Calling options saved: Phone only. Zoom Contacts invitations are disabled.")
print("No watcher was started and no call or invitation was placed.")
PY
  )
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

ax_helper_ready() {
  if [[ "$AX_HELPER" != /* ]]; then
    echo "Accessibility helper path must be absolute: $AX_HELPER" >&2
    return 1
  fi
  if [ ! -f "$AX_HELPER" ] || [ ! -x "$AX_HELPER" ]; then
    echo "Accessibility helper is missing or not executable: $AX_HELPER" >&2
    return 1
  fi
}

cmd_trusted() {
  local out
  ax_helper_ready || return 1
  out=$("$AX_HELPER" trusted 2>/dev/null) || return 1
  [ "$(trust_value "$out")" = true ]
}

# Call this through the app to diagnose the same process chain as its permission check.
cmd_permission_status() {
  local out rc value
  out=$(ax_helper_ready 2>&1); rc=$?
  if [ "$rc" -eq 0 ]; then out=$("$AX_HELPER" trusted 2>&1); rc=$?; fi
  value=$(trust_value "$out")
  printf 'Control payload: %s\nAccessibility helper: %s\nExit code: %s\nResult: %s\n' "$PAYLOAD" "$AX_HELPER" "$rc" "${out:-(no output)}"
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

# Open Settings once. The native app owns the permission request; asking through the helper as well produces
# two requests belonging to different launch contexts.
cmd_accessibility() {
  need_installed
  ax_helper_ready || return 1
  open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility" 2>/dev/null || true
  echo "Enable War Room Bot in Accessibility, then return to the app and check permission again."
}

case "${1:-}" in
  state)         cmd_state ;;
  setup)         cmd_setup ;;
  setup-bg)      cmd_setup_bg ;;
  progress)      cmd_progress ;;
  log)           shift; cmd_log "$@" ;;
  error)         cmd_error ;;
  start)         shift; cmd_start "$@" ;;
  dry)           launch dry ;;
  roster-preview) cmd_roster_preview ;;
  roster-dry)    launch roster-dry ;;
  roster-start)  launch roster-start ;;
  stop)          cmd_stop ;;
  status)        cmd_status ;;
  check)         cmd_check ;;
  recent)        cmd_recent ;;
  number)        cmd_number ;;
  has-number)    cmd_has_number ;;
  set-number)    shift; cmd_set_number "$@" ;;
  clear-number)  cmd_clear_number ;;
  calling-options) cmd_calling_options ;;
  set-calling-options) shift; cmd_set_calling_options "$@" ;;
  test-preview)  shift; cmd_test_preview "$@" ;;
  trusted)       need_installed; cmd_trusted && echo yes || { echo no; exit 1; } ;;
  permission-status) cmd_permission_status ;;
  accessibility) cmd_accessibility ;;
  open-data)     need_installed; open "$WR_HOME" ;;
  version)       echo "$(payload_version)" ;;
  *)             awk 'NR > 1 && /^#/ { print; next } NR > 1 { exit }' "$0"; exit 2 ;;
esac
