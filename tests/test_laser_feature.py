"""Tests for engines/laser_feature.py -- the FEATURE laser profile (2026-10-01,
Josh's bar residency: two lasers as the main light). Driven with a FakeClock
on a self-contained two-laser rig (left @1, right @13, both at the bar's
9 ft mount with its declared 2.7 m safe plane, wash bar @69)."""

from __future__ import annotations

import threading

import pytest

from livereact.clock import FakeClock
from livereact.core.frame_buffer import DmxFrameBuffer
from livereact.core.rise import RISE_FULL, RISE_ON
from livereact.core.show_engine import ShowEngine
from livereact.core.show_state import ShowSnapshot, ShowState
from livereact.engines.laser_feature import (
    CALM_COLOR_BARS,
    CALM_CYCLE,
    FAN_BASE,
    FAN_MIN_HIT,
    GROOVE_BASE,
    MOOD_CALM,
    MOOD_FAN,
    MOOD_GROOVE,
    MOOD_OFF,
    MOOD_TENSION,
    TENSION_ARMED_FLOOR,
    TENSION_MAX,
    LaserFeatureEngine,
    laser_color_name,
    laser_mood,
    tension_sweep,
)
from livereact.engines.laser import laser_color_for_palette
from livereact.fixtures.profiles import Laser
from livereact.fixtures.rig import _rig_from_dict
from livereact.merge.merge import ManualParams

BEAT_S = 60.0 / 128.0
BAR_S = 4 * BEAT_S


def _rig():
    return _rig_from_dict({
        "name": "bar-test", "laser_profile": "feature",
        "slots": [
            {"slot_id": "laser_l", "fixture_type": "shehds_3w_laser", "dmx_address": 1,
             "role": "laser", "side": "left"},
            {"slot_id": "laser_r", "fixture_type": "shehds_3w_laser", "dmx_address": 13,
             "role": "laser", "side": "right"},
            {"slot_id": "bar", "fixture_type": "ok103_wash_bar", "dmx_address": 69,
             "role": "wash", "side": "left"},
        ],
    })


def _snap(**kw) -> ShowSnapshot:
    base = dict(bpm=128.0, audio_fresh=True, pdl_fresh=True, bucket="break",
                drop_hit_intensity=0.85, energy=0.3, energy_norm=0.3, palette="deep_blue",
                audio_band_low_abs=5.0, bar=40, beat_in_bar=1)
    base.update(kw)
    return ShowSnapshot(**base)


def _channels(c, rig, slot):
    fx = rig.fixture(slot)
    return [c.values[fx.offset + i] for i in range(12)], any(c.touched[fx.offset + i] for i in range(12))


def _engine(ease_s=0.0, manual=None):
    clock = FakeClock(1000.0)
    return LaserFeatureEngine(clock, manual=manual, ease_s=ease_s), clock


def _settle(eng, rig, clock, snap, ticks=60, dt=0.02):
    for _ in range(ticks):
        eng.tick(snap, rig)
        clock.advance(dt)


# --- the mood table ---------------------------------------------------------------

@pytest.mark.parametrize("bucket,hit,rising,armed,expected", [
    ("break", 1.0, False, False, MOOD_CALM),
    ("outro", 1.0, False, False, MOOD_CALM),
    ("build", 1.0, False, False, MOOD_CALM),       # an unarmed, flat build is still calm
    ("build", 1.0, True, False, MOOD_TENSION),
    ("build", 1.0, False, True, MOOD_TENSION),
    ("drop", 1.0, False, False, MOOD_FAN),
    ("peak", 0.97, False, False, MOOD_FAN),
    ("drop", FAN_MIN_HIT, False, False, MOOD_FAN),
    ("drop", 0.90, False, False, MOOD_GROOVE),     # a softer drop grooves, never fans
    ("peak", 0.88, False, False, MOOD_GROOVE),
])
def test_mood_follows_the_bucket_and_the_hit(bucket, hit, rising, armed, expected):
    snap = _snap(bucket=bucket, drop_hit_intensity=hit, rising=rising, drop_armed=armed, rise_index=2.0)
    assert laser_mood(snap) == expected


def test_audio_loss_is_off_whatever_else_is_true():
    for bucket in ("break", "build", "drop", "peak"):
        assert laser_mood(_snap(bucket=bucket, audio_fresh=False, drop_hit_intensity=1.0)) == MOOD_OFF
    assert laser_mood(_snap(audio_fresh=False), cued=True) == MOOD_OFF  # even the K cue can't light dead audio


def test_pdl_loss_does_not_change_the_mood():
    """The manual-cue precedent (LASER-14): the look is audio-driven, so a
    Pro DJ Link hiccup must not blink the main light out."""
    assert laser_mood(_snap(pdl_fresh=False)) == MOOD_CALM
    assert laser_mood(_snap(pdl_fresh=False, bucket="drop", drop_hit_intensity=1.0)) == MOOD_FAN


