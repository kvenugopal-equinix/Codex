"""Native-app helper selection and permission checks without macOS or Zoom."""
import json
import shlex

import pytest

import warroom.ui_backend as ui


def helper(path, result=None, *, status=0, executable=True, raw=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    output = raw if raw is not None else json.dumps(result if result is not None else {"ok": True})
    path.write_text("#!/bin/sh\nprintf '%s\\n' " + shlex.quote(output) + "\nexit " + str(status) + "\n")
    path.chmod(0o755 if executable else 0o644)
    return path


def test_native_bundle_helper_with_spaces_handles_calls_and_trust(tmp_path, monkeypatch):
    bundled = helper(tmp_path / "War Room Bot.app" / "Contents" / "MacOS" / "axctl",
                     {"ok": True, "windows": ["Zoom Meeting"]})
    monkeypatch.setattr(ui, "AXCTL", tmp_path / "missing-data-helper")
    monkeypatch.setenv("WARROOM_AXCTL", str(bundled))
    commands, real_run = [], ui.subprocess.run

    def capture(command, **kwargs):
        commands.append(command)
        return real_run(command, **kwargs)

    monkeypatch.setattr(ui.subprocess, "run", capture)
    ax = ui.Ax()
    assert ax.call("windows")["windows"] == ["Zoom Meeting"]
    assert ax.trusted()
    assert commands == [[str(bundled), "windows"], [str(bundled), "trusted"]]


def test_terminal_uses_existing_data_helper_when_override_is_unset(tmp_path, monkeypatch):
    installed = helper(tmp_path / "WarRoomBot" / "tools" / "axctl", {"ok": True, "source": "data"})
    monkeypatch.setattr(ui, "AXCTL", installed)
    assert ui.Ax().call("windows")["source"] == "data"
    assert ui.DEBUG_PATH == ui.BASE / "logs" / "ui_debug.json"


def test_native_environment_wins_over_private_dotenv(tmp_path, monkeypatch, real_load_dotenv):
    bundled = helper(tmp_path / "App" / "Contents" / "MacOS" / "axctl", {"ok": True, "source": "app"})
    private = helper(tmp_path / "data" / "tools" / "axctl", {"ok": True, "source": "private"})
    settings = tmp_path / ".env"
    settings.write_text("WARROOM_AXCTL=" + shlex.quote(str(private)) + "\n")
    monkeypatch.setenv("WARROOM_AXCTL", str(bundled))
    real_load_dotenv(settings)
    assert ui.Ax().call("windows")["source"] == "app"


@pytest.mark.parametrize("override", ["", "   ", "tools/axctl", "~/WarRoomBot/tools/axctl"])
def test_malformed_override_fails_instead_of_falling_back(tmp_path, monkeypatch, override):
    installed = helper(tmp_path / "tools" / "axctl")
    monkeypatch.setattr(ui, "AXCTL", installed)
    monkeypatch.setenv("WARROOM_AXCTL", override)
    monkeypatch.setattr(ui.subprocess, "run", lambda *args, **kwargs: pytest.fail("invalid override executed a helper"))
    with pytest.raises(ui.UiUnavailable, match="WARROOM_AXCTL must be an absolute path"):
        ui.Ax().call("windows")
    assert not ui.Ax().trusted()


@pytest.mark.parametrize("kind,diagnosis", [
    ("missing", "missing or is not a file"),
    ("directory", "missing or is not a file"),
    ("not-executable", "not executable"),
])
def test_unusable_native_helper_has_actionable_diagnosis(tmp_path, monkeypatch, kind, diagnosis):
    bundled = tmp_path / "App" / "Contents" / "MacOS" / "axctl"
    if kind == "directory":
        bundled.mkdir(parents=True)
    elif kind == "not-executable":
        helper(bundled, executable=False)
    monkeypatch.setenv("WARROOM_AXCTL", str(bundled))
    monkeypatch.setattr(ui.subprocess, "run", lambda *args, **kwargs: pytest.fail("unusable helper was executed"))
    with pytest.raises(ui.UiUnavailable, match=diagnosis) as error:
        ui.Ax().call("windows")
    assert "rebuild and reinstall War Room Bot.app" in str(error.value)
    assert not ui.Ax().trusted()


@pytest.mark.parametrize("result,status", [
    ({"ok": "true"}, 0),
    ({"ok": 1}, 0),
    ({"nested": {"ok": True}}, 0),
    ([], 0),
    (True, 0),
    ({"ok": True}, 2),
])
def test_native_override_cannot_make_invalid_or_failed_permission_check_succeed(tmp_path, monkeypatch, result, status):
    bundled = helper(tmp_path / "axctl", result, status=status)
    monkeypatch.setenv("WARROOM_AXCTL", str(bundled))
    assert not ui.Ax().trusted()
    with pytest.raises(ui.UiError):
        ui.Ax().call("trusted")


def test_permission_denial_keeps_existing_unavailable_semantics(tmp_path, monkeypatch):
    bundled = helper(tmp_path / "axctl", {"ok": False, "error": "not trusted: denied"}, status=2)
    monkeypatch.setenv("WARROOM_AXCTL", str(bundled))
    assert not ui.Ax().trusted()
    with pytest.raises(ui.UiUnavailable, match="not trusted: denied"):
        ui.Ax().call("windows")


def test_helper_error_dictionary_is_retained_for_control_retry_logic(tmp_path, monkeypatch):
    denial = {"ok": False, "error": "press failed: -25200"}
    bundled = helper(tmp_path / "axctl", denial, status=2)
    monkeypatch.setenv("WARROOM_AXCTL", str(bundled))
    assert ui.Ax().call("press") == denial


def test_non_json_helper_output_is_not_permission_granted(tmp_path, monkeypatch):
    bundled = helper(tmp_path / "axctl", raw="permission check crashed")
    monkeypatch.setenv("WARROOM_AXCTL", str(bundled))
    assert not ui.Ax().trusted()
    with pytest.raises(ui.UiError, match="gave no JSON"):
        ui.Ax().call("trusted")
