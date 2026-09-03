"""Tests for fixture profiles: semantic<->channel translation, boot defaults,
brightness scaling, strobe cap, and the laser safety fail-safe."""

from __future__ import annotations

from livereact.core.frame_buffer import UNIVERSE_SIZE
from livereact.fixtures.profiles import (
    ChannelKind,
    Laser,
    MovingHead,
    Par,
    WashBar,
)
from livereact.merge.merge import Contribution


def _uni() -> bytearray:
    return bytearray(UNIVERSE_SIZE)


def test_moving_head_kinds_have_correct_length_and_types():
    mh = MovingHead(1, "MH", "spot", "left")
    kinds = mh.channel_kinds()
    assert len(kinds) == 15
    assert kinds[0] == ChannelKind.MOVEMENT   # pan
    assert kinds[5] == ChannelKind.DIMMER     # ch6 dimmer
    assert kinds[6] == ChannelKind.STROBE     # ch7 strobe
    assert kinds[7] == ChannelKind.COLOR      # ch8 color wheel


def test_moving_head_semantic_setters_hit_the_right_channels():
    mh = MovingHead(16, "MH-R", "spot", "right")  # address 16
    c = Contribution()
    mh.set_intensity(c, 1.0)
    mh.set_position(c, 0.0, 1.0)
    assert c.values[16 - 1 + 5] == 255  # ch6 dimmer (address+5)
    assert c.values[16 - 1 + 0] == 0    # ch1 pan = 0
    assert c.values[16 - 1 + 2] == 255  # ch3 tilt = 255


def test_moving_head_boot_defaults():
    mh = MovingHead(1, "MH", "spot", "left")
    uni = _uni()

    class _B:
        def set(self, ch, v):
            uni[ch - 1] = v

    mh.boot_defaults(_B())
    assert uni[0] == 128  # pan center
    assert uni[2] == 80   # tilt angled down
    assert uni[5] == 0    # dimmer off


def test_apply_home_position_is_a_noop_when_uncalibrated():
    """docs/14 §4: an uncalibrated fixture (home_pan/tilt still None) keeps
    the old raw 0.5-centered sweep behavior unchanged."""
    mh = MovingHead(1, "MH", "spot", "left")
    uni = _uni()
    uni[mh.offset + 0] = 200  # pan
    uni[mh.offset + 2] = 30   # tilt
    mh.apply_home_position(uni)
    assert uni[mh.offset + 0] == 200
    assert uni[mh.offset + 2] == 30


def test_apply_home_position_bounds_around_the_calibrated_home():
    mh = MovingHead(1, "MH", "spot", "left")
    mh.home_pan, mh.home_tilt = 0.7, 0.3
    uni = _uni()
    # A scene's raw sweep at its extreme (pan=1.0, i.e. byte 255) should land
    # at home + 0.5*bound, not at the raw extreme itself.
    uni[mh.offset + 0] = 255
    uni[mh.offset + 2] = 0
    mh.apply_home_position(uni, bound=0.20)
    assert uni[mh.offset + 0] == round((0.7 + 0.5 * 0.20) * 255)  # 0.8 -> 204
    assert uni[mh.offset + 2] == round((0.3 - 0.5 * 0.20) * 255)  # 0.2 -> 51


def test_apply_home_position_at_raw_center_lands_exactly_on_home():
    mh = MovingHead(1, "MH", "spot", "left")
    mh.home_pan, mh.home_tilt = 0.65, 0.4
    uni = _uni()
    uni[mh.offset + 0] = 128  # raw pan ~0.5 (center, no offset from home)
    uni[mh.offset + 2] = 128
    mh.apply_home_position(uni, bound=0.20)
    assert uni[mh.offset + 0] == round(0.65 * 255)
    assert uni[mh.offset + 2] == round(0.4 * 255)


def test_apply_home_position_clamps_within_0_1():
    """A home near the edge (e.g. 0.95) plus a wide-swinging raw sweep must
    still clamp into a valid DMX byte, not wrap or overflow."""
    mh = MovingHead(1, "MH", "spot", "left")
    mh.home_pan, mh.home_tilt = 0.95, 0.05
    uni = _uni()
    uni[mh.offset + 0] = 255  # raw pan at its extreme, pushing further past 0.95
    uni[mh.offset + 2] = 0
    mh.apply_home_position(uni, bound=0.5)
    assert 0 <= uni[mh.offset + 0] <= 255
    assert 0 <= uni[mh.offset + 2] <= 255


def test_par_master_brightness_scales_only_the_dimmer_channel():
    par = Par(55, "Par", "wash", "left")
    uni = _uni()
    for i, v in enumerate([200, 100, 50, 40]):  # dimmer, R, G, B
        uni[par.offset + i] = v
    par.apply_master_brightness(uni, 0.5)
    assert [uni[par.offset + i] for i in range(4)] == [100, 100, 50, 40]  # only ch1 scaled


def test_wash_bar_strobe_cap():
    bar = WashBar(63, "Bar", "wash", "left")
    uni = _uni()
    uni[bar.offset + 1] = 255  # ch2 strobe at full
    bar.cap_strobe(uni, 0.2)   # cap ~= 51
    assert uni[bar.offset + 1] == 51


def test_laser_boots_off_and_safety_zeros_when_disabled():
    laser = Laser(31, "Laser", "laser", "left")
    uni = _uni()
    # Pretend a scene set a pattern.
    laser.set_pattern(
        type("B", (), {"set": lambda self, ch, v: uni.__setitem__(ch - 1, v)})(),
        pattern=40,
    )
    assert uni[laser.offset] == Laser.MANUAL_PATTERN_MODE  # CH1 in manual range
    laser.apply_safety(uni, laser_enabled=False)
    assert all(uni[laser.offset + i] == 0 for i in range(12))  # all zeroed


def test_laser_safety_leaves_channels_when_enabled():
    laser = Laser(31, "Laser", "laser", "left")
    uni = _uni()
    uni[laser.offset] = Laser.MANUAL_PATTERN_MODE
    laser.apply_safety(uni, laser_enabled=True)
    assert uni[laser.offset] == Laser.MANUAL_PATTERN_MODE  # untouched when enabled


def test_laser_onset_gate_zeros_when_not_flashing():
    """docs/14 §3: additive to apply_safety — armed+enabled alone (which the
    two tests above already cover) isn't enough to show the laser now."""
    laser = Laser(31, "Laser", "laser", "left")
    uni = _uni()
    uni[laser.offset] = Laser.MANUAL_PATTERN_MODE
    laser.apply_onset_gate(uni, flash_active=False)
    assert all(uni[laser.offset + i] == 0 for i in range(12))


def test_laser_onset_gate_leaves_channels_when_flashing():
    laser = Laser(31, "Laser", "laser", "left")
    uni = _uni()
    uni[laser.offset] = Laser.MANUAL_PATTERN_MODE
    laser.apply_onset_gate(uni, flash_active=True)
    assert uni[laser.offset] == Laser.MANUAL_PATTERN_MODE


def test_visual_state_reads_back_color_and_brightness():
    par = Par(55, "Par", "wash", "left")
    uni = _uni()
    buf = type("B", (), {"set": lambda self, ch, v: uni.__setitem__(ch - 1, v)})()
    par.set_intensity(buf, 1.0)   # ch1 dimmer — needed for this fixture to be "active"
    par.set_color(buf, 1.0, 0.0, 0.0)
    vs = par.visual_state(bytes(uni))
    assert vs.r == 255 and vs.g == 0 and vs.b == 0
    assert vs.active and vs.brightness == 1.0