def test_the_k_cue_forces_the_fan_in_any_bucket():
    for bucket in ("break", "build", "outro"):
        assert laser_mood(_snap(bucket=bucket), cued=True) == MOOD_FAN


def test_in_transition_is_not_a_mood_input():
    assert laser_mood(_snap(bucket="drop", drop_hit_intensity=1.0, in_transition=True)) == MOOD_FAN
    assert laser_mood(_snap(bucket="break", in_transition=True)) == MOOD_CALM


# --- tension ------------------------------------------------------------------------

def test_tension_sweep_maps_the_rise_index_onto_the_tension_range():
    assert tension_sweep(_snap(rising=True, rise_index=RISE_ON)) == pytest.approx(0.0)
    assert tension_sweep(_snap(rising=True, rise_index=RISE_FULL)) == pytest.approx(TENSION_MAX)
    mid = (RISE_ON + RISE_FULL) / 2
    assert tension_sweep(_snap(rising=True, rise_index=mid)) == pytest.approx(TENSION_MAX / 2)
    assert tension_sweep(_snap(rising=True, rise_index=RISE_FULL * 2)) == pytest.approx(TENSION_MAX)  # clamped


def test_an_armed_drop_that_is_not_rising_holds_the_armed_floor():
    assert tension_sweep(_snap(rising=False, drop_armed=True, rise_index=1.0)) == pytest.approx(TENSION_ARMED_FLOOR)
    # rising AND armed: the bigger of the two
    assert tension_sweep(_snap(rising=True, drop_armed=True, rise_index=RISE_FULL)) == pytest.approx(TENSION_MAX)
    assert tension_sweep(_snap(rising=True, drop_armed=True, rise_index=RISE_ON)) == pytest.approx(TENSION_ARMED_FLOOR)


# --- what is written ---------------------------------------------------------------

def test_calm_writes_the_verified_dotted_line_on_both_lasers_at_the_slowest_sweep():
    rig = _rig()
    eng, clock = _engine()
    c = eng.tick(_snap(), rig)
    assert eng.mood == MOOD_CALM and eng.active and not eng.primed and eng.source == "feature"
    for slot in ("laser_l", "laser_r"):
        ch, touched = _channels(c, rig, slot)
        assert touched
        assert ch[0] == Laser.MANUAL_PATTERN_MODE          # CH1 lit (not primed)
        assert ch[1] == Laser.PATTERN_A1_DOTTED_LINE       # CH2
        assert ch[2] == Laser.PATTERN_A2_DEFAULT           # CH3
        assert ch[6] == Laser.SWEEP_SPEED_MIN              # CH7 128: the slowest confirmed sweep
        assert ch[8] == Laser.SCALE_STATIC                 # CH9 must stay 0
        assert ch[10] == Laser.SCAN_DOTS                   # CH11
    # the wash bar is nobody's business here
    bar = rig.fixture("bar")
    assert not any(c.touched[bar.offset + i] for i in range(bar.channel_count))


def test_only_verified_bytes_are_ever_written():
    """Every mood, every laser: CH1/2/3/9/11 are the 2026-09-06 combo, CH7
    stays in the confirmed 128-255 speed half, CH12 is a COLOR_* macro."""
    rig = _rig()
    eng, clock = _engine(ease_s=0.0)
    macros = set(Laser.COLOR_WHITE + 8 * i for i in range(7))
    snaps = [
        _snap(),
        _snap(bucket="build", rising=True, rise_index=RISE_FULL),
        _snap(bucket="build", drop_armed=True),
        _snap(bucket="drop", drop_hit_intensity=0.9, palette="blood_red"),
        _snap(bucket="peak", drop_hit_intensity=1.0, palette="cold_steel", audio_band_low_abs=40.0),
    ]
    for snap in snaps:
        _settle(eng, rig, clock, snap, ticks=30)
        c = eng.tick(snap, rig)
        for slot in ("laser_l", "laser_r"):
            ch, _ = _channels(c, rig, slot)
            assert (ch[0], ch[1], ch[2], ch[8], ch[10]) == (
                Laser.MANUAL_PATTERN_MODE, Laser.PATTERN_A1_DOTTED_LINE, Laser.PATTERN_A2_DEFAULT,
                Laser.SCALE_STATIC, Laser.SCAN_DOTS)
            assert Laser.SWEEP_SPEED_MIN <= ch[6] <= Laser.SWEEP_SPEED_MAX
            assert ch[11] in macros


