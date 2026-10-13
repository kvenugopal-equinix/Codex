"""Runtime patching uses private fake installations; no real app, Zoom or network."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import stat
import subprocess
from types import SimpleNamespace
import zipfile

import pytest


SPEC = importlib.util.spec_from_file_location(
    "runtime_update", Path(__file__).resolve().parents[1] / "tools/apply_runtime_update.py")
update = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(update)


def write_archive(source, destination):
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, "WarRoomBot/" + path.relative_to(source).as_posix())
    return update.digest(destination.read_bytes())


def inventory(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.fixture
def box(tmp_path, monkeypatch):
    home, app, source = tmp_path / "runtime", tmp_path / update.NAME, tmp_path / "published"
    (home / ".venv/bin").mkdir(parents=True)
    (home / ".venv/bin/python").write_text("fake Python: must never execute")
    (home / ".venv/bin/python").chmod(0o755)
    (home / "VERSION").write_text(update.BASE_VERSION + "\n")
    (home / ".env").write_text("WARROOM_TEST_NUMBER=private-number\n")
    (home / "roster.xlsx").write_bytes(b"private roster")
    (home / "logs").mkdir()
    (home / "logs/watcher.log").write_text("existing watcher log")
    (app / "Contents/Resources/payload").mkdir(parents=True)
    (app / "Contents/Resources/payload/VERSION").write_text(update.BASE_VERSION + "\n")
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps({
        "CFBundleIdentifier": "com.equinix.warroombot", "CFBundleShortVersionString": update.BASE_VERSION,
        "CFBundleExecutable": "WarRoomBot"}))
    (app / "Contents/MacOS").mkdir()
    for name in ("WarRoomBot", "axctl"):
        (app / "Contents/MacOS" / name).write_bytes(b"signed executable must stay intact")
    source.mkdir()
    (source / "VERSION").write_text(update.SOURCE_VERSION + "\n")
    baseline, desired = {}, {}
    for relative, original_digest in update.BASE_HASHES.items():
        original = ("old " + relative + "\n").encode() if original_digest else None
        replacement = ("new " + relative + "\n").encode()
        baseline[relative] = update.digest(original) if original is not None else None
        desired[relative] = replacement
        destination = home / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if original is not None:
            destination.write_bytes(original)
            destination.chmod(0o640)
        candidate = source / relative
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(replacement)
    monkeypatch.setattr(update, "BASE_HASHES", baseline)
    archive = tmp_path / "published.zip"
    checksum = write_archive(source, archive)
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[0] == "/bin/ps":
            assert kwargs["timeout"] == 5
            return subprocess.CompletedProcess(command, 0, "", "")
        assert command[0] == str(home / ".venv/bin/python")
        assert command[1:7] == ["-E", "-s", "-B", "-m", "pytest", "-q"]
        assert command[-1] == "tests"
        assert kwargs["timeout"] == 120
        assert kwargs["cwd"] != home
        assert (kwargs["cwd"] / "VERSION").read_text().strip() == update.SOURCE_VERSION
        assert not any(key.startswith("WARROOM_") for key in kwargs["env"])
        assert kwargs["env"]["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
        assert "PYTHONPATH" not in kwargs["env"] and "PYTEST_ADDOPTS" not in kwargs["env"]
        assert Path(kwargs["env"]["HOME"]) != Path.home()
        return subprocess.CompletedProcess(command, 0, "123 passed in 1.0s\n", "")

    monkeypatch.setattr(update.subprocess, "run", run)
    monkeypatch.setattr(update, "run_test_suite", lambda command, **kwargs:
                        update.subprocess.run(command, timeout=120, **kwargs))
    return SimpleNamespace(home=home, app=app, source=source, archive=archive, checksum=checksum,
                           desired=desired, calls=calls, run=run)


def apply(box):
    return update.apply(box.home, box.app, box.checksum, archive=box.archive)


def test_patch_changes_only_allowlist_preserves_bundle_private_data_and_version(box, capsys, monkeypatch):
    before, bundle = inventory(box.home), inventory(box.app)
    monkeypatch.setenv("WARROOM_LIVE_CALLING", "true")
    monkeypatch.setenv("PYTHONPATH", "/unexpected/imports")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--malicious-option")
    backup = apply(box)
    record = json.loads((backup / "receipt.json").read_text())
    assert record["status"] == "applied" and record["patch"] == update.PATCH
    assert record["source_sha256"] == box.checksum
    for relative, data in before.items():
        assert (box.home / relative).read_bytes() == box.desired.get(relative, data)
    for relative, data in box.desired.items():
        assert (box.home / relative).read_bytes() == data
        if relative in before:
            assert (backup / relative).read_bytes() == before[relative]
            assert stat.S_IMODE((box.home / relative).stat().st_mode) == 0o640
            assert stat.S_IMODE((backup / relative).stat().st_mode) == 0o600
        else:
            assert record["files"][relative]["before"] is None
    assert inventory(box.app) == bundle
    assert (box.home / "VERSION").read_text().strip() == update.BASE_VERSION
    assert stat.S_IMODE(backup.stat().st_mode) == 0o700
    assert len(box.calls) == 5  # Two process snapshots on each side of the tests.
    text = capsys.readouterr().out
    assert "Applied runtime patch " + update.PATCH in text
    assert "Update / Repair from 20261013.3" in text and "Reapply this patch afterward" in text
    before_second = inventory(box.home)
    assert apply(box) is None
    assert inventory(box.home) == before_second
    assert "already applied; all target bytes match" in capsys.readouterr().out


def test_sha256_checked_before_archive_parsing_or_test_execution(box, monkeypatch):
    before = inventory(box.home)
    monkeypatch.setattr(update, "extract_archive", lambda *_: pytest.fail("unverified ZIP must not be parsed"))
    box.checksum = "0" * 64
    with pytest.raises(update.UpdateError, match="SHA-256 does not match"):
        apply(box)
    assert inventory(box.home) == before
    assert all(command[0] == "/bin/ps" for command, _ in box.calls)


@pytest.mark.parametrize("relative", ["warroom/cli.py", "tests/test_roster_presence.py"])
def test_modified_or_unexpected_existing_target_is_refused_before_tests(box, relative):
    (box.home / relative).write_bytes(b"local modification")
    before = inventory(box.home)
    with pytest.raises(update.UpdateError, match="modified or unexpected"):
        apply(box)
    assert inventory(box.home) == before
    assert all(command[0] == "/bin/ps" for command, _ in box.calls)


@pytest.mark.parametrize("relative", ["warroom/cli.py", "warroom", "tests/test_roster_presence.py", "logs"])
def test_symlink_targets_and_parent_directories_are_refused(box, tmp_path, relative):
    path = box.home / relative
    target = tmp_path / "symlink-target"
    if path.exists():
        path.rename(target)
    else:
        target.write_text("must not be overwritten")
    path.symlink_to(target, target_is_directory=target.is_dir())
    target_before = inventory(target) if target.is_dir() else target.read_bytes()
    with pytest.raises(update.UpdateError, match="symlink|real directory"):
        apply(box)
    assert (inventory(target) if target.is_dir() else target.read_bytes()) == target_before


@pytest.mark.parametrize("place", ["runtime", "plist-version", "plist-id", "payload"])
def test_wrong_installation_version_or_identity_refused(box, place):
    if place in ("runtime", "payload"):
        path = box.home / "VERSION" if place == "runtime" else box.app / "Contents/Resources/payload/VERSION"
        path.write_text("20261012.7\n")
    else:
        path = box.app / "Contents/Info.plist"
        metadata = plistlib.loads(path.read_bytes())
        metadata["CFBundleIdentifier" if place == "plist-id" else "CFBundleShortVersionString"] = "wrong"
        path.write_bytes(plistlib.dumps(metadata))
    before = inventory(box.home)
    with pytest.raises(update.UpdateError, match="requires|disagree"):
        apply(box)
    assert inventory(box.home) == before and box.calls == []


@pytest.mark.parametrize("failure", ["exit", "timeout"])
def test_failed_preflight_leaves_installation_untouched(box, monkeypatch, failure):
    before = inventory(box.home)
    def fail_tests(command, **kwargs):
        if command[0] == "/bin/ps":
            return box.run(command, **kwargs)
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 120)
        return subprocess.CompletedProcess(command, 1, "test failed", "")
    monkeypatch.setattr(update.subprocess, "run", fail_tests)
    with pytest.raises(update.UpdateError, match="full test suite (failed|exceeded)"):
        apply(box)
    assert inventory(box.home) == before


def test_target_changed_during_preflight_is_refused(box, monkeypatch):
    def concurrent_edit(command, **kwargs):
        result = box.run(command, **kwargs)
        if command[0] != "/bin/ps":
            (box.home / "warroom/cli.py").write_bytes(b"concurrent change")
        return result
    monkeypatch.setattr(update.subprocess, "run", concurrent_edit)
    with pytest.raises(update.UpdateError, match="modified or unexpected"):
        apply(box)
    assert (box.home / "warroom/cli.py").read_bytes() == b"concurrent change"
    assert not (box.home / "logs/runtime-updates").exists()


@pytest.mark.parametrize("fail_after_replace", [False, True])
def test_atomic_write_failure_rolls_back_all_files_and_removes_added_test(box, monkeypatch, fail_after_replace):
    before, bundle = inventory(box.home), inventory(box.app)
    original = update.atomic_write
    failed = False
    def faulty_write(path, data, mode):
        nonlocal failed
        if path == box.home / "tests/test_roster_presence.py" and not failed:
            failed = True
            if fail_after_replace:
                original(path, data, mode)
            raise OSError("simulated disk error")
        return original(path, data, mode)
    monkeypatch.setattr(update, "atomic_write", faulty_write)
    with pytest.raises(update.UpdateError, match="original files were restored"):
        apply(box)
    for relative, data in before.items():
        assert (box.home / relative).read_bytes() == data
    assert not (box.home / "tests/test_roster_presence.py").exists()
    assert inventory(box.app) == bundle
    receipt, = (box.home / "logs/runtime-updates").glob("*/receipt.json")
    assert json.loads(receipt.read_text())["status"] == "rolled-back"
    assert not list(box.home.glob("**/.*.runtime-update-*"))


def test_rollback_continues_past_an_unsafe_destination_and_retains_backups(box, monkeypatch, tmp_path):
    before = inventory(box.home)
    original = update.atomic_write
    outsider = tmp_path / "unrelated-file"
    outsider.write_bytes(b"must remain untouched")
    failed = False
    def concurrent_symlink(path, data, mode):
        nonlocal failed
        if path == box.home / "tests/test_roster_presence.py" and not failed:
            failed = True
            watcher = box.home / "warroom/watcher.py"
            watcher.unlink()
            watcher.symlink_to(outsider)
            raise OSError("simulated write failure and concurrent destination change")
        return original(path, data, mode)
    monkeypatch.setattr(update, "atomic_write", concurrent_symlink)
    with pytest.raises(update.UpdateError, match="manual restoration for warroom/watcher.py"):
        apply(box)
    assert outsider.read_bytes() == b"must remain untouched"
    for relative, data in before.items():
        if relative != "warroom/watcher.py":
            assert (box.home / relative).read_bytes() == data
    receipt, = (box.home / "logs/runtime-updates").glob("*/receipt.json")
    assert json.loads(receipt.read_text())["status"] == "rollback-failed"
    assert (receipt.parent / "warroom/watcher.py").read_bytes() == before["warroom/watcher.py"]


@pytest.mark.parametrize("name,command", [
    ("WarRoomBot", "/Applications/War Room Bot.app/Contents/MacOS/WarRoomBot"),
    ("Python", "/Library/Frameworks/Python -m warroom.cli watch --watch-token abc"),
    ("bash", "/bin/bash /Applications/War Room Bot.app/Contents/Resources/payload/app/wrb.sh setup"),
    ("bash", "/bin/bash ./install.sh"),
    ("axctl", "/Applications/War Room Bot.app/Contents/MacOS/axctl status"),
])
def test_process_check_refuses_native_app_watcher_setup_or_helper_without_stopping_them(monkeypatch, name, command):
    calls = []
    def ps(arguments, **kwargs):
        calls.append(arguments)
        assert arguments[:3] == ["/bin/ps", "-ww", "-axo"]
        assert kwargs["timeout"] == 5
        return subprocess.CompletedProcess(arguments, 0, "123 " + (name if arguments[-1].endswith("comm=") else command), "")
    monkeypatch.setattr(update.subprocess, "run", ps)
    with pytest.raises(update.UpdateError, match="Running process IDs: 123"):
        update.ensure_idle()
    assert len(calls) == 2


def test_process_inspection_timeout_fails_closed(monkeypatch):
    def failed(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 5)
    monkeypatch.setattr(update.subprocess, "run", failed)
    with pytest.raises(update.UpdateError, match="Could not inspect"):
        update.ensure_idle()


def test_new_running_watcher_after_preflight_prevents_mutation(box, monkeypatch):
    checks = 0
    def idle():
        nonlocal checks
        checks += 1
        if checks == 2:
            raise update.UpdateError("watcher appeared")
    monkeypatch.setattr(update, "ensure_idle", idle)
    before = inventory(box.home)
    with pytest.raises(update.UpdateError, match="watcher appeared"):
        apply(box)
    assert inventory(box.home) == before


@pytest.mark.parametrize("entry", ["/absolute", "WarRoomBot/../escape", "WarRoomBot//file",
                                   "WarRoomBot/./file", "AnotherRoot/file", "WarRoomBot\\file"])
def test_unsafe_archive_paths_rejected_before_extraction(tmp_path, entry):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr(entry, b"bad")
    destination = tmp_path / "extracted"
    with pytest.raises(update.UpdateError, match="unsafe path"):
        update.extract_archive(archive, destination)
    assert not destination.exists()


@pytest.mark.parametrize("mode", [stat.S_IFLNK | 0o777, stat.S_IFIFO | 0o600, stat.S_IFREG | 0o4755])
def test_archive_links_and_special_entries_rejected(tmp_path, mode):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as output:
        entry = zipfile.ZipInfo("WarRoomBot/unsafe")
        entry.external_attr = mode << 16
        output.writestr(entry, b"target")
    with pytest.raises(update.UpdateError, match="unsupported entry"):
        update.extract_archive(archive, tmp_path / "extracted")


def test_archive_duplicate_case_aliases_rejected(tmp_path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("WarRoomBot/warroom/cli.py", b"a")
        output.writestr("WarRoomBot/warroom/CLI.py", b"b")
    with pytest.raises(update.UpdateError, match="duplicate"):
        update.extract_archive(archive, tmp_path / "extracted")


def test_wrong_source_version_refused_before_preflight(box):
    (box.source / "VERSION").write_text("20261013.3\n")
    box.checksum = write_archive(box.source, box.archive)
    before = inventory(box.home)
    with pytest.raises(update.UpdateError, match="WarRoomBot/VERSION 20261013.4"):
        apply(box)
    assert inventory(box.home) == before
    assert all(command[0] == "/bin/ps" for command, _ in box.calls)


def test_https_download_checks_published_digest_before_use(tmp_path, monkeypatch):
    payload = b"verified source archive bytes"
    url = "https://raw.githubusercontent.com/kvenugopal-equinix/Codex/main/source.zip"
    class Response(io.BytesIO):
        headers = {"Content-Length": str(len(payload))}
        def geturl(self):
            return url
    def open_request(request, timeout):
        assert request.full_url == url and timeout == 10
        return Response(payload)
    monkeypatch.setattr(update.urllib.request, "build_opener", lambda *_: SimpleNamespace(open=open_request))
    destination = tmp_path / "download"
    update.acquire_archive(destination, update.digest(payload), archive_url=url)
    assert destination.read_bytes() == payload
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


@pytest.mark.parametrize("url", ["http://raw.githubusercontent.com/kvenugopal-equinix/Codex/file.zip",
                                 "https://example.org/file.zip",
                                 "https://raw.githubusercontent.com/other/repo/file.zip"])
def test_download_rejects_unexpected_origins(url):
    with pytest.raises(update.UpdateError, match="HTTPS"):
        update.validate_url(url)


def test_acquisition_size_and_deadline_limits(tmp_path, monkeypatch):
    monkeypatch.setattr(update, "MAX_ARCHIVE", 3)
    with pytest.raises(update.UpdateError, match="32 MiB"):
        update.copy_archive(io.BytesIO(b"too big"), tmp_path / "oversized", "0" * 64, float("inf"))
    with pytest.raises(update.UpdateError, match="deadline"):
        update.copy_archive(io.BytesIO(b"ok"), tmp_path / "expired", "0" * 64, 0)


def test_cli_requires_sha256():
    with pytest.raises(SystemExit) as error:
        update.main(["--archive", "published.zip"])
    assert error.value.code == 2


@pytest.mark.parametrize("interruption", ["timeout", "keyboard"])
def test_test_suite_abort_stops_only_its_new_process_group(tmp_path, monkeypatch, interruption):
    calls, signals, waits = [], [], []
    class Child:
        pid = 54321
        def wait(self, timeout):
            waits.append(timeout)
            if len(waits) == 1:
                if interruption == "keyboard":
                    raise KeyboardInterrupt
                raise subprocess.TimeoutExpired(["test-python"], timeout)
            if timeout == 0.5:
                raise subprocess.TimeoutExpired(["test-python"], timeout)
            return -9
    def popen(command, **kwargs):
        calls.append(command)
        assert kwargs["start_new_session"] is True
        assert kwargs["stdin"] == subprocess.DEVNULL
        return Child()
    monkeypatch.setattr(update.subprocess, "Popen", popen)
    monkeypatch.setattr(update.os, "killpg", lambda pid, number: signals.append((pid, number)))
    with pytest.raises(KeyboardInterrupt if interruption == "keyboard" else subprocess.TimeoutExpired):
        update.run_test_suite(["test-python", "-m", "pytest"], cwd=tmp_path, env={"HOME": str(tmp_path)})
    assert signals == [(54321, update.signal.SIGTERM), (54321, update.signal.SIGKILL)]
    assert waits == [120, 0.5, 1]
    assert calls == [["test-python", "-m", "pytest"]]


def test_test_suite_success_reads_bounded_output_without_signals(tmp_path, monkeypatch):
    class Child:
        pid, returncode = 54321, 0
        def wait(self, timeout):
            assert timeout == 120
            return 0
    def popen(command, **kwargs):
        assert kwargs["start_new_session"] is True
        kwargs["stdout"].write(b"x" * 100000 + b"\n123 passed\n")
        return Child()
    monkeypatch.setattr(update.subprocess, "Popen", popen)
    monkeypatch.setattr(update.os, "killpg", lambda *_: pytest.fail("successful tests must not signal anything"))
    result = update.run_test_suite(["test-python"], cwd=tmp_path, env={})
    assert result.returncode == 0 and result.stdout.endswith("123 passed\n")
    assert len(result.stdout) == 65536
