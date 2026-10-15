#!/usr/bin/env python3
"""Choose a Finder location, then let War Room Bot create its activity workbook.

Run with the installed runtime Python::

    ~/WarRoomBot/.venv/bin/python ~/WarRoomBot/tools/choose_activity_log.py

AppleScript's ``choose file name`` returns a destination without creating a file.
This is useful for an existing native app whose window cannot gain a new button
through a Python-only runtime update.
"""

import os
from pathlib import Path
import subprocess
import sys
from typing import Optional

# The file is run by its absolute path from Terminal, where the current folder
# is usually not the installed runtime. Make that runtime importable.
HOME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOME))

from tools.set_env import Refused, set_value, validate_activity_workbook
from warroom.activity_report import publish_workbook
from warroom.config import Settings


_CANCELLED = "__WARROOM_ACTIVITY_CANCELLED__"
_CHOOSE_SCRIPT = '''
try
    set chosenFile to choose file name with prompt "Choose an activity workbook location (OneDrive in Finder is supported)" default name "War Room Activity.xlsx"
    return POSIX path of chosenFile
on error number -128
    return "__WARROOM_ACTIVITY_CANCELLED__"
end try
'''


def choose_path() -> Optional[str]:
    """Show the macOS save dialog; leave file creation to publish_workbook."""
    result = subprocess.run(["/usr/bin/osascript", "-e", _CHOOSE_SCRIPT],
                            capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError("Finder could not choose a location: " +
                           (result.stderr.strip() or f"osascript exited {result.returncode}"))
    chosen = result.stdout.rstrip("\n")
    if chosen == _CANCELLED:
        return None
    if not chosen:
        raise RuntimeError("Finder returned no location")
    return chosen


def ensure_idle(home: Path) -> None:
    """Refuse to change the destination while setup or any watcher is active."""
    setup_pid = home / "logs" / "setup.pid"
    if setup_pid.exists():
        pid = setup_pid.read_text(encoding="utf-8").strip()
        if pid.isdecimal():
            process = subprocess.run(["/bin/ps", "-p", pid, "-o", "command="],
                                     capture_output=True, text=True, check=False)
            if process.returncode == 0 and "wrb.sh" in process.stdout:
                raise RuntimeError("Wait for setup to finish before changing the activity log location")

    status = subprocess.run([str(home / "watch.sh"), "status"], cwd=home,
                            capture_output=True, text=True, check=False)
    if status.returncode:
        raise RuntimeError("Could not check watcher status; activity log location was not changed: " +
                           (status.stderr.strip() or status.stdout.strip()))
    if status.stdout.startswith("ON"):
        raise RuntimeError("Stop the watcher before changing the activity log location")
    if not status.stdout.startswith("OFF"):
        raise RuntimeError("Watcher status is unknown; activity log location was not changed")

    others = subprocess.run(["/usr/bin/pgrep", "-f", r"warroom\.cli watch"],
                            capture_output=True, text=True, check=False)
    if others.returncode == 0:
        raise RuntimeError("Another watcher is running; stop it before changing the activity log location")
    if others.returncode not in (0, 1):
        raise RuntimeError("Could not check for other watchers; activity log location was not changed")


def save_location(home: Path, chosen: str) -> str:
    """Create/backfill first, then save the path; never replace an unrelated workbook."""
    if "WARROOM_ACTIVITY_WORKBOOK" in os.environ:
        raise Refused("WARROOM_ACTIVITY_WORKBOOK in this Terminal's environment overrides the saved location; "
                      "remove that override before choosing a log file")
    destination = validate_activity_workbook(chosen)
    if not (home / ".env").is_file():
        raise RuntimeError("War Room Bot is not set up in " + str(home))
    ensure_idle(home)

    # A valid new choice must be able to repair a malformed path hand-edited into
    # .env. The temporary override exists only while we resolve the local CSV.
    os.environ["WARROOM_ACTIVITY_WORKBOOK"] = destination
    try:
        local_log = Settings.from_env().join_log_path
    finally:
        del os.environ["WARROOM_ACTIVITY_WORKBOOK"]

    publish_workbook(local_log, Path(destination))
    try:
        set_value(home / ".env", "WARROOM_ACTIVITY_WORKBOOK", destination)
    except (Refused, OSError) as error:
        raise RuntimeError("The workbook was created, but its location could not be saved: " + str(error)) from error
    return destination


def main() -> int:
    if sys.platform != "darwin":
        print("This Finder chooser runs on macOS only.", file=sys.stderr)
        return 2
    try:
        chosen = choose_path()
        if chosen is None:
            print("Canceled; activity log location was not changed.")
            return 0
        destination = save_location(HOME, chosen)
    except Exception as error:
        print("Activity log location was not changed: " + str(error), file=sys.stderr)
        return 1
    print("Activity workbook ready; location saved: " + destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