def test_audio_loss_writes_nothing_and_closes_the_gate_even_mid_fan():
    rig = _rig()
    eng, clock = _engine()
    eng.tick(_snap(bucket="peak", drop_hit_intensity=1.0), rig)
    assert eng.mood == MOOD_FAN and eng.active
    c = eng.tick(_snap(bucket="peak", drop_hit_intensity=1.0, audio_fresh=False), rig)
    assert eng.mood == MOOD_OFF and not eng.active and eng.source == ""
    assert eng.sweep == 0.0
    for slot in ("laser_l", "laser_r"):
        _, touched = _channels(c, rig, slot)
        assert not touched


def test_pdl_loss_keeps_the_line_lit():
    rig = _rig()
    eng, clock = _engine()
    c = eng.tick(_snap(pdl_fresh=False), rig)
    assert eng.active and eng.mood == MOOD_CALM
    ch, touched = _channels(c, rig, "laser_l")
    assert touched and ch[0] == Laser.MANUAL_PATTERN_MODE


# --- the sweep ---------------------------------------------------------------------

def test_fan_idles_at_the_fan_base_and_the_wub_adds_on_top():
    rig = _rig()
    eng, clock = _engine(ease_s=0.0)
    steady = _snap(bucket="peak", drop_hit_intensity=1.0, audio_band_low_abs=8.0)
    _settle(eng, rig, clock, steady, ticks=300)
    assert eng.mood == MOOD_FAN
    assert eng.sweep == pytest.approx(FAN_BASE, abs=0.05)
    c = eng.tick(_snap(bucket="peak", drop_hit_intensity=1.0, audio_band_low_abs=24.0), rig)  # a wub
    assert eng.sweep > FAN_BASE + 0.2
    ch, _ = _channels(c, rig, "laser_r")
    assert ch[6] > Laser.SWEEP_SPEED_MIN + 0.6 * (Laser.SWEEP_SPEED_MAX - Laser.SWEEP_SPEED_MIN)


def test_groove_is_a_medium_sweep_between_calm_and_the_fan():
    rig = _rig()
    eng, clock = _engine(ease_s=0.0)
    _settle(eng, rig, clock, _snap(bucket="drop", drop_hit_intensity=0.9, audio_band_low_abs=8.0), ticks=300)
    assert eng.mood == MOOD_GROOVE
    assert 0.0 < eng.sweep < FAN_BASE
    assert eng.sweep == pytest.approx(GROOVE_BASE, abs=0.05)


def test_tension_ramps_the_sweep_with_the_rise_and_the_fan_is_still_a_step_up():
    rig = _rig()
    eng, clock = _engine(ease_s=0.0)
    eng.tick(_snap(bucket="build", rising=True, rise_index=RISE_FULL), rig)
    assert eng.mood == MOOD_TENSION
    assert eng.sweep == pytest.approx(TENSION_MAX)
    assert TENSION_MAX < FAN_BASE


def test_the_sweep_eases_toward_its_target_so_a_blip_never_snaps_the_fan():
    rig = _rig()
    eng, clock = _engine(ease_s=0.5)
    _settle(eng, rig, clock, _snap(), ticks=60)          # calm, sweep ~0
    assert eng.sweep == pytest.approx(0.0, abs=0.01)
    eng.tick(_snap(bucket="peak", drop_hit_intensity=1.0), rig)
    assert eng.mood == MOOD_FAN                           # the mood flips at once...
    assert eng.sweep < 0.1                                # ...the speed does not
    _settle(eng, rig, clock, _snap(bucket="peak", drop_hit_intensity=1.0), ticks=100, dt=0.02)  # 2 s
    assert eng.sweep == pytest.approx(eng.target, abs=0.03)
    # one calm tick in the middle of the fan (a bucket blip) barely dents it
    clock.advance(0.02)
    eng.tick(_snap(), rig)
    assert eng.sweep > 0.9 * FAN_BASE


# --- colors -------------------------------------------------------------------------

def test_calm_colors_walk_the_cycle_every_8_bars_with_the_right_laser_a_step_ahead():
    rig = _rig()
    eng, clock = _engine()
    n = len(CALM_CYCLE)
    for step in range(n + 1):
        bar = 40 + step * CALM_COLOR_BARS
        c = eng.tick(_snap(bar=bar), rig)
        assert eng.color_l == CALM_CYCLE[step % n]
        assert eng.color_r == CALM_CYCLE[(step + 1) % n]
        assert eng.color == eng.color_l
        chl, _ = _channels(c, rig, "laser_l")
        chr_, _ = _channels(c, rig, "laser_r")
        assert chl[11] == eng.color_l and chr_[11] == eng.color_r
    # inside a step the color holds
    eng.tick(_snap(bar=40 + CALM_COLOR_BARS * (n + 1) + 3), rig)
    assert eng.color_l == CALM_CYCLE[(n + 1) % n]


