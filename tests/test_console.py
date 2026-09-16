"""Headless smoke test for the operator console (Qt offscreen)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from livereact.app import App, AppConfig  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    from PySide6 import QtWidgets

    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _app() -> App:
    # config_path=None so the test never touches a real config.json.
    return App(AppConfig(demo=True, config_path=None))


def test_console_builds_and_refreshes(qapp):
    from livereact.ui.console import ConsoleWindow

    app = _app()
    win = ConsoleWindow(app)
    win.refresh()  # must not raise; readouts populate from a real snapshot
    assert win.l_bpm.text() != ""


def test_controls_drive_manual_params(qapp):
    from livereact.ui.console import ConsoleWindow

    app = _app()
    win = ConsoleWindow(app)

    win.s_bright.setValue(50)
    assert app.manual.master_brightness == pytest.approx(0.5)

    win.b_black.toggle()
    assert app.manual.blackout is True
    win.b_black.toggle()
    assert app.manual.blackout is False


def test_skip_button_requests_a_rotation(qapp):
    from livereact.ui.console import ConsoleWindow

    app = _app()
    win = ConsoleWindow(app)
    assert app.phrase_engine._skip_requested is False
    win.b_skip.click()
    assert app.phrase_engine._skip_requested is True


def test_tap_tempo_injects_a_master_beat(qapp):
    from livereact.clock import FakeClock
    from livereact.ui.console import ConsoleWindow

    clock = FakeClock()
    app = App(AppConfig(demo=True, config_path=None), clock=clock)
    win = ConsoleWindow(app)
    before = app.input_queue.qsize()
    win._do_tap()           # first tap: no interval yet
    clock.advance(0.5)      # 120 BPM spacing
    win._do_tap()           # second tap establishes an interval -> a beat is queued
    assert app.input_queue.qsize() > before


def test_synth_sync_checkbox_and_shortcut_drive_manual_params(qapp):
    from PySide6 import QtCore, QtGui
    from livereact.ui.console import ConsoleWindow

    app = _app()
    win = ConsoleWindow(app)
    assert app.manual.synth_sync is False
    win.cb_synth.toggle()
    assert app.manual.synth_sync is True
    win.cb_synth.toggle()
    assert app.manual.synth_sync is False
    # the S shortcut flips the same checkbox
    win.show()
    for sc in win.findChildren(QtGui.QShortcut):
        if sc.key() == QtGui.QKeySequence("S"):
            sc.activated.emit()
    assert app.manual.synth_sync is True
    win.refresh()
    assert "SYNTH SYNC" in win.l_synth.text()
    _ = QtCore  # PySide6 import kept explicit for clarity
