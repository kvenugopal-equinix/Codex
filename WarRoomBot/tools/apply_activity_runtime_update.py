#!/usr/bin/env python3
"""Add the activity workbook runtime to an installed 20261013.3 Mac app.

Run this from an extracted 20261015.1 source ZIP with a published source ZIP
and its SHA-256 digest. The native app and installed VERSION remain untouched.
The old native window has no Choose log file button; --choose-workbook opens a
separate Mac file dialog after the Python update succeeds.
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

import apply_runtime_update as base


SOURCE_VERSION = "20261015.1"
PATCH = "activity-workbook-20261015.1"

# Exact bytes from the published 20261013.3 and 20261013.4 source ZIPs.
# The latter is the selected-engineer presence patch. Updating cli.py and
# watcher.py to the new source preserves that behavior even if the earlier
# patch was never applied. None allows only a file that did not exist before.
ALLOWED_HASHES = {
    "warroom/cli.py": (
        "302880d8703b56fbb61d686b9167d931e2a541eb6ffdc1bf18a2dd13fe26a120",
        "2bfe1e3b090c3385b7d14bda41c3fffed7bd961df2ecc67378d0ab3439684e6d",
    ),
    "warroom/watcher.py": (
        "bc5f57888c2f692b07c6a56bd4a8f6edfa86c8d89190cb203e111406532a879f",
        "934f89c2b2b8682b049ba9f2359181f2f8b66360454acc8d8c72ea4df67335bd",
    ),
    "warroom/config.py": "f06ed3399bb2a5050b0c44112b665ca43ac95e9b02cdfab608e251e29a313514",
    "warroom/joinlog.py": "d1786fb0b8e207be9780818abdab35cd6c688d0757fc72654fe93495035c205a",
    "warroom/activity_report.py": None,
    "tools/set_env.py": "af9466c0ab918da94a349fd517c93e2b2d4de4838eb7b77087a310933a5b4fa3",
    "tools/choose_activity_log.py": None,
    # These existing tests cover the selected-engineer and settings changes.
    # New activity test modules stay in staging: the old app's Repair merges
    # its 13.3 payload and would not remove newly named test files.
    "tests/test_participant_discovery.py": (
        "534c21c4ed3a142cc8ab143a4a26ee9cc426d2ef1956579a1b57ecf0d8ccfab3",
        "e35a684b66c9e46dcb22c2d67d9798387695c7edabceb1bf901351a2155fc5c7",
    ),
    "tests/test_watcher.py": (
        "633f3f020b8538b628d404d85e0a08549888d3e64807b60ca08068993ea8549b",
        "6942910ae4953a22d51b4e05d09f0d4efab146d9a8027130c33768e923dd4258",
    ),
    "tests/test_set_env.py": "d46e04595598dccd805ac751348de80f002820fb3ec4315621842a8ca40b9c49",
    "tests/test_zoom_invite.py": "8cdf98cce0b50636eded76df880f94d2147417b4a6eb32bf49d89478b725637f",
}


def apply(home, app, expected_digest, *, archive=None, archive_url=None, choose_workbook=False):
    home, app = Path(home).expanduser().absolute(), Path(app).expanduser().absolute()
    print("1/6 Checking the installed version and that War Room Bot is stopped...", flush=True)
    python = base.check_installation(home, app)
    base.ensure_idle()
    with tempfile.TemporaryDirectory(prefix="WarRoomBot-activity-update-") as temporary:
        container = Path(temporary)
        downloaded = container / "source.zip"
        print("2/6 Acquiring the source archive and checking SHA-256 (60-second limit)...", flush=True)
        base.acquire_archive(downloaded, expected_digest, archive=archive, archive_url=archive_url)
        print("3/6 Validating the archive and installed files...", flush=True)
        source = base.extract_archive(downloaded, container / "source", source_version=SOURCE_VERSION)
        changes = base.plan_changes(home, source, ALLOWED_HASHES)
        print("4/6 Running isolated tests (up to " + str(base.TEST_TIMEOUT_SECONDS)
              + " seconds; progress every " + str(base.TEST_PROGRESS_SECONDS)
              + " seconds). Installed files are unchanged so far.", flush=True)
        base.preflight(source, python, container)
        print("5/6 Rechecking the installation before applying the patch...", flush=True)
        base.ensure_idle()
        base.check_installation(home, app)
        if base.plan_changes(home, source, ALLOWED_HASHES) != changes:
            raise base.UpdateError("Installed files changed during preflight; no runtime update was applied.")
        if changes:
            print("6/6 Backing up and applying the runtime patch...", flush=True)
            backup = base.install_changes(home, changes, expected_digest, patch=PATCH)
            print("Applied runtime patch " + PATCH + ".", flush=True)
            print("Replaced files: " + ", ".join(changes), flush=True)
            print("Original files and receipt: " + str(backup), flush=True)
        else:
            backup = None
            print("6/6 Verified the existing runtime patch.", flush=True)
            print("Runtime patch " + PATCH + " is already applied; all target bytes match.", flush=True)
    print("Installed VERSION remains " + base.BASE_VERSION
          + "; the app bundle and signed helper were not modified.", flush=True)
    print("The old app's Update / Repair restores its bundled runtime. Reapply this patch afterward.", flush=True)
    if choose_workbook:
        print("Opening a Mac dialog to choose the activity workbook location...", flush=True)
        chooser = base.regular_file(home, "tools/choose_activity_log.py")
        try:
            result = subprocess.run([str(python), str(chooser)], check=False)
        except KeyboardInterrupt:
            raise base.UpdateError("The runtime patch is applied, but workbook selection was interrupted. "
                                   "Run " + str(python) + " " + str(chooser) + " to try again.") from None
        if result.returncode:
            raise base.UpdateError("The runtime patch is applied, but workbook selection did not finish "
                                   "(exit " + str(result.returncode) + "). Run " + str(python)
                                   + " " + str(chooser) + " to try again.")
    else:
        print("To choose a OneDrive or other Finder location, run: " + str(python) + " "
              + str(home / "tools/choose_activity_log.py"), flush=True)
    return backup


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--archive", type=Path, help="local published 20261015.1 source ZIP")
    source.add_argument("--archive-url", help="HTTPS raw GitHub URL of the published source ZIP")
    parser.add_argument("--sha256", required=True, help="published SHA-256 digest of the source ZIP")
    parser.add_argument("--home", type=Path, default=Path.home() / "WarRoomBot")
    parser.add_argument("--app", type=Path, default=Path("/Applications") / base.NAME)
    parser.add_argument("--choose-workbook", action="store_true",
                        help="after updating, show the Mac path picker and have the bot create the workbook")
    arguments = parser.parse_args(argv)
    try:
        if sys.platform != "darwin" or sys.version_info < (3, 9):
            raise base.UpdateError("Run this runtime patch on your Mac with Python 3.9 or newer.")
        apply(arguments.home, arguments.app, arguments.sha256,
              archive=arguments.archive, archive_url=arguments.archive_url,
              choose_workbook=arguments.choose_workbook)
        return 0
    except KeyboardInterrupt:
        print("Runtime update cancelled.", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
        print("RUNTIME UPDATE: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
