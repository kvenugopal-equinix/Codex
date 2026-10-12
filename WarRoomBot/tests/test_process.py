"""Worker identity and stop behavior, without the real Zoom or Accessibility."""
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid

import pytest

from warroom import process


TOKEN = "a" * 32


def record(install_root, **changes):
    data = {"pid": 4141, "token": TOKEN, "root": str(install_root.resolve()), "mode": "dry"}
    data.update(changes)
    (install_root / "logs").mkdir(parents=True, exist_ok=True)
    (install_root / "logs" / "watcher.pid.json").write_text(json.dumps(data))
    return data


def fake_ps(monkeypatch, *, comm="Python", args=None, returncode=0):
    if args is None:
        args = "/Library/Frameworks/Python.framework/Versions/3.9/Python -m warroom.cli watch --watch-token " + TOKEN
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert command[:5] == ["ps", "-ww", "-p", "4141", "-o"]
        assert kwargs["capture_output"] and kwargs["text"] and kwargs["timeout"] == 5
        text = comm if command[5] == "comm=" else args
        return subprocess.CompletedProcess(command, returncode, stdout=text + "\n", stderr="")

    monkeypatch.setattr(process.subprocess, "run", run)
    return calls


@pytest.mark.parametrize("comm,argv0", [
    ("Python", "/Library/Frameworks/Python.framework/Versions/3.9/Python"),
    ("/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/Python",
     "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/Python"),
    ("python3.9", "/Users/Test User/War Room Bot/.venv/bin/python3.9"),
    ("/Applications/My Python/python3", "/Applications/My Python/python3"),
])
def test_framework_python_and_paths_with_spaces_identify_worker(tmp_path, monkeypatch, comm, argv0):
    root = tmp_path / "War Room Bot"
    record(root)
    fake_ps(monkeypatch, comm=comm, args=argv0 + " -m warroom.cli watch --watch-token " + TOKEN)
    assert process.running_pid(root) == 4141


def test_caffeinate_wrapper_never_counts_as_worker(tmp_path, monkeypatch):
    record(tmp_path)
    calls = fake_ps(monkeypatch, comm="/usr/bin/caffeinate",
                    args="caffeinate -dis /Users/me/WarRoomBot/.venv/bin/python -m warroom.cli watch --watch-token " + TOKEN)
    assert process.running_pid(tmp_path) is None
    assert len(calls) == 1


@pytest.mark.parametrize("args", [
    "/venv/bin/python -m warroom.cli watch --watch-token " + "b" * 32,
    "/venv/bin/python -m warroom.cli watch",
    "/venv/bin/python -m warroom.cli watch --watch-token " + TOKEN + " extra",
    "/venv/bin/python -m warroom.cli dial --watch-token " + TOKEN,
    "/venv/bin/python helper.py -m warroom.cli watch --watch-token " + TOKEN,
])
def test_stale_or_different_command_is_not_a_watcher(tmp_path, monkeypatch, args):
    record(tmp_path)
    fake_ps(monkeypatch, args=args)
    assert process.running_pid(tmp_path) is None


def test_dead_process_is_off(tmp_path, monkeypatch):
    record(tmp_path)
    fake_ps(monkeypatch, returncode=1)
    assert process.running_pid(tmp_path) is None


@pytest.mark.parametrize("change", [
    {"pid": True}, {"pid": "4141"}, {"pid": 1}, {"pid": 0},
    {"token": "short"}, {"token": "A" * 32}, {"mode": "other"},
    {"root": "/some/other/install"},
])
def test_invalid_and_foreign_records_are_ignored_without_ps(tmp_path, monkeypatch, change):
    record(tmp_path, **change)
    monkeypatch.setattr(process.subprocess, "run", lambda *a, **k: pytest.fail("must not inspect foreign or invalid PID"))
    assert process.running_pid(tmp_path) is None


@pytest.mark.parametrize("raw", ["not JSON", "[]", "null", "x" * 8193])
def test_corrupt_records_are_off(tmp_path, raw):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "watcher.pid.json").write_text(raw)
    assert process.running_pid(tmp_path) is None


def test_missing_record_is_off(tmp_path):
    assert process.running_pid(tmp_path) is None


def test_stop_sends_sigint_only_to_valid_worker(tmp_path, monkeypatch):
    record(tmp_path)
    fake_ps(monkeypatch)
    sent = []
    monkeypatch.setattr(process.os, "kill", lambda pid, sig: sent.append((pid, sig)))
    assert process.request_stop(tmp_path) == 4141
    assert sent == [(4141, signal.SIGINT)]


def test_stop_does_not_signal_reused_pid(tmp_path, monkeypatch):
    record(tmp_path)
    fake_ps(monkeypatch, comm="sleep", args="sleep 100")
    monkeypatch.setattr(process.os, "kill", lambda *a: pytest.fail("must not signal reused PID"))
    assert process.request_stop(tmp_path) is None


def test_stop_handles_worker_exiting_before_signal(tmp_path, monkeypatch):
    record(tmp_path)
    fake_ps(monkeypatch)
    monkeypatch.setattr(process.os, "kill", lambda *a: (_ for _ in ()).throw(ProcessLookupError()))
    assert process.request_stop(tmp_path) is None


