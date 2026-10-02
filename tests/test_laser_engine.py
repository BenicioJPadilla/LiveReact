"""Tests for engines/laser.py -- the laser layer (2026-09-15, rebuilt
2026-09-16 as one sweep per 8-bar block in PEAK). Driven with a FakeClock;
the packaged default rig has one laser at slot `laser_l`."""

from __future__ import annotations

import threading

from livereact.clock import FakeClock
from livereact.core.frame_buffer import DmxFrameBuffer
from livereact.core.show_engine import ShowEngine
from livereact.core.show_state import ShowSnapshot, ShowState
from livereact.engines.laser import (
    LASER_BLOCK_BARS,
    LASER_MIN_HIT_INTENSITY,
    LASER_SWEEP_BARS,
    LASER_SWEEP_BASE,
    LaserEngine,
    laser_color_for_palette,
    laser_wanted,
)
from livereact.engines.reactive import ReactiveLayerEngine
from livereact.fixtures.profiles import Laser
from livereact.fixtures.rig import load_rig
from livereact.merge.merge import Contribution, ManualParams

BEAT_S = 60.0 / 128.0
BAR_S = 4 * BEAT_S


def _snap(**kw) -> ShowSnapshot:
    base = dict(bpm=128.0, audio_fresh=True, pdl_fresh=True, bucket="peak",
                drop_hit_intensity=1.0, energy=0.9, energy_norm=0.9, palette="blood_red",
                audio_band_low_abs=5.0, drop_start_bar=40, bar=48, beat_in_bar=1)
    base.update(kw)
    return ShowSnapshot(**base)


def _laser_channels(c, rig):
    laser = rig.fixture("laser_l")
    return [c.values[laser.offset + i] for i in range(12)], any(c.touched[laser.offset + i] for i in range(12))


def _run_bars(eng, rig, clock, first_bar, n_bars, ticks_per_bar=8, **kw):
    """Tick through n_bars of PEAK starting at `first_bar`; returns the list
    of (bar, beat, active) seen."""
    seen = []
    for b in range(n_bars):
        for k in range(ticks_per_bar):
            beat = 1 + (k * 4) // ticks_per_bar
            eng.tick(_snap(bar=first_bar + b, beat_in_bar=beat, **kw), rig)
            seen.append((first_bar + b, beat, eng.active))
            clock.advance(BAR_S / ticks_per_bar)
    return seen


# --- the musical gate ----------------------------------------------------------

def test_only_a_loud_peak_earns_the_laser():
    assert laser_wanted(_snap(bucket="peak", drop_hit_intensity=1.0))
    assert laser_wanted(_snap(bucket="peak", drop_hit_intensity=LASER_MIN_HIT_INTENSITY))
    assert not laser_wanted(_snap(bucket="peak", drop_hit_intensity=0.93))


def test_a_plain_drop_never_earns_it_however_loud():
    """Third live run: the flash version fired 104 times across every DROP
    and PEAK. The strobe owns the hit; the laser waits for the escalation."""
    assert not laser_wanted(_snap(bucket="drop", drop_hit_intensity=1.0))
    for bucket in ("break", "build", "outro"):
        assert not laser_wanted(_snap(bucket=bucket, drop_hit_intensity=1.0)), bucket


# --- the block trigger ---------------------------------------------------------------

def test_one_sweep_per_block_starting_on_the_block_boundary():
    """drop_start_bar 40 -> blocks start at bars 40, 48, 56... The engine
    enters PEAK at bar 48 (the escalation, a boundary): sweep. Bars 49-55
    stay primed but dark. Bar 56: the next sweep."""
    rig = load_rig()
    clock = FakeClock()
    eng = LaserEngine(clock)
    seen = _run_bars(eng, rig, clock, first_bar=48, n_bars=LASER_BLOCK_BARS + 1)
    lit_bars = sorted({bar for bar, _, on in seen if on})
    assert lit_bars == [48, 56]
    assert not any(on for bar, _, on in seen if bar in range(49, 56))


