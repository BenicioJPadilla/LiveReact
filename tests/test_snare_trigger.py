"""Tests for SnareOnsetDetector (build_snare_accent Step 1) and
SnareRollDetector (Step 2) — driven deterministically with a FakeClock,
same pattern as LaserOnsetDetector's own tests."""

from __future__ import annotations

from livereact.clock import FakeClock
from livereact.core.show_state import ShowSnapshot
from livereact.core.snare_trigger import SnareOnsetDetector, SnareRollDetector

BPM = 128.0
BEAT = 60.0 / BPM

WARMUP_TICKS = 60  # 60 * 0.02s = 1.2s, safely past the detector's 1.0s warmup gate


def _snap(**kw) -> ShowSnapshot:
    base = dict(audio_fresh=True, audio_band_mid_abs=0.0, audio_band_high_abs=0.0)
    base.update(kw)
    return ShowSnapshot(**base)


def _warm_up(d: SnareOnsetDetector, clock: FakeClock, **snap_kw) -> None:
    """Run the detector past its warmup gate on a steady, non-spiking signal."""
    for _ in range(WARMUP_TICKS):
        d.update(_snap(**snap_kw))
        clock.advance(0.02)


def test_fails_closed_when_audio_is_not_connected():
    clock = FakeClock()
    d = SnareOnsetDetector(clock)
    assert d.update(_snap(audio_fresh=False, audio_band_mid_abs=100.0, audio_band_high_abs=100.0)) is False


def test_warmup_gate_suppresses_false_triggers_on_a_steady_signal_at_startup():
    """Same shape as LaserOnsetDetector's own warmup bug (docs/14, 2026-09-01,
    found by testing): the rolling average starts at 0.0, so without a
    warmup guard, any steady non-spiking signal looks like a huge spike for
    the first several ticks after startup."""
    clock = FakeClock()
    d = SnareOnsetDetector(clock)
    fired_during_warmup = False
    for _ in range(WARMUP_TICKS):
        if d.update(_snap(audio_band_mid_abs=5.0, audio_band_high_abs=5.0)):
            fired_during_warmup = True
        clock.advance(0.02)
    assert not fired_during_warmup


def test_fires_on_a_real_spike_after_warmup():
    clock = FakeClock()
    d = SnareOnsetDetector(clock)
    _warm_up(d, clock, audio_band_mid_abs=1.0, audio_band_high_abs=1.0)
    assert d.update(_snap(audio_band_mid_abs=20.0, audio_band_high_abs=20.0)) is True


def test_does_not_fire_on_a_steady_signal_once_warmed_up():
    clock = FakeClock()
    d = SnareOnsetDetector(clock)
    _warm_up(d, clock, audio_band_mid_abs=3.0, audio_band_high_abs=3.0)
    # one more tick at the SAME steady level -- the rolling average has
    # already converged to it, so this must not read as a spike.
    assert d.update(_snap(audio_band_mid_abs=3.0, audio_band_high_abs=3.0)) is False


def test_refractory_period_blocks_an_immediate_re_fire():
    clock = FakeClock()
    d = SnareOnsetDetector(clock)
    _warm_up(d, clock, audio_band_mid_abs=1.0, audio_band_high_abs=1.0)
    assert d.update(_snap(audio_band_mid_abs=20.0, audio_band_high_abs=20.0)) is True
    clock.advance(0.05)  # well under REFRACTORY_S=0.15
    assert d.update(_snap(audio_band_mid_abs=20.0, audio_band_high_abs=20.0)) is False
    clock.advance(0.20)  # now past it
    assert d.update(_snap(audio_band_mid_abs=20.0, audio_band_high_abs=20.0)) is True


