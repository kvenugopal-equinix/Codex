"""Exercise a built app's real window and event loop without starting the bot."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def check_app(app):
    executable = Path(app).resolve() / "Contents" / "MacOS" / "WarRoomBot"
    if not executable.is_file():
        raise RuntimeError("Native app executable is missing: " + str(executable))
    with tempfile.TemporaryDirectory(prefix="war-room-bot-ui-check-") as scratch:
        environment = os.environ.copy()
        environment["WARROOM_HOME"] = str(Path(scratch) / "data")
        try:
            result = subprocess.run(
                [str(executable), "--ui-smoke-test"],
                env=environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, timeout=30,
            )
        except subprocess.TimeoutExpired as error:
            output = error.stdout or b""
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="replace")
            print(output, end="" if output.endswith("\n") else "\n")
            raise RuntimeError("The app window/event-loop check exceeded 30 seconds.") from None
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        reports = [line[len("WRB_UI_SMOKE "):] for line in result.stdout.splitlines()
                   if line.startswith("WRB_UI_SMOKE ")]
        if result.returncode != 0 or not reports:
            raise RuntimeError("The app window/event-loop check failed (exit {}).".format(result.returncode))
        try:
            report = json.loads(reports[-1])
        except ValueError:
            raise RuntimeError("The app window/event-loop check returned invalid JSON.") from None
        if (not isinstance(report, dict) or report.get("ok") is not True
                or report.get("window_visible") is not True
                or report.get("installation_checked") is not True):
            raise RuntimeError("The app did not confirm a visible window and completed startup check.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    arguments = parser.parse_args()
    try:
        check_app(arguments.app)
    except (OSError, RuntimeError) as error:
        print("UI CHECK: " + str(error), file=sys.stderr)
        sys.exit(1)