def test_a_sweep_lasts_one_bar_then_closes_on_its_own():
    rig = load_rig()
    clock = FakeClock()
    eng = LaserEngine(clock)
    eng.tick(_snap(bar=48), rig)
    assert eng.active
    clock.advance(LASER_SWEEP_BARS * BAR_S * 0.9)
    eng.tick(_snap(bar=48, beat_in_bar=4), rig)
    assert eng.active
    clock.advance(LASER_SWEEP_BARS * BAR_S * 0.2)
    eng.tick(_snap(bar=49), rig)
    assert not eng.active and eng.primed


def test_entering_peak_mid_block_fires_the_escalation_then_the_next_boundary():
    """PEAK that starts at bar 50 (not a boundary): the escalation itself is
    the block's sweep (fourth live run: the escalation landed a bar past a
    boundary and the first sweep waited 8 bars), then bar 56 as usual --
    never anything in between."""
    rig = load_rig()
    clock = FakeClock()
    eng = LaserEngine(clock)
    seen = _run_bars(eng, rig, clock, first_bar=50, n_bars=7)
    lit_bars = sorted({bar for bar, _, on in seen if on})
    assert lit_bars == [50, 56]


def test_the_same_block_never_fires_twice():
    rig = load_rig()
    clock = FakeClock()
    eng = LaserEngine(clock)
    eng.tick(_snap(bar=48), rig)
    clock.advance(LASER_SWEEP_BARS * BAR_S + 0.1)
    eng.tick(_snap(bar=48, beat_in_bar=4), rig)  # still bar 48, sweep over
    assert not eng.active
    clock.advance(0.1)
    eng.tick(_snap(bar=48, beat_in_bar=4), rig)
    assert not eng.active


def test_falls_back_to_its_entry_bar_when_the_snapshot_has_no_origin():
    rig = load_rig()
    clock = FakeClock()
    eng = LaserEngine(clock)
    seen = _run_bars(eng, rig, clock, first_bar=13, n_bars=LASER_BLOCK_BARS + 1, drop_start_bar=None)
    lit_bars = sorted({bar for bar, _, on in seen if on})
    assert lit_bars == [13, 13 + LASER_BLOCK_BARS]


def test_leaving_peak_closes_an_open_sweep_and_a_blip_back_does_not_refire_the_block():
    """The PEAK overlay has hysteresis but still blips PEAK->DROP->PEAK now
    and then (replayed 2026-09-16: a 0.2 s blip at 124.6 s). One sweep per
    block means one, blip or not. A NEW drop (new origin) starts fresh."""
    rig = load_rig()
    clock = FakeClock()
    eng = LaserEngine(clock)
    eng.tick(_snap(bar=48), rig)
    assert eng.active
    eng.tick(_snap(bar=48, bucket="drop"), rig)
    assert not eng.active and not eng.primed
    eng.tick(_snap(bar=48, bucket="peak"), rig)  # back in the same block
    assert not eng.active and eng.primed
    eng.tick(_snap(bar=48, drop_start_bar=48), rig)  # a new drop whose origin is this bar
    assert eng.active


def test_signal_loss_forces_off_even_mid_sweep():
    """LASER-12: any signal loss -> off, never a held value."""
    rig = load_rig()
    clock = FakeClock()
    eng = LaserEngine(clock)
    eng.tick(_snap(bar=48), rig)
    assert eng.active
    c = eng.tick(_snap(bar=48, audio_fresh=False), rig)
    assert not eng.active and not eng.primed
    _, touched = _laser_channels(c, rig)
    assert not touched
    eng.tick(_snap(bar=48), rig)
    assert not eng.active and eng.primed  # back in the same block: no second sweep
    eng.tick(_snap(bar=56), rig)          # the next block fires normally
    assert eng.active
    eng.tick(_snap(bar=56, pdl_fresh=False), rig)
    assert not eng.active


# --- what it writes --------------------------------------------------------------