def test_reconnecting_after_stale_audio_resets_the_rolling_average():
    """Same rationale as LaserOnsetDetector: don't let a stale reading (or
    the state built up before a dropout) pollute detection on reconnect --
    the rolling average and warmup both restart clean."""
    clock = FakeClock()
    d = SnareOnsetDetector(clock)
    _warm_up(d, clock, audio_band_mid_abs=1.0, audio_band_high_abs=1.0)
    d.update(_snap(audio_fresh=False))
    # immediately "reconnecting" must not fire just because the rolling
    # average was reset to 0 and this reads as a huge relative spike --
    # the warmup gate must re-engage too.
    assert d.update(_snap(audio_band_mid_abs=5.0, audio_band_high_abs=5.0)) is False


def test_hihat_level_energy_does_not_fire_but_snare_level_energy_does():
    """The actual thing verified by simulation (tools/simulations/
    snare_onset_sim.py): a real snare hit and a routine hi-hat share the
    same high band, so the detector must have a real, measured margin
    between "background hi-hat activity" and "an actual snare hit," not
    just "any high-frequency content at all." Levels below are illustrative
    of that ratio, not a literal recording."""
    clock = FakeClock()
    d = SnareOnsetDetector(clock)
    _warm_up(d, clock, audio_band_mid_abs=1.0, audio_band_high_abs=1.0)
    # a hi-hat: a real but modest bump, well under TRIGGER_RATIO=2.6 relative to baseline
    assert d.update(_snap(audio_band_mid_abs=1.2, audio_band_high_abs=1.5)) is False
    clock.advance(0.2)
    # a snare: body tone (mid) + broadband hiss (high), a much bigger jump
    assert d.update(_snap(audio_band_mid_abs=6.0, audio_band_high_abs=8.0)) is True


# --- SnareRollDetector (Step 2) -----------------------------------------

def test_steady_backbeat_never_reads_as_a_roll():
    """The actual adversary for this detector: a real, ordinary house/
    techno backbeat (constant 2-beat spacing) is multiple onsets in a row,
    same as a roll superficially looks -- must never be flagged."""
    clock = FakeClock()
    d = SnareRollDetector(clock)
    active_at_any_point = False
    for _ in range(10):  # 10 backbeat hits, constant 2*BEAT apart
        if d.update(True, "build"):
            active_at_any_point = True
        clock.advance(2 * BEAT)
    assert not active_at_any_point


def test_a_real_accelerating_roll_is_detected_and_expires():
    """The real shape a roll takes: quarter -> eighth -> sixteenth notes,
    tightening into a drop. FOUND BY SIMULATION (tools/simulations/
    snare_roll_sim.py, 2026-09-14): requiring EVERY consecutive interval to
    individually tighten rejected this exact, textbook pattern outright,
    since a real roll plateaus at each subdivision for a couple of hits
    before dropping to the next -- fixed to compare the window's overall
    first-vs-last interval instead."""
    clock = FakeClock()
    d = SnareRollDetector(clock)
    intervals = [BEAT, BEAT, BEAT / 2, BEAT / 2, BEAT / 4, BEAT / 4, BEAT / 4, BEAT / 4]
    fired_at_any_point = False
    for interval in intervals:
        clock.advance(interval)
        if d.update(True, "build"):
            fired_at_any_point = True
    assert fired_at_any_point  # correctly caught partway through, not never

    # and it correctly expires once the hits stop (ROLL_MAX_AGE_S=0.5s)
    clock.advance(1.0)
    assert d.update(False, "build") is False


def test_roll_detection_is_gated_to_build_bucket_only():
    """LIGHTING_BIBLE.md's own [BUILD] tag for build_snare_accent, enforced
    at this layer (not the onset detector, which stays bucket-agnostic).
    The exact same accelerating pattern must never read as a roll in any
    other bucket."""
    clock = FakeClock()
    d = SnareRollDetector(clock)
    intervals = [BEAT, BEAT, BEAT / 2, BEAT / 2, BEAT / 4, BEAT / 4, BEAT / 4, BEAT / 4]
    fired_at_any_point = False
    for interval in intervals:
        clock.advance(interval)
        if d.update(True, "drop"):  # NOT build
            fired_at_any_point = True
    assert not fired_at_any_point
