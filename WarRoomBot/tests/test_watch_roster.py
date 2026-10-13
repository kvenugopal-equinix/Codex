"""Roster launch gates and process ownership with a fake worker, never Zoom or a phone call."""
import csv
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest


REPO = Path(__file__).resolve().parents[1]
NUMBER = "+14155550123"


def _exe(path, source):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    path.chmod(0o755)


@pytest.fixture
def launcher(tmp_path):
    root = tmp_path / "War Room Bot install"
    shutil.copytree(REPO / "warroom", root / "warroom", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(REPO / "watch.sh", root / "watch.sh")
    (root / "watch.sh").chmod(0o755)
    _exe(root / ".venv" / "bin" / "python", "#!/bin/sh\nexec " + shlex.quote(sys.executable) + ' "$@"\n')
    _exe(root / "testbin" / "pgrep", '#!/bin/sh\nif [ "${FAKE_WATCHER:-}" = on ]; then echo 4141; exit 0; fi\nexit 1\n')
    _exe(root / "tools" / "axctl", '#!/bin/sh\necho "{\\"ok\\":true}"\n')
    shutil.copy(REPO / "tools" / "set_env.py", root / "tools" / "set_env.py")
    # This fixture represents an updated install. Setup temporarily removes the
    # payload VERSION while running tests, when wrb.sh reports "dev".
    version = (REPO / "VERSION").read_text() if (REPO / "VERSION").exists() else "dev\n"
    (root / "VERSION").write_text(version)
    # Production roster selection, config and process manager remain intact. This CLI records the settings passed
    # to a watcher and optionally stays alive for Stop/Status testing. It has no UI, audio or dialer imports.
    (root / "warroom" / "cli.py").write_text(r'''
import json
import os
from pathlib import Path
import signal
import sys
import time
from .config import BASE, Settings
from .process import managed_watcher

assert sys.argv[1:3] == ["watch", "--watch-token"], sys.argv
settings = Settings.from_env()
signal.signal(signal.SIGINT, signal.default_int_handler)
with managed_watcher(BASE, sys.argv[3], "dry" if settings.dry_run else "live"):
    data = dict(dry_run=settings.dry_run, live_calling=settings.live_calling, target_mode=settings.target_mode,
                roster_calls=settings.allow_roster_calls, voice_in_dry_run=settings.voice_in_dry_run,
                trust_display_names=settings.trust_display_names, token=sys.argv[3],
                helper=os.environ.get("WARROOM_AXCTL", ""), parent_pid=os.getppid(),
                test_number=settings.test_number, zoom_invite=settings.zoom_invite,
                zoom_contact_lookup=settings.zoom_contact_lookup, test_zoom_contact=settings.test_zoom_contact,
                test_zoom_email=settings.test_zoom_email)
    (BASE / "worker-evidence.json").write_text(json.dumps(data))
    try:
        if os.environ.get("FAKE_BLOCK") == "yes":
            while True:
                time.sleep(0.04)
    except KeyboardInterrupt:
        pass
''')
    roster = root / "roster.csv"
    (root / ".env").write_text(
        f"WARROOM_ROSTER={roster}\nWARROOM_TEST_NUMBER={NUMBER}\n"
        "WARROOM_DRY_RUN=false\nWARROOM_LIVE_CALLING=true\nWARROOM_TARGET_MODE=test\n"
        "WARROOM_ALLOW_ROSTER_CALLS=false\nWARROOM_VOICE_IN_DRY_RUN=true\nWARROOM_TRUST_DISPLAY_NAMES=true\n")
    environment = {key: value for key, value in os.environ.items() if not key.startswith("WARROOM_")}
    environment["PATH"] = str(root / "testbin") + os.pathsep + environment["PATH"]
    workers = []

    def rows(entries=None):
        entries = entries if entries is not None else [dict(name="Selected Engineer", phone=NUMBER, priority=1)]
        headers = ["name", "zoom_email", "phone", "timezone", "days", "shift_start", "shift_end", "priority", "active", "notes"]
        defaults = dict(zoom_email="eng@example.com", timezone="Asia/Singapore", days="daily",
                        shift_start="00:00", shift_end="00:00", active="yes", notes="")
        with roster.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=headers)
            writer.writeheader()
            writer.writerows(dict(defaults, **entry) for entry in entries)

    def run(command, **overrides):
        return subprocess.run(["/bin/bash", str(root / "watch.sh"), command],
                              cwd=root, env=dict(environment, **overrides), capture_output=True, text=True, timeout=10)

    def start(command):
        worker = subprocess.Popen(["/bin/bash", str(root / "watch.sh"), command], cwd=root,
                                  env=dict(environment, FAKE_BLOCK="yes"), stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, start_new_session=True)
        workers.append(worker)
        return worker

    def run_wrapper(command, *args):
        return subprocess.run(["/bin/bash", str(REPO / "app" / "wrb.sh"), command, *args], cwd=root,
                              env=dict(environment, WARROOM_HOME=str(root)), capture_output=True, text=True, timeout=10)

    def start_wrapper(command, *args):
        worker = subprocess.Popen(["/bin/bash", str(REPO / "app" / "wrb.sh"), command, *args], cwd=root,
                                  env=dict(environment, FAKE_BLOCK="yes", WARROOM_HOME=str(root),
                                           WARROOM_APP_FOREGROUND="1"), stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
        workers.append(worker)
        return worker

    rows()
    try:
        yield SimpleNamespace(root=root, roster=roster, rows=rows, run=run, start=start, start_wrapper=start_wrapper, run_wrapper=run_wrapper)
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.send_signal(signal.SIGINT)
                try:
                    worker.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait(timeout=3)
            worker.communicate()


def test_roster_preview_uses_priority_and_ignores_placeholders_without_launching(launcher):
    launcher.rows([
        dict(name="<Placeholder>", phone="+65XXXXXXXX", priority=0),
        dict(name="Inactive Engineer", phone=NUMBER, priority=0, active="no"),
        dict(name="Backup Engineer", phone="+14155550124", priority=2),
        dict(name="Selected Engineer", phone=NUMBER, priority=1),
    ])
    before = (launcher.root / ".env").read_bytes()
    result = launcher.run("roster-preview", WARROOM_TARGET_MODE="test", WARROOM_DRY_RUN="false", WARROOM_LIVE_CALLING="true")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Selected on-duty engineer: Selected Engineer" in result.stdout and "Phone: " + NUMBER in result.stdout
    assert "Priority: 1" in result.stdout and "Asia/Singapore" in result.stdout
    assert "Backup Engineer" not in result.stdout and "Placeholder" not in result.stdout
    assert (launcher.root / ".env").read_bytes() == before
    assert not (launcher.root / "worker-evidence.json").exists()
    assert not (launcher.root / "logs").exists()


@pytest.mark.parametrize("command", ["roster-preview", "roster"])
@pytest.mark.parametrize("entries,reason", [
    ([], "nobody on duty"),
    ([dict(name="Off Duty", phone=NUMBER, priority=1, active="no")], "nobody on duty"),
    ([dict(name="<Placeholder>", phone="+65XXXXXXXX", priority=1)], "nobody on duty"),
    ([dict(name="Engineer", phone="not-a-number", priority=1)], "not an international number"),
    ([dict(name="Engineer", phone=NUMBER, priority=1, days="invalid")], "could not select"),
])
def test_roster_commands_refuse_unavailable_or_invalid_target_without_worker(launcher, command, entries, reason):
    launcher.rows(entries)
    result = launcher.run(command)
    assert result.returncode != 0 and reason in result.stdout
    assert not (launcher.root / "worker-evidence.json").exists()
    assert not (launcher.root / "logs").exists()


@pytest.mark.parametrize("command,dry,live,target,allow,mode", [
    ("start", False, True, "test", False, "live"),
    ("dry", True, False, "test", False, "dry"),
    ("roster", False, True, "roster", True, "roster-live"),
    ("roster-dry", True, False, "roster", True, "roster-dry"),
])
def test_watcher_commands_set_their_gates_and_managed_identity(launcher, command, dry, live, target, allow, mode):
    helper = str(launcher.root / "Bundled App.app" / "Contents" / "MacOS" / "axctl")
    result = launcher.run(command, WARROOM_AXCTL=helper)
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads((launcher.root / "worker-evidence.json").read_text())
    assert (data["dry_run"], data["live_calling"], data["target_mode"], data["roster_calls"]) == (dry, live, target, allow)
    assert data["trust_display_names"] is True and data["helper"] == helper
    if dry:
        assert data["voice_in_dry_run"] is False
    assert re.fullmatch(r"[0-9a-f]{32}", data["token"])
    assert (launcher.root / "logs" / "watcher.mode").read_text().strip() == mode
    assert not (launcher.root / "logs" / "watcher.pid.json").exists()


@pytest.mark.parametrize("command", ["start", "dry", "roster", "roster-dry"])
def test_every_launch_refuses_an_existing_watcher_before_work(launcher, command):
    launcher.roster.unlink()
    result = launcher.run(command, FAKE_WATCHER="on")
    assert result.returncode == 1 and "already running" in result.stdout
    assert "could not select" not in result.stdout
    assert not (launcher.root / "worker-evidence.json").exists()


@pytest.mark.parametrize("command,mode", [("roster", "roster-live"), ("roster-dry", "roster-dry")])
def test_roster_workers_can_be_stopped_by_validated_pid(launcher, command, mode):
    worker = launcher.start(command)
    record = launcher.root / "logs" / "watcher.pid.json"
    deadline = time.monotonic() + 5
    while not record.exists() and time.monotonic() < deadline:
        if worker.poll() is not None:
            pytest.fail("fake worker exited early: " + str(worker.communicate()))
        time.sleep(0.02)
    assert record.exists()
    assert json.loads(record.read_text())["pid"] == worker.pid
    assert (launcher.root / "logs" / "watcher.mode").read_text().strip() == mode
    status = launcher.run("status")
    assert status.returncode == 0 and status.stdout.strip() == f"ON (pid {worker.pid})"
    stopped = launcher.run("stop")
    assert stopped.returncode == 0 and "stop signal sent" in stopped.stdout
    assert worker.wait(timeout=5) == 0
    assert not record.exists() and launcher.run("status").stdout.strip() == "OFF"


@pytest.mark.parametrize("command,target,dry", [("roster-start", "roster", False),
                                               ("roster-dry", "roster", True),
                                               ("start", "test", False), ("dry", "test", True)])
def test_native_foreground_launch_keeps_the_apps_child_as_managed_worker(launcher, command, target, dry):
    settings_before = (launcher.root / ".env").read_bytes()
    entered = "+14155550456"
    worker = launcher.start_wrapper(command, *([entered] if command == "start" else []))
    record = launcher.root / "logs" / "watcher.pid.json"
    evidence = launcher.root / "worker-evidence.json"
    deadline = time.monotonic() + 5
    while not evidence.exists() and time.monotonic() < deadline:
        if worker.poll() is not None:
            pytest.fail("foreground fake worker exited early: " + str(worker.communicate()))
        time.sleep(0.02)
    assert record.exists() and evidence.exists()
    data = json.loads(evidence.read_text())
    assert json.loads(record.read_text())["pid"] == worker.pid
    assert data["parent_pid"] == os.getpid()
    assert (data["target_mode"], data["dry_run"]) == (target, dry)
    if command == "start":
        assert data["test_number"] == entered
    assert (launcher.root / ".env").read_bytes() == settings_before
    assert worker.poll() is None
    assert launcher.run("stop").returncode == 0
    assert worker.wait(timeout=5) == 0
    assert not record.exists()


@pytest.mark.parametrize("command,mode", [("start", "live"), ("roster-start", "roster-live")])
@pytest.mark.parametrize("route", ["phone", "contacts-phone"])
def test_native_start_carries_per_run_calling_options_to_managed_worker_and_status(launcher, command, mode, route):
    settings = launcher.root / ".env"
    with settings.open("a") as stream:
        stream.write("WARROOM_ZOOM_INVITE=" + ("true" if route == "phone" else "false") + "\n"
                     "WARROOM_ZOOM_CONTACT_LOOKUP=email\nWARROOM_TEST_ZOOM_CONTACT=Saved Name\n"
                     "WARROOM_TEST_ZOOM_EMAIL=saved@example.com\n")
    before = settings.read_bytes()
    args = (["+14155550456"] if command == "start" else []) + ["--calling", route]
    if command == "start" and route == "contacts-phone":
        args += ["--test-contact", "  Run Contact  "]
    worker = launcher.start_wrapper(command, *args)
    evidence = launcher.root / "worker-evidence.json"
    deadline = time.monotonic() + 5
    while not evidence.exists() and time.monotonic() < deadline:
        if worker.poll() is not None:
            pytest.fail("foreground fake worker exited early: " + str(worker.communicate()))
        time.sleep(0.02)
    assert evidence.exists()
    data = json.loads(evidence.read_text())
    assert data["zoom_invite"] is (route == "contacts-phone")
    assert data["zoom_contact_lookup"] == "name" and data["test_zoom_email"] == ""
    assert data["test_zoom_contact"] == ("Run Contact" if command == "start" and route == "contacts-phone" else "")
    route_file = launcher.root / "logs" / "watcher.calling"
    assert route_file.read_text() == f"{worker.pid} {mode} {route}\n"
    assert settings.read_bytes() == before
    status = launcher.run_wrapper("status")
    assert status.returncode == 0, status.stdout + status.stderr
    assert "Calling this run: " + ("Phone only." if route == "phone" else "Zoom Contacts + phone.") in status.stdout
    assert "Saved Name" not in status.stdout and "Run Contact" not in status.stdout
    stopped = launcher.run_wrapper("stop")
    assert stopped.returncode == 0, stopped.stdout + stopped.stderr
    assert worker.wait(timeout=5) == 0
    assert not route_file.exists()
    assert settings.read_bytes() == before