def test_writes_the_verified_dotted_line_sweep_when_lit():
    rig = load_rig()
    clock = FakeClock()
    eng = LaserEngine(clock)
    c = eng.tick(_snap(bar=48), rig)
    values, touched = _laser_channels(c, rig)
    assert touched and eng.active
    assert values[0] == Laser.MANUAL_PATTERN_MODE       # CH1 manual
    assert values[1] == Laser.PATTERN_A1_DOTTED_LINE    # CH2 flattened line
    assert values[8] == Laser.SCALE_STATIC              # CH9 MUST stay 0
    assert values[10] == Laser.SCAN_DOTS                # CH11 dotted outline
    assert Laser.SWEEP_SPEED_MIN <= values[6] <= Laser.SWEEP_SPEED_MAX  # CH7 in the sweep band
    assert values[6] >= Laser.SWEEP_SPEED_MIN + round(LASER_SWEEP_BASE * 127) - 1  # never below the idle fan speed


def test_between_sweeps_the_pattern_is_primed_with_ch1_off():
    """Third live run: 0.24 s flashes from an all-zero universe showed the
    unit's default circle. Between sweeps the line is held with CH1 = 0."""
    rig = load_rig()
    clock = FakeClock()
    eng = LaserEngine(clock)
    eng.tick(_snap(bar=48), rig)                  # the block's sweep...
    clock.advance(LASER_SWEEP_BARS * BAR_S + 0.1)
    c = eng.tick(_snap(bar=50), rig)              # ...is over: mid-block, primed, not lit
    values, touched = _laser_channels(c, rig)
    assert touched and eng.primed and not eng.active
    assert values[0] == 0
    assert values[1] == Laser.PATTERN_A1_DOTTED_LINE
    assert values[10] == Laser.SCAN_DOTS
    assert values[11] == Laser.COLOR_RED


def test_writes_nothing_outside_the_gate():
    rig = load_rig()
    clock = FakeClock()
    eng = LaserEngine(clock)
    for bucket in ("break", "build", "drop", "outro"):
        c = eng.tick(_snap(bar=48, bucket=bucket), rig)
        _, touched = _laser_channels(c, rig)
        assert not touched and not eng.active and not eng.primed, bucket


def test_color_is_the_palette_entry_snapped_to_a_macro():
    assert laser_color_for_palette("blood_red") == Laser.COLOR_RED
    assert laser_color_for_palette("cold_steel") == Laser.COLOR_BLUE
    assert laser_color_for_palette("hot_magenta") == Laser.COLOR_PURPLE
    assert laser_color_for_palette("neutral_wash") == Laser.COLOR_WHITE
    assert laser_color_for_palette("something_new") == Laser.COLOR_WHITE
    rig = load_rig()
    clock = FakeClock()
    eng = LaserEngine(clock)
    c = eng.tick(_snap(bar=48, palette="cold_steel"), rig)
    values, _ = _laser_channels(c, rig)
    assert values[11] == Laser.COLOR_BLUE


# --- the wub envelope on CH7 ------------------------------------------------------

def _settle(eng, rig, clock, level, ticks=300, dt=0.02):
    for _ in range(ticks):
        eng.tick(_snap(bar=50, audio_band_low_abs=level), rig)
        clock.advance(dt)


def test_fan_idles_at_the_base_speed_on_a_steady_bassline():
    """First live run: with no base the fan crawled at CH7 ~136 -- Josh:
    'it should be more of like a fan.' It now idles mid-band."""
    clock = FakeClock()
    rig = load_rig()
    eng = LaserEngine(clock)
    _settle(eng, rig, clock, level=8.0)
    eng.tick(_snap(bar=50, audio_band_low_abs=8.0), rig)
    assert eng.wub <= 0.05
    assert abs(eng.sweep - LASER_SWEEP_BASE) < 0.05
    laser = rig.fixture("laser_l")
    probe = Contribution()
    laser.set_dotted_line_sweep(probe, color=eng.color, sweep_intensity=eng.sweep)
    assert abs(probe.values[laser.offset + 6] - (Laser.SWEEP_SPEED_MIN + LASER_SWEEP_BASE * 127)) <= 4


