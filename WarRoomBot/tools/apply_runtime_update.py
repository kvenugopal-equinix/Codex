#!/usr/bin/env python3
"""Apply the selected-engineer presence fix without replacing the signed Mac app."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile


BASE_VERSION = "20261013.3"
SOURCE_VERSION = "20261013.4"
PATCH = "selected-engineer-presence-20261013.4"
NAME = "War Room Bot.app"
# Exact bytes from source commit b47fd6fc6f5367be8066c48a79fcbf907ffdc7ca.
# Replace existing files only: the old app's merge-based Update / Repair must
# restore a compatible baseline. New regression tests run only in staging.
BASE_HASHES = {
    "warroom/cli.py": "302880d8703b56fbb61d686b9167d931e2a541eb6ffdc1bf18a2dd13fe26a120",
    "warroom/watcher.py": "bc5f57888c2f692b07c6a56bd4a8f6edfa86c8d89190cb203e111406532a879f",
    "tests/test_participant_discovery.py": "534c21c4ed3a142cc8ab143a4a26ee9cc426d2ef1956579a1b57ecf0d8ccfab3",
    "tests/test_watcher.py": "633f3f020b8538b628d404d85e0a08549888d3e64807b60ca08068993ea8549b",
}
MAX_ARCHIVE = 32 * 1024 * 1024
MAX_EXPANDED = 128 * 1024 * 1024
MAX_ENTRIES = 10000


class UpdateError(RuntimeError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def validate_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != "raw.githubusercontent.com"
            or not parsed.path.startswith("/kvenugopal-equinix/Codex/")
            or parsed.query or parsed.fragment):
        raise UpdateError("Use an HTTPS raw.githubusercontent.com URL in kvenugopal-equinix/Codex.")
    return url


class UpdateRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        validate_url(new_url)
        return super().redirect_request(request, file, code, message, headers, new_url)


def copy_archive(stream, destination, expected, deadline):
    checksum, total = hashlib.sha256(), 0
    read = getattr(stream, "read1", stream.read)
    with destination.open("xb") as output:
        os.fchmod(output.fileno(), 0o600)
        while True:
            if time.monotonic() > deadline:
                raise UpdateError("Source archive acquisition exceeded its 60-second deadline.")
            block = read(64 * 1024)
            if not block:
                break
            total += len(block)
            if total > MAX_ARCHIVE:
                raise UpdateError("The source archive exceeds the 32 MiB limit.")
            checksum.update(block)
            output.write(block)
    if checksum.hexdigest() != expected:
        raise UpdateError("SHA-256 does not match; no archive code was loaded or installed files changed.")


def acquire_archive(destination, expected, *, archive=None, archive_url=None):
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        raise UpdateError("--sha256 must be the published 64-character SHA-256 digest.")
    if (archive is None) == (archive_url is None):
        raise UpdateError("Provide exactly one of --archive or --archive-url.")
    deadline = time.monotonic() + 60
    if archive is not None:
        archive = Path(archive)
        details = archive.stat()
        if not stat.S_ISREG(details.st_mode) or details.st_size > MAX_ARCHIVE:
            raise UpdateError("The local archive must be a regular file no larger than 32 MiB.")
        with archive.open("rb") as source:
            copy_archive(source, destination, expected.lower(), deadline)
    else:
        opener = urllib.request.build_opener(UpdateRedirect())
        request = urllib.request.Request(validate_url(archive_url), headers={"User-Agent": "WarRoomBot-runtime-update"})
        with opener.open(request, timeout=10) as source:
            validate_url(source.geturl())
            size = source.headers.get("Content-Length")
            if size is not None and (not size.isdigit() or int(size) > MAX_ARCHIVE):
                raise UpdateError("The download reports an invalid or oversized archive.")
            copy_archive(source, destination, expected.lower(), deadline)


def extract_archive(archive, destination):
    """Validate the complete source archive before writing any extracted files."""
    with zipfile.ZipFile(archive) as source:
        entries, records, seen, expanded = source.infolist(), {}, set(), 0
        if not entries or len(entries) > MAX_ENTRIES:
            raise UpdateError("The source archive has an invalid number of entries.")
        for entry in entries:
            raw = entry.filename[:-1] if entry.is_dir() else entry.filename
            parts = raw.split("/")
            if (entry.orig_filename != entry.filename or "\\" in raw
                    or any(part in ("", ".", "..") for part in parts)
                    or parts[0] != "WarRoomBot" or entry.flag_bits & 1):
                raise UpdateError("The source archive contains an unsafe path or unexpected root.")
            path = PurePosixPath(raw)
            # Case-insensitive Macs must not interpret two archive entries as one.
            if str(path).casefold() in seen:
                raise UpdateError("The source archive contains duplicate paths.")
            seen.add(str(path).casefold())
            mode = entry.external_attr >> 16
            kind = stat.S_IFMT(mode) or (stat.S_IFDIR if entry.is_dir() else stat.S_IFREG)
            if (kind not in (stat.S_IFDIR, stat.S_IFREG) or mode & 0o7000
                    or entry.is_dir() != (kind == stat.S_IFDIR)
                    or (raw == "WarRoomBot" and kind != stat.S_IFDIR)):
                raise UpdateError("The source archive contains a symlink or unsupported entry type or mode.")
            expanded += entry.file_size
            if entry.file_size > MAX_ARCHIVE or expanded > MAX_EXPANDED:
                raise UpdateError("The expanded source archive exceeds its size limit.")
            records[path] = (entry, kind, stat.S_IMODE(mode) or (0o755 if entry.is_dir() else 0o644))
        kinds = {str(path).casefold(): value[1] for path, value in records.items()}
        for path in records:
            if any(kinds.get(str(parent).casefold(), stat.S_IFDIR) != stat.S_IFDIR for parent in path.parents):
                raise UpdateError("The source archive places a file under a non-directory entry.")
        destination.mkdir(mode=0o700)
        for relative, (entry, kind, mode) in records.items():
            path = destination.joinpath(*relative.parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            if kind == stat.S_IFDIR:
                path.mkdir(exist_ok=True)
            else:
                data = source.read(entry)
                if len(data) != entry.file_size:
                    raise UpdateError("A source archive file has an incorrect size.")
                with path.open("xb") as output:
                    output.write(data)
                path.chmod(mode)
    root = destination / "WarRoomBot"
    if (root / "VERSION").read_text(encoding="utf-8").strip() != SOURCE_VERSION:
        raise UpdateError("The source archive must contain WarRoomBot/VERSION " + SOURCE_VERSION + ".")
    return root


def regular_file(root, relative, *, absent=False):
    """Refuse destination symlinks, including directories above each target file."""
    path = root
    for part in Path(relative).parts[:-1]:
        path /= part
        if path.is_symlink() or not path.is_dir():
            raise UpdateError("Expected a real directory: " + str(path))
    path = root / relative
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise UpdateError("Expected a regular file, not a symlink: " + str(path))
    if not path.exists() and not absent:
        raise UpdateError("Required installed file is missing: " + str(path))
    return path


def check_installation(home, app):
    if home.is_symlink() or not home.is_dir():
        raise UpdateError("--home must be the existing runtime directory, not a symlink.")
    if (home.resolve().is_relative_to(app.resolve())
            or home.resolve().is_relative_to(Path("/Applications"))
            or any(parent.suffix == ".app" for parent in (home.resolve(), *home.resolve().parents))):
        raise UpdateError("The runtime directory must be outside Applications and app bundles.")
    if regular_file(home, "VERSION").read_text(encoding="utf-8").strip() != BASE_VERSION:
        raise UpdateError("This patch requires installed runtime VERSION " + BASE_VERSION + ".")
    with regular_file(app, "Contents/Info.plist").open("rb") as stream:
        identity = plistlib.load(stream)
    if (identity.get("CFBundleIdentifier") != "com.equinix.warroombot"
            or identity.get("CFBundleShortVersionString") != BASE_VERSION
            or identity.get("CFBundleExecutable") != "WarRoomBot"):
        raise UpdateError("This patch requires the native com.equinix.warroombot app version " + BASE_VERSION + ".")
    if regular_file(app, "Contents/Resources/payload/VERSION").read_text(encoding="utf-8").strip() != BASE_VERSION:
        raise UpdateError("The installed app and bundled payload versions disagree.")
    python = home / ".venv/bin/python"
    if not python.is_file() or not os.access(python, os.X_OK):
        raise UpdateError("The existing runtime .venv/bin/python is unavailable; no packages were installed.")
    return python


def ensure_idle():
    results = []
    for field in ("comm", "args"):
        try:
            result = subprocess.run(["/bin/ps", "-ww", "-axo", "pid=," + field + "="],
                                    capture_output=True, text=True, timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise UpdateError("Could not inspect running apps and watchers; no runtime update was applied.") from None
        if result.returncode or len(result.stdout) > 2 * 1024 * 1024:
            raise UpdateError("Could not completely inspect running apps and watchers.")
        results.append(result.stdout)
    names = {}
    for line in results[0].splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) == 2 and fields[0].isdigit():
            names[int(fields[0])] = Path(fields[1]).name
    blocked = {pid for pid, name in names.items() if name in ("WarRoomBot", "axctl")}
    for line in results[1].splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) != 2 or not fields[0].isdigit():
            continue
        pid, command = int(fields[0]), fields[1]
        if pid == os.getpid():
            continue
        if (re.search(r"(?:^|\s)-m\s+warroom\.cli\s+watch(?:\s|$)", command)
                or re.search(r"(?:^|[/\s])wrb\.sh\s+setup(?:-bg)?(?:\s|$)", command)
                or re.search(r"(?:^|[/\s])install\.sh(?:\s|$)", command)
                or (names.get(pid) == "applet" and "War Room Bot.app/Contents/MacOS/applet" in command)):
            blocked.add(pid)
    if blocked:
        raise UpdateError("Quit War Room Bot and stop watchers/setup before applying this patch. Running process IDs: "
                          + ", ".join(map(str, sorted(blocked))) + ". No process was stopped.")


def run_test_suite(command, *, cwd, env):
    """Bound staged tests and clean up only their newly created process group."""
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        child = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                 stdout=output, stderr=errors, start_new_session=True)
        try:
            with rollback_signals():
                child.wait(timeout=120)
        except BaseException:
            # pytest can own shell/Python test children; stopping only pytest
            # would leave those running against a disappearing temporary tree.
            for number, timeout in ((signal.SIGTERM, 0.5), (signal.SIGKILL, 1)):
                try:
                    os.killpg(child.pid, number)
                except ProcessLookupError:
                    pass
                try:
                    child.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    pass
            raise
        tails = []
        for stream in (output, errors):
            length = stream.seek(0, 2)
            stream.seek(max(0, length - 65536))
            tails.append(stream.read(65536).decode("utf-8", errors="replace"))
        return subprocess.CompletedProcess(command, child.returncode, *tails)


def preflight(source, python, container):
    private_home, temporary = container / "test-home", container / "test-tmp"
    private_home.mkdir(mode=0o700)
    temporary.mkdir(mode=0o700)
    environment = {"HOME": str(private_home), "TMPDIR": str(temporary),
                   "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "en_US.UTF-8",
                   "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    command = [str(python), "-E", "-s", "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
               "--basetemp=" + str(temporary / "pytest"), "tests"]
    try:
        result = run_test_suite(command, cwd=source, env=environment)
    except subprocess.TimeoutExpired:
        raise UpdateError("The isolated full test suite exceeded 120 seconds; installed files are unchanged.") from None
    if result.returncode:
        raise UpdateError("The isolated full test suite failed; installed files are unchanged.\n"
                          + (result.stdout + result.stderr)[-6000:])
    summary = result.stdout.strip().splitlines()
    print("Isolated full test suite passed" + (": " + summary[-1] if summary else "."), flush=True)


def plan_changes(home, source):
    changes = {}
    for relative, expected in BASE_HASHES.items():
        path = regular_file(home, relative)
        desired = regular_file(source, relative).read_bytes()
        current = path.read_bytes()
        if current == desired:
            continue
        if digest(current) != expected:
            raise UpdateError("Refusing modified or unexpected installed file: " + relative)
        mode = stat.S_IMODE(path.stat().st_mode)
        changes[relative] = (current, desired, mode)
    return changes


def atomic_write(path, data, mode):
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".runtime-update-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def rollback_signals():
    def interrupted(signum, _frame):
        raise UpdateError("Runtime update interrupted by signal " + str(signum) + ".")
    saved = {number: signal.signal(number, interrupted) for number in (signal.SIGTERM, signal.SIGHUP)}
    try:
        yield
    finally:
        for number, handler in saved.items():
            signal.signal(number, handler)


def install_changes(home, changes, checksum):
    folder = home
    for name in ("logs", "runtime-updates"):
        folder /= name
        if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
            raise UpdateError("Runtime backup location must be a real directory: " + str(folder))
        folder.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-")
    backup = Path(tempfile.mkdtemp(prefix=stamp, dir=folder))
    receipt = {"patch": PATCH, "source_sha256": checksum.lower(), "installed_version": BASE_VERSION,
               "status": "prepared", "files": {}}
    for relative, (before, after, mode) in changes.items():
        # The app runs pytest from the runtime root during Update / Repair.
        # Backup test files must never be collected alongside installed tests.
        backup_relative = relative + ".before"
        receipt["files"][relative] = {"before": digest(before),
                                      "after": digest(after), "mode": mode, "backup": backup_relative}
        saved = backup / backup_relative
        saved.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        atomic_write(saved, before, 0o600)
    receipt_path = backup / "receipt.json"
    atomic_write(receipt_path, json.dumps(receipt, indent=2).encode() + b"\n", 0o600)
    changed = []
    try:
        with rollback_signals():
            for relative, (before, after, mode) in changes.items():
                path = regular_file(home, relative)
                current = path.read_bytes()
                if current != before:
                    raise UpdateError("Installed file changed during patching: " + relative)
                # Include the target before replacement so an interruption just
                # after rename still restores it.
                changed.append(relative)
                atomic_write(path, after, mode)
            for relative, (_, after, _) in changes.items():
                if regular_file(home, relative).read_bytes() != after:
                    raise UpdateError("Patched file did not verify: " + relative)
            receipt["status"] = "applied"
            atomic_write(receipt_path, json.dumps(receipt, indent=2).encode() + b"\n", 0o600)
    except BaseException as error:
        failures = []
        for relative in reversed(changed):
            before, _, mode = changes[relative]
            try:
                path = regular_file(home, relative, absent=True)
                atomic_write(path, before, mode)
            except (OSError, UpdateError):
                failures.append(relative)
        receipt["status"] = "rollback-failed" if failures else "rolled-back"
        try:
            atomic_write(receipt_path, json.dumps(receipt, indent=2).encode() + b"\n", 0o600)
        except OSError:
            pass
        if failures:
            raise UpdateError("Rollback needs manual restoration for " + ", ".join(failures)
                              + ". Original files: " + str(backup)) from error
        raise UpdateError("Runtime patch failed; original files were restored. Backup: " + str(backup)
                          + ". " + str(error)) from error
    return backup


def apply(home, app, expected_digest, *, archive=None, archive_url=None):
    home, app = Path(home).expanduser().absolute(), Path(app).expanduser().absolute()
    python = check_installation(home, app)
    ensure_idle()
    with tempfile.TemporaryDirectory(prefix="WarRoomBot-runtime-update-") as temporary:
        container = Path(temporary)
        downloaded = container / "source.zip"
        acquire_archive(downloaded, expected_digest, archive=archive, archive_url=archive_url)
        source = extract_archive(downloaded, container / "source")
        changes = plan_changes(home, source)
        preflight(source, python, container)
        ensure_idle()
        check_installation(home, app)
        if plan_changes(home, source) != changes:
            raise UpdateError("Installed files changed during preflight; no runtime update was applied.")
        if changes:
            backup = install_changes(home, changes, expected_digest)
            print("Applied runtime patch " + PATCH + ".", flush=True)
            print("Replaced files: " + ", ".join(changes), flush=True)
            print("Original files and receipt: " + str(backup), flush=True)
        else:
            backup = None
            print("Runtime patch " + PATCH + " is already applied; all target bytes match.", flush=True)
        print("Installed VERSION remains " + BASE_VERSION + "; the app bundle and signed helper were not modified.", flush=True)
        print("The app's Update / Repair from " + BASE_VERSION + " restores the bundled runtime. Reapply this patch afterward.", flush=True)
        return backup


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--archive", type=Path, help="local published source ZIP")
    source.add_argument("--archive-url", help="HTTPS raw GitHub URL of the published source ZIP")
    parser.add_argument("--sha256", required=True, help="published SHA-256 digest of the source ZIP")
    parser.add_argument("--home", type=Path, default=Path.home() / "WarRoomBot")
    parser.add_argument("--app", type=Path, default=Path("/Applications") / NAME)
    arguments = parser.parse_args(argv)
    try:
        if sys.platform != "darwin" or sys.version_info < (3, 9):
            raise UpdateError("Run this runtime patch on your Mac with Python 3.9 or newer.")
        apply(arguments.home, arguments.app, arguments.sha256,
              archive=arguments.archive, archive_url=arguments.archive_url)
        return 0
    except KeyboardInterrupt:
        print("Runtime update cancelled.", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
        print("RUNTIME UPDATE: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
