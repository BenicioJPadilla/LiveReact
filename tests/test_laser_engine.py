"""Tests for engines/laser.py -- the laser layer (2026-09-15). Driven with a
FakeClock; the packaged default rig has one laser at slot `laser_l`."""

from __future__ import annotations

import threading

from livereact.clock import FakeClock
from livereact.core.frame_buffer import DmxFrameBuffer
from livereact.core.show_engine import ShowEngine
from livereact.core.show_state import ShowSnapshot, ShowState
from livereact.engines.laser import (
    LASER_MIN_HIT_INTENSITY,
    LASER_SWEEP_BASE,
    LaserEngine,
    laser_color_for_palette,
    laser_wanted,
)
from livereact.engines.reactive import ReactiveLayerEngine
from livereact.fixtures.profiles import Laser
from livereact.fixtures.rig import load_rig
from livereact.merge.merge import ManualParams


def _snap(**kw) -> ShowSnapshot:
    base = dict(bpm=128.0, audio_fresh=True, pdl_fresh=True, bucket="drop",
                drop_hit_intensity=1.0, energy=0.9, energy_norm=0.9, palette="blood_red",
                audio_band_low_abs=5.0)
    base.update(kw)
    return ShowSnapshot(**base)


def _laser_channels(c, rig):
    laser = rig.fixture("laser_l")
    return [c.values[laser.offset + i] for i in range(12)], any(c.touched[laser.offset + i] for i in range(12))


# --- the musical gate ----------------------------------------------------------

def test_a_loud_drop_earns_the_laser_from_the_first_tick():
    assert laser_wanted(_snap(bucket="drop", drop_hit_intensity=1.0))
    assert laser_wanted(_snap(bucket="drop", drop_hit_intensity=LASER_MIN_HIT_INTENSITY))


def test_a_softer_drop_waits_for_the_peak_escalation():
    """Measured 2026-09-15: second drops captured 0.92-0.94 and all escalated
    to PEAK ~15 s in -- the laser arrives with the escalation, not the hit."""
    assert not laser_wanted(_snap(bucket="drop", drop_hit_intensity=0.93))
    assert laser_wanted(_snap(bucket="peak", drop_hit_intensity=0.93))


def test_never_outside_drop_or_peak():
    for bucket in ("break", "build", "outro"):
        assert not laser_wanted(_snap(bucket=bucket, drop_hit_intensity=1.0)), bucket


def test_signal_loss_forces_off_even_mid_drop():
    """LASER-12: any signal loss -> off, never a held value."""
    rig = load_rig()
    eng = LaserEngine(FakeClock())
    eng.tick(_snap(), rig)
    assert eng.active
    eng.tick(_snap(audio_fresh=False), rig)
    assert not eng.active
    eng.tick(_snap(pdl_fresh=False), rig)
    assert not eng.active


# --- what it writes --------------------------------------------------------------

def test_writes_the_verified_dotted_line_sweep_when_on():
    rig = load_rig()
    eng = LaserEngine(FakeClock())
    c = eng.tick(_snap(), rig)
    values, touched = _laser_channels(c, rig)
    assert touched
    assert values[0] == Laser.MANUAL_PATTERN_MODE       # CH1 manual
    assert values[1] == Laser.PATTERN_A1_DOTTED_LINE    # CH2 flattened line
    assert values[8] == Laser.SCALE_STATIC              # CH9 MUST stay 0
    assert values[10] == Laser.SCAN_DOTS                # CH11 dotted outline
    assert Laser.SWEEP_SPEED_MIN <= values[6] <= Laser.SWEEP_SPEED_MAX  # CH7 in the sweep band
    assert values[6] >= Laser.SWEEP_SPEED_MIN + round(LASER_SWEEP_BASE * 127) - 1  # never below the idle fan speed


def test_writes_nothing_when_off():
    rig = load_rig()
    eng = LaserEngine(FakeClock())
    c = eng.tick(_snap(bucket="build"), rig)
    _, touched = _laser_channels(c, rig)
    assert not touched and not eng.active


def test_color_is_the_palette_entry_snapped_to_a_macro():
    assert laser_color_for_palette("blood_red") == Laser.COLOR_RED
    assert laser_color_for_palette("cold_steel") == Laser.COLOR_BLUE
    assert laser_color_for_palette("hot_magenta") == Laser.COLOR_PURPLE
    assert laser_color_for_palette("neutral_wash") == Laser.COLOR_WHITE
    assert laser_color_for_palette("something_new") == Laser.COLOR_WHITE
    rig = load_rig()
    eng = LaserEngine(FakeClock())
    c = eng.tick(_snap(palette="cold_steel"), rig)
    values, _ = _laser_channels(c, rig)
    assert values[11] == Laser.COLOR_BLUE


# --- the wub envelope on CH7 ------------------------------------------------------

def _settle(eng, rig, clock, level, ticks=300, dt=0.02):
    for _ in range(ticks):
        eng.tick(_snap(audio_band_low_abs=level), rig)
        clock.advance(dt)


