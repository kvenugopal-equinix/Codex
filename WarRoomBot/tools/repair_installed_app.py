#!/usr/bin/env python3
"""Stage and test a metadata-clean, byte-identical native app before replacing it."""
import argparse
from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import signal
import stat
import subprocess
import sys
import tempfile


NAME = "War Room Bot.app"
PYTHON = re.compile(r"python(?:\d+(?:\.\d+)*)?", re.I)


class RepairError(RuntimeError):
    pass


@contextmanager
def blocked_signals():
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


@contextmanager
def repair_signals():
    def interrupted(_number, _frame):
        raise KeyboardInterrupt

    previous = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
    for number in previous:
        signal.signal(number, interrupted)
    try:
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def run(command, timeout=15):
    """Bound child execution, output and cleanup; never signal other processes."""
    def tail(stream):
        length = stream.seek(0, 2)
        stream.seek(max(0, length - 1048576))
        return stream.read(1048576).decode("utf-8", errors="replace"), length > 1048576

    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output, stderr=errors)
        expired = False
        unreaped = False
        try:
            child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            expired = True
            try:
                child.terminate()
            except OSError:
                pass
            try:
                child.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                try:
                    child.kill()
                except OSError:
                    pass
                try:
                    child.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    unreaped = True
        finally:
            if sys.exc_info()[0] is KeyboardInterrupt:
                try:
                    child.kill()
                    child.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        stdout, stdout_truncated = tail(output)
        stderr, stderr_truncated = tail(errors)
        return {"code": child.poll(), "timeout": expired, "unreaped": unreaped,
                "stdout": stdout, "stderr": stderr,
                "truncated": stdout_truncated or stderr_truncated}


def checked(command, description, timeout=15):
    result = run(command, timeout)
    if result["timeout"] or result["code"] != 0:
        why = "timed out" if result["timeout"] else "failed"
        detail = (result["stderr"] or result["stdout"]).strip()[-2000:]
        raise RepairError("{} {}.{}".format(description, why, "\n" + detail if detail else ""))
    return result


