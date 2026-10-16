"""Activity runtime patch tests use a private fake app and no Zoom or network."""
from contextlib import nullcontext
import hashlib
import importlib.util
import json
from pathlib import Path
import plistlib
import subprocess
import sys
import zipfile

import pytest


TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location("activity_runtime_update", TOOLS / "apply_activity_runtime_update.py")
activity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(activity)
base = activity.base


def digest(data):
    return hashlib.sha256(data).hexdigest()


def archive_source(source, destination):
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as output:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                output.write(path, "WarRoomBot/" + path.relative_to(source).as_posix())
    return digest(destination.read_bytes())


@pytest.fixture
def box(tmp_path, monkeypatch):
    home, app, source = tmp_path / "runtime", tmp_path / base.NAME, tmp_path / "published"
    (home / ".venv/bin").mkdir(parents=True)
    python = home / ".venv/bin/python"
    python.write_text("fake Python; not executed")
    python.chmod(0o755)
    (home / "VERSION").write_text(base.BASE_VERSION + "\n")
    (home / ".env").write_text("WARROOM_TEST_NUMBER=private-number\n")
    (home / "roster.xlsx").write_bytes(b"private roster")
    (home / "logs").mkdir()
    (home / "logs/join_log.csv").write_bytes(b"private activity\n")
    (app / "Contents/Resources/payload").mkdir(parents=True)
    (app / "Contents/Resources/payload/VERSION").write_text(base.BASE_VERSION + "\n")
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps({
        "CFBundleIdentifier": "com.equinix.warroombot",
        "CFBundleShortVersionString": base.BASE_VERSION,
        "CFBundleExecutable": "WarRoomBot",
    }))
    (app / "Contents/MacOS").mkdir()
    (app / "Contents/MacOS/WarRoomBot").write_bytes(b"signed app")
    (app / "Contents/MacOS/axctl").write_bytes(b"signed helper")
    source.mkdir()
    (source / "VERSION").write_text(activity.SOURCE_VERSION + "\n")
    allowed, desired, originals = {}, {}, {}
    for relative, expected in activity.ALLOWED_HASHES.items():
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(("new " + relative + "\n").encode())
        desired[relative] = target.read_bytes()
        if expected is None:
            allowed[relative] = None
        else:
            old = ("old " + relative + "\n").encode()
            installed = home / relative
            installed.parent.mkdir(parents=True, exist_ok=True)
            installed.write_bytes(old)
            originals[relative] = old
            allowed[relative] = digest(old)
    archive = tmp_path / "published.zip"
    checksum = archive_source(source, archive)
    monkeypatch.setattr(activity, "ALLOWED_HASHES", allowed)
    monkeypatch.setattr(base, "ensure_idle", lambda: None)
    # Signal handling is exercised by the original updater on macOS; SIGHUP
    # is unavailable on this Windows test host.
    if not hasattr(base.signal, "SIGHUP"):
        monkeypatch.setattr(base, "rollback_signals", nullcontext)
    # Mac uses fchmod. This Windows-only test host has no equivalent descriptor API.
    if not hasattr(base.os, "fchmod"):
        monkeypatch.setattr(base.os, "fchmod", lambda *_: None, raising=False)
    staged = []

    def preflight(extracted, python_path, container):
        assert python_path == python
        assert extracted != home
        assert (extracted / "VERSION").read_text().strip() == activity.SOURCE_VERSION
        assert (extracted / "tools/choose_activity_log.py").is_file()
        staged.append(extracted)

    monkeypatch.setattr(base, "preflight", preflight)
    return dict(home=home, app=app, source=source, archive=archive, checksum=checksum,
                allowed=allowed, desired=desired, originals=originals, staged=staged)


def apply(box, **kwargs):
    return activity.apply(box["home"], box["app"], box["checksum"], archive=box["archive"], **kwargs)


def test_patch_preserves_app_private_files_version_and_is_repeatable(box):
    home, app = box["home"], box["app"]
    bundle = {p.relative_to(app): p.read_bytes() for p in app.rglob("*") if p.is_file()}
    private = {relative: (home / relative).read_bytes() for relative in
               ("VERSION", ".env", "roster.xlsx", "logs/join_log.csv")}
    backup = apply(box)
    receipt = json.loads((backup / "receipt.json").read_text())
    assert receipt["status"] == "applied" and receipt["patch"] == activity.PATCH
    assert receipt["source_sha256"] == box["checksum"]
    for relative, data in box["desired"].items():
        assert (home / relative).read_bytes() == data
        record = receipt["files"][relative]
        if relative in box["originals"]:
            assert (backup / record["backup"]).read_bytes() == box["originals"][relative]
        else:
            assert record["before"] is None and record["backup"] is None
    for relative, data in private.items():
        assert (home / relative).read_bytes() == data
    assert {p.relative_to(app): p.read_bytes() for p in app.rglob("*") if p.is_file()} == bundle
    assert not (home / "tests/test_activity_report.py").exists()
    assert apply(box) is None
    assert len(list((home / "logs/runtime-updates").glob("*/receipt.json"))) == 1
    assert len(box["staged"]) == 2