def test_tension_holds_the_color_calm_reached_and_calm_resumes_the_walk():
    rig = _rig()
    eng, clock = _engine()
    eng.tick(_snap(bar=40), rig)
    eng.tick(_snap(bar=40 + CALM_COLOR_BARS), rig)       # one step in
    held = eng.color_l
    assert held == CALM_CYCLE[1]
    eng.tick(_snap(bar=40 + 2 * CALM_COLOR_BARS, bucket="build", rising=True, rise_index=2.0), rig)
    assert eng.mood == MOOD_TENSION and eng.color_l == held   # no step mid-build
    eng.tick(_snap(bar=40 + 2 * CALM_COLOR_BARS, bucket="build"), rig)  # the build fizzles
    assert eng.mood == MOOD_CALM and eng.color_l == CALM_CYCLE[2]      # the walk continues from the same origin


def test_a_new_calm_stretch_after_a_drop_restarts_the_walk():
    rig = _rig()
    eng, clock = _engine()
    eng.tick(_snap(bar=40), rig)
    eng.tick(_snap(bar=40 + 3 * CALM_COLOR_BARS), rig)
    assert eng.color_l == CALM_CYCLE[3]
    eng.tick(_snap(bar=70, bucket="peak", drop_hit_intensity=1.0), rig)
    eng.tick(_snap(bar=100), rig)                         # the breakdown after the drop
    assert eng.mood == MOOD_CALM and eng.color_l == CALM_CYCLE[0] and eng.color_r == CALM_CYCLE[1]


def test_fan_and_groove_use_the_drop_palette_on_both_lasers():
    rig = _rig()
    eng, clock = _engine()
    for hit in (1.0, 0.9):
        c = eng.tick(_snap(bucket="drop", drop_hit_intensity=hit, palette="blood_red"), rig)
        want = laser_color_for_palette("blood_red")
        assert want == Laser.COLOR_RED
        assert eng.color_l == eng.color_r == want
        for slot in ("laser_l", "laser_r"):
            ch, _ = _channels(c, rig, slot)
            assert ch[11] == want


def test_color_names_cover_every_macro():
    for macro in CALM_CYCLE:
        assert laser_color_name(macro) in ("blue", "cyan", "purple", "green")
    assert laser_color_name(Laser.COLOR_RED) == "red"
    assert laser_color_name(999) == "999"


# --- the K cue ----------------------------------------------------------------------

def test_the_k_cue_forces_the_fan_and_releasing_it_returns_to_the_bucket():
    rig = _rig()
    manual = ManualParams(laser_cue=True)
    eng, clock = _engine(ease_s=0.0, manual=manual)
    _settle(eng, rig, clock, _snap(audio_band_low_abs=8.0), ticks=300)  # let the wub envelope settle
    assert eng.mood == MOOD_FAN and eng.source == "manual"
    assert eng.sweep == pytest.approx(FAN_BASE, abs=0.05)
    manual.laser_cue = False
    eng.tick(_snap(), rig)
    assert eng.mood == MOOD_CALM and eng.source == "feature"


# --- end to end ---------------------------------------------------------------------

def _show(snap: ShowSnapshot, rig, manual: ManualParams, ticks: int = 3):
    clock = FakeClock(1000.0)
    state = ShowState(snap)
    eng = LaserFeatureEngine(clock, manual=manual, ease_s=0.0)
    show = ShowEngine(state, rig, DmxFrameBuffer(), [eng], manual, clock, threading.Event(),
                      laser_engine=eng)
    frame = b""
    for _ in range(ticks):
        frame = show.tick()
        clock.advance(0.02)
    return frame, eng


def _ch1(frame, rig, slot):
    fx = rig.fixture(slot)
    return frame[fx.offset]


def test_end_to_end_both_lasers_light_in_calm_when_armed():
    rig = _rig()
    frame, eng = _show(_snap(), rig, ManualParams(laser_enable=True))
    assert eng.mood == MOOD_CALM
    assert _ch1(frame, rig, "laser_l") == Laser.MANUAL_PATTERN_MODE
    assert _ch1(frame, rig, "laser_r") == Laser.MANUAL_PATTERN_MODE


def test_end_to_end_the_arm_switch_still_rules():
    rig = _rig()
    frame, eng = _show(_snap(bucket="peak", drop_hit_intensity=1.0), rig, ManualParams(laser_enable=False))
    assert eng.mood == MOOD_FAN            # the engine wants it...
    for slot in ("laser_l", "laser_r"):    # ...finalize says no, all 12 channels
        fx = rig.fixture(slot)
        assert frame[fx.offset:fx.offset + 12] == bytes(12)


def test_end_to_end_audio_loss_closes_the_gate():
    rig = _rig()
    frame, eng = _show(_snap(audio_fresh=False), rig, ManualParams(laser_enable=True))
    assert not eng.active
    assert _ch1(frame, rig, "laser_l") == 0 and _ch1(frame, rig, "laser_r") == 0