def test_a_wub_above_the_bassline_speeds_the_sweep_up_then_it_relaxes():
    clock = FakeClock()
    rig = load_rig()
    eng = LaserEngine(clock)
    _settle(eng, rig, clock, level=8.0)
    c = eng.tick(_snap(bar=50, audio_band_low_abs=24.0), rig)  # a wub: 3x the bassline
    values, _ = _laser_channels(c, rig)
    fast = eng.sweep
    assert fast > LASER_SWEEP_BASE + 0.3
    assert values[6] > Laser.SWEEP_SPEED_MIN + round(LASER_SWEEP_BASE * 127) + 30  # written even while primed
    clock.advance(0.15)
    eng.tick(_snap(bar=50, audio_band_low_abs=8.0), rig)
    assert eng.sweep < fast  # releasing back toward the idle speed


def test_a_smaller_wub_after_a_bigger_one_reads_proportionally():
    """Self-normalized: the biggest recent wub is full speed, a smaller one
    that follows it is a fraction of that, not a fixed-gain absolute."""
    clock = FakeClock()
    rig = load_rig()
    eng = LaserEngine(clock)
    _settle(eng, rig, clock, level=8.0)
    eng.tick(_snap(bar=50, audio_band_low_abs=40.0), rig)  # a big wub sets the peak
    big = eng.wub
    for _ in range(20):  # release, ~0.4 s
        clock.advance(0.02)
        eng.tick(_snap(bar=50, audio_band_low_abs=8.0), rig)
    eng.tick(_snap(bar=50, audio_band_low_abs=16.0), rig)  # a smaller wub
    assert 0.0 < eng.wub < big


def test_active_is_a_plain_python_bool_even_from_numpy_inputs():
    """The recorder lost 162 samples on the first live run to a numpy bool
    leaking out of the hit-intensity comparison."""
    import numpy as np
    rig = load_rig()
    clock = FakeClock()
    eng = LaserEngine(clock)
    eng.tick(_snap(bar=48, drop_hit_intensity=np.float64(0.97)), rig)
    assert type(eng.active) is bool and eng.active
    assert type(laser_wanted(_snap(drop_hit_intensity=np.float64(0.90)))) is bool
    eng2 = LaserEngine(FakeClock())
    eng2.tick(_snap(bar=48, drop_hit_intensity=np.float64(0.90)), rig)
    assert type(eng2.active) is bool and not eng2.active


# --- end to end through the real ShowEngine + finalize --------------------------------

def _show(snap: ShowSnapshot, testing: bool, after_sweep: bool = False):
    """One ShowEngine tick on `snap`; with after_sweep, first spend bar 48's
    sweep so `snap` lands between sweeps."""
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
    if after_sweep:
        state.publish(snap.replace(bar=48))
        eng.tick()
        clock.advance(LASER_SWEEP_BARS * BAR_S + 0.1)
        state.publish(snap)
    frame = eng.tick()
    off = rig.fixture("laser_l").offset
    return frame[off], frame[off + 1], laser


def test_end_to_end_the_laser_lights_on_a_peak_block_boundary_under_testing_mode():
    ch1, ch2, laser = _show(_snap(bar=48), testing=True)
    assert laser.active
    assert ch1 == Laser.MANUAL_PATTERN_MODE and ch2 == Laser.PATTERN_A1_DOTTED_LINE


def test_end_to_end_primed_keeps_ch1_off_but_the_pattern_channels_set():
    ch1, ch2, laser = _show(_snap(bar=50), testing=True, after_sweep=True)
    assert laser.primed and not laser.active
    assert ch1 == 0 and ch2 == Laser.PATTERN_A1_DOTTED_LINE


def test_end_to_end_the_geometry_gate_still_wins_without_testing_mode():
    """The layer says on, but a 0.9 m mount without --testing is forced off
    by Laser.apply_safety -- the bench override is the ONLY bypass."""
    ch1, ch2, laser = _show(_snap(bar=48), testing=False)
    assert laser.active
    assert ch1 == 0 and ch2 == 0


def test_end_to_end_a_drop_never_lights_the_laser_even_in_testing_mode():
    ch1, ch2, laser = _show(_snap(bar=48, bucket="drop"), testing=True)
    assert not laser.active and not laser.primed
    assert ch1 == 0 and ch2 == 0


