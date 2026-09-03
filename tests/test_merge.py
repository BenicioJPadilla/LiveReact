"""Tests for the merge + finalize layer — these encode the Phase 2 acceptance
criteria (docs/12 Phase 2)."""

from __future__ import annotations

from livereact.fixtures.profiles import Laser, MovingHead, Par, WashBar
from livereact.fixtures.rig import load_rig
from livereact.merge.merge import (
    Contribution,
    ManualParams,
    finalize,
    merge_contributions,
    render_universe,
)


def _rig():
    return load_rig()


def test_color_and_dimmer_merge_by_max():
    rig = _rig()
    par = rig.fixture("par_l")
    c1, c2 = Contribution(), Contribution()
    par.set_color(c1, 0.2, 1.0, 0.0)  # R=51,  G=255 (ch2=R, ch3=G)
    par.set_color(c2, 0.8, 0.1, 0.0)  # R=204, G=25
    merged = merge_contributions([c1, c2], rig)
    assert merged[par.offset + 1] == 204  # max red
    assert merged[par.offset + 2] == 255  # max green


def test_movement_is_last_write_wins():
    rig = _rig()
    mh = rig.fixture("mh_l")
    c1, c2 = Contribution(), Contribution()
    mh.set_position(c1, 0.0, 0.0)
    mh.set_position(c2, 1.0, 1.0)  # later contribution wins for movement
    merged = merge_contributions([c1, c2], rig)
    assert merged[mh.offset + 0] == 255  # pan from c2
    assert merged[mh.offset + 2] == 255  # tilt from c2


def test_untouched_channels_keep_boot_defaults():
    rig = _rig()
    merged = merge_contributions([Contribution()], rig)  # empty contribution
    assert merged[0] == 128  # MH Left pan stays centered (boot default)


def test_blackout_zeros_everything():
    rig = _rig()
    par = rig.fixture("par_l")
    c = Contribution()
    par.set_color(c, 1.0, 1.0, 1.0)
    out = render_universe([c], rig, ManualParams(blackout=True))
    assert out == bytes(512)


def test_master_brightness_scales_dimmers():
    rig = _rig()
    bar = rig.fixture("bar_l")
    c = Contribution()
    bar.set_intensity(c, 1.0)  # ch1 dimmer = 255
    full = render_universe([c], rig, ManualParams(master_brightness=1.0))
    half = render_universe([c], rig, ManualParams(master_brightness=0.5))
    assert full[bar.offset] == 255
    assert half[bar.offset] == 127  # scaled


def test_lasers_cannot_be_nonzero_unless_enabled():
    """Isolates the arm gate specifically — laser_flash_active=True so the
    docs/14 §3 onset gate (tested separately above) doesn't also zero it."""
    rig = _rig()
    laser = rig.fixture("laser_l")
    c = Contribution()
    laser.set_pattern(c, pattern=40, color=200)

    off = render_universe([c], rig, ManualParams(laser_enable=False), laser_flash_active=True)
    assert all(off[laser.offset + i] == 0 for i in range(12))  # fail-safe

    on = render_universe([c], rig, ManualParams(laser_enable=True), laser_flash_active=True)
    assert on[laser.offset] == Laser.MANUAL_PATTERN_MODE  # CH1 enabled


def test_strobe_capped_on_finalize():
    rig = _rig()
    bar = rig.fixture("bar_l")
    c = Contribution()
    bar.set_strobe(c, 1.0)  # ch2 strobe full
    out = render_universe([c], rig, ManualParams(strobe_cap=0.2))
    assert out[bar.offset + 1] == 51  # ~0.2 * 255


def test_auto_blackout_zeros_the_frame_independently_of_manual():
    """docs/14 §2: auto_blackout and manual.blackout are independent triggers
    — the operator's switch must not need to be flipped for the automatic
    one to work, and vice versa."""
    rig = _rig()
    mh = rig.fixture("mh_l")
    c = Contribution()
    mh.set_intensity(c, 1.0)
    lit = render_universe([c], rig, ManualParams())
    assert any(lit)

    merged = merge_contributions([c], rig)
    blacked = finalize(merged, rig, ManualParams(), auto_blackout=True)
    assert blacked == bytes(len(blacked))
    assert not any(blacked)


def test_finalize_bounds_movement_around_a_calibrated_home_position():
    """docs/14 §4, end-to-end through finalize(): a scene's raw wide sweep
    gets remapped around the fixture's calibrated home once set."""
    rig = _rig()
    mh = rig.fixture("mh_l")
    mh.home_pan, mh.home_tilt = 0.7, 0.3
    c = Contribution()
    mh.set_position(c, 1.0, 0.0)  # a scene sweeping to its raw extreme
    out = render_universe([c], rig, ManualParams())
    assert out[mh.offset + 0] == round((0.7 + 0.5 * 0.20) * 255)  # bounded near home, not raw 255
    assert out[mh.offset + 2] == round((0.3 - 0.5 * 0.20) * 255)


def test_laser_flash_gate_zeros_the_laser_independently_of_scene_and_arm():
    """docs/14 §3: even armed + an eligible scene set a pattern, the laser
    stays off through finalize() unless a real onset flash is active."""
    rig = _rig()
    laser = rig.fixture("laser_l")
    c = Contribution()
    laser.set_pattern(c, pattern=60)
    armed = ManualParams(laser_enable=True)

    not_flashing = render_universe([c], rig, armed, laser_flash_active=False)
    assert all(not_flashing[laser.offset + i] == 0 for i in range(12))

    flashing = render_universe([c], rig, armed, laser_flash_active=True)
    assert flashing[laser.offset] != 0


def test_one_engine_movement_does_not_clobber_another_engines_color():
    rig = _rig()
    mh = rig.fixture("mh_l")
    color_engine, move_engine = Contribution(), Contribution()
    mh.set_color(color_engine, 1.0, 0.0, 0.0)  # sets color wheel only
    mh.set_position(move_engine, 1.0, 1.0)     # sets movement only
    merged = merge_contributions([color_engine, move_engine], rig)
    assert merged[mh.offset + 7] != 0   # color wheel preserved
    assert merged[mh.offset + 0] == 255  # movement applied
