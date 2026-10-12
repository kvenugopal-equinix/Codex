"""Suite-wide safety: no test may drive the real Zoom, read the real .env, or leak settings between tests."""
import os
import pytest
import warroom.config as config
import warroom.ui_backend as ui
import warroom.voice as voice

REAL_LOAD_DOTENV = config.load_dotenv
REAL_RENDER, REAL_PLAY = voice.render, voice.play
REAL_OPEN_ZOOM = ui._open_zoom      # for the tests of the say/afplay command lines themselves


class _NoRealZoom:
    def call(self, *a, **k):
        raise AssertionError(f"a test reached the real axctl: {a}")

    def trusted(self):
        raise AssertionError("a test reached the real axctl")


def _no_real_audio(*a, **k):
    raise AssertionError(f"a test reached the real say/afplay: {a}")


def _no_real_open(*a, **k):
    raise AssertionError("a test would have brought the real Zoom to the front (open -a zoom.us)")


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    saved = dict(os.environ)
    monkeypatch.setattr(ui, "ax", _NoRealZoom())
    monkeypatch.setattr(ui, "_open_zoom", _no_real_open)
    monkeypatch.setattr(voice, "render", _no_real_audio)
    monkeypatch.setattr(voice, "play", _no_real_audio)
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)
    for k in [k for k in os.environ if k.startswith("WARROOM_")]:
        monkeypatch.delenv(k)
    yield
    voice._may_be_sharing.clear()           # the atexit hook must not drive the real Zoom after the suite
    os.environ.clear()
    os.environ.update(saved)


@pytest.fixture
def real_load_dotenv():
    return REAL_LOAD_DOTENV
