"""app/wrb.sh: the control script behind War Room Bot.app. Runs it against a throwaway install folder and a fake
pgrep/axctl, so nothing here touches the real home folder, the real Zoom, or a watcher that is running on this Mac."""
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parent.parent
WRB = REPO / "app" / "wrb.sh"
NUM = "+14155550123"

FAKE_PGREP = r"""#!/bin/sh
# pgrep -f PATTERN. Mode comes from $FAKE_WATCHERS: none | mine | foreign
case "$FAKE_WATCHERS" in
  mine)    echo 4141; exit 0 ;;
  foreign) case "$2" in /*|\\/*) exit 1 ;; *) echo 4242; exit 0 ;; esac ;;
esac
exit 1
"""


def _exe(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def box(tmp_path):
    """A fake finished install plus a way to run wrb.sh against it."""
    home = tmp_path / "install"
    shutil.copytree(REPO / "warroom", home / "warroom", ignore=shutil.ignore_patterns("__pycache__"))
    (home / "tools").mkdir()
    shutil.copy(REPO / "tools" / "set_env.py", home / "tools" / "set_env.py")
    shutil.copy(REPO / "watch.sh", home / "watch.sh")
    (home / "watch.sh").chmod(0o755)
    _exe(home / ".venv" / "bin" / "python", f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    _exe(home / "tools" / "axctl", '#!/bin/sh\necho "{\\"ok\\": ${AX_TRUSTED:-false}}"\n')
    (home / ".env").write_text("WARROOM_TEST_NUMBER=   # my phone\n")
    (home / "VERSION").write_text((REPO / "VERSION").read_text())        # the repo has no VERSION file, so the payload version is "dev"
    _exe(tmp_path / "fakebin" / "pgrep", FAKE_PGREP)

    env = {k: v for k, v in os.environ.items() if not k.startswith("WARROOM_")}
    env.update(HOME=str(tmp_path / "home"), WARROOM_HOME=str(home), FAKE_WATCHERS="none",
               PATH=f"{tmp_path / 'fakebin'}:{os.environ['PATH']}")
    (tmp_path / "home").mkdir()

    class Box:
        pass
    b = Box()
    b.home, b.env, b.tmp = home, env, tmp_path

    def run(*args, **over):
        e = dict(env, **over)
        return subprocess.run(["/bin/bash", str(WRB), *args], env=e, capture_output=True, text=True, timeout=60)
    b.run = run
    return b


def test_unknown_command_prints_usage_and_exits_2(box):
    r = box.run("frobnicate")
    assert r.returncode == 2
    assert "wrb.sh state" in r.stdout and "start | dry" in r.stdout


def test_state_follows_the_install(box, tmp_path):
    empty = tmp_path / "nothing-here"
    assert box.run("state", WARROOM_HOME=str(empty)).stdout.strip() == "NOT_INSTALLED"
    assert box.run("state").stdout.strip() == "READY"
    (box.home / "VERSION").write_text("20200101\n")
    assert box.run("state").stdout.strip() == "UPDATE_AVAILABLE"


def test_state_is_setting_up_only_while_a_wrb_process_holds_the_pid_file(box):
    (box.home / "logs").mkdir()
    (box.home / "logs" / "setup.pid").write_text("99999999\n")            # not a running process
    assert box.run("state").stdout.strip() == "READY"
    holder = subprocess.Popen(["/bin/bash", "-c", f"exec -a 'bash {WRB} setup' sleep 30"])
    try:
        (box.home / "logs" / "setup.pid").write_text(f"{holder.pid}\n")
        assert box.run("state").stdout.strip() == "SETTING_UP"
    finally:
        holder.kill()
        holder.wait()


def test_a_script_inside_a_folder_with_spaces_reports_the_payload_version(tmp_path):
    app = tmp_path / "War Room Bot.app" / "Contents" / "Resources" / "payload"
    (app / "app").mkdir(parents=True)
    shutil.copy(WRB, app / "app" / "wrb.sh")
    (app / "VERSION").write_text("20261009\n")
    r = subprocess.run(["/bin/bash", str(app / "app" / "wrb.sh"), "version"], capture_output=True, text=True)
    assert (r.returncode, r.stdout.strip()) == (0, "20261009")


def test_commands_refuse_before_set_up(box, tmp_path):
    away = {"WARROOM_HOME": str(tmp_path / "nothing-here")}
    for cmd in ("start", "dry", "stop", "status", "check", "recent", "number", "trusted"):
        r = box.run(cmd, **away)
        assert r.returncode == 20, cmd
        assert "not set up" in r.stdout, cmd


def test_set_number_accepts_a_good_number_and_normalises_it(box):
    r = box.run("set-number", "+1 (415) 555-0123")
    assert r.returncode == 0, r.stdout + r.stderr
    assert box.run("number").stdout.strip() == NUM
    assert box.run("has-number").returncode == 0


@pytest.mark.parametrize("bad", ["12345", "+0123456789", "+1415; touch pwned", "$(touch pwned)", "", "+" + "1" * 20])
def test_set_number_rejects_bad_values_and_leaves_the_file_alone(box, bad):
    before = (box.home / ".env").read_text()
    r = box.run("set-number", bad)
    assert r.returncode != 0
    assert (box.home / ".env").read_text() == before
    assert not (box.tmp / "pwned").exists() and not (box.home / "pwned").exists()
    assert box.run("has-number").returncode != 0


def test_has_number_is_false_until_one_is_set(box):
    assert box.run("has-number").returncode != 0
    box.run("set-number", NUM)
    assert box.run("has-number").returncode == 0


def test_status_off_on_and_on_from_outside_the_app(box):
    assert box.run("status").stdout.splitlines()[0] == "OFF"
    (box.home / "logs").mkdir()
    (box.home / "logs" / "watcher.mode").write_text("live\n")
    r = box.run("status", FAKE_WATCHERS="mine")
    assert r.stdout.startswith("ON, live in test mode")
    (box.home / "logs" / "watcher.mode").write_text("dry\n")
    assert box.run("status", FAKE_WATCHERS="mine").stdout.startswith("ON, dry run")
    (box.home / "logs" / "watcher.mode").unlink()
    assert box.run("status", FAKE_WATCHERS="mine").stdout.startswith("ON (started outside this app)")


def test_status_off_mentions_a_foreign_watcher(box):
    out = box.run("status", FAKE_WATCHERS="foreign").stdout
    assert out.splitlines()[0] == "OFF"
    assert "not started by this script" in out


def test_start_without_a_number_stops_with_22(box):
    r = box.run("start", AX_TRUSTED="true")
    assert r.returncode == 22
    assert "test phone number" in r.stdout


def test_missing_number_is_reported_even_when_a_foreign_watcher_runs(box):
    assert box.run("start", FAKE_WATCHERS="foreign").returncode == 22


def test_a_foreign_watcher_blocks_start_and_dry_with_21(box):
    box.run("set-number", NUM)
    for cmd in ("start", "dry"):
        r = box.run(cmd, FAKE_WATCHERS="foreign", AX_TRUSTED="true")
        assert r.returncode == 21, cmd
        assert "4242" in r.stdout
    assert not (box.home / "logs" / "watcher.mode").exists()


def test_without_accessibility_start_and_dry_stop_with_23_before_anything_launches(box):
    box.run("set-number", NUM)
    for cmd in ("start", "dry"):
        r = box.run(cmd, AX_TRUSTED="false")
        assert r.returncode == 23, cmd
        assert "Accessibility" in r.stdout
    assert not (box.home / "logs" / "watcher.mode").exists()
    assert not (box.home / "logs" / "watcher.log").exists()


def test_dry_does_not_need_a_number(box):
    r = box.run("dry", AX_TRUSTED="false")
    assert r.returncode == 23           # got past the number check and stopped at Accessibility


def test_start_on_a_running_watcher_does_nothing(box):
    box.run("set-number", NUM)
    r = box.run("start", FAKE_WATCHERS="mine", AX_TRUSTED="true")
    assert r.returncode == 0 and "already running" in r.stdout


def test_trusted_reflects_axctl(box):
    assert box.run("trusted", AX_TRUSTED="true").stdout.strip() == "yes"
    r = box.run("trusted", AX_TRUSTED="false")
    assert (r.returncode, r.stdout.strip()) == (1, "no")


def test_stop_when_off_says_so(box):
    r = box.run("stop")
    assert r.returncode == 0 and "not running" in r.stdout


def test_progress_and_error_read_the_setup_log(box):
    logs = box.home / "logs"
    logs.mkdir()
    (logs / "setup.log").write_text("==> 0/6 Checking\nsome pip noise\n==> 3/6 Installing packages\n")
    assert box.run("progress").stdout.strip() == "DONE 1"              # no result and nothing running: it died
    (logs / "setup.done").write_text("0\n")
    assert box.run("progress").stdout.strip() == "DONE 0"
    (logs / "setup.log").write_text("==> 0/6 Checking\nERROR: cannot reach https://example.invalid/. Connect to the VPN.\n")
    (logs / "setup.done").write_text("11\n")
    assert box.run("progress").stdout.strip() == "DONE 11"
    assert box.run("error").stdout.strip() == "cannot reach https://example.invalid/. Connect to the VPN."


def test_setup_with_an_unreachable_index_stops_at_the_network_check_with_11(box, tmp_path):
    _exe(tmp_path / "fakebin" / "uname", '#!/bin/sh\necho Darwin\n')
    _exe(tmp_path / "fakebin" / "xcode-select", '#!/bin/sh\nexit 0\n')
    _exe(tmp_path / "fakebin" / "curl", '#!/bin/sh\nprintf 000\nexit 7\n')
    # Nothing is copied: the script is run from the repo, which holds private files, and must stop before ditto.
    r = box.run("setup", WARROOM_HOME=str(tmp_path / "fresh"), WARROOM_PIP_INDEX="http://127.0.0.1:9/")
    assert r.returncode == 11, r.stdout + r.stderr
    log = (tmp_path / "fresh" / "logs" / "setup.log").read_text()
    assert "Equinix network or VPN" in log
    assert not (tmp_path / "fresh" / ".env").exists() and not (tmp_path / "fresh" / "warroom").exists()
    assert (tmp_path / "fresh" / "logs" / "setup.done").read_text().strip() == "11"
    assert not (tmp_path / "fresh" / "logs" / "setup.pid").exists()


def test_recent_with_no_log_says_so_and_lists_rows_newest_first(box):
    assert "No visitors logged yet" in box.run("recent").stdout
    (box.home / "logs").mkdir()
    (box.home / "logs" / "join_log.csv").write_text(
        "joined_at_local,participant_name,welcome_voice,engineer_called,zoom_invited,notes\n"
        "2026-10-09 10:00,Ann,yes,yes,,first\n2026-10-09 11:00,Bob,yes,no,,second\n")
    out = box.run("recent").stdout
    assert out.index("Bob") < out.index("Ann")


def test_setup_error_reports_underlying_cause_not_outer_wrapper(box):
    logs = box.home / "logs"
    logs.mkdir()
    (logs / "setup.log").write_text(
        "---- setup latest ----\nERROR: could not install dependencies: VPN needed\n"
        "ERROR: the install did not finish (see the lines above, or setup.log)\n")
    assert box.run("error").stdout.strip() == "could not install dependencies: VPN needed"


def test_setup_error_does_not_use_a_previous_attempt(box):
    logs = box.home / "logs"
    logs.mkdir()
    (logs / "setup.log").write_text(
        "---- setup old ----\nERROR: old network failure\n"
        "---- setup latest ----\naxctl.swift:42: error: cannot convert value\n"
        "ERROR: the install did not finish (see the lines above, or setup.log)\n")
    out = box.run("error").stdout
    assert "cannot convert value" in out
    assert "old network failure" not in out and "install did not finish" not in out
