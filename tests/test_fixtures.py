"""Tests for fixture profiles: semantic<->channel translation, boot defaults,
brightness scaling, strobe cap, and the laser safety fail-safe."""

from __future__ import annotations

import pytest

from livereact.core.frame_buffer import UNIVERSE_SIZE
from livereact.fixtures.profiles import (
    DIMMER_FLOOR_DMX,
    ChannelKind,
    Laser,
    MovingHead,
    Par,
    WashBar,
    _intensity_to8,
)
from livereact.merge.merge import Contribution


def _uni() -> bytearray:
    return bytearray(UNIVERSE_SIZE)


# --- _intensity_to8: gamma + floor dimmer curve (LIGHTING_BIBLE.md §3.7) ----


def test_intensity_curve_true_zero_stays_zero():
    assert _intensity_to8(0.0) == 0


def test_intensity_curve_never_dwells_in_the_1_to_30_stepping_zone():
    """Any nonzero intent, however dim, snaps straight to at least the floor
    (31/12%) -- it never lands in the visually-broken 1-30 DMX range."""
    for level in (1e-6, 0.01, 0.1, 0.3):
        value = _intensity_to8(level)
        assert value == 0 or value >= DIMMER_FLOOR_DMX


def test_intensity_curve_full_level_hits_max():
    assert _intensity_to8(1.0) == 255


def test_intensity_curve_is_gamma_shaped_not_linear():
    """A linear mapping would put 0.5 at 128; the gamma curve (exponent 2.2)
    pushes it well below that, per LIGHTING_BIBLE.md §3.7's square-law finding."""
    assert _intensity_to8(0.5) == 55


def test_moving_head_kinds_have_correct_length_and_types():
    mh = MovingHead(1, "MH", "spot", "left")
    kinds = mh.channel_kinds()
    assert len(kinds) == 15
    assert kinds[0] == ChannelKind.MOVEMENT   # pan
    assert kinds[5] == ChannelKind.DIMMER     # ch6 dimmer
    assert kinds[6] == ChannelKind.STROBE     # ch7 strobe
    assert kinds[7] == ChannelKind.COLOR      # ch8 color wheel


def test_moving_head_capabilities_are_wheel_discrete_not_rgb():
    """Bible-integration Phase 1: MovingHead overrides the base's generic
    capabilities() derivation specifically to avoid claiming "rgb" -- CH8 is
    tagged ChannelKind.COLOR for merge purposes (MERGE-06) but it's a
    discrete wheel slot, not continuous RGB mixing."""
    mh = MovingHead(1, "MH", "spot", "left")
    caps = mh.capabilities()
    assert caps == {"pan_tilt", "native_strobe_channel", "wheel_discrete"}
    assert "rgb" not in caps


def test_par_capabilities_derive_generically_from_channel_kinds():
    from livereact.fixtures.profiles import Par
    par = Par(1, "Par", "wash", "left")
    assert par.capabilities() == {"rgb"}  # DIMMER isn't a capability token; no strobe/movement/laser channel


def test_wash_bar_capabilities_include_native_strobe():
    from livereact.fixtures.profiles import WashBar
    bar = WashBar(1, "Bar", "wash", "left")
    assert bar.capabilities() == {"rgb", "native_strobe_channel"}


def test_laser_capabilities_are_laser_only():
    from livereact.fixtures.profiles import Laser
    laser = Laser(1, "Laser", "laser", "left")
    assert laser.capabilities() == {"laser"}


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


def test_apply_slew_limit_passes_through_the_first_commanded_position():
    """No prior reference on the very first call -- nothing to ramp from, so
    the command goes through unclamped (matches the pre-slew-limit behavior
    for a freshly-constructed fixture)."""
    mh = MovingHead(1, "MH", "spot", "left")
    uni = _uni()
    uni[mh.offset + 0] = 255
    uni[mh.offset + 2] = 0
    mh.apply_slew_limit(uni, dt=0.025)
    assert uni[mh.offset + 0] == 255
    assert uni[mh.offset + 2] == 0


def test_apply_slew_limit_clamps_a_large_jump():
    """LIGHTING_BIBLE.md §6.6 worked example: 260 deg/s over a 540 deg range,
    at a 25ms (40Hz) frame, gives ~3.07 DMX/frame max pan step."""
    mh = MovingHead(1, "MH", "spot", "left")
    uni = _uni()
    uni[mh.offset + 0] = 0
    mh.apply_slew_limit(uni, dt=0.025)  # establishes prev=0
    uni[mh.offset + 0] = 255  # a scene commands an instant full-range jump
    mh.apply_slew_limit(uni, dt=0.025)
    assert uni[mh.offset + 0] == 3  # round(260*0.025/540*255) = round(3.069) = 3