def inventory(app):
    """Hash every relative name, file byte, symlink target and POSIX mode, never xattrs."""
    app = Path(app)
    records = []
    pending = [app]
    while pending:
        path = pending.pop()
        details = path.lstat()
        record = [path.relative_to(app).as_posix(), stat.S_IMODE(details.st_mode)]
        if stat.S_ISLNK(details.st_mode):
            record.extend(["link", os.readlink(path)])
        elif stat.S_ISDIR(details.st_mode):
            record.append("directory")
            pending.extend(path.iterdir())
        elif stat.S_ISREG(details.st_mode):
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            record.extend(["file", digest.hexdigest()])
        else:
            raise RepairError("The app contains an unsupported filesystem entry.")
        records.append(record)
    data = json.dumps(sorted(records), separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return {"sha256": hashlib.sha256(data).hexdigest(), "entries": len(records)}


def bounded_inventory(app):
    result = checked([sys.executable, str(Path(__file__).resolve()), "--_inventory", str(app)],
                     "Bundle content inventory", timeout=30)
    try:
        value = json.loads(result["stdout"])
    except ValueError:
        raise RepairError("The bundle inventory returned an invalid report.") from None
    if not isinstance(value, dict) or not re.fullmatch(r"[0-9a-f]{64}", value.get("sha256", "")):
        raise RepairError("The bundle inventory returned an invalid digest.")
    return value


def identity(app):
    with (app / "Contents/Info.plist").open("rb") as stream:
        metadata = plistlib.load(stream)
    identifier = metadata.get("CFBundleIdentifier")
    version = metadata.get("CFBundleShortVersionString")
    if (metadata.get("CFBundleName") != "War Room Bot"
            or metadata.get("CFBundleDisplayName") != "War Room Bot"
            or metadata.get("CFBundleExecutable") != "WarRoomBot"
            or not isinstance(identifier, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{2,254}", identifier)
            or not isinstance(version, str) or not re.fullmatch(r"\d{8}\.\d+", version)):
        raise RepairError("Choose the native War Room Bot app with its original name and valid identifier.")
    if tuple(map(int, version.split("."))) < (20261012, 7):
        raise RepairError("This repair requires version 20261012.7 or newer with isolated UI checks.")
    payload = app / "Contents/Resources/payload"
    if (payload / "VERSION").read_text(encoding="utf-8").strip() != version:
        raise RepairError("The app and bundled payload versions disagree.")
    source = (payload / "app/WarRoomBot.swift").read_text(encoding="utf-8")
    if "--ui-smoke-test" not in source or "--ui-smoke-home" not in source:
        raise RepairError("The bundled controller does not support the required isolated UI check.")
    for name in ("WarRoomBot", "axctl"):
        path = app / "Contents/MacOS" / name
        if path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
            raise RepairError("The native executable or bundled helper is unavailable.")
    return {"name": "War Room Bot", "bundle_id": identifier, "version": version}


def ensure_idle():
    names = run(["/bin/ps", "-ww", "-axo", "pid=,comm="], timeout=5)
    commands = run(["/bin/ps", "-ww", "-axo", "pid=,args="], timeout=5)
    if any(result["code"] != 0 or result["timeout"] or result.get("truncated", False)
           for result in (names, commands)):
        # Never print raw process arguments, including on inspection failure.
        raise RepairError("Could not completely inspect running apps and watchers; nothing was replaced.")
    processes = {}
    for line in names["stdout"].splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) == 2 and fields[0].isdigit():
            processes[int(fields[0])] = Path(fields[1]).name
    blocked = {pid for pid, name in processes.items() if name in ("WarRoomBot", "axctl")}
    for line in commands["stdout"].splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) != 2 or not fields[0].isdigit():
            continue
        pid, command = int(fields[0]), fields[1]
        if PYTHON.fullmatch(processes.get(pid, "")) and re.search(r"(?:^|\s)-m\s+warroom\.cli\s+watch(?:\s|$)", command):
            blocked.add(pid)
        if processes.get(pid) == "applet" and "War Room Bot.app/Contents/MacOS/applet" in command:
            blocked.add(pid)
    if blocked:
        raise RepairError("Quit War Room Bot and stop all watchers before repairing it. Running process IDs: "
                          + ", ".join(map(str, sorted(blocked))) + ". No process was stopped by this tool.")


def verify_signature(app):
    checked(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)],
            "App signature verification", timeout=5)


def ui_check(app, expected, home):
    result = checked([str(app / "Contents/MacOS/WarRoomBot"), "--ui-smoke-test",
                      "--ui-smoke-home", str(home)], "Isolated app window check", timeout=15)
    reports = [line[len("WRB_UI_SMOKE "):] for line in result["stdout"].splitlines()
               if line.startswith("WRB_UI_SMOKE ")]
    try:
        report = json.loads(reports[-1]) if reports else None
    except ValueError:
        report = None
    if not isinstance(report, dict) or any(report.get(key) is not True
                                          for key in ("ok", "window_visible", "installation_checked")):
        raise RepairError("The app did not confirm a responsive window and completed startup check.")
    if any(report.get(key) != value for key, value in expected.items()):
        raise RepairError("The tested app's name, identifier or version changed.")
    paths = {"native_executable": app / "Contents/MacOS/WarRoomBot",
             "payload": app / "Contents/Resources/payload",
             "helper": app / "Contents/MacOS/axctl", "home": home}
    for key, path in paths.items():
        value = report.get(key)
        if not isinstance(value, str) or not Path(value).is_absolute() or Path(value).resolve() != path.resolve():
            raise RepairError("The UI check reported a different executable, payload or isolated data path.")


