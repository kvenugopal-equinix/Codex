"""Spoken welcome via macOS `say`.

speak() plays on this Mac's speakers only (WARROOM_VOICE_ROUTE=local). speak_in_meeting() plays it into the
meeting as Zoom shared computer sound, like the Windows bot: render to a file, start an audio-only "Computer
audio" share, play the file, stop the share. Both return a handle at once, so the call-out runs while the
voice plays; the handle's wait() is the only thing that blocks.
"""
import atexit
import os
import subprocess
import sys
import tempfile
import threading
import time
from typing import Optional

DEFAULT_MESSAGE = ("Welcome to the war room bridge. Support has been alerted "
                   "and an engineer is being called to join you now. Please stay on the line.")

LEAD_IN = 1.0               # seconds between Zoom showing the share and the first sound, so the start is not clipped
TAIL = 1.0                  # seconds after the sound ends before the share is stopped, so the end is not clipped
RENDER_TIMEOUT = 60
PLAY_TIMEOUT = 120


def _say_args(voice: Optional[str], rate: Optional[int]) -> list:
    return (["-v", voice] if voice else []) + (["-r", str(rate)] if rate else [])


def speak(text: str, voice: Optional[str] = None, rate: Optional[int] = None) -> subprocess.Popen:
    cmd = ["say", *_say_args(voice, rate), text]
    # Popen returns at once, so the call-out proceeds while the voice plays.
    return subprocess.Popen(cmd, start_new_session=True)


def render(text: str, voice: Optional[str] = None, rate: Optional[int] = None) -> str:
    """Speaks `text` into a temporary AIFF file and returns its path. The text goes in on stdin, so a message that
    starts with '-' cannot be read as an option. The caller deletes the file."""
    fd, path = tempfile.mkstemp(prefix="warroom-voice-", suffix=".aiff")
    os.close(fd)
    try:
        subprocess.run(["say", "-o", path, *_say_args(voice, rate), "-f", "-"], input=text, text=True,
                       capture_output=True, check=True, timeout=RENDER_TIMEOUT)
    except BaseException:
        _remove(path)
        raise
    return path


def play(path: str) -> None:
    """Plays a file on the default output device and waits for it to finish."""
    subprocess.run(["afplay", path], check=True, capture_output=True, timeout=PLAY_TIMEOUT)


def _remove(path: Optional[str]) -> None:
    try:
        if path:
            os.unlink(path)
    except OSError:
        pass


def _zoom():
    from . import ui_backend
    return ui_backend


_one_at_a_time = threading.Lock()       # two greetings must not fight over one share
_may_be_sharing: set = set()            # handles whose computer-audio share may still be running
_active_welcomes: set = set()           # includes rendering and greetings waiting for another share
_state = threading.Lock()


def finish_welcomes() -> None:
    """Cancel queued work and finish active greetings before releasing Zoom ownership.

    Rendering or playback already in progress retains its existing timeout. No
    subprocess or Zoom operation is forcefully terminated by this cleanup.
    """
    with _state:
        active = list(_active_welcomes)
        for speech in active:
            speech._cancel.set()
    for speech in active:
        # An interrupted Thread.join can report a finished thread prematurely on
        # older Python versions. The event certifies that resource cleanup ran.
        speech._finished.wait()
        speech._thread.join()
    _stop_leftovers()


def _stop_leftovers() -> None:
    """At exit (including Ctrl-C): a share must never be left running in the meeting."""
    with _state:
        if not _may_be_sharing:
            return
        sharing = set(_may_be_sharing)
    try:
        _zoom().stop_audio_share()
        with _state:
            _may_be_sharing.difference_update(sharing)
    except Exception as e:
        _shout(e)


def _shout(e) -> None:
    print(f"WELCOME SHARE STILL RUNNING: {e}. In Zoom, click the x on the 'My computer sound' tab.", file=sys.stderr)


atexit.register(_stop_leftovers)


class SharedSpeech:
    """The welcome being played into the meeting on a background thread. Truthy while it exists; wait() blocks until
    it is over and returns the outcome: 'yes', or 'FAILED: <why>' (nothing is then played on the local speakers)."""

    def __init__(self, text: str, voice: Optional[str] = None, rate: Optional[int] = None, *, ui=None,
                 render_fn=None, play_fn=None, sleep=None, lead_in: float = LEAD_IN, tail: float = TAIL):
        self.outcome = "unfinished"
        self._args = (text, voice, rate)
        self._ui = ui or _zoom()
        self._render, self._play = render_fn or render, play_fn or play
        self._sleep = sleep or time.sleep
        self._lead_in, self._tail = lead_in, tail
        self._cancel, self._finished = threading.Event(), threading.Event()
        self._thread = threading.Thread(target=self._run, name="welcome-voice", daemon=True)
        with _state:
            _active_welcomes.add(self)
            try:
                self._thread.start()
            except BaseException:
                _active_welcomes.discard(self)
                raise

    def __bool__(self) -> bool:
        return True

    def wait(self, timeout: Optional[float] = None) -> str:
        self._finished.wait(timeout)
        return self.outcome

    def _run(self) -> None:
        path, outcome = None, "FAILED: stopped early"
        try:
            with _one_at_a_time:
                attempted = False
                try:
                    if self._cancel.is_set():
                        return
                    path = self._render(*self._args)
                    if self._cancel.is_set():
                        return
                    with _state:
                        _may_be_sharing.add(self)       # before starting: an exit during the start still cleans up
                    attempted = True
                    self._ui.start_audio_share()
                    if self._cancel.is_set():
                        return
                    self._sleep(self._lead_in)
                    if self._cancel.is_set():
                        return
                    self._play(path)
                    self._sleep(self._tail)
                    outcome = "yes"
                except Exception as e:
                    outcome = f"FAILED: {e}"
                finally:
                    if attempted:                       # a failed start is verified too: it may have half-started
                        try:
                            self._ui.stop_audio_share()
                            with _state:
                                _may_be_sharing.discard(self)
                        except Exception as e:
                            outcome = (f"FAILED: share left running: {e}" if outcome == "yes"
                                       else f"{outcome}; the share may be left running: {e}")
                            _shout(e)
        finally:
            _remove(path)
            self.outcome = outcome
            with _state:
                _active_welcomes.discard(self)
                self._finished.set()


def speak_in_meeting(text: str, voice: Optional[str] = None, rate: Optional[int] = None, **kw) -> SharedSpeech:
    return SharedSpeech(text, voice, rate, **kw)
