"""Bounded, read-only launch diagnostics preserve the user's existing mounts."""
import importlib.util
from pathlib import Path
import plistlib
import sys
import time

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "diagnose_app_launch.py"
SPEC = importlib.util.spec_from_file_location("diagnose_app_launch", SCRIPT)
diagnose = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnose)


def result(*, stdout="", code=0, timeout=False):
    return {"code": code, "timeout": timeout, "stdout": stdout, "stderr": ""}


def inspected(*, passed=True, timeout=False):
    hashes = {name: {"sha256": "a" * 64} for name in diagnose.FILES}
    smoke = dict(result(code=-15 if timeout else 0, timeout=timeout),
                 passed=passed, codesign_valid=True)
    return hashes, smoke


def test_real_probe_timeout_preserves_bounded_partial_output():
    started = time.monotonic()
    probe = diagnose.run([sys.executable, "-c",
                          "import sys,time; sys.stdout.write('x'*2000000+'END'); "
                          "sys.stdout.flush(); time.sleep(30)"], timeout=0.5)
    assert probe["timeout"] and probe["code"] != 0
    assert time.monotonic() - started < 3
    assert probe["stdout"].endswith("END")
    assert len(probe["stdout"]) < 66000


def test_exit_zero_with_false_string_or_invalid_json_is_not_a_pass(tmp_path, monkeypatch):
    app = tmp_path / "War Room Bot.app"
    executable = app / diagnose.FILES["main"]
    executable.parent.mkdir(parents=True)
    executable.write_text("not executed in this test")
    monkeypatch.setattr(diagnose, "fingerprint", lambda _: inspected()[0])
    for output in ('{"ok":false}', '{"ok":"true"}', 'not JSON', '[true]'):
        monkeypatch.setattr(diagnose, "run", lambda command, **kwargs:
                            result(stdout=output if "--smoke-test" in command else ""))
        _, smoke = diagnose.inspect(app, "Fixture")
        assert smoke["code"] == 0 and not smoke["passed"]


def test_hash_mismatch_and_unknown_hash_do_not_report_success(capsys):
    installed = inspected()
    rebuilt = inspected()
    rebuilt[0]["helper"]["sha256"] = "b" * 64
    assert diagnose.summarize(installed, rebuilt) == 1
    assert "files differ: helper" in capsys.readouterr().out
    rebuilt[0]["helper"]["sha256"] = None
    assert diagnose.summarize(installed, rebuilt) == 1
    output = capsys.readouterr().out
    assert "Could not compare" in output and "No copy mismatch is established" in output


def test_existing_exact_mount_is_used_and_never_detached(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnose.sys, "platform", "darwin")
    app = tmp_path / "Applications" / "War Room Bot.app"
    app.mkdir(parents=True)
    dmg = tmp_path / "exact local build.dmg"
    dmg.write_text("fixture image")
    wrong = tmp_path / "Other volume" / "War Room Bot.app"
    existing = tmp_path / "Exact volume" / "War Room Bot.app"
    wrong.mkdir(parents=True)
    existing.mkdir(parents=True)
    information = plistlib.dumps({"images": [
        {"image-path": str(tmp_path / "other.dmg"), "system-entities": [{"mount-point": str(wrong.parent)}]},
        {"image-path": str(dmg), "system-entities": [{"mount-point": str(existing.parent)}]},
    ]}).decode()
    calls = []
    inspected_paths = []

    def run(command, **kwargs):
        calls.append(command)
        return result(stdout=information if "info" in command else "arm64\n")

    def inspect(path, label):
        inspected_paths.append(path)
        return inspected()

    monkeypatch.setattr(diagnose, "run", run)
    monkeypatch.setattr(diagnose, "inspect", inspect)
    monkeypatch.setattr(diagnose, "successful_build_log", lambda _: (True, {"ok": True}))
    assert diagnose.main(["--app", str(app), "--dmg", str(dmg)]) == 0
    assert inspected_paths == [app, existing]
    assert not any("attach" in command or "detach" in command for command in calls)


def test_owned_readonly_mount_is_detached_after_reference_probe_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnose.sys, "platform", "darwin")
    app = tmp_path / "Applications" / "War Room Bot.app"
    app.mkdir(parents=True)
    dmg = tmp_path / "local build.dmg"
    dmg.write_text("fixture image")
    scratch = tmp_path / "private scratch"
    scratch.mkdir()
    monkeypatch.setattr(diagnose.tempfile, "mkdtemp", lambda **kwargs: str(scratch))
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if "info" in command:
            return result(stdout=plistlib.dumps({"images": []}).decode())
        if "attach" in command:
            assert "-readonly" in command and "-noautoopen" in command
            mount = Path(command[command.index("-mountpoint") + 1])
            (mount / "War Room Bot.app").mkdir()
        elif "detach" in command:
            (Path(command[-1]) / "War Room Bot.app").rmdir()  # Simulated unmount removes image contents.
        return result(stdout="arm64\n")

    monkeypatch.setattr(diagnose, "run", run)
    monkeypatch.setattr(diagnose, "inspect", lambda path, label:
                        inspected() if label == "Installed" else inspected(passed=False, timeout=True))
    monkeypatch.setattr(diagnose, "successful_build_log", lambda _: (True, {"ok": True}))
    assert diagnose.main(["--app", str(app), "--dmg", str(dmg)]) == 1
    detached = [command for command in calls if "detach" in command]
    assert detached == [["/usr/bin/hdiutil", "detach", str(scratch / "mount")]]
    assert not scratch.exists() and app.exists() and dmg.exists()


def test_missing_reference_is_nonzero_without_mounting(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnose.sys, "platform", "darwin")
    app = tmp_path / "War Room Bot.app"
    app.mkdir()
    monkeypatch.setattr(diagnose, "inspect", lambda *args: inspected())
    commands = []
    monkeypatch.setattr(diagnose, "run", lambda command, **kwargs: commands.append(command) or result(stdout="arm64"))
    assert diagnose.main(["--app", str(app), "--dmg", str(tmp_path / "missing.dmg")]) == 1
    assert not any("attach" in command or "detach" in command for command in commands)