def atomic_exchange(first, second):
    """macOS atomic exchange keeps the original path present throughout replacement."""
    library = ctypes.CDLL(None, use_errno=True)
    exchange = library.renamex_np
    exchange.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    exchange.restype = ctypes.c_int
    if exchange(os.fsencode(first), os.fsencode(second), 2) != 0:  # RENAME_SWAP
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def repair(app):
    app = Path(app)
    if not app.is_absolute() or app.name != NAME or app.is_symlink() or not app.is_dir():
        raise RepairError("Use the absolute path to the installed War Room Bot.app, not a symlink.")
    app = app.resolve()
    ensure_idle()
    expected = identity(app)
    verify_signature(app)
    original_content = bounded_inventory(app)
    if not os.access(app.parent, os.W_OK | os.X_OK):
        raise RepairError("The app's parent folder is not writable. This tool will not use sudo or change permissions. "
                          "Use Finder to install a tested metadata-clean copy, keeping the app name and a backup.")
    container = Path(tempfile.mkdtemp(prefix=".WarRoomBot-repair-", dir=str(app.parent)))
    replacement_folder, backup_folder = container / "replacement", container / "original"
    replacement_folder.mkdir(mode=0o700)
    backup_folder.mkdir(mode=0o700)
    staged, backup = replacement_folder / NAME, backup_folder / NAME
    swapped = False
    original_location = staged
    print("Staging a metadata-clean copy; the installed app is unchanged.", flush=True)
    try:
        checked(["/usr/bin/ditto", "--noextattr", "--noqtn", str(app), str(staged)],
                "Metadata-clean copy", timeout=60)
        if identity(staged) != expected or bounded_inventory(staged) != original_content:
            raise RepairError("The staged copy does not preserve every bundle byte, path, symlink and mode.")
        verify_signature(staged)
        ui_check(staged, expected, container / "preflight-data")
        ensure_idle()
        if identity(app) != expected or bounded_inventory(app) != original_content:
            raise RepairError("The installed app changed during preflight; nothing was replaced.")
        verify_signature(app)
        print("Staged checks passed. Replacing the same installed path atomically…", flush=True)
        with blocked_signals():
            atomic_exchange(app, staged)
            swapped = True
        with blocked_signals():
            staged.rename(backup)
            original_location = backup
        if identity(app) != expected or bounded_inventory(app) != original_content:
            raise RepairError("The installed copy differs from the tested bundle.")
        verify_signature(app)
        ui_check(app, expected, container / "installed-check-data")
    except BaseException:
        if swapped:
            try:
                with blocked_signals():
                    atomic_exchange(app, original_location)
                    swapped = False
            except (OSError, AttributeError) as rollback_error:
                print("Automatic rollback failed. Original app retained at: " + str(original_location), file=sys.stderr)
                raise RepairError("Rollback failed: {}. Keep this backup; do not retry replacement.".format(rollback_error)) from None
            print("The original installed app was restored. The tested copy remains at: " + str(original_location), file=sys.stderr)
        else:
            print("The installed app was not replaced. Diagnostic copy: " + str(container), file=sys.stderr)
        raise
    print("Metadata-clean app installed with unchanged code, name, identifier and version.", flush=True)
    print("Original app backup: " + str(backup), flush=True)
    print("Open the exact app from Applications in Finder. Its direct window check passed; normal Finder launch and Accessibility still need confirmation.", flush=True)
    return backup


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=Path("/Applications") / NAME)
    parser.add_argument("--_inventory", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args._inventory is not None:
            print(json.dumps(inventory(args._inventory), sort_keys=True))
            return 0
        if sys.platform != "darwin":
            raise RepairError("Run this repair on the Mac where the installed app stalls.")
        if sys.version_info < (3, 9):
            raise RepairError("Python 3.9 or newer is required.")
        with repair_signals():
            repair(args.app)
        return 0
    except KeyboardInterrupt:
        print("Repair cancelled. No existing app or watcher was signalled.", file=sys.stderr)
        return 130
    except (OSError, ValueError, RepairError, plistlib.InvalidFileException, AttributeError) as error:
        print("REPAIR: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
