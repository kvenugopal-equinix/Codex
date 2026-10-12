"""Exercise a built app's real window and event loop without starting the bot."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile


def require_report(report):
    if (not isinstance(report, dict) or report.get("ok") is not True
            or report.get("window_visible") is not True
            or report.get("installation_checked") is not True):
        raise RuntimeError("The app did not confirm a visible window and completed startup check.")


def stop_launchservices_check(executable, report_path):
    """Stop only the isolated UI test bearing this unique report argument."""
    result = subprocess.run(["/bin/ps", "-ww", "-axo", "pid=,args="],
                            capture_output=True, text=True, timeout=5)
    if result.returncode != 0:
        return
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) != 2:
            continue
        pid, command = fields
        if (command.startswith(str(executable) + " --ui-smoke-test ")
                and "--ui-smoke-report " + str(report_path) + " --ui-smoke-home " in command):
            try:
                os.kill(int(pid), signal.SIGTERM)
            except ProcessLookupError:
                pass


def check_app(app):
    app = Path(app).resolve()
    executable = app / "Contents" / "MacOS" / "WarRoomBot"
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
        require_report(report)
        # Finder launches through LaunchServices rather than directly executing
        # the binary. Check that route separately with an isolated data directory.
        report_path = Path(scratch) / "launchservices-report.json"
        arguments = ["/usr/bin/open", "-n", "-W", "-a", str(app), "--args",
                     "--ui-smoke-test", "--ui-smoke-report", str(report_path),
                     "--ui-smoke-home", str(Path(scratch) / "launchservices-data")]
        try:
            launched = subprocess.run(arguments, stdin=subprocess.DEVNULL,
                                      capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            stop_launchservices_check(executable, report_path)
            raise RuntimeError("LaunchServices did not finish the UI check within 30 seconds.") from None
        if launched.returncode != 0:
            raise RuntimeError("LaunchServices could not open the UI check: " + launched.stderr.strip())
        try:
            launch_report = json.loads(report_path.read_text())
        except (OSError, ValueError):
            raise RuntimeError("LaunchServices did not produce a valid UI check report.") from None
        print("WRB_LAUNCHSERVICES_UI_SMOKE " + json.dumps(launch_report, sort_keys=True))
        require_report(launch_report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    arguments = parser.parse_args()
    try:
        check_app(arguments.app)
    except (OSError, RuntimeError) as error:
        print("UI CHECK: " + str(error), file=sys.stderr)
        sys.exit(1)
