"""Native form smoke reports are required on both launch routes; no native app is run here."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "check_app_ui.py"
SPEC = importlib.util.spec_from_file_location("check_app_ui", SCRIPT)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def report():
    return {"ok": True, "window_visible": True, "installation_checked": True,
            "start_forms": {
                "test_has_phone": True, "test_has_contact": True,
                "test_phone": "", "next_test_phone": "",
                "test_routes": ["Phone only", "Zoom Contacts + phone"],
                "roster_routes": ["Phone only", "Zoom Contacts + phone"],
                "phone_route_contact_enabled": False, "contacts_route_contact_enabled": True,
                "roster_has_phone": False, "roster_has_test_contact": False,
                "phone_route_options": ["--calling", "phone"],
                "contacts_route_options": ["--calling", "contacts-phone", "--test-contact", "Fixture Contact"],
                "roster_route_options": ["--calling", "contacts-phone"],
                "cancel_response": "cancel", "cancel_has_selection": False,
                "cancel_started_worker": False}}


def test_startup_success_without_native_form_inspection_is_rejected():
    checked = report()
    del checked["start_forms"]
    with pytest.raises(RuntimeError, match="inspect its native Start forms"):
        checker.require_report(checked)


@pytest.mark.parametrize("field,value", [
    ("test_has_phone", False), ("test_phone", "saved value"),
    ("next_test_phone", "earlier form input"),
    ("test_routes", ["Phone only"]), ("roster_routes", ["Zoom Contacts + phone"]),
    ("phone_route_contact_enabled", True), ("contacts_route_contact_enabled", False),
    ("roster_has_phone", True), ("roster_has_test_contact", True),
    ("phone_route_options", ["--calling", "phone", "--test-contact", "stale contact"]),
    ("contacts_route_options", ["--calling", "phone"]),
    ("roster_route_options", ["--calling", "contacts-phone", "--test-contact", "test contact"]),
    ("cancel_response", "continue"), ("cancel_has_selection", True),
    ("cancel_started_worker", True), ("cancel_started_worker", 0),
    ("test_has_contact", "true")])
def test_bad_native_form_state_cannot_pass_startup_smoke(field, value):
    checked = report()
    checked["start_forms"][field] = value
    with pytest.raises(RuntimeError):
        checker.require_report(checked)


def fake_app(tmp_path):
    app = tmp_path / "War Room Bot.app"
    executable = app / "Contents" / "MacOS" / "WarRoomBot"
    executable.parent.mkdir(parents=True)
    executable.write_text("This test never executes a native app.")
    return app, executable


def simulated_launches(monkeypatch, app, executable, *, fail_route=None, write_settings=False):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        direct = command[0] == str(executable)
        assert direct or command[:5] == ["/usr/bin/open", "-n", "-W", "-a", str(app)]
        assert "--ui-smoke-test" in command
        home = Path(command[command.index("--ui-smoke-home") + 1])
        checked = report()
        checked.update(native_executable=str(executable), home=str(home))
        if fail_route == ("direct" if direct else "launchservices"):
            checked["start_forms"]["next_test_phone"] = "reused input"
        if write_settings:
            home.mkdir()
            (home / ".env").write_text("Unexpected settings mutation.")
        if direct:
            assert kwargs["env"]["WARROOM_HOME"] == str(home)
            return subprocess.CompletedProcess(command, 0, "WRB_UI_SMOKE " + json.dumps(checked) + "\n")
        destination = Path(command[command.index("--ui-smoke-report") + 1])
        destination.write_text(json.dumps(checked))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(checker.subprocess, "run", run)
    return calls


def test_real_form_report_is_required_for_direct_and_launchservices_routes(tmp_path, monkeypatch):
    app, executable = fake_app(tmp_path)
    calls = simulated_launches(monkeypatch, app, executable)
    checker.check_app(app)
    assert len(calls) == 2
    assert not any("start" in command or "set-number" in command for command in calls)


@pytest.mark.parametrize("route,expected_calls", [("direct", 1), ("launchservices", 2)])
def test_cached_number_report_fails_on_either_launch_route(tmp_path, monkeypatch, route, expected_calls):
    app, executable = fake_app(tmp_path)
    calls = simulated_launches(monkeypatch, app, executable, fail_route=route)
    with pytest.raises(RuntimeError, match="fresh blank phone field"):
        checker.check_app(app)
    assert len(calls) == expected_calls


def test_ui_smoke_cannot_write_settings_into_its_isolated_home(tmp_path, monkeypatch):
    app, executable = fake_app(tmp_path)
    calls = simulated_launches(monkeypatch, app, executable, write_settings=True)
    with pytest.raises(RuntimeError, match="wrote files"):
        checker.check_app(app)
    assert len(calls) == 1


def test_report_from_another_executable_or_nonisolated_home_is_rejected(tmp_path):
    _, executable = fake_app(tmp_path)
    home = tmp_path / "isolated"
    checked = report()
    checked.update(native_executable="/another/app", home=str(home))
    with pytest.raises(RuntimeError, match="selected app"):
        checker.require_isolated_report(checked, executable, home)
    checked.update(native_executable=str(executable), home="/another/data")
    with pytest.raises(RuntimeError, match="isolated data folder"):
        checker.require_isolated_report(checked, executable, home)
