"""Transactional repair checks using private fake bundles, never the installed app."""
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import shutil
import signal
import sys
import tempfile

import pytest


SPEC = importlib.util.spec_from_file_location(
    "repair_app", Path(__file__).resolve().parents[1] / "tools/repair_installed_app.py")
repair_app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repair_app)


def exchange(first, second):
    temporary = first.parent / ".test-exchange"
    os.rename(first, temporary)
    os.rename(second, first)
    os.rename(temporary, second)


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    parent = tmp_path / "Applications"
    app = parent / repair_app.NAME
    binary = app / "Contents/MacOS"
    binary.mkdir(parents=True)
    for name in ("WarRoomBot", "axctl"):
        (binary / name).write_bytes(b"fake executable bytes")
        (binary / name).chmod(0o755)
    metadata = {"CFBundleName": "War Room Bot", "CFBundleDisplayName": "War Room Bot",
                "CFBundleExecutable": "WarRoomBot", "CFBundleIdentifier": "com.example.warroombot",
                "CFBundleShortVersionString": "20261012.7"}
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps(metadata))
    payload = app / "Contents/Resources/payload"
    (payload / "app").mkdir(parents=True)
    (payload / "VERSION").write_text("20261012.7\n")
    (payload / "app/WarRoomBot.swift").write_text("--ui-smoke-test --ui-smoke-home")
    (app / "Contents/Resources/alias").symlink_to("payload/VERSION")
    private = tmp_path / "WarRoomBot/.env"
    private.parent.mkdir()
    private.write_text("private setting, unchanged\n")
    monkeypatch.setattr(repair_app, "ensure_idle", lambda: None)
    monkeypatch.setattr(repair_app, "atomic_exchange", exchange)
    monkeypatch.setattr(repair_app, "bounded_inventory", repair_app.inventory)
    staging = tmp_path / "User staging"
    staging.mkdir()
    make_temporary = tempfile.mkdtemp
    def make_staging(*args, **kwargs):
        if kwargs.get("prefix") == "WarRoomBot-Finder-repair-" and "dir" not in kwargs:
            kwargs["dir"] = str(staging)
        return make_temporary(*args, **kwargs)
    monkeypatch.setattr(repair_app.tempfile, "mkdtemp", make_staging)

    def checked(command, description, timeout=15):
        if command[0] == "/usr/bin/ditto":
            assert len(command) == 3 or command[1:3] == ["--noextattr", "--noqtn"]
            assert not Path(command[-1]).exists()
            shutil.copytree(command[-2], command[-1], symlinks=True)
            return {"code": 0, "timeout": False, "stdout": "", "stderr": ""}
        if command[0] == "/usr/bin/codesign":
            assert "--sign" not in command
            return {"code": 0, "timeout": False, "stdout": "", "stderr": ""}
        current = Path(command[0]).parents[2]
        report = dict(repair_app.identity(current), ok=True, window_visible=True,
                      installation_checked=True, native_executable=command[0],
                      payload=str(current / "Contents/Resources/payload"),
                      helper=str(current / "Contents/MacOS/axctl"), home=command[-1])
        assert command[1:3] == ["--ui-smoke-test", "--ui-smoke-home"]
        return {"code": 0, "timeout": False, "stdout": "WRB_UI_SMOKE " + json.dumps(report), "stderr": ""}

    monkeypatch.setattr(repair_app, "checked", checked)
    return app, private, checked


def test_success_preserves_all_content_identity_and_private_data_with_retained_backup(bundle):
    app, private, _ = bundle
    old_inode = app.stat().st_ino
    content, identity = repair_app.inventory(app), repair_app.identity(app)
    backup = repair_app.repair(app)
    assert backup.name == app.name == "War Room Bot.app"
    assert backup.parent.name == "original" and backup.parent.parent.name.startswith(".WarRoomBot-repair-")
    assert backup.stat().st_ino == old_inode
    assert app.stat().st_ino != old_inode
    assert repair_app.inventory(app) == repair_app.inventory(backup) == content
    assert repair_app.identity(app) == repair_app.identity(backup) == identity
    assert private.read_text() == "private setting, unchanged\n"


def test_failed_staged_window_check_does_not_replace_original(bundle, monkeypatch):
    app, private, _ = bundle
    original = app.stat().st_ino
    def failed(*_args):
        raise repair_app.RepairError("window did not become ready")
    monkeypatch.setattr(repair_app, "ui_check", failed)
    with pytest.raises(repair_app.RepairError, match="window"):
        repair_app.repair(app)
    assert app.stat().st_ino == original
    assert not list(app.parent.glob(".WarRoomBot-repair-*/original/War Room Bot.app"))
    assert private.read_text() == "private setting, unchanged\n"


