#!/usr/bin/env python3
"""Prepare a verified War Room Bot update for Finder; never write to Applications."""
import argparse
import hashlib
import importlib.util
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import stat
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile


NAME = "War Room Bot.app"
MAX_ARCHIVE = 32 * 1024 * 1024
MAX_EXPANDED = 128 * 1024 * 1024
MAX_ENTRIES = 10000


class UpdateError(RuntimeError):
    pass


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
    digest = hashlib.sha256()
    total = 0
    # read1 returns after one socket read, so a slowly streaming server cannot
    # postpone the overall deadline by keeping a large read() incomplete.
    read = getattr(stream, "read1", stream.read)
    with destination.open("xb") as output:
        os.fchmod(output.fileno(), 0o600)
        while True:
            if time.monotonic() > deadline:
                raise UpdateError("The update download exceeded its 60-second deadline.")
            block = read(64 * 1024)
            if not block:
                break
            total += len(block)
            if total > MAX_ARCHIVE:
                raise UpdateError("The update archive exceeds the 32 MiB limit.")
            digest.update(block)
            output.write(block)
    if digest.hexdigest() != expected:
        raise UpdateError("The update SHA-256 does not match. No archive code was loaded or app changed.")


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
        request = urllib.request.Request(validate_url(archive_url), headers={"User-Agent": "WarRoomBot-update"})
        with opener.open(request, timeout=10) as source:
            validate_url(source.geturl())
            size = source.headers.get("Content-Length")
            if size is not None and (not size.isdigit() or int(size) > MAX_ARCHIVE):
                raise UpdateError("The download reports an invalid or oversized archive.")
            copy_archive(source, destination, expected.lower(), deadline)


