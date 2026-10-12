"""Shutdown waits for welcome work and prevents cancelled work from starting Zoom actions."""
import threading

import pytest

import warroom.voice as voice


class FakeZoom:
    def __init__(self, log, start=None, stop=None):
        self.log, self.start, self.stop = log, start, stop

    def start_audio_share(self):
        self.log.append("start")
        if self.start:
            self.start()

    def stop_audio_share(self):
        self.log.append("stop")
        if self.stop:
            self.stop()


@pytest.fixture
def gates():
    events = []
    yield events
    # A failed assertion must not leave a blocked welcome thread in another test.
    for event in events:
        event.set()
    voice.finish_welcomes()
    assert not voice._active_welcomes


def block(gates):
    entered, release = threading.Event(), threading.Event()
    gates.append(release)

    def pause(*args):
        entered.set()
        if not release.wait(5):
            raise RuntimeError("test did not release the blocked operation")

    return entered, release, pause


def greeting(tmp_path, log, *, render_hook=None, start_hook=None, play_hook=None, sleep_hook=None, name="welcome"):
    path = tmp_path / (name + ".aiff")

    def render(*args):
        log.append("render")
        path.write_bytes(b"fake audio")
        if render_hook:
            render_hook()
        return str(path)

    def play(audio_path):
        log.append("play")
        if play_hook:
            play_hook()

    speech = voice.speak_in_meeting(
        "hello", ui=FakeZoom(log, start=start_hook), render_fn=render, play_fn=play,
        sleep=sleep_hook or (lambda seconds: None), lead_in=0.5, tail=0.25)
    return speech, path


def finish_async():
    done, errors = threading.Event(), []

    def finish():
        try:
            voice.finish_welcomes()
        except BaseException as error:
            errors.append(error)
        finally:
            done.set()

    thread = threading.Thread(target=finish, daemon=True)
    thread.start()
    return thread, done, errors


def finished(thread, done, errors):
    assert done.wait(5), "welcome cleanup did not finish"
    thread.join(5)
    assert not thread.is_alive()
    assert not errors
    assert not voice._active_welcomes
    assert not voice._may_be_sharing


def test_shutdown_tracks_rendering_and_waits_without_starting_share(tmp_path, gates):
    log = []
    entered, release, pause = block(gates)
    speech, path = greeting(tmp_path, log, render_hook=pause)
    assert entered.wait(5)
    assert speech in voice._active_welcomes and speech not in voice._may_be_sharing
    thread, done, errors = finish_async()
    assert speech._cancel.wait(5)
    assert not done.is_set()
    release.set()
    finished(thread, done, errors)
    assert speech.wait(5) == "FAILED: stopped early"
    assert log == ["render"]
    assert not path.exists()


def test_shutdown_during_share_start_stops_share_and_skips_playback(tmp_path, gates):
    log = []
    entered, release, pause = block(gates)
    speech, path = greeting(tmp_path, log, start_hook=pause)
    assert entered.wait(5)
    thread, done, errors = finish_async()
    assert speech._cancel.wait(5)
    assert not done.is_set()
    release.set()
    finished(thread, done, errors)
    assert speech.wait(5) == "FAILED: stopped early"
    assert log == ["render", "start", "stop"]
    assert not path.exists()


def test_shutdown_during_lead_in_skips_playback_and_stops_share(tmp_path, gates):
    log = []
    entered, release, pause = block(gates)
    speech, path = greeting(tmp_path, log, sleep_hook=pause)
    assert entered.wait(5)
    thread, done, errors = finish_async()
    assert speech._cancel.wait(5)
    release.set()
    finished(thread, done, errors)
    assert speech.wait(5) == "FAILED: stopped early"
    assert log == ["render", "start", "stop"]
    assert not path.exists()


def test_shutdown_waits_for_playback_already_in_progress(tmp_path, gates):
    log = []
    entered, release, pause = block(gates)
    speech, path = greeting(tmp_path, log, play_hook=pause)
    assert entered.wait(5)
    thread, done, errors = finish_async()
    assert speech._cancel.wait(5)
    assert not done.is_set()
    assert path.exists()
    release.set()
    finished(thread, done, errors)
    assert speech.wait(5) == "yes"
    assert log == ["render", "start", "play", "stop"]
    assert not path.exists()


def test_shutdown_cancels_queued_greeting_before_it_renders(tmp_path, gates):
    first_log, queued_log = [], []
    entered, release, pause = block(gates)
    first, _ = greeting(tmp_path, first_log, play_hook=pause, name="first")
    assert entered.wait(5)
    queued, queued_path = greeting(tmp_path, queued_log, name="queued")
    thread, done, errors = finish_async()
    assert first._cancel.wait(5) and queued._cancel.wait(5)
    assert not done.is_set()
    release.set()
    finished(thread, done, errors)
    assert queued.wait(5) == "FAILED: stopped early"
    assert queued_log == []
    assert not queued_path.exists()


def test_shutdown_retries_failed_share_cleanup_after_threads_finish(tmp_path, gates, monkeypatch):
    log = []

    def stop():
        if log.count("stop") == 1:
            raise RuntimeError("first stop failed")

    zoom = FakeZoom(log, stop=stop)
    monkeypatch.setattr(voice, "_zoom", lambda: zoom)
    speech = voice.speak_in_meeting(
        "hello", ui=zoom, render_fn=lambda *args: str(tmp_path / "missing.aiff"),
        play_fn=lambda path: None, sleep=lambda seconds: None)
    assert speech.wait(5) == "FAILED: share left running: first stop failed"
    assert speech not in voice._active_welcomes and speech in voice._may_be_sharing
    voice.finish_welcomes()
    assert log == ["start", "stop", "stop"]
    assert not voice._active_welcomes and not voice._may_be_sharing