def test_fan_idles_at_the_base_speed_on_a_steady_bassline():
    """First live run: with no base the fan crawled at CH7 ~136 -- Josh:
    'it should be more of like a fan.' It now idles mid-band."""
    clock = FakeClock()
    rig = load_rig()
    eng = LaserEngine(clock)
    _settle(eng, rig, clock, level=8.0)
    c = eng.tick(_snap(audio_band_low_abs=8.0), rig)
    values, _ = _laser_channels(c, rig)
    assert eng.wub <= 0.05
    assert abs(eng.sweep - LASER_SWEEP_BASE) < 0.05
    assert abs(values[6] - (Laser.SWEEP_SPEED_MIN + LASER_SWEEP_BASE * 127)) <= 4


def test_a_wub_above_the_bassline_speeds_the_sweep_up_then_it_relaxes():
    clock = FakeClock()
    rig = load_rig()
    eng = LaserEngine(clock)
    _settle(eng, rig, clock, level=8.0)
    c = eng.tick(_snap(audio_band_low_abs=24.0), rig)  # a wub: 3x the bassline
    values, _ = _laser_channels(c, rig)
    fast = eng.sweep
    assert fast > LASER_SWEEP_BASE + 0.3
    assert values[6] > Laser.SWEEP_SPEED_MIN + round(LASER_SWEEP_BASE * 127) + 30
    clock.advance(0.15)
    eng.tick(_snap(audio_band_low_abs=8.0), rig)
    assert eng.sweep < fast  # releasing back toward the idle speed


def test_a_smaller_wub_after_a_bigger_one_reads_proportionally():
    """Self-normalized: the biggest recent wub is full speed, a smaller one
    that follows it is a fraction of that, not a fixed-gain absolute."""
    clock = FakeClock()
    rig = load_rig()
    eng = LaserEngine(clock)
    _settle(eng, rig, clock, level=8.0)
    eng.tick(_snap(audio_band_low_abs=40.0), rig)  # a big wub sets the peak
    big = eng.wub
    for _ in range(20):  # release, ~0.4 s
        clock.advance(0.02)
        eng.tick(_snap(audio_band_low_abs=8.0), rig)
    eng.tick(_snap(audio_band_low_abs=16.0), rig)  # a smaller wub
    assert 0.0 < eng.wub < big


def test_active_is_a_plain_python_bool_even_from_numpy_inputs():
    """The recorder lost 162 samples on the first live run to a numpy bool
    leaking out of the hit-intensity comparison."""
    import numpy as np
    rig = load_rig()
    eng = LaserEngine(FakeClock())
    eng.tick(_snap(drop_hit_intensity=np.float64(0.97)), rig)
    assert type(eng.active) is bool and eng.active
    eng.tick(_snap(drop_hit_intensity=np.float64(0.90)), rig)
    assert type(eng.active) is bool and not eng.active


# --- end to end through the real ShowEngine + finalize --------------------------------

def _show(snap: ShowSnapshot, testing: bool):
    rig = load_rig()
    for fx in rig.by_role("laser"):
        fx.mount_height_m = 0.9  # like Josh's real rig: below LASER-09's 3 m
        fx.safety_test_mode = testing
    clock = FakeClock()
    state = ShowState()
    state.publish(snap)
    laser = LaserEngine(clock)
    eng = ShowEngine(state, rig, DmxFrameBuffer(), [ReactiveLayerEngine(clock), laser],
                     ManualParams(laser_enable=True), clock, threading.Event(), laser_engine=laser)
    frame = eng.tick()
    return frame[rig.fixture("laser_l").offset], laser


def test_end_to_end_the_laser_lights_in_a_loud_drop_under_testing_mode():
    ch1, laser = _show(_snap(), testing=True)
    assert laser.active
    assert ch1 == Laser.MANUAL_PATTERN_MODE


def test_end_to_end_the_geometry_gate_still_wins_without_testing_mode():
    """The layer says on, but a 0.9 m mount without --testing is forced off
    by Laser.apply_safety -- the bench override is the ONLY bypass."""
    ch1, laser = _show(_snap(), testing=False)
    assert laser.active
    assert ch1 == 0


def test_end_to_end_a_break_never_lights_the_laser_even_in_testing_mode():
    ch1, laser = _show(_snap(bucket="break"), testing=True)
    assert not laser.active
    assert ch1 == 0


def test_show_engine_without_a_laser_engine_keeps_the_gate_closed():
    rig = load_rig()
    for fx in rig.by_role("laser"):
        fx.safety_test_mode = True
    clock = FakeClock()
    state = ShowState()
    state.publish(_snap())
    eng = ShowEngine(state, rig, DmxFrameBuffer(), [ReactiveLayerEngine(clock)],
                     ManualParams(laser_enable=True), clock, threading.Event())
    frame = eng.tick()
    assert frame[rig.fixture("laser_l").offset] == 0