def test_apply_slew_limit_allows_a_small_move_through_unclamped():
    mh = MovingHead(1, "MH", "spot", "left")
    uni = _uni()
    uni[mh.offset + 2] = 100
    mh.apply_slew_limit(uni, dt=0.025)  # establishes prev=100
    uni[mh.offset + 2] = 101  # a 1-count move, well within the per-frame limit
    mh.apply_slew_limit(uni, dt=0.025)
    assert uni[mh.offset + 2] == 101


def test_apply_slew_limit_ramps_a_large_move_over_multiple_frames():
    mh = MovingHead(1, "MH", "spot", "left")
    uni = _uni()
    uni[mh.offset + 0] = 0
    mh.apply_slew_limit(uni, dt=0.025)
    values = []
    for _ in range(5):
        uni[mh.offset + 0] = 255  # scene keeps commanding the same far target
        mh.apply_slew_limit(uni, dt=0.025)
        values.append(uni[mh.offset + 0])
    assert values == sorted(values)  # monotonic climb toward the target
    assert values[-1] < 255  # still ramping, hasn't arrived in just 5 frames


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
    laser.set_dotted_line_sweep(
        type("B", (), {"set": lambda self, ch, v: uni.__setitem__(ch - 1, v)})(),
        color=Laser.COLOR_WHITE, sweep_intensity=0.5,
    )
    assert uni[laser.offset] == Laser.MANUAL_PATTERN_MODE  # CH1 in manual range
    laser.apply_safety(uni, laser_enabled=False)
    assert all(uni[laser.offset + i] == 0 for i in range(12))  # all zeroed


def test_set_dotted_line_sweep_writes_the_verified_channels():
    """docs/14 §3, 2026-09-06: the one hardware-verified laser pattern."""
    laser = Laser(31, "Laser", "laser", "left")
    c = Contribution()
    laser.set_dotted_line_sweep(c, color=Laser.COLOR_GREEN, sweep_intensity=0.0)
    assert c.values[laser.offset + 0] == Laser.MANUAL_PATTERN_MODE      # CH1
    assert c.values[laser.offset + 1] == Laser.PATTERN_A1_DOTTED_LINE   # CH2
    assert c.values[laser.offset + 2] == Laser.PATTERN_A2_DEFAULT       # CH3
    assert c.values[laser.offset + 6] == Laser.SWEEP_SPEED_MIN          # CH7 @ intensity=0
    assert c.values[laser.offset + 8] == Laser.SCALE_STATIC             # CH9 -- must stay 0
    assert c.values[laser.offset + 10] == Laser.SCAN_DOTS               # CH11
    assert c.values[laser.offset + 11] == Laser.COLOR_GREEN             # CH12


def test_dotted_line_sweep_speed_scales_with_intensity():
    laser = Laser(31, "Laser", "laser", "left")
    c = Contribution()
    laser.set_dotted_line_sweep(c, color=Laser.COLOR_WHITE, sweep_intensity=1.0)
    assert c.values[laser.offset + 6] == Laser.SWEEP_SPEED_MAX


def test_laser_safety_leaves_channels_when_enabled():
    """mount_height_m set to a safe value (Stage 6 audit fix, LASER-08/09/10/
    11): apply_safety now ALSO fails closed on undeclared/unsafe beam-height
    geometry, isolated from the arm switch this test is actually about --
    see test_laser_safety_zeros_channels_on_undeclared_geometry below for
    that half."""
    laser = Laser(31, "Laser", "laser", "left")
    laser.mount_height_m = 3.0
    uni = _uni()
    uni[laser.offset] = Laser.MANUAL_PATTERN_MODE
    laser.apply_safety(uni, laser_enabled=True)
    assert uni[laser.offset] == Laser.MANUAL_PATTERN_MODE  # untouched when enabled


def test_laser_safety_zeros_channels_on_undeclared_geometry():
    """LIGHTING_BIBLE.md §8.6, LASER-08/09/10/11 (Stage 6 audit fix,
    2026-09-09): even armed, the laser fails closed if `mount_height_m` was
    never declared in the rig manifest -- fixes a real, previously-confirmed
    gap where safety depended entirely on the operator's arm switch with no
    geometry precondition at all."""
    laser = Laser(31, "Laser", "laser", "left")
    uni = _uni()
    uni[laser.offset] = Laser.MANUAL_PATTERN_MODE
    laser.apply_safety(uni, laser_enabled=True)
    assert uni[laser.offset] == 0  # undeclared geometry -- forced off despite being armed


def test_laser_safety_zeros_channels_below_the_minimum_beam_height():
    laser = Laser(31, "Laser", "laser", "left")
    laser.mount_height_m = 2.5  # below the 3.0 m default minimum
    uni = _uni()
    uni[laser.offset] = Laser.MANUAL_PATTERN_MODE
    laser.apply_safety(uni, laser_enabled=True)
    assert uni[laser.offset] == 0


