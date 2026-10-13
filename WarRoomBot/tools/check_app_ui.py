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
    forms = report.get("start_forms")
    if not isinstance(forms, dict):
        raise RuntimeError("The app did not inspect its native Start forms.")
    if (forms.get("test_has_phone") is not True or forms.get("test_has_contact") is not True
            or forms.get("test_phone") != "" or forms.get("next_test_phone") != ""):
        raise RuntimeError("The native test Start form did not provide a fresh blank phone field.")
    choices = ["Phone only", "Zoom Contacts + phone"]
    if forms.get("test_routes") != choices or forms.get("roster_routes") != choices:
        raise RuntimeError("The native Start forms did not offer both calling routes.")
    if (forms.get("phone_route_contact_enabled") is not False
            or forms.get("contacts_route_contact_enabled") is not True
            or forms.get("roster_has_phone") is not False
            or forms.get("roster_has_test_contact") is not False):
        raise RuntimeError("The native Start forms did not separate test contact entry from roster calling.")
    if (forms.get("phone_route_options") != ["--calling", "phone"]
            or forms.get("contacts_route_options") != ["--calling", "contacts-phone",
                                                       "--test-contact", "Fixture Contact"]
            or forms.get("roster_route_options") != ["--calling", "contacts-phone"]):
        raise RuntimeError("The native Start form did not pass its selected calling route correctly.")
    if (forms.get("cancel_response") != "cancel"
            or forms.get("cancel_has_selection") is not False
            or forms.get("cancel_started_worker") is not False):
        raise RuntimeError("Cancelling the native Start form did not leave the worker stopped.")


def require_isolated_report(report, executable, home):
    require_report(report)
    if report.get("native_executable") != str(executable) or report.get("home") != str(home):
        raise RuntimeError("The UI check did not run the selected app with its isolated data folder.")
    if home.exists() and any(home.iterdir()):
        raise RuntimeError("The read-only UI check wrote files into its isolated data folder.")


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
        scratch = Path(scratch).resolve()
        environment = os.environ.copy()
        home = scratch / "data"
        environment["WARROOM_HOME"] = str(home)
        try:
            result = subprocess.run(
                [str(executable), "--ui-smoke-test", "--ui-smoke-home", str(home)],
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
        require_isolated_report(report, executable, home)
        # Finder launches through LaunchServices rather than directly executing
        # the binary. Check that route separately with an isolated data directory.
        report_path = scratch / "launchservices-report.json"
        launch_home = scratch / "launchservices-data"
        arguments = ["/usr/bin/open", "-n", "-W", "-a", str(app), "--args",
                     "--ui-smoke-test", "--ui-smoke-report", str(report_path),
                     "--ui-smoke-home", str(launch_home)]
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
        require_isolated_report(launch_report, executable, launch_home)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    arguments = parser.parse_args()
    try:
        check_app(arguments.app)
    except (OSError, RuntimeError) as error:
        print("UI CHECK: " + str(error), file=sys.stderr)
        sys.exit(1)