def test_show_engine_without_a_laser_engine_keeps_the_gate_closed():
    rig = load_rig()
    for fx in rig.by_role("laser"):
        fx.safety_test_mode = True
    clock = FakeClock()
    state = ShowState()
    state.publish(_snap(bar=48))
    eng = ShowEngine(state, rig, DmxFrameBuffer(), [ReactiveLayerEngine(clock)],
                     ManualParams(laser_enable=True), clock, threading.Event())
    frame = eng.tick()
    assert frame[rig.fixture("laser_l").offset] == 0


def test_the_peak_escalation_itself_fires_when_its_block_is_unused():
    """Fourth live run: PEAK began one bar past a block boundary and the
    first sweep waited 8 bars. The gate opening now fires the block's
    sweep; the next boundary still gets its own; a blip re-entry does not."""
    rig = load_rig()
    clock = FakeClock()
    eng = LaserEngine(clock)
    seen = _run_bars(eng, rig, clock, first_bar=49, n_bars=8)  # enters at 49, boundary at 56
    lit_bars = sorted({bar for bar, _, on in seen if on})
    assert lit_bars == [49, 56]
    eng.tick(_snap(bar=56, bucket="drop"), rig)   # blip out...
    clock.advance(LASER_SWEEP_BARS * BAR_S + 0.1)
    eng.tick(_snap(bar=57, bucket="peak"), rig)   # ...and back, mid-block: no extra sweep
    assert not eng.active and eng.primed


# --- manual cue (2026-09-30: the operator's taste-tuned option) ------------------

def _cued_engine(clock, cue=True):
    manual = ManualParams(laser_enable=True, laser_cue=cue)
    return LaserEngine(clock, manual=manual), manual


def test_manual_cue_lights_the_dotted_line_outside_any_peak():
    """No PEAK, no drop, an ordinary BREAK: the held cue alone shows the line."""
    rig = load_rig()
    clock = FakeClock()
    eng, _ = _cued_engine(clock)
    c = eng.tick(_snap(bucket="break", drop_hit_intensity=0.0, drop_start_bar=None, bar=3), rig)
    values, touched = _laser_channels(c, rig)
    assert touched and eng.active and eng.source == "manual" and not eng.primed
    assert values[0] == Laser.MANUAL_PATTERN_MODE
    assert values[1] == Laser.PATTERN_A1_DOTTED_LINE
    assert values[8] == Laser.SCALE_STATIC
    assert values[10] == Laser.SCAN_DOTS
    assert Laser.SWEEP_SPEED_MIN <= values[6] <= Laser.SWEEP_SPEED_MAX  # never the unverified static half


def test_manual_cue_is_off_without_the_manual_params_or_with_the_flag_down():
    rig = load_rig()
    clock = FakeClock()
    eng, manual = _cued_engine(clock, cue=False)
    c = eng.tick(_snap(bucket="break", drop_hit_intensity=0.0, bar=3), rig)
    _, touched = _laser_channels(c, rig)
    assert not touched and not eng.active and eng.source == "" and not eng.manual_cued
    manual.laser_cue = True
    eng.tick(_snap(bucket="break", drop_hit_intensity=0.0, bar=3), rig)
    assert eng.active and eng.manual_cued
    assert not LaserEngine(clock).manual_cued


