"""tools/set_env.py: replaces one setting in .env in place, refuses anything outside its allowlist."""
import importlib.util
import os
import stat
from pathlib import Path
import pytest
import warroom.config as config

_spec = importlib.util.spec_from_file_location("set_env", Path(__file__).resolve().parent.parent / "tools" / "set_env.py")
set_env = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(set_env)

NUM = "+14155550123"


def env(tmp_path, text=None):
    p = tmp_path / ".env"
    if text is not None:
        p.write_text(text)
    return p


def test_patterns_match_the_config_module():
    assert set_env.E164.pattern == config.E164.pattern
    assert set_env.EMAIL.pattern == config.EMAIL.pattern


def test_replaces_the_first_line_in_place_and_keeps_its_comment(tmp_path):
    p = env(tmp_path, "A=1\nWARROOM_TEST_NUMBER=   # my phone\nB=2\n")
    assert set_env.set_value(p, "WARROOM_TEST_NUMBER", NUM) == "replaced"
    assert p.read_text() == f"A=1\nWARROOM_TEST_NUMBER={NUM}  # my phone\nB=2\n"


def test_replaced_value_is_the_one_the_loader_reads(tmp_path, real_load_dotenv):
    # The loader lets the first duplicate win, so the replacement has to land on the first line.
    p = env(tmp_path, "WARROOM_TEST_NUMBER=+10000000000\nWARROOM_TEST_NUMBER=+19999999999\n")
    set_env.set_value(p, "WARROOM_TEST_NUMBER", NUM)
    real_load_dotenv(p)                    # the suite fixture restores os.environ afterwards
    assert os.environ["WARROOM_TEST_NUMBER"] == NUM


def test_a_commented_out_line_is_not_the_setting_so_it_is_appended(tmp_path):
    p = env(tmp_path, "# WARROOM_TEST_NUMBER=+10000000000\n")
    assert set_env.set_value(p, "WARROOM_TEST_NUMBER", NUM) == "added"
    assert p.read_text() == f"# WARROOM_TEST_NUMBER=+10000000000\nWARROOM_TEST_NUMBER={NUM}\n"


def test_creates_a_missing_file_private(tmp_path):
    p = env(tmp_path)
    assert set_env.set_value(p, "WARROOM_TEST_NUMBER", NUM) == "added"
    assert p.read_text() == f"WARROOM_TEST_NUMBER={NUM}\n"
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_keeps_the_mode_of_an_existing_file(tmp_path):
    p = env(tmp_path, "X=1\n")
    p.chmod(0o640)
    set_env.set_value(p, "WARROOM_TEST_NUMBER", NUM)
    assert stat.S_IMODE(p.stat().st_mode) == 0o640


def test_file_without_a_final_newline_gets_one(tmp_path):
    p = env(tmp_path, "A=1")
    set_env.set_value(p, "WARROOM_TEST_NUMBER", NUM)
    assert p.read_text() == f"A=1\nWARROOM_TEST_NUMBER={NUM}\n"


@pytest.mark.parametrize("typed", ["+1 (415) 555-0123", "+1 415 555 0123", "+1-415-555-0123", " +14155550123 "])
def test_typed_number_formats_are_cleaned(tmp_path, typed):
    p = env(tmp_path, "")
    set_env.set_value(p, "WARROOM_TEST_NUMBER", typed)
    assert p.read_text() == f"WARROOM_TEST_NUMBER={NUM}\n"


@pytest.mark.parametrize("bad", [" ", "().-", "4155550123", "+0155550123", "+1", "abc", "+1415555012345678", "+٣٣٣٣٣٣٣٣٣٣", "+1415555012x",
                                 "+14155550123\nWARROOM_DRY_RUN=false"])
def test_bad_number_changes_nothing(tmp_path, bad):
    p = env(tmp_path, "WARROOM_TEST_NUMBER=\n")
    with pytest.raises(set_env.Refused):
        set_env.set_value(p, "WARROOM_TEST_NUMBER", bad)
    assert p.read_text() == "WARROOM_TEST_NUMBER=\n"


