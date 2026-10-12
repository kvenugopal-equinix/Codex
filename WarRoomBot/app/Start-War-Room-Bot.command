#!/bin/bash
# Open the installed app through Terminal, using Terminal's authorized launch context.
# Does not start the watcher or change settings. Optional argument: a different app path.
set -euo pipefail
WRB_APP_PATH="${1:-/Applications/War Room Bot.app}"
if [ ! -d "$WRB_APP_PATH" ]; then
  printf 'War Room Bot was not found at %s. Install it in Applications first.\n' "$WRB_APP_PATH" >&2
  exit 1
fi
WRB_APP_BIN=$(python3 - "$WRB_APP_PATH/Contents/Info.plist" <<'PY'
import plistlib
import sys
from pathlib import Path
try:
    with open(sys.argv[1], 'rb') as f:
        name = plistlib.load(f).get('CFBundleExecutable')
    if not isinstance(name, str) or not name or name in ('.', '..') or '/' in name or '\0' in name:
        raise ValueError('invalid CFBundleExecutable')
except (OSError, ValueError, plistlib.InvalidFileException) as e:
    print(f'Cannot read the app executable: {e}', file=sys.stderr)
    sys.exit(1)
print(name)
PY
)
WRB_APP_EXE="$WRB_APP_PATH/Contents/MacOS/$WRB_APP_BIN"
if [ ! -x "$WRB_APP_EXE" ]; then
  printf 'The app executable is missing or not executable: %s\n' "$WRB_APP_EXE" >&2
  exit 1
fi
printf 'Opening %s through Terminal.\nKeep this Terminal window open while using the app.\n' "$WRB_APP_PATH"
exec "$WRB_APP_EXE"