def test_failed_installed_window_check_atomically_restores_original(bundle, monkeypatch):
    app, private, _ = bundle
    original, content = app.stat().st_ino, repair_app.inventory(app)
    check = repair_app.ui_check
    def failed_installed(current, expected, home):
        if current == app:
            raise repair_app.RepairError("installed check timed out")
        check(current, expected, home)
    monkeypatch.setattr(repair_app, "ui_check", failed_installed)
    with pytest.raises(repair_app.RepairError, match="timed out"):
        repair_app.repair(app)
    assert app.stat().st_ino == original
    assert repair_app.inventory(app) == content
    assert private.read_text() == "private setting, unchanged\n"


@pytest.mark.parametrize("number", [signal.SIGINT, signal.SIGTERM])
def test_interrupt_immediately_after_exchange_rolls_back_original(bundle, monkeypatch, number):
    app, _, _ = bundle
    original = app.stat().st_ino
    calls = []
    def interrupted_exchange(first, second):
        exchange(first, second)
        calls.append(True)
        if len(calls) == 1:
            # Signals must stay deferred until the transaction state is updated.
            os.kill(os.getpid(), number)
    monkeypatch.setattr(repair_app, "atomic_exchange", interrupted_exchange)
    with repair_app.repair_signals():
        with pytest.raises(KeyboardInterrupt):
            repair_app.repair(app)
    assert len(calls) == 2 and app.stat().st_ino == original


def test_backup_rename_failure_rolls_back_from_staging_slot(bundle, monkeypatch):
    app, _, _ = bundle
    original = app.stat().st_ino
    rename = Path.rename
    def failed_backup(path, target):
        if path.parent.name == "replacement":
            raise OSError("could not retain backup")
        return rename(path, target)
    monkeypatch.setattr(Path, "rename", failed_backup)
    with pytest.raises(OSError, match="retain backup"):
        repair_app.repair(app)
    assert app.stat().st_ino == original


def test_inventory_detects_resource_bytes_symlink_and_executable_mode(bundle, tmp_path):
    app, _, _ = bundle
    other = tmp_path / "copy.app"
    shutil.copytree(app, other, symlinks=True)
    assert repair_app.inventory(app) == repair_app.inventory(other)
    version = other / "Contents/Resources/payload/VERSION"
    version.write_text("different bytes")
    assert repair_app.inventory(app) != repair_app.inventory(other)
    version.write_bytes((app / "Contents/Resources/payload/VERSION").read_bytes())
    alias = other / "Contents/Resources/alias"
    alias.unlink()
    alias.symlink_to("payload/app/WarRoomBot.swift")
    assert repair_app.inventory(app) != repair_app.inventory(other)
    alias.unlink()
    alias.symlink_to("payload/VERSION")
    (other / "Contents/MacOS/WarRoomBot").chmod(0o644)
    assert repair_app.inventory(app) != repair_app.inventory(other)


def test_ui_check_rejects_a_healthy_different_executable(bundle, monkeypatch):
    app, _, checked = bundle
    def wrong_app(command, description, timeout=15):
        result = checked(command, description, timeout)
        report = json.loads(result["stdout"][len("WRB_UI_SMOKE "):])
        report["native_executable"] = "/tmp/another/War Room Bot.app/Contents/MacOS/WarRoomBot"
        result["stdout"] = "WRB_UI_SMOKE " + json.dumps(report)
        return result
    monkeypatch.setattr(repair_app, "checked", wrong_app)
    with pytest.raises(repair_app.RepairError, match="different executable"):
        repair_app.ui_check(app, repair_app.identity(app), app.parent / "isolated")


def test_existing_native_host_or_framework_python_watcher_is_refused(monkeypatch):
    def inspection(command, *_args, **_kwargs):
        data = "123 /path/WarRoomBot\n456 /Framework/Python\n" if "pid=,comm=" in command else "123 /path/WarRoomBot\n456 /Framework/Python -m warroom.cli watch --watch-token harmless\n"
        return {"stdout": data, "code": 0, "timeout": False}
    monkeypatch.setattr(repair_app, "run", inspection)
    monkeypatch.setattr(os, "kill", lambda *_: pytest.fail("must not signal an existing process"))
    with pytest.raises(repair_app.RepairError, match="123, 456"):
        repair_app.ensure_idle()


def test_owned_probe_timeout_is_bounded_and_reports_failure():
    result = repair_app.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.05)
    assert result["timeout"] and result["code"] is not None and not result["unreaped"]


def test_incomplete_process_inspection_refuses_repair_without_printing_arguments(monkeypatch):
    monkeypatch.setattr(repair_app, "run", lambda *_args, **_kwargs:
                        {"code": 0, "timeout": False, "truncated": True,
                         "stdout": "private command arguments", "stderr": ""})
    with pytest.raises(repair_app.RepairError, match="completely inspect") as error:
        repair_app.ensure_idle()
    assert "private command arguments" not in str(error.value)


