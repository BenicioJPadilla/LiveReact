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
    expected = {"B", "F", "T", "S", "L", "K", "C", "D", "J",  # J = LASER HIT (2026-10-06, trigger profile)
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
    # 2026-10-05: unticking Jog releases pan/tilt but the calibration beam
    # stays while "Light" is ticked (selecting a head lights it); unticking
    # Light too clears every pin
    pins = app.manual.calibration
    assert pins is not None and mh.address not in pins.channels and pins.channels[mh.address + 5] == 255
    tab.cb_light.setChecked(False)
    assert app.manual.calibration is None
    tab.cb_light.setChecked(True)
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


# --- the bar's feature laser profile (2026-10-01) ------------------------------------

_FEATURE_RIG = {
    "name": "bar-test", "laser_profile": "feature", "slots": [
        {"slot_id": "laser_l", "fixture_type": "shehds_3w_laser", "dmx_address": 1,
         "role": "laser", "side": "left"},
        {"slot_id": "laser_r", "fixture_type": "shehds_3w_laser", "dmx_address": 13,
         "role": "laser", "side": "right"},
        {"slot_id": "bar", "fixture_type": "ok103_wash_bar", "dmx_address": 69,
         "role": "wash", "side": "left"},
    ],
}


def _feature_app(tmp_path) -> App:
    import json

    path = tmp_path / "bar.json"
    path.write_text(json.dumps(_FEATURE_RIG))
    return App(AppConfig(demo=True, config_path=None, rig_path=str(path)))


def test_the_rig_file_picks_the_laser_engine(qapp, tmp_path):
    from livereact.engines.laser import LaserEngine
    from livereact.engines.laser_feature import LaserFeatureEngine

    assert isinstance(_app().laser_engine, LaserEngine)            # packaged default: accent
    app = _feature_app(tmp_path)
    assert isinstance(app.laser_engine, LaserFeatureEngine)
    assert app.show_engine.laser_engine is app.laser_engine        # the finalize gate reads the same object
    assert app.laser_engine.manual is app.manual                   # K cue reaches it


def test_console_shows_the_laser_profile_and_mood(qapp, tmp_path):
    from livereact.core.show_state import ShowSnapshot
    from livereact.ui.console import ConsoleWindow

    win = ConsoleWindow(_app())
    win.refresh()
    assert win.l_laser.text() == "ACCENT"

    app = _feature_app(tmp_path)
    win = ConsoleWindow(app)
    app.manual.laser_enable = True
    # no real audio yet (the metronome isn't running): OFF, and the banner says why
    app.laser_engine.tick(app.show_state.snapshot(), app.rig)
    win.refresh()
    assert win.l_laser.text() == "FEATURE · OFF"
    assert "waiting for real audio" in win.l_laser_flash.text()
    # a calm break with fresh audio
    snap = ShowSnapshot(bpm=128.0, bar=8, audio_fresh=True, bucket="break")
    app.show_state.publish(snap)
    app.laser_engine.tick(snap, app.rig)
    win.refresh()
    assert win.l_laser.text() == "FEATURE · CALM"
    assert win.l_laser_flash.text().startswith("● LASER CALM")
    assert "blue / cyan" in win.l_laser_flash.text()
    # the K cue forces the fan and the banner says so
    app.manual.laser_cue = True
    app.laser_engine.tick(snap, app.rig)
    win.refresh()
    assert win.l_laser.text() == "FEATURE · FAN"
    assert "K forcing the fan" in win.l_laser_flash.text()
    app.manual.laser_cue = False
    # disarmed is the loudest banner in this profile
    app.manual.laser_enable = False
    app.laser_engine.tick(snap, app.rig)
    win.refresh()
    assert "NOT ARMED" in win.l_laser_flash.text()


def test_venue_tab_selecting_a_head_lights_it_and_jog_adds_pan_tilt(qapp):
    """2026-10-05 (Josh): 'when I go to the moving head, I should be able to
    turn on the light just by clicking on it so that I can calibrate it.'"""
    from livereact.merge.merge import CalibrationPins
    from livereact.ui.console import ConsoleWindow

    app = _app()
    win = ConsoleWindow(app)
    tab = win.venue_tab
    mh = app.rig.fixture("mh_l")
    a = mh.address
    tab._load_fixture("mh_l")
    pins = app.manual.calibration
    assert isinstance(pins, CalibrationPins)
    assert pins.channels[a + 5] == 255 and pins.channels[a + 6] == 0 and pins.channels[a + 7] == 0  # dimmer full, strobe off, open white
    assert a not in pins.channels and not pins.absolute_slots                                      # pan/tilt untouched until Jog
    tab.cb_jog.setChecked(True)
    pins = app.manual.calibration
    assert a in pins.channels and a + 2 in pins.channels and pins.absolute_slots == frozenset({"mh_l"})
    assert pins.channels[a + 5] == 255
    tab.cb_light.setChecked(False)                                                                  # jog without the beam
    pins = app.manual.calibration
    assert a in pins.channels and a + 5 not in pins.channels
    tab.cb_jog.setChecked(False)
    assert app.manual.calibration is None                                                           # nothing ticked = no pins
    tab.cb_light.setChecked(True)
    assert app.manual.calibration.channels[a + 5] == 255
    tab._load_fixture("par_l")
    assert app.manual.calibration is None                                                           # leaving the head clears it


def test_laser_hit_button_and_j_key_count_moments(qapp):
    """2026-10-06: the trigger profile's manual laser button is a counter on ManualParams."""
    from livereact.ui.console import ConsoleWindow

    app = _app()
    win = ConsoleWindow(app)
    assert app.manual.laser_hit == 0
    win.b_laser_hit.click()
    win.b_laser_hit.click()
    assert app.manual.laser_hit == 2


def test_outside_writes_to_manual_params_are_mirrored_and_one_press_releases(qapp):
    """The phone console and the relaunch supervisor write ManualParams
    directly; refresh() must show it (signals blocked, never writing back),
    so ONE press of B releases a phone blackout and one L re-arms."""
    from PySide6 import QtGui
    from livereact.ui.console import ConsoleWindow

    app = _app()
    win = ConsoleWindow(app)
    win.refresh()
    # what the phone thread does
    app.manual.blackout = True
    app.manual.laser_enable = False
    app.manual.master_brightness = 0.4
    app.manual.strobe_cap = 0.0
    win.refresh()
    assert win.b_black.isChecked()
    assert not win.cb_laser.isChecked()
    assert win.s_bright.value() == 40 and win.l_bright_v.text() == "40%"
    assert win.s_strobe.value() == 0 and win.l_strobe_v.text() == "0%"
    # the mirror wrote nothing back
    assert app.manual.master_brightness == 0.4 and app.manual.strobe_cap == 0.0
    win.refresh()
    assert app.manual.blackout is True and app.manual.laser_enable is False

    win.b_black.toggle()                     # one press releases it
    assert app.manual.blackout is False
    win.show()
    for sc in win.findChildren(QtGui.QShortcut):
        if sc.key() == QtGui.QKeySequence("L"):
            sc.activated.emit()              # one press re-arms
    assert app.manual.laser_enable is True
    win.refresh()
    assert not win.b_black.isChecked() and win.cb_laser.isChecked()

    # phone freeze, then the phone's blackout clears it
    app.manual.freeze = True
    win.refresh()
    assert win.b_freeze.isChecked()
    app.manual.freeze = False
    win.refresh()
    assert not win.b_freeze.isChecked()


def test_fader_mirror_ignores_values_within_one_step(qapp):
    from livereact.ui.console import ConsoleWindow

    app = _app()
    win = ConsoleWindow(app)
    win.s_bright.setValue(50)
    app.manual.master_brightness = 0.505     # between two steps: no hunting
    win.refresh()
    assert win.s_bright.value() == 50
    assert app.manual.master_brightness == 0.505


def test_console_built_after_a_relaunch_shows_the_restored_state(qapp):
    from livereact.ui.console import ConsoleWindow

    app = _app()
    app.manual.blackout = True
    app.manual.laser_enable = False
    app.manual.master_brightness = 0.4
    app.manual.strobe_cap = 0.0
    win = ConsoleWindow(app)
    assert win.b_black.isChecked()
    assert not win.cb_laser.isChecked()
    assert win.s_bright.value() == 40 and win.s_strobe.value() == 0
    # building the window wrote nothing
    assert app.manual.blackout is True and app.manual.master_brightness == 0.4
    win.b_black.toggle()
    assert app.manual.blackout is False


def test_lost_dj_link_reads_look_held(qapp):
    import dataclasses

    from livereact.ui.console import ConsoleWindow

    app = _app()
    win = ConsoleWindow(app)
    snap = app.show_state.snapshot()
    win._refresh_status(dataclasses.replace(snap, pdl_fresh=False))
    assert win.l_pdl_lost.isHidden()                 # plain stale: no banner
    assert "PDL STALE" in win.l_health.text()

    class Lost:                                      # pdl_lost lives on another branch
        def __init__(self, s):
            self._s = s

        def __getattr__(self, k):
            return getattr(self._s, k)

        pdl_fresh = False
        pdl_lost = True

    win._refresh_status(Lost(snap))
    assert not win.l_pdl_lost.isHidden()
    assert "DJ LINK LOST, look held" in win.l_pdl_lost.text()
    assert "LOST, look held" in win.l_health.text()


def test_dmx_dot_uses_output_ok_when_the_writer_has_it(qapp):
    from livereact.ui.console import ConsoleWindow

    app = _app()
    win = ConsoleWindow(app)
    snap = app.show_state.snapshot()

    class W:
        def __init__(self, name, is_open, **kw):
            self.backend = type("B", (), {"name": name})()
            self.is_open = is_open
            self.__dict__.update(kw)

    app.writer = W("enttec", True)                   # no output_ok: the old logic
    win._refresh_status(snap)
    assert win.pill_conn._segs[3][2] == "ok"
    app.writer = W("enttec", True, output_ok=False)  # open but every write failing
    win._refresh_status(snap)
    assert win.pill_conn._segs[3][2] == "bad"
    app.writer = W("null-log", True, output_ok=True)  # the log fallback is never green
    win._refresh_status(snap)
    assert win.pill_conn._segs[3][2] == "bad"


def test_phone_url_label_appears_when_the_app_has_one(qapp):
    from PySide6 import QtCore
    from livereact.ui.console import ConsoleWindow

    app = _app()
    win = ConsoleWindow(app)
    win.refresh()
    assert win.phone_row.isHidden()
    app.phone_url = "http://192.168.1.20:8765/?k=7F3K9Q"
    win.refresh()
    assert not win.phone_row.isHidden()
    assert win.l_phone.text() == "http://192.168.1.20:8765/?k=7F3K9Q"
    assert win.l_phone.textInteractionFlags() & QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
    app.phone_url = None
    win.refresh()
    assert win.phone_row.isHidden()