def test_manual_cue_sweep_is_stationary_on_steady_mids_and_speeds_up_on_a_stab():
    """Speed follows the mids + highs envelope: steady content reads as the
    floor (CH7 128, the slowest confirmed sweep), a stab pushes it up and it
    relaxes again. The low band is ignored on this path."""
    from livereact.engines.laser import MANUAL_SWEEP_FLOOR
    rig = load_rig()
    clock = FakeClock()
    eng, _ = _cued_engine(clock)
    quiet = dict(bucket="break", drop_hit_intensity=0.0, bar=3,
                 audio_band_low_abs=5.0, audio_band_mid_abs=2.0, audio_band_high_abs=1.0)
    for _ in range(300):  # settle the baseline (6 s, like _settle) well past the 1 s warm-up
        eng.tick(_snap(**quiet), rig)
        clock.advance(0.02)
    assert eng.sweep <= MANUAL_SWEEP_FLOOR + 0.05
    steady_ch7 = eng._stab.level
    for _ in range(3):   # a stab in the mids + highs
        eng.tick(_snap(**dict(quiet, audio_band_mid_abs=8.0, audio_band_high_abs=4.0)), rig)
        clock.advance(1 / 60)
    stab_sweep = eng.sweep
    assert stab_sweep > steady_ch7 + 0.3
    c = eng.tick(_snap(**dict(quiet, audio_band_mid_abs=8.0, audio_band_high_abs=4.0)), rig)
    values, _ = _laser_channels(c, rig)
    assert values[6] > Laser.SWEEP_SPEED_MIN + 0.3 * 127
    for _ in range(60):  # ...and it relaxes
        eng.tick(_snap(**quiet), rig)
        clock.advance(1 / 60)
    assert eng.sweep < stab_sweep - 0.3
    # a kick on its own (low band) does nothing to the manual sweep
    before = eng.sweep
    for _ in range(3):
        eng.tick(_snap(**dict(quiet, audio_band_low_abs=30.0)), rig)
        clock.advance(1 / 60)
    assert abs(eng.sweep - before) < 0.05


def test_manual_cue_dies_with_the_audio_but_survives_pdl_loss():
    """LASER-12 on the manual path: no real audio means off at once; the cue
    has no beat grid to lock to, so PDL alone is not required."""
    rig = load_rig()
    clock = FakeClock()
    eng, _ = _cued_engine(clock)
    eng.tick(_snap(bucket="break", drop_hit_intensity=0.0, bar=3, pdl_fresh=False), rig)
    assert eng.active and eng.source == "manual"
    c = eng.tick(_snap(bucket="break", drop_hit_intensity=0.0, bar=3, audio_fresh=False), rig)
    _, touched = _laser_channels(c, rig)
    assert not touched and not eng.active and eng.source == ""
    assert eng.manual_cued  # the cue is still held; it lights again when audio returns


def test_releasing_the_cue_returns_to_the_auto_path_with_its_block_state_intact():
    rig = load_rig()
    clock = FakeClock()
    eng, manual = _cued_engine(clock)
    eng.tick(_snap(bar=48), rig)                      # PEAK block boundary, but the cue owns it
    assert eng.source == "manual"
    manual.laser_cue = False
    eng.tick(_snap(bar=48), rig)                      # auto path: this block still gets its sweep
    assert eng.active and eng.source == "auto"
    clock.advance(LASER_SWEEP_BARS * BAR_S + 0.1)
    eng.tick(_snap(bar=50), rig)
    assert eng.primed and not eng.active and eng.source == ""


def test_end_to_end_the_manual_cue_lights_when_armed_and_stays_dark_when_not():
    """The cue is musical; arming (and the geometry check / --testing) stays
    the safety decision in finalize."""
    for armed, expect_lit in ((True, True), (False, False)):
        rig = load_rig()
        for fx in rig.by_role("laser"):
            fx.mount_height_m = 0.9
            fx.safety_test_mode = True
        clock = FakeClock()
        state = ShowState()
        state.publish(_snap(bucket="break", drop_hit_intensity=0.0, drop_start_bar=None, bar=3))
        manual = ManualParams(laser_enable=armed, laser_cue=True)
        laser = LaserEngine(clock, manual=manual)
        eng = ShowEngine(state, rig, DmxFrameBuffer(), [ReactiveLayerEngine(clock, manual=manual), laser],
                         manual, clock, threading.Event(), laser_engine=laser)
        frame = eng.tick()
        off = rig.fixture("laser_l").offset
        assert laser.active and laser.source == "manual"
        assert (frame[off] == Laser.MANUAL_PATTERN_MODE) is expect_lit
        if expect_lit:
            assert frame[off + 1] == Laser.PATTERN_A1_DOTTED_LINE
