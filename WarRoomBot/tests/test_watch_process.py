"""Real launcher/worker lifecycle with isolated, fake Zoom and keep-awake tools."""
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest


REPO = Path(__file__).resolve().parents[1]


def _executable(path, contents):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    path.chmod(0o755)


def _wait_for(predicate, description, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.04)
    pytest.fail("timed out waiting for " + description)


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.fixture
def install(tmp_path):
    root = tmp_path / "War Room Bot install"
    shutil.copytree(REPO / "warroom", root / "warroom",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(REPO / "watch.sh", root / "watch.sh")
    (root / ".env").write_text("")
    tools = root / "test tools"
    tools.mkdir()
    evidence = root / "test evidence"
    evidence.mkdir()
    # A venv shim can exec a framework/system Python with a different argv[0].
    # Stop must identify the worker without relying on the launcher's venv path.
    _executable(root / ".venv" / "bin" / "python",
                "#!/bin/sh\nexec " + shlex.quote(sys.executable) + ' "$@"\n')
    # Do not inspect or interact with any watcher outside this temporary install.
    _executable(tools / "pgrep", "#!/bin/sh\nexit 1\n")
    _executable(tools / "caffeinate", "#!" + sys.executable + "\n" + r'''
import json
import os
from pathlib import Path
import signal
import sys
import time

directory = Path(os.environ["WRB_TEST_EVIDENCE"])
worker = int(sys.argv[-1])
(directory / "observer.json").write_text(json.dumps({"pid": os.getpid(), "args": sys.argv[1:]}))
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
try:
    # Also leave if a failed test kills its own worker; no orphan is left behind.
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            os.kill(worker, 0)
        except ProcessLookupError:
            break
        time.sleep(0.04)
finally:
    (directory / "observer.exited").write_text("yes\n")
''')
    # Python loads this before -m warroom.cli, so imported CLI aliases also see
    # the fakes. There is no real Accessibility helper in this temporary tree.
    (tools / "sitecustomize.py").write_text(r'''
import os
from pathlib import Path
import time

import warroom.roster as roster
import warroom.ui_backend as ui
import warroom.voice as voice

directory = Path(os.environ["WRB_TEST_EVIDENCE"])
mode = os.environ.get("WRB_TEST_PREFLIGHT", "ready")
roster.load_roster = lambda *_: []
ui.input_available = lambda: mode != "untrusted"

def prepare_meeting():
    (directory / "preflight.entered").write_text("yes\n")
    if mode == "blocked":
        while True:
            time.sleep(0.04)
    if mode == "missing":
        raise ui.UiUnavailable("fake meeting is missing")
    return "Zoom Meeting"

ui.prepare_meeting = prepare_meeting
ui.read_participants = lambda: [ui.UiParticipant("Test Bot", "self", True, True)]

def unexpected_audio(*_args, **_kwargs):
    (directory / "unexpected.audio").write_text("called\n")
    raise AssertionError("audio must never run in this isolated dry-run test")

voice.speak = unexpected_audio
voice.speak_in_meeting = unexpected_audio
''')
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith("WARROOM_"):
            environment.pop(key)
    environment.update(PATH=str(tools) + os.pathsep + environment.get("PATH", ""),
                       PYTHONPATH=os.pathsep.join((str(tools), str(root))),
                       WRB_TEST_EVIDENCE=str(evidence),
                       WARROOM_POLL_SECONDS="1", PYTHONUNBUFFERED="1")
    workers = []

    def run(command):
        return subprocess.run(["/bin/bash", str(root / "watch.sh"), command],
                              cwd=root, env=environment, capture_output=True,
                              text=True, timeout=10)

    def start(preflight="ready"):
        child_environment = dict(environment, WRB_TEST_PREFLIGHT=preflight)
        worker = subprocess.Popen(["/bin/bash", str(root / "watch.sh"), "dry"],
                                  cwd=root, env=child_environment,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, start_new_session=True,
                                  preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_IGN))
        workers.append(worker)
        return worker

    box = SimpleNamespace(root=root, evidence=evidence,
                          record=root / "logs" / "watcher.pid.json", run=run, start=start)
    try:
        yield box
    finally:
        # Only test-owned PIDs are cleaned up, never a process-name/group match.
        for worker in workers:
            if worker.poll() is None:
                worker.send_signal(signal.SIGINT)
                try:
                    worker.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait(timeout=3)
            worker.communicate()


