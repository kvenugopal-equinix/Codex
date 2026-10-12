#!/bin/bash
# One-time setup on a Mac:   ./install.sh [--no-tests]
# Creates .venv, installs the pinned dependencies (from the Equinix Nexus PyPI mirror only, hash-checked),
# builds the Accessibility helper tools/axctl, creates .env and a placeholder roster.xlsx, then runs the tests.
# Safe to run again: it never overwrites an existing .env, roster.xlsx or logs.
set -euo pipefail
cd "$(dirname "$0")"

INDEX="${WARROOM_PIP_INDEX:-https://nexus.equinix.com/repository/pypi-mirror/simple/}"
PYTHON="${WARROOM_PYTHON:-python3}"
RUN_TESTS=true
[ "${1:-}" = "--no-tests" ] && RUN_TESTS=false

say()  { printf '\n==> %s\n' "$*"; }
die()  { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

say "1/6 Checking this Mac"
[ "$(uname -s)" = "Darwin" ] || die "this runs on macOS only (it drives the Zoom app through Accessibility)"
command -v "$PYTHON" >/dev/null || die "$PYTHON not found. Install the Xcode command line tools ('xcode-select --install') or set WARROOM_PYTHON=/path/to/python3"
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
  || die "Python 3.9 or newer is needed (found $("$PYTHON" --version 2>&1))"
command -v swiftc >/dev/null || die "swiftc not found: run 'xcode-select --install', wait for it to finish, then run ./install.sh again"
echo "macOS $(sw_vers -productVersion), $("$PYTHON" --version 2>&1), $(swiftc --version 2>&1 | head -1)"

say "2/6 Creating the Python environment (.venv)"
[ -x .venv/bin/python ] || "$PYTHON" -m venv .venv
echo ".venv ready"

say "3/6 Installing dependencies from $INDEX"
# Only the Nexus mirror is used, and every file must match the hash pinned in requirements*.txt.
.venv/bin/python -m pip install --quiet --disable-pip-version-check --index-url "$INDEX" --require-hashes -r requirements-dev.txt \
  || die "could not install the dependencies. Are you on the Equinix network or VPN (so $INDEX is reachable)? Public registries are deliberately not used."
echo "installed: $(.venv/bin/python -m pip list --format=freeze 2>/dev/null | grep -i -E '^(openpyxl|et[-_]xmlfile|pytest)==' | tr '\n' ' ')"

say "4/6 Building the Accessibility helper (tools/axctl)"
tools/build_axctl.sh

say "5/6 Creating your private files (never overwritten)"
if [ -f .env ]; then echo ".env already exists; left alone"; else cp .env.example .env && echo "created .env from .env.example (dry run, no live calling, no test number yet)"; fi
.venv/bin/python tools/make_roster.py
mkdir -p logs

if $RUN_TESTS; then
  say "6/6 Running the tests"
  .venv/bin/python -m pytest -q || die "tests failed: do not use this install until they pass"
else
  say "6/6 Tests skipped (--no-tests)"
fi

cat <<'EOF'

Installed. What is left is manual, once:

  1. Accessibility permission. System Settings > Privacy & Security > Accessibility > switch ON the app you
     run the bot from (Terminal, iTerm, or the Claude app). Quit and reopen that app afterwards.
  2. Put your OWN phone number in .env:   WARROOM_TEST_NUMBER=+<country code><number>
     While WARROOM_TARGET_MODE=test (the default) this is the only number the bot can ever dial.
  3. Sign Zoom in as the bot account, join the bridge meeting and leave the meeting open on this Mac.
  4. Check it can see the meeting (read-only, places no call):   ./watch.sh check
  5. Rehearse without calling anyone:                            ./watch.sh dry
  6. Go live in test mode (calls ONLY your test number):         ./watch.sh start
     Stop it with Ctrl-C, or './watch.sh stop' from another window. './watch.sh status' says ON or OFF.

Read README.md first, then MAC_SETUP.md for the details.
EOF