def test_unwritable_parent_prepares_tested_finder_copy_without_installation_or_elevation(bundle, monkeypatch, capsys):
    app, _, _ = bundle
    original, content = app.stat().st_ino, repair_app.inventory(app)
    access = os.access
    monkeypatch.setattr(os, "access", lambda path, mode: False if Path(path) == app.parent else access(path, mode))
    monkeypatch.setattr(repair_app, "atomic_exchange", lambda *_: pytest.fail("Finder fallback must not exchange installed apps"))
    revealed = []
    monkeypatch.setattr(repair_app, "run", lambda command, **_kwargs:
                        revealed.append(command) or {"code": 0, "timeout": False})
    receipt = repair_app.repair(app)
    record = json.loads(receipt.read_text())
    candidate, backup = Path(record["candidate"]), Path(record["backup"])
    assert receipt.parent.parent.name == "User staging"
    assert app.stat().st_ino == original and repair_app.inventory(app) == content
    assert repair_app.inventory(candidate) == repair_app.inventory(backup) == content
    assert repair_app.identity(candidate) == repair_app.identity(app) == record["identity"]
    assert (candidate.parent / "Applications").resolve() == app.parent
    assert revealed == [["/usr/bin/open", "-R", str(candidate)]]
    assert "installation is still pending" in capsys.readouterr().out
    assert not list(app.parent.glob(".WarRoomBot-repair-*"))


def test_explicit_finder_preparation_no_reveal_preserves_original_and_verifies_later_copy(bundle, monkeypatch, capsys):
    app, private, _ = bundle
    original = app.stat().st_ino
    monkeypatch.setattr(repair_app, "atomic_exchange", lambda *_: pytest.fail("manual preparation must not exchange"))
    monkeypatch.setattr(repair_app, "run", lambda *_args, **_kwargs: pytest.fail("--no-reveal must not invoke Finder"))
    receipt = repair_app.repair(app, prepare_for_finder=True, reveal=False)
    record = json.loads(receipt.read_text())
    assert app.stat().st_ino == original
    assert record["app"] == str(app)
    assert Path(record["candidate"]).name == Path(record["backup"]).name == app.name
    assert not list(app.parent.glob(".WarRoomBot-repair-*"))
    # Simulate the user's approved Finder replacement in this private test tree.
    old_copy = app.parent / "old-test-copy"
    os.rename(app, old_copy)
    shutil.copytree(record["candidate"], app, symlinks=True)
    repair_app.verify_installed(receipt)
    assert "Installed replacement verified" in capsys.readouterr().out
    assert private.read_text() == "private setting, unchanged\n"
    assert receipt.exists() and Path(record["backup"]).exists()


def test_failed_finder_candidate_check_never_reveals_or_reports_ready(bundle, monkeypatch, capsys):
    app, _, _ = bundle
    original = app.stat().st_ino
    monkeypatch.setattr(repair_app, "atomic_exchange", lambda *_: pytest.fail("manual candidate failure must not exchange"))
    monkeypatch.setattr(repair_app, "run", lambda *_args, **_kwargs: pytest.fail("failed candidate must not be revealed"))
    def fail(*_args):
        raise repair_app.RepairError("candidate check failed")
    monkeypatch.setattr(repair_app, "ui_check", fail)
    with pytest.raises(repair_app.RepairError, match="candidate check"):
        repair_app.repair(app, prepare_for_finder=True)
    assert app.stat().st_ino == original
    assert "Finder replacement prepared" not in capsys.readouterr().out


def test_receipt_verification_refuses_changed_bundle_before_launching_it(bundle, monkeypatch):
    app, _, _ = bundle
    receipt = repair_app.repair(app, prepare_for_finder=True, reveal=False)
    (app / "Contents/MacOS/axctl").write_bytes(b"changed executable")
    monkeypatch.setattr(repair_app, "ui_check", lambda *_: pytest.fail("different installed content must not execute"))
    with pytest.raises(repair_app.RepairError, match="does not match"):
        repair_app.verify_installed(receipt)


@pytest.mark.parametrize("mutation", [lambda record: record.update(app="relative/War Room Bot.app"),
                                     lambda record: record["inventory"].update(entries=True),
                                     lambda record: record["identity"].update(bundle_id="invalid identifier")])
def test_invalid_receipt_expectations_are_rejected_without_running_app(bundle, monkeypatch, mutation):
    app, _, _ = bundle
    receipt = repair_app.repair(app, prepare_for_finder=True, reveal=False)
    record = json.loads(receipt.read_text())
    mutation(record)
    receipt.write_text(json.dumps(record))
    monkeypatch.setattr(repair_app, "ui_check", lambda *_: pytest.fail("invalid receipt must not execute app"))
    with pytest.raises(repair_app.RepairError, match="valid installed-app expectations"):
        repair_app.verify_installed(receipt)
