"""Update delivery checks use private fake bundles and never touch Applications."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import tempfile
import zipfile

import pytest


TOOLS = Path(__file__).resolve().parents[1] / "tools"
SPEC = importlib.util.spec_from_file_location("prepare_update", TOOLS / "prepare_app_update.py")
update = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(update)


def write_archive(app, destination):
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in [app] + sorted(app.rglob("*")):
            relative = path.relative_to(app.parent).as_posix()
            mode = path.lstat().st_mode
            entry = zipfile.ZipInfo(relative + ("/" if stat.S_ISDIR(mode) else ""))
            entry.create_system = 3
            entry.external_attr = mode << 16
            data = os.readlink(path).encode() if path.is_symlink() else b"" if path.is_dir() else path.read_bytes()
            archive.writestr(entry, data)
    return hashlib.sha256(destination.read_bytes()).hexdigest()


def set_version(app, version):
    metadata = app / "Contents/Info.plist"
    values = plistlib.loads(metadata.read_bytes())
    values["CFBundleShortVersionString"] = version
    metadata.write_bytes(plistlib.dumps(values))
    (app / "Contents/Resources/payload/VERSION").write_text(version + "\n")


@pytest.fixture
def bundles(tmp_path, monkeypatch):
    installed = tmp_path / "Applications" / update.NAME
    binaries = installed / "Contents/MacOS"
    binaries.mkdir(parents=True)
    for name in ("WarRoomBot", "axctl"):
        (binaries / name).write_text("old fake executable")
        (binaries / name).chmod(0o755)
    metadata = {"CFBundleName": "War Room Bot", "CFBundleDisplayName": "War Room Bot",
                "CFBundleExecutable": "WarRoomBot", "CFBundleIdentifier": "com.equinix.warroombot",
                "CFBundleShortVersionString": "20261012.7"}
    (installed / "Contents/Info.plist").write_bytes(plistlib.dumps(metadata))
    payload = installed / "Contents/Resources/payload"
    (payload / "app").mkdir(parents=True)
    (payload / "app/WarRoomBot.swift").write_text("--ui-smoke-test --ui-smoke-home")
    (payload / "VERSION").write_text("20261012.7\n")
    (installed / "Contents/Resources/version-alias").symlink_to("payload/VERSION")
    candidate = tmp_path / "build" / update.NAME
    shutil.copytree(installed, candidate, symlinks=True)
    set_version(candidate, "20261013.1")
    (candidate / "Contents/MacOS/WarRoomBot").write_text("new fake executable")
    (candidate / "Contents/Resources/payload/tools").mkdir()
    shutil.copy2(TOOLS / "repair_installed_app.py", candidate / "Contents/Resources/payload/tools/repair_installed_app.py")
    archive = tmp_path / "app.zip"
    digest = write_archive(candidate, archive)
    private = tmp_path / "WarRoomBot/.env"
    private.parent.mkdir()
    private.write_text("private settings must stay unchanged")
    stage = tmp_path / "private staging"
    stage.mkdir()
    make_temporary = tempfile.mkdtemp
    def staging(*args, **kwargs):
        if kwargs.get("prefix") == "WarRoomBot-Finder-update-":
            kwargs["dir"] = stage
        return make_temporary(*args, **kwargs)
    monkeypatch.setattr(update.tempfile, "mkdtemp", staging)
    repair = update.load_repair(candidate)
    monkeypatch.setattr(repair, "bounded_inventory", repair.inventory)
    inspections, commands = [], []
    monkeypatch.setattr(repair, "ensure_idle", lambda: inspections.append("idle"))

    def checked(command, description, timeout=15):
        commands.append(command)
        if command[0] == "/usr/bin/ditto":
            destination = Path(command[-1])
            assert not destination.is_relative_to(installed.parent)
            assert not destination.exists()
            shutil.copytree(command[-2], destination, symlinks=True)
        elif command[0] == "/usr/bin/codesign":
            assert command[1:4] == ["--verify", "--deep", "--strict"]
        else:
            assert command[1:3] == ["--ui-smoke-test", "--ui-smoke-home"]
            app = Path(command[0]).parents[2]
            assert app != installed
            report = dict(repair.identity(app), ok=True, window_visible=True, installation_checked=True,
                          native_executable=command[0], helper=str(app / "Contents/MacOS/axctl"),
                          payload=str(app / "Contents/Resources/payload"), home=command[-1])
            return {"code": 0, "timeout": False, "stdout": "WRB_UI_SMOKE " + json.dumps(report), "stderr": ""}
        return {"code": 0, "timeout": False, "stdout": "", "stderr": ""}

    monkeypatch.setattr(repair, "checked", checked)
    monkeypatch.setattr(update, "load_repair", lambda _app: repair)
    monkeypatch.setattr(repair, "run", lambda *_args, **_kwargs: pytest.fail("no Finder reveal expected"))
    return installed, candidate, archive, digest, private, repair, commands, inspections


def test_update_retains_old_backup_and_verified_new_receipt_without_applications_writes(bundles, capsys):
    installed, candidate, archive, digest, private, repair, commands, inspections = bundles
    original, original_inode = repair.inventory(installed), installed.stat().st_ino
    expected = repair.inventory(candidate)
    receipt = update.prepare(installed, digest, archive=archive, reveal=False)
    record = json.loads(receipt.read_text())
    assert repair.inventory(installed) == original and installed.stat().st_ino == original_inode
    assert repair.inventory(Path(record["backup"])) == original
    assert repair.inventory(Path(record["candidate"])) == expected
    assert record["app"] == str(installed)
    assert record["identity"]["version"] == "20261013.1"
    assert record["inventory"] == expected
    assert (Path(record["candidate"]).parent / "Applications").resolve() == installed.parent
    assert private.read_text() == "private settings must stay unchanged"
    assert len(inspections) == 2
    assert any(command[1:3] == ["--noextattr", "--noqtn"] for command in commands)
    assert stat.S_IMODE(receipt.parent.stat().st_mode) == 0o700
    output = capsys.readouterr().out
    assert "Finder replacement is still pending" in output
    assert "verified-archive/War Room Bot.app/Contents/Resources/payload/tools/repair_installed_app.py" in output
    # The verifier remains available even if Finder moves the candidate app.
    candidate_path = Path(record["candidate"])
    moved = candidate_path.parent / "moved-away.app"
    candidate_path.rename(moved)
    assert (receipt.parent / "verified-archive" / update.NAME / "Contents/Resources/payload/tools/repair_installed_app.py").is_file()
    assert repair.read_receipt(receipt) == (installed, record["identity"], expected)


def test_bad_digest_never_loads_archive_code_or_changes_installed_app(bundles, monkeypatch):
    installed, _, archive, _, _, repair, commands, _ = bundles
    before = repair.inventory(installed)
    monkeypatch.setattr(update, "load_repair", lambda *_: pytest.fail("unverified archive code must not load"))
    with pytest.raises(update.UpdateError, match="SHA-256 does not match"):
        update.prepare(installed, "0" * 64, archive=archive, reveal=False)
    assert repair.inventory(installed) == before and commands == []


def test_local_archive_acquisition_uses_real_file_and_private_mode(tmp_path):
    original = tmp_path / "published.zip"
    original.write_bytes(b"published archive bytes")
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    acquired = tmp_path / "downloaded.zip"
    update.acquire_archive(acquired, digest, archive=original)
    assert acquired.read_bytes() == original.read_bytes()
    assert stat.S_IMODE(acquired.stat().st_mode) == 0o600


def test_receipt_rejects_old_installed_app_then_checks_actual_replacement_path(bundles, monkeypatch):
    installed, _, archive, digest, _, repair, _, _ = bundles
    receipt = update.prepare(installed, digest, archive=archive, reveal=False)
    checked_paths = []
    monkeypatch.setattr(repair, "ui_check", lambda app, expected, home: checked_paths.append((app, expected, home)))
    with pytest.raises(repair.RepairError, match="does not match"):
        repair.verify_installed(receipt)
    assert checked_paths == []
    record = json.loads(receipt.read_text())
    installed.rename(installed.parent / "previous-test-copy")
    shutil.copytree(record["candidate"], installed, symlinks=True)
    repair.verify_installed(receipt)
    assert len(checked_paths) == 1
    assert checked_paths[0][0] == installed
    assert checked_paths[0][1]["version"] == "20261013.1"
    assert not checked_paths[0][2].is_relative_to(installed)


@pytest.mark.parametrize("field,value", [("CFBundleIdentifier", "com.other.bot"),
                                         ("CFBundleName", "Renamed Bot")])
def test_changed_identity_is_refused_before_backup_or_window(bundles, field, value):
    installed, candidate, archive, _, _, repair, commands, _ = bundles
    metadata = candidate / "Contents/Info.plist"
    values = plistlib.loads(metadata.read_bytes())
    values[field] = value
    metadata.write_bytes(plistlib.dumps(values))
    digest = write_archive(candidate, archive)
    before = repair.inventory(installed)
    with pytest.raises(RuntimeError, match="name|identifier"):
        update.prepare(installed, digest, archive=archive, reveal=False)
    assert repair.inventory(installed) == before and commands == []


def test_older_version_is_refused(bundles):
    installed, candidate, archive, _, _, _, commands, _ = bundles
    set_version(installed, "20261014.1")
    digest = write_archive(candidate, archive)
    with pytest.raises(update.UpdateError, match="older"):
        update.prepare(installed, digest, archive=archive, reveal=False)
    assert commands == []


def test_running_app_stops_preparation_before_checks_or_backup(bundles, monkeypatch):
    installed, _, archive, digest, _, repair, commands, _ = bundles
    def busy():
        raise repair.RepairError("Quit War Room Bot")
    monkeypatch.setattr(repair, "ensure_idle", busy)
    with pytest.raises(RuntimeError, match="Quit War Room Bot"):
        update.prepare(installed, digest, archive=archive, reveal=False)
    assert commands == []


def test_failed_window_keeps_original_and_backup_without_revealing_or_receipt(bundles, monkeypatch):
    installed, _, archive, digest, _, repair, _, _ = bundles
    before = repair.inventory(installed)
    def failed(*_args):
        raise repair.RepairError("window timed out")
    monkeypatch.setattr(repair, "ui_check", failed)
    with pytest.raises(RuntimeError, match="timed out"):
        update.prepare(installed, digest, archive=archive)
    assert repair.inventory(installed) == before
    assert not list(installed.parent.parent.glob("private staging/**/repair-receipt.json"))
    backups = list(installed.parent.parent.glob("private staging/**/original/War Room Bot.app"))
    assert len(backups) == 1 and repair.inventory(backups[0]) == before


@pytest.mark.parametrize("entry", ["/absolute", "War Room Bot.app/../outside", "War Room Bot.app//file",
                                   "War Room Bot.app/./file", "Other.app/file", "War Room Bot.app\\escape"])
def test_archive_rejects_unsafe_paths_before_extraction(tmp_path, entry):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr(entry, "bad")
    with pytest.raises(update.UpdateError, match="unsafe path"):
        update.extract_archive(archive, tmp_path / "extracted")
    assert not (tmp_path / "extracted").exists()


@pytest.mark.parametrize("target", ["/tmp/outside", "../../outside", "inside/../../../outside"])
def test_archive_rejects_escaping_symlink(tmp_path, target):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as output:
        link = zipfile.ZipInfo(update.NAME + "/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        output.writestr(link, target)
    with pytest.raises(update.UpdateError, match="symlink"):
        update.extract_archive(archive, tmp_path / "extracted")


def test_archive_rejects_children_under_symlinks(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as output:
        link = zipfile.ZipInfo(update.NAME + "/link")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        output.writestr(link, "target")
        output.writestr(update.NAME + "/link/child", "bad")
    with pytest.raises(update.UpdateError, match="non-directory"):
        update.extract_archive(archive, tmp_path / "extracted")
    assert not (tmp_path / "extracted").exists()


@pytest.mark.parametrize("kind", [stat.S_IFIFO | 0o600, stat.S_IFREG | 0o4755])
def test_archive_rejects_special_entries_or_privileged_modes(tmp_path, kind):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as output:
        entry = zipfile.ZipInfo(update.NAME + "/special")
        entry.external_attr = kind << 16
        output.writestr(entry, "bad")
    with pytest.raises(update.UpdateError, match="unsupported entry"):
        update.extract_archive(archive, tmp_path / "extracted")
    assert not (tmp_path / "extracted").exists()


def test_archive_rejects_cycles_between_internal_symlinks(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as output:
        for name, target in (("first", "second"), ("second", "first")):
            link = zipfile.ZipInfo(update.NAME + "/" + name)
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            output.writestr(link, target)
    with pytest.raises(update.UpdateError, match="cyclic"):
        update.extract_archive(archive, tmp_path / "extracted")


def test_real_archive_extraction_preserves_modes_links_and_signed_bundle_inventory(bundles, tmp_path):
    _, candidate, archive, _, _, repair, _, _ = bundles
    extracted = update.extract_archive(archive, tmp_path / "extracted")
    assert repair.inventory(extracted) == repair.inventory(candidate)
    # Loading the shared verifier must leave the signed archive byte-for-byte intact.
    fresh_spec = importlib.util.spec_from_file_location("fresh_prepare_update", TOOLS / "prepare_app_update.py")
    fresh = importlib.util.module_from_spec(fresh_spec)
    fresh_spec.loader.exec_module(fresh)
    fresh.load_repair(extracted)
    assert repair.inventory(extracted) == repair.inventory(candidate)
    assert not list(extracted.rglob("__pycache__"))


def test_safe_bundle_links_extract_under_a_symlinked_temporary_parent(bundles, tmp_path):
    _, candidate, archive, _, _, repair, _, _ = bundles
    physical = tmp_path / "physical-temporary-directory"
    physical.mkdir()
    alias = tmp_path / "temporary-directory-alias"
    alias.symlink_to(physical, target_is_directory=True)
    extracted = update.extract_archive(archive, alias / "extracted")
    assert extracted == physical / "extracted" / update.NAME
    assert repair.inventory(extracted) == repair.inventory(candidate)
    assert (extracted / "Contents/Resources/version-alias").resolve() == extracted / "Contents/Resources/payload/VERSION"


@pytest.mark.parametrize("url", ["http://raw.githubusercontent.com/kvenugopal-equinix/Codex/file.zip",
                                 "https://example.com/file.zip",
                                 "https://raw.githubusercontent.com/other/repo/file.zip",
                                 "https://raw.githubusercontent.com@evil.test/kvenugopal-equinix/Codex/file.zip"])
def test_only_explicit_https_repo_urls_are_allowed(url):
    with pytest.raises(update.UpdateError, match="HTTPS"):
        update.validate_url(url)


def test_download_size_limit_is_checked_during_streaming(tmp_path, monkeypatch):
    monkeypatch.setattr(update, "MAX_ARCHIVE", 3)
    with pytest.raises(update.UpdateError, match="32 MiB"):
        update.copy_archive(io.BytesIO(b"too big"), tmp_path / "download", "0" * 64, float("inf"))


def test_download_deadline_is_bounded_before_reading(tmp_path, monkeypatch):
    class NeverRead:
        def read(self, *_args):
            pytest.fail("expired download must not read again")
    monkeypatch.setattr(update.time, "monotonic", lambda: 61)
    with pytest.raises(update.UpdateError, match="deadline"):
        update.copy_archive(NeverRead(), tmp_path / "download", "0" * 64, 60)
