"""app/wrb.sh: the control script behind War Room Bot.app. Runs it against a throwaway install folder and a fake
pgrep/axctl, so nothing here touches the real home folder, the real Zoom, or a watcher that is running on this Mac."""
import os
import json
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

FAKE_PS = r"""#!/bin/sh
# A framework interpreter's executable path no longer names this install's venv.
case "$*" in
  *4141*comm=*) echo Python ;;
  *4141*args=*|*4141*command=*) echo '/Library/Frameworks/Python -m warroom.cli watch --watch-token aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' ;;
  *4141*etime=*) echo '00:01' ;;
  *) exec /bin/ps "$@" ;;
esac
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
    # App setup removes the destination VERSION until installation succeeds.
    # Match wrb.sh payload_version(), which reports dev in that temporary state.
    version = (REPO / "VERSION").read_text() if (REPO / "VERSION").exists() else "dev\n"
    (home / "VERSION").write_text(version)
    _exe(tmp_path / "fakebin" / "pgrep", FAKE_PGREP)
    _exe(tmp_path / "fakebin" / "ps", FAKE_PS)

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
        if e.get("FAKE_WATCHERS") == "mine":
            (home / "logs").mkdir(exist_ok=True)
            (home / "logs" / "watcher.pid.json").write_text(json.dumps(
                dict(pid=4141, root=str(home.resolve()), token="a" * 32, mode="dry")))
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


@pytest.mark.parametrize("command", ["roster-preview", "roster-dry", "roster-start", "start", "dry", "check",
                                     "calling-options", "set-calling-options", "test-preview"])
def test_new_actions_require_runtime_update_before_executing_old_watcher(box, command):
    (box.home / "VERSION").write_text("20261012.5\n")
    _exe(box.home / "watch.sh", '''#!/bin/sh
cd "$(dirname "$0")" || exit 1
touch old-watcher-was-invoked
echo 'usage: ./watch.sh [start|stop|status|dry|check]'
exit 2
''')
    before = (box.home / ".env").read_bytes()
    result = box.run(command)
    assert result.returncode == 27
    assert "20261012.5" in result.stdout and "Update / Repair" in result.stdout
    assert "usage:" not in result.stdout
    assert not (box.home / "old-watcher-was-invoked").exists()
    assert (box.home / ".env").read_bytes() == before


def test_status_and_stop_remain_available_while_runtime_update_is_pending(box):
    (box.home / "VERSION").write_text("20261012.5\n")
    assert box.run("state").stdout.strip() == "UPDATE_AVAILABLE"
    assert box.run("status").stdout.startswith("OFF")
    result = box.run("stop")
    assert result.returncode == 0 and "not running" in result.stdout


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
    for cmd in ("start", "dry", "roster-start", "roster-dry", "roster-preview", "stop", "status", "check", "recent", "number", "clear-number", "trusted"):
        r = box.run(cmd, **away)
        assert r.returncode == 20, cmd
        assert "not set up" in r.stdout, cmd


def test_set_number_accepts_a_good_number_and_normalises_it(box):
    r = box.run("set-number", "+1 (415) 555-0123")
    assert r.returncode == 0, r.stdout + r.stderr
    assert box.run("number").stdout.strip() == NUM
    assert box.run("has-number").returncode == 0


@pytest.mark.parametrize("bad", ["12345", "+0123456789", "+1415; touch pwned", "$(touch pwned)", "", "   ", "+" + "1" * 20])
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


def test_clear_number_disables_test_start_and_preserves_other_settings(box):
    path = box.home / ".env"
    extra = "WARROOM_DRY_RUN=true\nWARROOM_TEST_ZOOM_EMAIL=test.engineer@example.com\n# local preference\n"
    path.write_text(path.read_text() + extra)
    assert box.run("set-number", NUM).returncode == 0
    assert box.run("has-number").returncode == 0
    result = box.run("clear-number")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "cleared" in result.stdout and NUM not in result.stdout + result.stderr
    assert box.run("number").stdout.strip() == ""
    assert box.run("has-number").returncode != 0
    assert path.read_text() == "WARROOM_TEST_NUMBER=  # my phone\n" + extra
    result = box.run("start", AX_TRUSTED="true")
    assert result.returncode == 22
    assert not (box.home / "logs" / "watcher.log").exists()


def test_clear_number_refuses_a_running_watcher_without_changing_settings(box):
    assert box.run("set-number", NUM).returncode == 0
    before = (box.home / ".env").read_bytes()
    result = box.run("clear-number", FAKE_WATCHERS="mine")
    assert result.returncode == 13
    assert "Stop the watcher" in result.stdout
    assert NUM not in result.stdout + result.stderr
    assert (box.home / ".env").read_bytes() == before


def test_clear_number_refuses_unknown_watcher_state_without_changing_settings(box):
    assert box.run("set-number", NUM).returncode == 0
    before = (box.home / ".env").read_bytes()
    _exe(box.home / "watch.sh", "#!/bin/sh\nexit 2\n")
    result = box.run("clear-number")
    assert result.returncode == 1
    assert "Could not check watcher status" in result.stderr
    assert (box.home / ".env").read_bytes() == before


def test_calling_options_default_to_phone_without_a_test_contact(box):
    result = box.run("calling-options")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"zoom_invite": False, "zoom_contact_lookup": "email",
                                        "test_zoom_contact": ""}
    assert not (box.home / "logs").exists()


def test_calling_options_save_by_name_together_preserving_private_settings(box):
    settings = box.home / ".env"
    private = "WARROOM_TEST_NUMBER=+14155550123\nWARROOM_TEST_ZOOM_EMAIL=legacy@example.com\n# private setting\nPRIVATE_TOKEN=unchanged\n"
    settings.write_text(private + "WARROOM_ZOOM_INVITE=false\nWARROOM_ZOOM_CONTACT_LOOKUP=email\n")
    name = "Alex O'Connor #2"
    result = box.run("set-calling-options", "contacts-phone", name)
    assert result.returncode == 0, result.stdout + result.stderr
    assert name not in result.stdout and NUM not in result.stdout
    assert settings.read_text().startswith(private)
    assert json.loads(box.run("calling-options").stdout) == {
        "zoom_invite": True, "zoom_contact_lookup": "name", "test_zoom_contact": name}
    assert not (box.home / "logs").exists()
    preview = box.run("test-preview")
    assert preview.returncode == 0 and NUM in preview.stdout and name in preview.stdout
    assert "Contacts tab" in preview.stdout and "legacy@example.com" not in preview.stdout
    assert "No call or invitation" in preview.stdout


def test_selecting_phone_only_disables_invites_and_clears_optional_test_contact(box):
    assert box.run("set-calling-options", "contacts-phone", "Fixture Contact").returncode == 0
    assert box.run("set-calling-options", "phone", "").returncode == 0
    assert json.loads(box.run("calling-options").stdout) == {
        "zoom_invite": False, "zoom_contact_lookup": "name", "test_zoom_contact": ""}


def test_enabled_contacts_with_no_test_name_does_not_use_legacy_email(box):
    box.run("set-number", NUM)
    with (box.home / ".env").open("a") as stream:
        stream.write("WARROOM_TEST_ZOOM_EMAIL=legacy@example.com\n")
    assert box.run("set-calling-options", "contacts-phone", "").returncode == 0
    preview = box.run("test-preview")
    assert preview.returncode == 0 and "Phone only: no test Zoom contact" in preview.stdout
    assert "legacy@example.com" not in preview.stdout
    assert not (box.home / "logs").exists()


@pytest.mark.parametrize("mode,code", [("mine", 13), ("foreign", 21)])
def test_calling_options_refuse_any_running_watcher(box, mode, code):
    before = (box.home / ".env").read_bytes()
    result = box.run("set-calling-options", "contacts-phone", "Fixture Contact", FAKE_WATCHERS=mode)
    assert result.returncode == code and "Stop" in result.stdout
    assert (box.home / ".env").read_bytes() == before


@pytest.mark.parametrize("status_script", ["exit 1", "echo UNKNOWN", "exit 0"])
def test_calling_options_refuse_unreadable_or_unknown_watcher_state(box, status_script):
    _exe(box.home / "watch.sh", "#!/bin/sh\n" + status_script + "\n")
    before = (box.home / ".env").read_bytes()
    result = box.run("set-calling-options", "contacts-phone", "Fixture Contact")
    assert result.returncode == 1 and "not changed" in result.stdout
    assert (box.home / ".env").read_bytes() == before


def test_calling_options_refuse_failed_foreign_process_check(box):
    _exe(box.home / "watch.sh", "#!/bin/sh\necho OFF\n")
    _exe(box.tmp / "fakebin" / "pgrep", "#!/bin/sh\nexit 2\n")
    before = (box.home / ".env").read_bytes()
    result = box.run("set-calling-options", "contacts-phone", "Fixture Contact")
    assert result.returncode == 1 and "other watchers" in result.stdout
    assert (box.home / ".env").read_bytes() == before


@pytest.mark.parametrize("name", ["Alex\nWARROOM_LIVE_CALLING=true", "Alex\tSmith", "Alex\x7fSmith", "A" * 201])
def test_invalid_test_contact_leaves_all_calling_options_unchanged(box, name):
    before = (box.home / ".env").read_bytes()
    result = box.run("set-calling-options", "contacts-phone", name)
    assert result.returncode == 2, result.stdout + result.stderr
    assert (box.home / ".env").read_bytes() == before


def test_test_contact_does_not_remove_the_phone_number_requirement(box):
    assert box.run("set-calling-options", "contacts-phone", "Fixture Contact").returncode == 0
    preview = box.run("test-preview")
    assert preview.returncode == 22 and "test phone number" in preview.stdout
    assert box.run("start", AX_TRUSTED="true").returncode == 22
    assert not (box.home / "logs").exists()


def test_roster_status_describes_saved_contacts_and_phone_route(box):
    assert box.run("set-calling-options", "contacts-phone", "Fixture Contact").returncode == 0
    (box.home / "logs").mkdir()
    (box.home / "logs" / "watcher.mode").write_text("roster-live\n")
    result = box.run("status", FAKE_WATCHERS="mine")
    assert "Zoom Contacts by the selected engineer's roster name, plus their phone" in result.stdout
    assert "Fixture Contact" not in result.stdout


def test_status_off_on_and_on_from_outside_the_app(box):
    assert box.run("status").stdout.splitlines()[0] == "OFF"
    (box.home / "logs").mkdir()
    (box.home / "logs" / "watcher.mode").write_text("live\n")
    r = box.run("status", FAKE_WATCHERS="mine")
    assert r.stdout.startswith("ON, live in test mode")
    (box.home / "logs" / "watcher.mode").write_text("dry\n")
    assert box.run("status", FAKE_WATCHERS="mine").stdout.startswith("ON, dry run")
    (box.home / "logs" / "watcher.mode").write_text("roster-live\n")
    assert box.run("status", FAKE_WATCHERS="mine").stdout.startswith("ON, live in roster mode")
    (box.home / "logs" / "watcher.mode").write_text("roster-dry\n")
    assert box.run("status", FAKE_WATCHERS="mine").stdout.startswith("ON, roster dry run")
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
    for cmd in ("start", "dry", "roster-start", "roster-dry"):
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


def test_stop_reports_off_only_after_worker_exits(box):
    _exe(box.home / "watch.sh", r'''#!/bin/bash
case "$1" in
  status) if [ -f "${0%/*}/logs/stopped" ]; then echo OFF; else echo 'ON (pid 4141)'; fi ;;
  stop) mkdir -p "${0%/*}/logs"; touch "${0%/*}/logs/stopped"; echo 'stop signal sent to watcher' ;;
esac
''')
    r = box.run("stop")
    assert r.returncode == 0 and r.stdout.splitlines()[-1] == "OFF"


def test_slow_stop_does_not_assume_a_call_or_report_success(box):
    _exe(box.home / "watch.sh", '#!/bin/sh\ncase "$1" in status) echo "ON (pid 4141)" ;; stop) echo "stop signal sent" ;; esac\n')
    _exe(box.tmp / "fakebin" / "sleep", '#!/bin/sh\nexit 0\n')
    r = box.run("stop")
    assert r.returncode == 25
    assert "still stopping" in r.stdout and "watcher.log" in r.stdout
    assert "call in progress" not in r.stdout and "OFF" not in r.stdout


def test_stop_inspection_error_is_not_reported_as_off(box):
    _exe(box.home / "watch.sh", '#!/bin/sh\necho "process inspection failed" >&2\nexit 1\n')
    r = box.run("stop")
    assert r.returncode != 0 and "process inspection failed" in r.stderr
    assert "not running" not in r.stdout and "OFF" not in r.stdout


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


@pytest.mark.parametrize("status_error", [False, True])
def test_update_refuses_legacy_worker_or_failed_process_inspection_before_copy(box, status_error):
    _exe(box.tmp / "fakebin" / "uname", '#!/bin/sh\necho Darwin\n')
    _exe(box.tmp / "fakebin" / "xcode-select", '#!/bin/sh\nexit 0\n')
    _exe(box.tmp / "fakebin" / "curl", '#!/bin/sh\necho 200\n')
    # An older script can miss a framework interpreter; inspection failure also cannot allow an update.
    _exe(box.home / "watch.sh", '#!/bin/sh\n' + ('exit 1\n' if status_error else 'echo OFF\n'))
    marker = box.tmp / "copied"
    import shlex
    _exe(box.tmp / "fakebin" / "ditto", '#!/bin/sh\ntouch ' + shlex.quote(str(marker)) + '\nexit 1\n')
    r = box.run("setup", FAKE_WATCHERS="none" if status_error else "foreign")
    assert r.returncode == 13 and not marker.exists()
    message = "could not check watcher status" if status_error else "watcher is running"
    assert message in r.stdout


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


@pytest.mark.parametrize("output,rc", [
    ('{"ok":true}', 2), ('{"ok":"true"}', 0), ('{"nested":{"ok":true}}', 0),
    ('{"ok":false,"text":"ok: true"}', 0), ('not json', 0), ('', 0),
])
def test_trusted_requires_success_and_top_level_boolean(box, output, rc):
    import shlex
    _exe(box.home / "tools" / "axctl", '#!/bin/sh\nprintf "%s\\n" ' + shlex.quote(output)
         + '\nexit ' + str(rc) + '\n')
    assert box.run("trusted").returncode == 1


def test_permission_status_distinguishes_denial_and_helper_failure(box):
    _exe(box.home / "tools" / "axctl", "#!/bin/sh\necho '{\"ok\":false}'\nexit 2\n")
    r = box.run("permission-status")
    assert "lacks Accessibility permission" in r.stdout
    assert str(box.home / "tools" / "axctl") in r.stdout
    _exe(box.home / "tools" / "axctl", '#!/bin/sh\necho "cannot load library" >&2\nexit 1\n')
    r = box.run("permission-status")
    assert "cannot load library" in r.stdout and "Exit code: 1" in r.stdout
    assert "does not establish" in r.stdout
    assert "lacks Accessibility permission" not in r.stdout


def test_permission_status_reports_grant_in_current_context(box):
    r = box.run("permission-status", AX_TRUSTED="true")
    assert "Permission is granted" in r.stdout and "Exit code: 0" in r.stdout


@pytest.mark.parametrize("remove", [True, False])
def test_permission_status_reports_missing_or_nonexecutable_helper(box, remove):
    helper = box.home / "tools" / "axctl"
    if remove:
        helper.unlink()
    else:
        helper.chmod(0o644)
    out = box.run("permission-status").stdout
    assert str(helper) in out and "The helper check failed" in out
    assert "not set up" not in out


def _roster(box, phone=NUM, active="yes", name="On Call Engineer"):
    path = box.home / "roster.csv"
    path.write_text("name,zoom_email,phone,timezone,days,shift_start,shift_end,priority,active,notes\n"
                    + f"{name},engineer@example.com,{phone},Asia/Singapore,daily,00:00,00:00,1,{active},\n")
    with (box.home / ".env").open("a") as stream:
        stream.write(f"WARROOM_ROSTER={path}\nWARROOM_TARGET_MODE=test\nWARROOM_ALLOW_ROSTER_CALLS=false\n")


def test_roster_preview_selects_roster_without_test_number_or_permission(box):
    _roster(box)
    original = (box.home / ".env").read_bytes()
    result = box.run("roster-preview", AX_TRUSTED="false")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "On Call Engineer" in result.stdout and NUM in result.stdout
    assert "No call has been placed" in result.stdout
    assert (box.home / ".env").read_bytes() == original
    assert not (box.home / "logs").exists()


@pytest.mark.parametrize("phone,active", [(NUM, "no"), ("not-a-number", "yes")])
def test_roster_start_refuses_missing_or_invalid_target_before_launch(box, phone, active):
    _roster(box, phone=phone, active=active)
    result = box.run("roster-start", AX_TRUSTED="true")
    assert result.returncode == 26
    assert "nobody on duty" in result.stdout or "not an international number" in result.stdout
    assert not (box.home / "logs" / "watcher.mode").exists()
    assert not (box.home / "logs" / "watcher.log").exists()


def test_roster_dry_does_not_need_a_test_number(box):
    result = box.run("roster-dry", AX_TRUSTED="false")
    assert result.returncode == 23


@pytest.mark.parametrize("command,watch_command,mode,description", [
    ("roster-start", "roster", "roster-live", "live in roster mode"),
    ("roster-dry", "roster-dry", "roster-dry", "roster dry run"),
])
def test_roster_wrapper_dispatches_and_reports_correct_mode(box, command, watch_command, mode, description):
    _exe(box.home / "watch.sh", r'''#!/bin/bash
ROOT="${0%/*}"
case "$1" in
  status) if [ -f "$ROOT/logs/test-launched" ]; then echo 'ON (pid 4141)'; else echo OFF; fi ;;
  roster-preview) echo 'Selected on-duty engineer: Fixture Engineer'; echo 'Phone: +14155550123' ;;
  roster|roster-dry) printf '%s\n%s\n' "$1" "${WARROOM_AXCTL:-}" > "$ROOT/logs/test-launched" ;;
  *) exit 2 ;;
esac
''')
    _exe(box.tmp / "fakebin" / "sleep", '#!/bin/sh\nexec /bin/sleep 0.02\n')
    helper = box.tmp / "Native App.app" / "Contents" / "MacOS" / "axctl"
    _exe(helper, '#!/bin/sh\necho "{\\"ok\\":true}"\n')
    result = box.run(command, WARROOM_AXCTL=str(helper))
    assert result.returncode == 0, result.stdout + result.stderr
    assert description in result.stdout and "test mode" not in result.stdout
    assert (box.home / "logs" / "watcher.mode").read_text().strip() == mode
    assert (box.home / "logs" / "test-launched").read_text().splitlines() == [watch_command, str(helper)]
    if command == "roster-start":
        assert "Selected on-duty engineer" in result.stdout


def test_bundled_helper_override_controls_trust_and_diagnostics(box):
    helper = box.tmp / "Native App.app" / "Contents" / "MacOS" / "axctl"
    _exe(helper, '#!/bin/sh\necho "{\\"ok\\":true}"\n')
    assert box.run("trusted", WARROOM_AXCTL=str(helper), AX_TRUSTED="false").stdout.strip() == "yes"
    result = box.run("permission-status", WARROOM_AXCTL=str(helper))
    assert str(helper) in result.stdout and "Permission is granted" in result.stdout


@pytest.mark.parametrize("override", ["relative/axctl", "/does/not/exist/axctl"])
def test_invalid_helper_override_never_falls_back_to_permitted_data_helper(box, override):
    result = box.run("trusted", WARROOM_AXCTL=override, AX_TRUSTED="true")
    assert result.returncode == 1 and result.stdout.strip() == "no"
    diagnostic = box.run("permission-status", WARROOM_AXCTL=override, AX_TRUSTED="true")
    assert override in diagnostic.stdout and "The helper check failed" in diagnostic.stdout
    assert "Permission is granted" not in diagnostic.stdout


def test_accessibility_opens_settings_once_without_requesting_helper_permission(box):
    import shlex
    evidence = box.tmp / "settings-opened"
    helper = box.tmp / "bundled axctl"
    _exe(helper, '#!/bin/sh\nprintf "%s\\n" "$*" >> ' + shlex.quote(str(box.tmp / "helper-called")) + '\nexit 0\n')
    _exe(box.tmp / "fakebin" / "open", '#!/bin/sh\nprintf "%s\\n" "$*" >> ' + shlex.quote(str(evidence)) + '\n')
    result = box.run("accessibility", WARROOM_AXCTL=str(helper))
    assert result.returncode == 0
    assert evidence.read_text().splitlines() == ["x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"]
    assert not (box.tmp / "helper-called").exists()
    assert "check permission again" in result.stdout
