"""Identify and stop the actual watcher, independent of macOS Python launchers."""
import argparse
from contextlib import contextmanager
import errno
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
from typing import Optional


_TOKEN = re.compile(r"[0-9a-f]{32}")
_PYTHON = re.compile(r"python(?:[0-9]+(?:\.[0-9]+)*)?", re.IGNORECASE)
_RECORD = "watcher.pid.json"


class WatcherAlreadyRunning(RuntimeError):
    """Another watcher holds this installation's process lock."""


def _canonical_root(root: Path) -> Path:
    return Path(root).resolve()


def _valid_token(token) -> bool:
    return isinstance(token, str) and _TOKEN.fullmatch(token) is not None


def _read_record(root: Path):
    try:
        with (root / "logs" / _RECORD).open() as stream:
            # A corrupt file must not make process inspection consume arbitrary data.
            raw = stream.read(8193)
    except (FileNotFoundError, UnicodeError):
        return None
    if len(raw) > 8192:
        return None
    try:
        record = json.loads(raw)
    except (ValueError, UnicodeError):
        return None
    if not isinstance(record, dict):
        return None
    if (record.get("root") != str(root)
            or type(record.get("pid")) is not int or record["pid"] <= 1
            or not _valid_token(record.get("token"))
            or record.get("mode") not in ("dry", "live")):
        return None
    return record


def _write_record(root: Path, record: dict) -> None:
    logs = root / "logs"
    fd, temporary = tempfile.mkstemp(prefix="watcher.pid.", suffix=".tmp", dir=str(logs))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(record, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, logs / _RECORD)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


@contextmanager
def managed_watcher(root: Path, token: str, mode: str):
    """Publish this Python worker while holding its installation's exclusive lock.

    The launcher supplies a fresh UUID hex token and includes it in the worker's
    argv. Status and Stop use that token to reject stale or reused process IDs.
    """
    if not _valid_token(token):
        raise ValueError("watch token must contain exactly 32 lowercase hexadecimal characters")
    if mode not in ("dry", "live"):
        raise ValueError("watcher mode must be dry or live")
    root = _canonical_root(root)
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(str(logs / "watcher.lock"), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(lock_fd, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EAGAIN):
                raise WatcherAlreadyRunning("a watcher is already running from this installation") from None
            raise
        record = {"pid": os.getpid(), "token": token, "root": str(root), "mode": mode}
        try:
            _write_record(root, record)
            yield
        finally:
            # A later owner's record must survive an old worker's cleanup.
            current = _read_record(root)
            if current is not None and all(current.get(key) == record[key]
                                           for key in ("pid", "token", "root")):
                try:
                    (logs / _RECORD).unlink()
                except FileNotFoundError:
                    pass
    finally:
        os.close(lock_fd)


def _ps_field(pid: int, field: str) -> Optional[str]:
    result = subprocess.run(["ps", "-ww", "-p", str(pid), "-o", field + "="],
                            capture_output=True, text=True, timeout=5)
    if result.returncode == 1:
        return None  # Process exited before inspection.
    if result.returncode != 0:
        raise RuntimeError("could not inspect the watcher process (ps exited with status {})".format(
            result.returncode))
    return result.stdout.strip() or None


def running_pid(root: Path) -> Optional[int]:
    """Return a validated Python watcher PID, never a caffeinate wrapper PID."""
    root = _canonical_root(root)
    record = _read_record(root)
    if record is None:
        return None
    pid = record["pid"]
    executable = _ps_field(pid, "comm")
    if executable is None or _PYTHON.fullmatch(Path(executable).name) is None:
        return None
    command = _ps_field(pid, "args")
    suffix = " -m warroom.cli watch --watch-token " + record["token"]
    if command is None or not command.endswith(suffix):
        return None
    # argv[0] can be a framework Python path rather than the venv path, and either
    # path can contain spaces. There are no arguments before the module selector.
    argv0 = command[:-len(suffix)]
    if _PYTHON.fullmatch(Path(argv0).name) is None:
        return None
    return pid


def request_stop(root: Path) -> Optional[int]:
    """Send SIGINT only to a validated worker; never force termination."""
    pid = running_pid(root)
    if pid is None:
        return None
    try:
        os.kill(pid, signal.SIGINT)
    except ProcessLookupError:
        return None
    return pid


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="warroom.process")
    parser.add_argument("command", choices=("status", "stop"))
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            pid = running_pid(args.root)
            print("ON (pid {})".format(pid) if pid is not None else "OFF")
        else:
            pid = request_stop(args.root)
            print("stop signal sent to watcher (pid {})".format(pid)
                  if pid is not None else "was not running")
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        # Inspection errors must never look like OFF or reveal the process argv.
        print("WATCHER CONTROL: {}".format(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