@pytest.mark.parametrize("key", ["WARROOM_DRY_RUN", "WARROOM_LIVE_CALLING", "WARROOM_TARGET_MODE",
                                 "WARROOM_ALLOW_ROSTER_CALLS", "PATH", "", "warroom_test_number"])
def test_only_allowlisted_keys_can_be_set(tmp_path, key):
    p = env(tmp_path, "A=1\n")
    with pytest.raises(set_env.Refused):
        set_env.set_value(p, key, "true")
    assert p.read_text() == "A=1\n"


def test_zoom_invite_flag_and_email(tmp_path):
    p = env(tmp_path, "WARROOM_ZOOM_INVITE=false\nWARROOM_TEST_ZOOM_EMAIL=\n")
    set_env.set_value(p, "WARROOM_ZOOM_INVITE", " TRUE ")
    set_env.set_value(p, "WARROOM_TEST_ZOOM_EMAIL", "test.engineer@example.com")
    assert p.read_text() == "WARROOM_ZOOM_INVITE=true\nWARROOM_TEST_ZOOM_EMAIL=test.engineer@example.com\n"
    for key, bad in [("WARROOM_ZOOM_INVITE", "yes"), ("WARROOM_TEST_ZOOM_EMAIL", "not-an-email")]:
        with pytest.raises(set_env.Refused):
            set_env.set_value(p, key, bad)


def test_email_may_be_cleared(tmp_path):
    p = env(tmp_path, "WARROOM_TEST_ZOOM_EMAIL=test.engineer@example.com\n")
    set_env.set_value(p, "WARROOM_TEST_ZOOM_EMAIL", "")
    assert p.read_text() == "WARROOM_TEST_ZOOM_EMAIL=\n"


def test_number_clear_removes_active_duplicates_and_preserves_other_settings(tmp_path, real_load_dotenv):
    p = env(tmp_path, f"WARROOM_TEST_NUMBER={NUM} # primary\n"
                     "WARROOM_TARGET_MODE=roster\nWARROOM_DRY_RUN=true\n"
                     f" WARROOM_TEST_NUMBER = {NUM} # duplicate\n"
                     "WARROOM_TEST_ZOOM_EMAIL=test.engineer@example.com\n")
    p.chmod(0o600)
    assert set_env.set_value(p, "WARROOM_TEST_NUMBER", "") == "replaced"
    assert p.read_text() == ("WARROOM_TEST_NUMBER=  # primary\n"
                             "WARROOM_TARGET_MODE=roster\nWARROOM_DRY_RUN=true\n"
                             "WARROOM_TEST_NUMBER=  # duplicate\n"
                             "WARROOM_TEST_ZOOM_EMAIL=test.engineer@example.com\n")
    assert NUM not in p.read_text()
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    real_load_dotenv(p)
    assert os.environ["WARROOM_TEST_NUMBER"] == ""


@pytest.mark.parametrize("value", ['te"st@example.com', "te#st@example.com"])
def test_characters_the_loader_would_cut_are_refused(tmp_path, value):
    p = env(tmp_path, "")
    with pytest.raises(set_env.Refused):
        set_env.set_value(p, "WARROOM_TEST_ZOOM_EMAIL", value)


def test_no_temp_file_is_left_behind(tmp_path):
    p = env(tmp_path, "A=1\n")
    set_env.set_value(p, "WARROOM_TEST_NUMBER", NUM)
    assert sorted(x.name for x in tmp_path.iterdir()) == [".env"]


def test_main_exit_codes_and_the_value_is_never_printed(tmp_path, capsys):
    p = env(tmp_path, "")
    assert set_env.main(["--env", str(p), "WARROOM_TEST_NUMBER", NUM]) == 0
    out = capsys.readouterr()
    assert "added WARROOM_TEST_NUMBER" in out.out and NUM not in out.out + out.err
    assert set_env.main(["--env", str(p), "WARROOM_TEST_NUMBER", "nope"]) == 2
    assert "REFUSED" in capsys.readouterr().err
    assert p.read_text() == f"WARROOM_TEST_NUMBER={NUM}\n"
