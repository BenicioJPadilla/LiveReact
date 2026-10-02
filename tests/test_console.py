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
    assert app.manual.synth_sync is True  # on by default (Josh, 2026-09-19)
    assert win.cb_synth.isChecked()
    win.cb_synth.toggle()
    assert app.manual.synth_sync is False
    win.cb_synth.toggle()
    assert app.manual.synth_sync is True
    # the S shortcut flips the same checkbox
    win.show()
    for sc in win.findChildren(QtGui.QShortcut):
        if sc.key() == QtGui.QKeySequence("S"):
            sc.activated.emit()
    assert app.manual.synth_sync is False
    win.cb_synth.toggle()
    assert app.manual.synth_sync is True
    win.refresh()
    assert "SYNTH SYNC" in win.l_synth.text()
    _ = QtCore  # PySide6 import kept explicit for clarity


def test_laser_arming_checkbox_and_shortcut_drive_manual_params(qapp):
    """2026-09-16: arming is per track by hand (never persisted; demo mode
    alone pre-arms so its drop scenes can show the laser) -- the checkbox
    mirrors the manual state and L toggles the same checkbox."""
    from PySide6 import QtGui
    from livereact.ui.console import ConsoleWindow

    app = _app()
    win = ConsoleWindow(app)
    assert win.cb_laser.isChecked() == app.manual.laser_enable
    armed_before = app.manual.laser_enable
    win.show()
    for sc in win.findChildren(QtGui.QShortcut):
        if sc.key() == QtGui.QKeySequence("L"):
            sc.activated.emit()
    assert app.manual.laser_enable is (not armed_before)
    win.cb_laser.toggle()
    assert app.manual.laser_enable is armed_before


def test_build_cue_button_and_shortcut_reach_the_metronome(qapp):
    from PySide6 import QtGui
    from livereact.ui.console import ConsoleWindow

    app = _app()
    win = ConsoleWindow(app)
    assert not app.metronome.build_cue_active
    win.b_cue.click()
    assert app.metronome.build_cue_active
    win.show()
    for sc in win.findChildren(QtGui.QShortcut):
        if sc.key() == QtGui.QKeySequence("C"):
            sc.activated.emit()
    assert not app.metronome.build_cue_active  # second press cancels
    app.metronome.cue_build()
    win.refresh()
    assert "BUILD CUED" in win.l_cue.text()


def test_console_shows_energy_bucket(qapp):
    """2026-09-18 redesign: the debounced energy bucket (never displayed
    before) is in the status strip, colored per bucket."""
    from livereact.ui.console import ConsoleWindow

    app = _app()
    win = ConsoleWindow(app)
    win.refresh()
    assert win.l_bucket.text() in {"BREAK", "BUILD", "DROP", "PEAK", "OUTRO"}
    assert "background:" in win.l_bucket.styleSheet()


def test_show_tab_rig_view_is_not_movable(qapp):
    """The Show tab's rig view is a live view only -- nothing can be dragged
    mid-set by a stray click (editing moves to the Venue tab)."""
    from PySide6 import QtWidgets
    from livereact.ui.console import ConsoleWindow

    app = _app()
    win = ConsoleWindow(app)
    movable = QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
    bodies = list(win.rig_view._bodies.values())
    assert bodies, "rig view built no fixture items"
    assert all(not (item.flags() & movable) for item in bodies)


def test_all_shortcuts_present(qapp):
    """Every pre-redesign shortcut survives the regrouping."""
    from PySide6 import QtCore, QtGui
    from livereact.ui.console import ConsoleWindow

    app = _app()
    win = ConsoleWindow(app)
    keys = {sc.key().toString() for sc in win.findChildren(QtGui.QShortcut)}
    expected = {"B", "F", "T", "S", "L", "K", "C", "D",
                QtGui.QKeySequence(QtCore.Qt.Key.Key_Right).toString(),
                QtGui.QKeySequence(QtCore.Qt.Key.Key_Space).toString()}
    assert keys == expected


def test_drop_arm_button_and_shortcut_reach_the_metronome(qapp):
    from PySide6 import QtGui
    from livereact.ui.console import ConsoleWindow

    app = _app()
    win = ConsoleWindow(app)
    assert not app.metronome.drop_armed
    win.b_arm.click()
    assert app.metronome.drop_armed
    win.show()
    for sc in win.findChildren(QtGui.QShortcut):
        if sc.key() == QtGui.QKeySequence("D"):
            sc.activated.emit()
    assert app.metronome.drop_armed and app.metronome.drop_cut_pending  # second press: hard cut on the downbeat
    win.refresh()
    assert "DROP CUT" in win.l_arm.text()
    win.b_arm.click()
    assert not app.metronome.drop_armed  # third press cancels


# --- Venue tab (2026-09-18 floor plan + calibration) ---------------------------

def test_venue_tab_is_present_and_width_edits_the_live_rig(qapp):
    from livereact.fixtures.geometry import ft_to_m
    from livereact.ui.console import ConsoleWindow

    app = _app()
    win = ConsoleWindow(app)
    labels = [win.tabs.tabText(i) for i in range(win.tabs.count())]
    assert labels == ["Show", "Venue", "Rig Config"]
    assert app.rig.venue is not None            # the Venue tab gives an unplanned rig a default room
    win.venue_tab.sb_width.setValue(42.0)
    assert app.rig.venue.width_m == pytest.approx(ft_to_m(42.0))


