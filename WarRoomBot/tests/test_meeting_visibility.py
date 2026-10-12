"""Startup visibility recovery never places calls and never activates during polling."""
import pytest
import warroom.ui_backend as ui
import warroom.cli as cli


class WindowAx:
    def __init__(self, visible, recover=True):
        self.visible, self.recover = visible, recover
        self.opens, self.commands = 0, []

    def call(self, cmd, *args, **kw):
        self.commands.append(cmd)
        if cmd == 'windows':
            return {'ok': True, 'windows': ['Zoom Workplace'] + (['Zoom Meeting'] if self.visible else [])}
        if cmd == 'participants':
            return {'ok': True, 'participants': ['Bot (me)', 'Visitor']}
        raise AssertionError(f'unexpected UI action {cmd}')

    def open_zoom(self):
        self.opens += 1
        self.visible = self.recover


def rig(monkeypatch, visible, recover=True):
    ax = WindowAx(visible, recover)
    monkeypatch.setattr(ui, 'ax', ax)
    monkeypatch.setattr(ui, '_open_zoom', ax.open_zoom)
    monkeypatch.setattr(ui, 'SURFACE_WAIT', 0.02)
    monkeypatch.setattr(ui.time, 'sleep', lambda sec: None)
    return ax


def test_startup_recovers_fullscreen_meeting_hidden_on_another_space(monkeypatch):
    ax = rig(monkeypatch, False)
    assert ui.prepare_meeting() == 'Zoom Meeting'
    assert ax.opens == 1
    assert ui.read_participants()[0].is_me
    assert set(ax.commands) <= {'windows', 'participants'}


def test_visible_or_minimized_meeting_is_read_without_activation(monkeypatch):
    ax = rig(monkeypatch, True)
    assert ui.prepare_meeting() == 'Zoom Meeting'
    assert ax.opens == 0


def test_missing_meeting_fails_after_one_recovery_attempt(monkeypatch):
    ax = rig(monkeypatch, False, recover=False)
    with pytest.raises(ui.UiMeetingHidden):
        ui.prepare_meeting()
    assert ax.opens == 1


def test_participant_polling_does_not_reactivate_zoom(monkeypatch):
    ax = rig(monkeypatch, False)
    ui.prepare_meeting()
    ax.visible = False
    with pytest.raises(ui.UiMeetingHidden):
        ui.read_participants()
    assert ax.opens == 1


def test_unavailable_zoom_is_not_launched_or_activated(monkeypatch):
    ax = rig(monkeypatch, False)
    def unavailable(*a, **kw):
        raise ui.UiUnavailable('Zoom is not running or not trusted')
    monkeypatch.setattr(ax, 'call', unavailable)
    with pytest.raises(ui.UiUnavailable):
        ui.prepare_meeting()
    assert ax.opens == 0


def test_probe_uses_startup_recovery(monkeypatch, capsys):
    ax = rig(monkeypatch, False)
    monkeypatch.setattr(ui, 'input_available', lambda: True)
    assert cli.ui_commands('ui-probe') == 0
    assert ax.opens == 1
    assert 'meeting window: Zoom Meeting' in capsys.readouterr().out