def test_laser_gate_zeros_when_the_laser_layer_is_off():
    """docs/14 §3: additive to apply_safety — armed+enabled alone (which the
    two tests above already cover) isn't enough to show the laser now."""
    laser = Laser(31, "Laser", "laser", "left")
    uni = _uni()
    uni[laser.offset] = Laser.MANUAL_PATTERN_MODE
    laser.apply_laser_gate(uni, laser_on=False)
    assert all(uni[laser.offset + i] == 0 for i in range(12))


def test_laser_gate_leaves_channels_when_the_laser_layer_is_on():
    laser = Laser(31, "Laser", "laser", "left")
    uni = _uni()
    uni[laser.offset] = Laser.MANUAL_PATTERN_MODE
    laser.apply_laser_gate(uni, laser_on=True)
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


# --- 16-bit pan/tilt + laser static line (2026-09-18 venue aiming) -------------

def test_set_position_writes_fine_bytes():
    from livereact.merge.merge import Contribution
    mh = MovingHead(1, "MH", "spot", "left")
    c = Contribution()
    mh.set_position(c, 0.5, 0.5)
    assert (c.values[0], c.values[1]) == (128, 0)      # 32768 -> coarse 128, fine 0
    assert (c.values[2], c.values[3]) == (128, 0)
    mh.set_position(c, 300 / 65535, 1.0)
    assert (c.values[0], c.values[1]) == (1, 44)       # 300 = 1*256 + 44
    assert (c.values[2], c.values[3]) == (255, 255)


def test_visual_state_reads_16_bit():
    mh = MovingHead(1, "MH", "spot", "left")
    uni = _uni()
    uni[0], uni[1] = 128, 128   # 32896/65535
    uni[2], uni[3] = 0, 0
    vs = mh.visual_state(bytes(uni))
    assert vs.pan == pytest.approx(32896 / 65535)
    assert vs.tilt == 0.0


def test_slew_limit_has_sub_8bit_resolution():
    """A ramp toward a far target advances in 16-bit counts: the fine byte
    is nonzero mid-ramp (789 counts/frame at 40 Hz = coarse 3, fine 21)."""
    mh = MovingHead(1, "MH", "spot", "left")
    uni = _uni()
    mh.apply_slew_limit(uni, dt=0.025)  # prev = 0
    uni[0], uni[1] = 255, 255
    mh.apply_slew_limit(uni, dt=0.025)
    assert (uni[0], uni[1]) == (3, 21)  # round(260*0.025/540*65535) = 789 = 3*256 + 21


def test_home_remap_preserves_fine_precision():
    mh = MovingHead(1, "MH", "spot", "left")
    mh.home_pan, mh.home_tilt = 0.7, 0.3
    uni = _uni()
    uni[0], uni[1] = 128, 0      # raw centre
    mh.apply_home_position(uni, bound=0.20)
    pan16 = (uni[0] << 8) | uni[1]
    assert pan16 == pytest.approx(0.7 * 65535, abs=2)
    assert uni[1] != 0           # the fine byte carries real precision


def test_home_remap_is_skipped_for_an_absolute_aim():
    mh = MovingHead(1, "MH", "spot", "left")
    mh.home_pan, mh.home_tilt = 0.7, 0.3
    uni = _uni()
    uni[0], uni[2] = 255, 0
    mh.apply_home_position(uni, bound=0.20, absolute=True)
    assert (uni[0], uni[2]) == (255, 0)


def test_fine_channels_can_be_switched_off():
    from livereact.merge.merge import Contribution
    mh = MovingHead(1, "MH", "spot", "left")
    mh.USE_FINE_CHANNELS = False
    c = Contribution()
    mh.set_position(c, 300 / 65535, 0.5)
    assert (c.values[0], c.values[1]) == (1, 0)


def test_laser_static_line_never_writes_the_sweep_half_of_ch7():
    from livereact.fixtures.profiles import Laser
    from livereact.merge.merge import Contribution
    laser = Laser(1, "L", "laser", "left")
    for h in (0.0, 0.5, 1.0, 7.0, -3.0):
        c = Contribution()
        laser.set_static_line(c, Laser.COLOR_GREEN, h)
        assert 0 <= c.values[6] <= 127          # CH7 static half only
        assert c.values[0] == Laser.MANUAL_PATTERN_MODE
        assert c.values[1] == Laser.PATTERN_A1_DOTTED_LINE
    c = Contribution()
    laser.set_static_line(c, Laser.COLOR_GREEN, 0.5)
    assert c.values[6] == 64