def extract_archive(archive, destination):
    """Validate all paths and modes before extraction; create symlinks only last."""
    # macOS exposes the temporary directory through /var -> /private/var.
    # Compare resolved link targets against the same canonical root.
    destination = Path(destination).resolve()
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        if not entries or len(entries) > MAX_ENTRIES:
            raise UpdateError("The update archive has an invalid number of entries.")
        records = {}
        expanded = 0
        for entry in entries:
            raw = entry.filename.rstrip("/")
            parts = raw.split("/")
            if (entry.orig_filename != entry.filename or "\\" in raw
                    or any(part in ("", ".", "..") for part in parts)
                    or parts[0] != NAME or entry.flag_bits & 1):
                raise UpdateError("The archive contains an unsafe path, unexpected root or encrypted entry.")
            path = PurePosixPath(raw)
            if path in records:
                raise UpdateError("The archive contains duplicate paths.")
            mode = entry.external_attr >> 16
            kind = stat.S_IFMT(mode)
            if kind == 0:
                kind = stat.S_IFDIR if entry.is_dir() else stat.S_IFREG
            if (kind not in (stat.S_IFDIR, stat.S_IFREG, stat.S_IFLNK)
                    or mode & 0o7000 or (entry.is_dir() and kind != stat.S_IFDIR)
                    or (path == PurePosixPath(NAME) and kind != stat.S_IFDIR)):
                raise UpdateError("The archive contains an unsupported entry type or privileged mode.")
            expanded += entry.file_size
            if entry.file_size > MAX_ARCHIVE or expanded > MAX_EXPANDED:
                raise UpdateError("The extracted update exceeds its size limit.")
            permissions = stat.S_IMODE(mode) or (0o755 if kind == stat.S_IFDIR else 0o644)
            records[path] = (entry, kind, permissions)
        for path in records:
            for parent in path.parents:
                if parent in records and records[parent][1] != stat.S_IFDIR:
                    raise UpdateError("The archive places a file underneath a non-directory entry.")
        destination.mkdir(mode=0o700)
        links = []
        folders = []
        for relative, (entry, kind, permissions) in records.items():
            path = destination.joinpath(*relative.parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            if kind == stat.S_IFDIR:
                path.mkdir(exist_ok=True)
                folders.append((path, permissions))
            elif kind == stat.S_IFLNK:
                if entry.file_size > 4096:
                    raise UpdateError("An archive symlink target is too long.")
                target = source.read(entry).decode("utf-8")
                if not target or "\0" in target or "\\" in target or PurePosixPath(target).is_absolute():
                    raise UpdateError("An archive symlink has an unsafe target.")
                resolved = (path.parent / target).resolve()
                if not resolved.is_relative_to(destination / NAME):
                    raise UpdateError("An archive symlink escapes the app bundle.")
                links.append((path, target))
            else:
                total = 0
                with source.open(entry) as input_file, path.open("xb") as output:
                    while True:
                        block = input_file.read(1024 * 1024)
                        if not block:
                            break
                        total += len(block)
                        if total > entry.file_size:
                            raise UpdateError("An archive entry expanded beyond its declared size.")
                        output.write(block)
                if total != entry.file_size:
                    raise UpdateError("An archive entry has an incorrect size.")
                path.chmod(permissions)
        for path, target in links:
            path.symlink_to(target)
        for path, _ in links:
            try:
                if not path.resolve().is_relative_to(destination / NAME):
                    raise UpdateError("An archive symlink chain escapes the app bundle.")
            except RuntimeError:
                raise UpdateError("An archive symlink chain is cyclic or unsafe.") from None
        for path, permissions in sorted(folders, key=lambda item: len(item[0].parts), reverse=True):
            path.chmod(permissions)
    app = destination / NAME
    if not app.is_dir() or app.is_symlink():
        raise UpdateError("The archive does not contain a complete app bundle.")
    return app


def load_repair(app):
    source = app / "Contents/Resources/payload/tools/repair_installed_app.py"
    if source.is_symlink() or not source.is_file():
        raise UpdateError("The verified archive does not include its repair utility.")
    specification = importlib.util.spec_from_file_location("warroombot_update_repair", source)
    module = importlib.util.module_from_spec(specification)
    # Import must not create __pycache__ inside the signed app bundle.
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        specification.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def prepare(app, expected_digest, *, archive=None, archive_url=None, reveal=True):
    container = Path(tempfile.mkdtemp(prefix="WarRoomBot-Finder-update-"))
    print("Preparing a verified update. The installed app is unchanged.", flush=True)
    try:
        downloaded = container / "update.zip"
        acquire_archive(downloaded, expected_digest, archive=archive, archive_url=archive_url)
        source = extract_archive(downloaded, container / "verified-archive")
        repair = load_repair(source)
        with repair.repair_signals():
            repair.ensure_idle()
            app = repair.installed_path(app)
            original_identity = repair.identity(app)
            candidate_identity = repair.identity(source)
            if any(candidate_identity[key] != original_identity[key] for key in ("name", "bundle_id")):
                raise UpdateError("The update changes the installed app's name or identifier.")
            if tuple(map(int, candidate_identity["version"].split("."))) < tuple(map(int, original_identity["version"].split("."))):
                raise UpdateError("The update is older than the installed app.")
            repair.verify_signature(app)
            original_content = repair.bounded_inventory(app)
            repair.verify_signature(source)
            candidate_content = repair.bounded_inventory(source)
            replacement, retained = container / "replacement", container / "original"
            replacement.mkdir(mode=0o700)
            retained.mkdir(mode=0o700)
            staged, backup = replacement / NAME, retained / NAME
            repair.checked(["/usr/bin/ditto", str(app), str(backup)], "Original-app backup", timeout=60)
            if repair.identity(backup) != original_identity or repair.bounded_inventory(backup) != original_content:
                raise UpdateError("The backup differs from the original installed app.")
            repair.verify_signature(backup)
            repair.checked(["/usr/bin/ditto", "--noextattr", "--noqtn", str(source), str(staged)],
                           "Metadata-clean update copy", timeout=60)
            if repair.identity(staged) != candidate_identity or repair.bounded_inventory(staged) != candidate_content:
                raise UpdateError("The clean update differs from the verified archive.")
            repair.verify_signature(staged)
            repair.ui_check(staged, candidate_identity, container / "preflight-data")
            repair.ensure_idle()
            if repair.identity(app) != original_identity or repair.bounded_inventory(app) != original_content:
                raise UpdateError("The installed app changed during preparation; no update was installed.")
            repair.verify_signature(app)
            receipt = repair.prepare_receipt(container, app, staged, backup, candidate_identity, candidate_content)
            (replacement / "Applications").symlink_to(app.parent, target_is_directory=True)
            verifier = source / "Contents/Resources/payload/tools/repair_installed_app.py"
            command = [sys.executable, str(verifier), "--verify-installed", str(receipt)]
            print("Update " + candidate_identity["version"] + " verified; Finder replacement is still pending.", flush=True)
            print("Verified replacement app: " + str(staged), flush=True)
            print("Original app backup: " + str(backup), flush=True)
            print("Drag War Room Bot onto the Applications shortcut and choose Replace. Keep its existing name.", flush=True)
            print("If Finder requests administrator authentication, use your approved credentials or administrator team.", flush=True)
            print("After replacing the app, quit it and run this verification command:\n" + " ".join(map(shlex.quote, command)), flush=True)
            print("Then open War Room Bot from Applications and choose Update / Repair to update its program files. Your roster, settings and logs are preserved.", flush=True)
            if reveal:
                result = repair.run(["/usr/bin/open", "-R", str(staged)], timeout=10)
                if result["timeout"] or result["code"] != 0:
                    print("Finder could not reveal the update automatically. Open the replacement path above.", flush=True)
            return receipt
    except BaseException:
        print("No installed app was replaced. Retained preparation folder: " + str(container), file=sys.stderr)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--archive-url", help="HTTPS raw GitHub URL of the published app ZIP")
    source.add_argument("--archive", type=Path, help="local copy of the published app ZIP")
    parser.add_argument("--sha256", required=True, help="published SHA-256 digest of the app ZIP")
    parser.add_argument("--app", type=Path, default=Path("/Applications") / NAME)
    parser.add_argument("--no-reveal", action="store_true", help="do not reveal the verified update in Finder")
    arguments = parser.parse_args(argv)
    try:
        if sys.platform != "darwin" or sys.version_info < (3, 9):
            raise UpdateError("Run this update preparation on your Mac with Python 3.9 or newer.")
        prepare(arguments.app, arguments.sha256, archive=arguments.archive,
                archive_url=arguments.archive_url, reveal=not arguments.no_reveal)
        return 0
    except KeyboardInterrupt:
        print("Update preparation cancelled. The installed app was not replaced.", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
        print("UPDATE: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