def test_known_prior_patch_is_accepted_and_old_repair_can_be_reapplied(box):
    home = box["home"]
    prior = {}
    for relative in ("warroom/cli.py", "warroom/watcher.py", "tests/test_watcher.py"):
        data = ("prior " + relative + "\n").encode()
        (home / relative).write_bytes(data)
        box["allowed"][relative] = (digest(box["originals"][relative]), digest(data))
        prior[relative] = data
    first = apply(box)
    assert first.is_dir()
    for relative, data in box["originals"].items():
        (home / relative).write_bytes(data)  # old app's merge-based Repair
    second = apply(box)
    assert second != first
    for relative, data in box["desired"].items():
        assert (home / relative).read_bytes() == data
    assert (home / "VERSION").read_text().strip() == base.BASE_VERSION
    assert len(prior) == 3


def test_unexpected_existing_new_file_refused_before_tests(box):
    target = box["home"] / "warroom/activity_report.py"
    target.write_bytes(b"local customization")
    with pytest.raises(base.UpdateError, match="modified or unexpected"):
        apply(box)
    assert target.read_bytes() == b"local customization"
    assert box["staged"] == []


def test_missing_existing_target_refused_before_tests(box):
    (box["home"] / "warroom/config.py").unlink()
    with pytest.raises(base.UpdateError, match="modified or unexpected"):
        apply(box)
    assert box["staged"] == []


def test_failed_write_removes_new_files_and_restores_existing(box, monkeypatch):
    home = box["home"]
    original_write = base.atomic_write
    failed = False

    def fail_at_last_test(path, data, mode):
        nonlocal failed
        if path == home / "tests/test_set_env.py" and not failed:
            failed = True
            raise OSError("simulated disk failure")
        return original_write(path, data, mode)

    monkeypatch.setattr(base, "atomic_write", fail_at_last_test)
    with pytest.raises(base.UpdateError, match="original files were restored"):
        apply(box)
    for relative, data in box["originals"].items():
        assert (home / relative).read_bytes() == data
    assert not (home / "warroom/activity_report.py").exists()
    assert not (home / "tools/choose_activity_log.py").exists()
    receipts = list((home / "logs/runtime-updates").glob("*/receipt.json"))
    assert len(receipts) == 1
    assert json.loads(receipts[0].read_text())["status"] == "rolled-back"


def test_new_file_appearing_during_create_is_never_overwritten_or_removed(box, monkeypatch):
    home = box["home"]
    target = home / "warroom/activity_report.py"
    original_create = base.atomic_create

    def race(path, data, mode):
        if path == target:
            target.write_bytes(b"another process created this file")
            raise FileExistsError(str(target))
        return original_create(path, data, mode)

    monkeypatch.setattr(base, "atomic_create", race)
    with pytest.raises(base.UpdateError, match="original files were restored"):
        apply(box)
    assert target.read_bytes() == b"another process created this file"
    for relative, data in box["originals"].items():
        assert (home / relative).read_bytes() == data


def test_choose_workbook_runs_only_after_successful_patch(box, monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert (box["home"] / "warroom/activity_report.py").read_bytes() == box["desired"]["warroom/activity_report.py"]
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(activity.subprocess, "run", run)
    apply(box, choose_workbook=True)
    assert calls == [[str(box["home"] / ".venv/bin/python"),
                      str(box["home"] / "tools/choose_activity_log.py")]]


def test_picker_failure_reports_patch_was_applied(box, monkeypatch):
    monkeypatch.setattr(activity.subprocess, "run", lambda command, **kwargs:
                        subprocess.CompletedProcess(command, 1))
    with pytest.raises(base.UpdateError, match="runtime patch is applied, but workbook selection did not finish"):
        apply(box, choose_workbook=True)
    assert (box["home"] / "warroom/activity_report.py").is_file()


def test_picker_interrupt_reports_patch_was_applied(box, monkeypatch):
    def interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(activity.subprocess, "run", interrupt)
    with pytest.raises(base.UpdateError, match="runtime patch is applied, but workbook selection was interrupted"):
        apply(box, choose_workbook=True)
    assert (box["home"] / "warroom/activity_report.py").is_file()


def test_source_version_is_checked_before_preflight(box):
    (box["source"] / "VERSION").write_text("wrong\n")
    box["checksum"] = archive_source(box["source"], box["archive"])
    with pytest.raises(base.UpdateError, match="WarRoomBot/VERSION " + activity.SOURCE_VERSION):
        apply(box)
    assert box["staged"] == []


def test_allowlist_matches_published_baselines():
    releases = Path(__file__).resolve().parents[2] / "releases"
    if not (releases / "WarRoomBot-fixed-20261013.3.zip").is_file():
        pytest.skip("published baseline ZIPs are outside the shareable source ZIP")
    for version, index in (("20261013.3", 0), ("20261013.4", 1)):
        with zipfile.ZipFile(releases / ("WarRoomBot-fixed-" + version + ".zip")) as published:
            for relative, allowed in activity.ALLOWED_HASHES.items():
                key = "WarRoomBot/" + relative
                if allowed is None:
                    assert key not in published.namelist()
                elif isinstance(allowed, tuple):
                    assert digest(published.read(key)) == allowed[index]
                else:
                    assert digest(published.read(key)) == allowed