def _record(box):
    try:
        return json.loads(box.record.read_text())
    except FileNotFoundError:
        return None


def _observer(box):
    try:
        return json.loads((box.evidence / "observer.json").read_text())
    except (FileNotFoundError, ValueError):
        return None


def _assert_finished(box, worker):
    stdout, stderr = worker.communicate(timeout=8)
    assert worker.returncode == 0, (stdout, stderr)
    assert "stopped" in stdout
    assert not box.record.exists()
    observer = _wait_for(lambda: _observer(box), "fake caffeinate startup record")
    _wait_for(lambda: (box.evidence / "observer.exited").exists(), "fake caffeinate exit")
    assert not _alive(observer["pid"])
    status = box.run("status")
    assert status.returncode == 0, status.stderr
    assert status.stdout.strip() == "OFF"
    assert not (box.evidence / "unexpected.audio").exists()


def test_background_dry_worker_with_ignored_sigint_stops_by_its_actual_pid(install):
    worker = install.start()
    _wait_for(lambda: (install.evidence / "preflight.entered").exists(), "worker preflight")
    record = _wait_for(lambda: _record(install), "worker PID record")
    assert record["pid"] == worker.pid
    assert record["root"] == str(install.root.resolve())
    assert record["mode"] == "dry"
    command = subprocess.run(["ps", "-ww", "-p", str(worker.pid), "-o", "args="],
                             capture_output=True, text=True, check=True).stdout
    assert str(install.root / ".venv" / "bin" / "python") not in command
    assert " -m warroom.cli watch --watch-token " + record["token"] in command
    observer = _wait_for(lambda: _observer(install), "fake caffeinate startup record")
    assert observer["args"] == ["-dis", "-w", str(worker.pid)]
    assert observer["pid"] != worker.pid
    status = install.run("status")
    assert status.returncode == 0, status.stderr
    assert status.stdout.strip() == "ON (pid {})".format(worker.pid)
    stopped = install.run("stop")
    assert stopped.returncode == 0, stopped.stderr
    assert stopped.stdout.strip() == "stop signal sent to watcher (pid {})".format(worker.pid)
    _assert_finished(install, worker)


def test_stop_interrupts_a_worker_blocked_during_preflight(install):
    worker = install.start("blocked")
    _wait_for(lambda: (install.evidence / "preflight.entered").exists(), "blocked preflight")
    _wait_for(lambda: _observer(install), "fake caffeinate startup record")
    assert install.run("status").stdout.strip() == "ON (pid {})".format(worker.pid)
    stopped = install.run("stop")
    assert stopped.returncode == 0, stopped.stderr
    assert str(worker.pid) in stopped.stdout
    _assert_finished(install, worker)


@pytest.mark.parametrize("preflight, message", [("untrusted", "NOT TRUSTED"),
                                                ("missing", "fake meeting is missing")])
def test_rejected_preflight_leaves_no_worker_record_or_keep_awake_process(install, preflight, message):
    worker = install.start(preflight)
    stdout, stderr = worker.communicate(timeout=8)
    assert worker.returncode == 1, (stdout, stderr)
    assert message in stdout
    assert not install.record.exists()
    observer = _observer(install)
    if observer is not None:
        _wait_for(lambda: not _alive(observer["pid"]), "fake caffeinate termination")
    assert install.run("status").stdout.strip() == "OFF"
    assert not (install.evidence / "unexpected.audio").exists()