def test_stop_permission_errors_are_reported(tmp_path, monkeypatch, capsys):
    record(tmp_path)
    fake_ps(monkeypatch)
    monkeypatch.setattr(process.os, "kill", lambda *a: (_ for _ in ()).throw(PermissionError("permission denied")))
    assert process.main(["stop", "--root", str(tmp_path)]) == 1
    out = capsys.readouterr()
    assert not out.out and "permission denied" in out.err


def test_ps_failure_is_reported_without_command_line(tmp_path, monkeypatch, capsys):
    record(tmp_path)
    fake_ps(monkeypatch, returncode=2)
    assert process.main(["status", "--root", str(tmp_path)]) == 1
    out = capsys.readouterr()
    assert not out.out and "status 2" in out.err and TOKEN not in out.err


def test_command_line_outputs(tmp_path, monkeypatch, capsys):
    assert process.main(["status", "--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "OFF\n"
    assert process.main(["stop", "--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "was not running\n"
    record(tmp_path)
    fake_ps(monkeypatch)
    monkeypatch.setattr(process.os, "kill", lambda *a: None)
    assert process.main(["status", "--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "ON (pid 4141)\n"
    assert process.main(["stop", "--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "stop signal sent to watcher (pid 4141)\n"


def test_manager_records_real_pid_and_private_permissions_then_cleans_up(tmp_path):
    with process.managed_watcher(tmp_path / "nested" / "..", TOKEN, "live"):
        root = tmp_path.resolve()
        path = root / "logs" / "watcher.pid.json"
        assert json.loads(path.read_text()) == {"pid": os.getpid(), "root": str(root), "token": TOKEN, "mode": "live"}
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE((root / "logs" / "watcher.lock").stat().st_mode) == 0o600
        assert not list((root / "logs").glob("*.tmp"))
    assert not path.exists()


def test_manager_exception_cleans_up_and_releases_lock(tmp_path):
    with pytest.raises(RuntimeError, match="test failure"):
        with process.managed_watcher(tmp_path, TOKEN, "dry"):
            raise RuntimeError("test failure")
    assert not (tmp_path / "logs" / "watcher.pid.json").exists()
    with process.managed_watcher(tmp_path, "b" * 32, "dry"):
        pass


def test_interrupt_during_registration_cleans_record_and_releases_lock(tmp_path, monkeypatch):
    real_write = process._write_record

    def write_then_interrupt(root, data):
        real_write(root, data)
        raise KeyboardInterrupt

    monkeypatch.setattr(process, "_write_record", write_then_interrupt)
    with pytest.raises(KeyboardInterrupt):
        with process.managed_watcher(tmp_path, TOKEN, "dry"):
            pytest.fail("interrupted registration must not enter watcher body")
    assert not (tmp_path / "logs" / "watcher.pid.json").exists()
    monkeypatch.setattr(process, "_write_record", real_write)
    with process.managed_watcher(tmp_path, "b" * 32, "dry"):
        pass


def test_lock_contention_keeps_first_record(tmp_path):
    with process.managed_watcher(tmp_path, TOKEN, "dry"):
        with pytest.raises(process.WatcherAlreadyRunning):
            with process.managed_watcher(tmp_path, "b" * 32, "live"):
                pytest.fail("second manager must not start")
        assert json.loads((tmp_path / "logs" / "watcher.pid.json").read_text())["token"] == TOKEN


def test_cleanup_does_not_delete_another_launch_record(tmp_path):
    with process.managed_watcher(tmp_path, TOKEN, "dry"):
        replacement = record(tmp_path, token="b" * 32)
    assert json.loads((tmp_path / "logs" / "watcher.pid.json").read_text()) == replacement


@pytest.mark.parametrize("token,mode", [("invalid", "dry"), ("A" * 32, "dry"), (TOKEN, "other")])
def test_manager_validates_before_writing(tmp_path, token, mode):
    with pytest.raises(ValueError):
        with process.managed_watcher(tmp_path, token, mode):
            pass
    assert not (tmp_path / "logs").exists()


def test_real_worker_registration_and_sigint_stop(tmp_path):
    # A tiny standalone CLI has the exact production argv but no Zoom code. The
    # real ps and os.kill calls establish that the recorded PID is the worker.
    package = tmp_path / "package" / "warroom"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    shutil.copy(process.__file__, package / "process.py")
    root = tmp_path / "install with spaces"
    token = uuid.uuid4().hex
    (package / "cli.py").write_text(
        "import os, signal, sys, time\n"
        "from pathlib import Path\n"
        "from .process import managed_watcher\n"
        "signal.signal(signal.SIGINT, signal.default_int_handler)\n"
        "with managed_watcher(Path(os.environ['TEST_WATCH_ROOT']), sys.argv[3], 'dry'):\n"
        "    try:\n"
        "        while True: time.sleep(30)\n"
        "    except KeyboardInterrupt:\n"
        "        pass\n")
    env = dict(os.environ, TEST_WATCH_ROOT=str(root))
    child = subprocess.Popen([sys.executable, "-m", "warroom.cli", "watch", "--watch-token", token],
                             cwd=str(package.parent), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 5
        while not (root / "logs" / "watcher.pid.json").exists() and time.monotonic() < deadline:
            if child.poll() is not None:
                pytest.fail("worker failed to start: " + child.communicate()[1].decode())
            time.sleep(0.02)
        assert process.running_pid(root) == child.pid
        assert process.request_stop(root) == child.pid
        assert child.wait(timeout=5) == 0
        assert process.running_pid(root) is None
        assert not (root / "logs" / "watcher.pid.json").exists()
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=5)
