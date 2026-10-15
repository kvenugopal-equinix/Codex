"""The runtime-only Finder chooser must create the workbook before saving its path."""

import importlib.util
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "tools" / "choose_activity_log.py"
spec = importlib.util.spec_from_file_location("choose_activity_log", SOURCE)
chooser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chooser)


def test_finder_choice_returns_path_without_writing(monkeypatch, tmp_path):
    destination = tmp_path / "OneDrive - Work" / "War Room Activity.xlsx"
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        assert args[:2] == ["/usr/bin/osascript", "-e"]
        assert "choose file name" in args[2]
        assert "open for access" not in args[2]
        return subprocess.CompletedProcess(args, 0, stdout=str(destination) + "\n", stderr="")

    monkeypatch.setattr(chooser.subprocess, "run", run)
    assert chooser.choose_path() == str(destination)
    assert not destination.exists()
    assert len(calls) == 1


def test_cancel_skips_setting_and_publication(monkeypatch, capsys):
    monkeypatch.setattr(chooser.sys, "platform", "darwin")
    monkeypatch.setattr(chooser, "choose_path", lambda: None)
    monkeypatch.setattr(chooser, "save_location", lambda *_: pytest.fail("must not save after cancel"))
    assert chooser.main() == 0
    assert "Canceled" in capsys.readouterr().out


def test_save_location_publishes_before_persisting(monkeypatch, tmp_path):
    destination = tmp_path / "OneDrive - Work" / "War Room Activity.xlsx"
    destination.parent.mkdir()
    (tmp_path / ".env").write_text("", encoding="utf-8")
    events = []
    monkeypatch.delenv("WARROOM_ACTIVITY_WORKBOOK", raising=False)
    monkeypatch.setattr(chooser, "ensure_idle", lambda *_: events.append("idle"))

    def settings():
        assert os.environ["WARROOM_ACTIVITY_WORKBOOK"] == str(destination)
        return SimpleNamespace(join_log_path=tmp_path / "logs" / "join_log.csv")

    monkeypatch.setattr(chooser.Settings, "from_env", settings)

    def publish(journal, workbook):
        assert journal == tmp_path / "logs" / "join_log.csv"
        assert workbook == destination
        assert not destination.exists()
        destination.write_bytes(b"workbook")
        events.append("publish")

    def save(env, key, value):
        assert destination.is_file()
        assert env == tmp_path / ".env"
        assert (key, value) == ("WARROOM_ACTIVITY_WORKBOOK", str(destination))
        assert "WARROOM_ACTIVITY_WORKBOOK" not in os.environ
        events.append("save")

    monkeypatch.setattr(chooser, "publish_workbook", publish)
    monkeypatch.setattr(chooser, "set_value", save)
    assert chooser.save_location(tmp_path, str(destination)) == str(destination)
    assert events == ["idle", "publish", "save"]


def test_publication_error_keeps_old_location(monkeypatch, tmp_path):
    destination = tmp_path / "report.xlsx"
    (tmp_path / ".env").write_text("WARROOM_ACTIVITY_WORKBOOK=/old/report.xlsx\n", encoding="utf-8")
    monkeypatch.delenv("WARROOM_ACTIVITY_WORKBOOK", raising=False)
    monkeypatch.setattr(chooser, "ensure_idle", lambda *_: None)
    monkeypatch.setattr(chooser.Settings, "from_env", lambda: SimpleNamespace(join_log_path=tmp_path / "log.csv"))
    monkeypatch.setattr(chooser, "publish_workbook", lambda *_: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr(chooser, "set_value", lambda *_: pytest.fail("must not persist after publish error"))
    with pytest.raises(OSError, match="offline"):
        chooser.save_location(tmp_path, str(destination))
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "WARROOM_ACTIVITY_WORKBOOK=/old/report.xlsx\n"


def test_settings_write_error_reports_that_workbook_was_created(monkeypatch, tmp_path):
    destination = tmp_path / "report.xlsx"
    (tmp_path / ".env").write_text("", encoding="utf-8")
    monkeypatch.delenv("WARROOM_ACTIVITY_WORKBOOK", raising=False)
    monkeypatch.setattr(chooser, "ensure_idle", lambda *_: None)
    monkeypatch.setattr(chooser.Settings, "from_env", lambda: SimpleNamespace(join_log_path=tmp_path / "log.csv"))
    monkeypatch.setattr(chooser, "publish_workbook", lambda *_: destination.write_bytes(b"workbook"))
    monkeypatch.setattr(chooser, "set_value", lambda *_: (_ for _ in ()).throw(OSError("read only")))
    with pytest.raises(RuntimeError, match="workbook was created"):
        chooser.save_location(tmp_path, str(destination))
    assert destination.is_file()


def test_watcher_must_be_off(monkeypatch, tmp_path):
    def run(args, **kwargs):
        if args[1] == "status":
            return subprocess.CompletedProcess(args, 0, stdout="ON 123\n", stderr="")
        pytest.fail("did not stop after active watcher")

    monkeypatch.setattr(chooser.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="Stop the watcher"):
        chooser.ensure_idle(tmp_path)


def test_other_watcher_must_be_off(monkeypatch, tmp_path):
    def run(args, **kwargs):
        if args[1] == "status":
            return subprocess.CompletedProcess(args, 0, stdout="OFF\n", stderr="")
        assert args[:2] == ["/usr/bin/pgrep", "-f"]
        return subprocess.CompletedProcess(args, 0, stdout="123\n", stderr="")

    monkeypatch.setattr(chooser.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="Another watcher"):
        chooser.ensure_idle(tmp_path)