def test_venue_tab_placement_boxes_write_real_positions(qapp):
    from livereact.fixtures.geometry import ft_to_m
    from livereact.ui.console import ConsoleWindow

    app = _app()
    win = ConsoleWindow(app)
    tab = win.venue_tab
    idx = tab.cb_fixture.findData("mh_l")
    tab.cb_fixture.setCurrentIndex(idx)
    tab.sb_x.setValue(6.0); tab.sb_y.setValue(3.0); tab.sb_z.setValue(1.5); tab.sb_facing.setValue(10.0)
    mh = app.rig.fixture("mh_l")
    assert mh.position is not None
    assert mh.position.x == pytest.approx(ft_to_m(6.0)) and mh.position.z == pytest.approx(ft_to_m(1.5))
    assert mh.facing_deg == 10.0
    assert mh.side == "left"                    # 6 ft of a 30 ft room: derived from x, matches


def test_jog_live_pins_the_head_and_unticking_clears_them(qapp):
    from livereact.ui.console import ConsoleWindow

    app = _app()
    win = ConsoleWindow(app)
    tab = win.venue_tab
    tab.cb_fixture.setCurrentIndex(tab.cb_fixture.findData("mh_l"))
    mh = app.rig.fixture("mh_l")
    tab.cb_jog.setChecked(True)
    pins = app.manual.calibration
    assert pins is not None
    assert pins.channels[mh.address] == 128 and pins.channels[mh.address + 5] == 255
    assert "mh_l" in pins.absolute_slots
    tab.s_pan.setValue(65535)
    assert app.manual.calibration.channels[mh.address] == 255
    tab.cb_jog.setChecked(False)
    assert app.manual.calibration is None
    # leaving the tab also clears pins
    win.tabs.setCurrentWidget(tab)
    tab.cb_jog.setChecked(True)
    assert app.manual.calibration is not None
    win.tabs.setCurrentIndex(0)
    assert app.manual.calibration is None and not tab.cb_jog.isChecked()


def test_set_aim_captures_a_calibration_and_aim_at_target_reuses_it(qapp):
    from livereact.ui.console import ConsoleWindow

    app = _app()
    win = ConsoleWindow(app)
    tab = win.venue_tab
    tab.cb_fixture.setCurrentIndex(tab.cb_fixture.findData("mh_l"))
    mh = app.rig.fixture("mh_l")
    tab.sb_x.setValue(5.0); tab.sb_y.setValue(2.0); tab.sb_z.setValue(1.0)
    tab.s_pan.setValue(int(0.41 * 65535)); tab.s_tilt.setValue(int(0.63 * 65535))
    tab.cb_target.setCurrentText("dj_booth")
    tab.b_set_aim.click()
    assert mh.calibration.captured and mh.calibration.target == "dj_booth"
    assert "Captured on dj_booth" in tab.l_cal.text()
    # aiming back at the captured target reproduces the captured sliders
    tab.s_pan.setValue(0); tab.s_tilt.setValue(0)
    tab.b_aim.click()
    assert tab.s_pan.value() == pytest.approx(int(0.41 * 65535), abs=2)
    assert tab.s_tilt.value() == pytest.approx(int(0.63 * 65535), abs=2)
    tab.cb_target.setCurrentText("dancefloor_centre")
    tab.b_home.click()
    assert mh.home_pan is not None and mh.home_tilt is not None


def test_laser_probe_pins_a_static_line_only_within_ch7s_static_half(qapp):
    from livereact.fixtures.profiles import Laser
    from livereact.ui.console import ConsoleWindow

    app = _app()
    win = ConsoleWindow(app)
    tab = win.venue_tab
    tab.cb_fixture.setCurrentIndex(tab.cb_fixture.findData("laser_l"))
    laser = app.rig.fixture("laser_l")
    tab.cb_probe.setChecked(True)
    pins = app.manual.calibration
    assert pins is not None and pins.laser_open
    assert pins.channels[laser.address] == Laser.MANUAL_PATTERN_MODE
    assert 0 <= pins.channels[laser.address + 6] <= 127
    tab.s_hoff.setValue(127)
    assert app.manual.calibration.channels[laser.address + 6] == 127
    tab.cb_probe.setChecked(False)
    assert app.manual.calibration is None


def test_laser_cue_button_and_shortcut_drive_manual_params_and_midi_mirrors_back(qapp):
    """2026-09-30: CUE LASER (K) holds ManualParams.laser_cue; a MIDI-learned
    'laser_cue' control writes the same flag and refresh() mirrors it onto
    the button without re-firing the slot."""
    from PySide6 import QtGui
    from livereact.ui.console import ConsoleWindow

    app = _app()
    win = ConsoleWindow(app)
    assert not app.manual.laser_cue and not win.b_laser_cue.isChecked()
    win.b_laser_cue.click()
    assert app.manual.laser_cue
    win.show()
    for sc in win.findChildren(QtGui.QShortcut):
        if sc.key() == QtGui.QKeySequence("K"):
            sc.activated.emit()
    assert not app.manual.laser_cue
    app._on_operator_control("laser_cue", 1.0)      # a knob turned past half-way
    assert app.manual.laser_cue
    win.refresh()
    assert win.b_laser_cue.isChecked()
    app._on_operator_control("laser_cue", 0.2)      # ...and back
    win.refresh()
    assert not win.b_laser_cue.isChecked() and not app.manual.laser_cue
    app._on_operator_control("something_else", 1.0)  # unknown cue names are ignored
    assert not app.manual.laser_cue


def test_laser_cue_banner_tells_josh_when_the_cue_is_not_armed(qapp):
    from livereact.ui.console import ConsoleWindow

    app = _app()
    win = ConsoleWindow(app)
    app.manual.laser_enable = False
    app.manual.laser_cue = True
    win.refresh()
    assert "not armed" in win.l_laser_flash.text()
