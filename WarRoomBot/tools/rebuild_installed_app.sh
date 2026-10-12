#!/bin/bash
# Rebuild the installed native app's source in a private temporary folder.
# Nothing is installed automatically; the resulting DMG is opened in Finder.
set -euo pipefail

REBUILD_APP="/Applications/War Room Bot.app"
REBUILD_OPEN=1
REBUILD_APP_SET=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --no-open) REBUILD_OPEN=0; shift ;;
    --app)
      [ "$#" -ge 2 ] && [ "$REBUILD_APP_SET" -eq 0 ] || { echo "--app requires one app path." >&2; exit 2; }
      REBUILD_APP="$2"; REBUILD_APP_SET=1; shift 2 ;;
    --help|-h)
      echo "Usage: bash rebuild_installed_app.sh [--no-open] [--app path/to/War Room Bot.app]"
      exit 0 ;;
    -*) echo "Unknown option: $1" >&2; exit 2 ;;
    *)
      [ "$REBUILD_APP_SET" -eq 0 ] || { echo "Choose one app path." >&2; exit 2; }
      REBUILD_APP="$1"; REBUILD_APP_SET=1; shift ;;
  esac
done
[ "$(uname -s)" = "Darwin" ] || { echo "Run this local rebuild on macOS." >&2; exit 1; }
command -v python3 >/dev/null || { echo "Python 3.9 or newer is required for the local rebuild." >&2; exit 1; }
python3 - "$REBUILD_APP" "$REBUILD_OPEN" <<'PY'
import math
import os
from pathlib import Path
import plistlib
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time


if sys.version_info < (3, 9):
    print("Python 3.9 or newer is required for the local rebuild.", file=sys.stderr)
    sys.exit(1)


def say(message):
    print(message, flush=True)


def show_failure_log(path):
    if path is None:
        return
    say("Build log: " + str(path))
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            length = stream.tell()
            stream.seek(max(0, length - 16384))
            lines = stream.read().decode("utf-8", errors="replace").splitlines()[-35:]
        if lines:
            say("Recent build output:")
            for line in lines:
                say(line)
    except OSError:
        pass


def stop_build_group(process):
    """Stop only the fresh session started for this copy/build operation."""
    if process is None or process.poll() is not None:
        return
    group = process.pid  # start_new_session=True makes this PID the session/group ID.
    try:
        if os.getpgid(process.pid) != group:
            raise RuntimeError("The rebuild process no longer has its expected process group.")
        os.killpg(group, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        process.poll()  # Reap the leader while its compiler/smoke descendants exit.
        try:
            os.killpg(group, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    try:
        os.killpg(group, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        pass


def main():
    log_path = None
    operation = None
    try:
        app = Path(sys.argv[1]).expanduser().resolve(strict=True)
        if not app.is_dir() or app.name != "War Room Bot.app":
            raise ValueError("Choose the installed War Room Bot.app bundle.")
        with (app / "Contents/Info.plist").open("rb") as stream:
            metadata = plistlib.load(stream)
        name = metadata.get("CFBundleDisplayName", metadata.get("CFBundleName"))
        identifier = metadata.get("CFBundleIdentifier")
        if name != "War Room Bot" or metadata.get("CFBundleExecutable") != "WarRoomBot":
            raise ValueError("This rebuild requires the native War Room Bot app.")
        if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{2,254}", identifier):
            raise ValueError("The installed app has no valid bundle identifier to preserve.")
        payload = app / "Contents/Resources/payload"
        for source in ("app/WarRoomBot.swift", "tools/axctl.swift", "tools/build_app.sh", "tools/package.py", "VERSION"):
            if not (payload / source).is_file():
                raise ValueError("The installed source payload is missing " + source + ".")
        version = (payload / "VERSION").read_text(encoding="utf-8").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", version):
            raise ValueError("The installed payload has an invalid version.")
        if metadata.get("CFBundleShortVersionString") != version:
            raise ValueError("The installed app and its source payload have different versions.")
        utilities = ["ditto", "xcrun", "codesign", "hdiutil"] + (["open"] if sys.argv[2] == "1" else [])
        for utility in utilities:
            if shutil.which(utility) is None:
                raise ValueError("Required macOS build utility is unavailable: " + utility + ".")
        timeout = float(os.environ.get("WARROOM_REBUILD_TIMEOUT", "300"))
        if not math.isfinite(timeout) or not 1 <= timeout <= 1800:
            raise ValueError("WARROOM_REBUILD_TIMEOUT must be between 1 and 1800 seconds.")

        working = Path(tempfile.mkdtemp(prefix="WarRoomBot-local-build-"))
        copied = working / "source"
        destination = working / "dist"
        destination.mkdir(mode=0o700)
        log_path = working / "build.log"
        log_fd = os.open(str(log_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.fchmod(log_fd, 0o600)
        say("War Room Bot " + version + " — local rebuild")
        say("Installed app: " + str(app))
        say("Bundle identifier: " + identifier)
        say("Build folder: " + str(working))
        say("Build log: " + str(log_path))
        with os.fdopen(log_fd, "wb") as log:
            log.write(("Local rebuild of War Room Bot " + version + "\n").encode("utf-8"))
            log.flush()
            say("1/2 Copying the bundled source to the temporary build folder…")
            operation = subprocess.Popen(
                ["ditto", "--noextattr", "--noqtn", str(payload), str(copied)],
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                copy_code = operation.wait(timeout=60)
            except subprocess.TimeoutExpired:
                stop_build_group(operation)
                operation = None
                raise RuntimeError("Copying the source exceeded its 60-second deadline.") from None
            if copy_code:
                raise RuntimeError("Copying the bundled source failed (exit {}).".format(copy_code))
            operation = None

            say("2/2 Compiling and checking the local app (deadline: {:g} seconds)…".format(timeout))
            environment = dict(os.environ)
            environment["WARROOM_EXISTING_APP"] = str(app)
            environment["WARROOM_BUNDLE_ID"] = identifier
            # The build script compiles both binaries from the copied source. Its
            # own smoke test is covered by this deadline if a new binary stalls.
            operation = subprocess.Popen(
                ["/bin/bash", str(copied / "tools/build_app.sh"), str(destination)],
                cwd=str(copied), env=environment, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            )
            try:
                build_code = operation.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                stop_build_group(operation)
                operation = None
                raise RuntimeError("The local build exceeded its {:g}-second deadline.".format(timeout)) from None
            if build_code:
                raise RuntimeError("The local build failed (exit {}).".format(build_code))
            operation = None

        dmg = destination / ("War-Room-Bot-" + version + ".dmg")
        if not dmg.is_file() or dmg.stat().st_size == 0:
            raise RuntimeError("The build finished without the expected DMG.")
        say("Built: " + str(dmg))
        say("To install: quit War Room Bot, then drag its rebuilt copy from the DMG into Applications and choose Replace.")
        say("The build folder is kept so you can copy the DMG before closing Terminal.")
        if sys.argv[2] == "1":
            say("Opening the DMG…")
            try:
                subprocess.run(["open", str(dmg)], check=True, timeout=15,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (OSError, subprocess.SubprocessError):
                say("Finder could not open it automatically. Open the DMG at the path above.")
        return 0
    except KeyboardInterrupt:
        stop_build_group(operation)
        say("\nLocal rebuild cancelled.")
        show_failure_log(log_path)
        return 130
    except (OSError, ValueError, RuntimeError, plistlib.InvalidFileException) as error:
        stop_build_group(operation)
        print("Local rebuild failed: " + str(error), file=sys.stderr, flush=True)
        show_failure_log(log_path)
        return 1


sys.exit(main())
PY
