"""Tests for engines/envelope.py's BandEnvelope (the shared baseline-excess
follower behind the laser sweep and Synth Sync)."""

from __future__ import annotations

from livereact.clock import FakeClock
from livereact.engines.envelope import BandEnvelope


def _settle(env: BandEnvelope, clock: FakeClock, level: float, ticks: int = 300, dt: float = 0.02) -> None:
    for _ in range(ticks):
        env.update(level)
        clock.advance(dt)


def test_a_steady_signal_settles_to_nothing():
    clock = FakeClock()
    env = BandEnvelope(clock)
    _settle(env, clock, 8.0)
    assert env.update(8.0) <= 0.01


def test_a_transient_above_the_baseline_rises_fast_then_releases():
    clock = FakeClock()
    env = BandEnvelope(clock)
    _settle(env, clock, 8.0)
    peak = env.update(24.0)  # 3x the baseline
    assert peak > 0.3
    clock.advance(0.15)
    assert env.update(8.0) < peak


def test_bigger_transients_read_bigger():
    a, b = FakeClock(), FakeClock()
    small, big = BandEnvelope(a), BandEnvelope(b)
    _settle(small, a, 8.0)
    _settle(big, b, 8.0)
    assert big.update(30.0) > small.update(14.0)


def test_stale_audio_resets_the_state():
    clock = FakeClock()
    env = BandEnvelope(clock)
    _settle(env, clock, 8.0)
    env.update(24.0)
    assert env.update(24.0, fresh=False) == 0.0
    assert env.level == 0.0


def test_gain_scales_the_output():
    a, b = FakeClock(), FakeClock()
    lo, hi = BandEnvelope(a, gain=0.1), BandEnvelope(b, gain=0.5)
    _settle(lo, a, 8.0)
    _settle(hi, b, 8.0)
    assert hi.update(16.0) > lo.update(16.0)


def test_normalized_mode_reads_the_loudest_recent_transient_as_full():
    """2026-09-15 night: a fixed gain left a sustained-bass song's wubs at
    ~0.06. Normalized, the biggest recent excess is 1.0 whatever its size."""
    clock = FakeClock()
    env = BandEnvelope(clock, normalize_tau_s=4.0)
    _settle(env, clock, 8.0)
    assert env.update(12.0) > 0.9   # a modest (50%) wub reads full when it's the biggest around
    clock.advance(0.02)
    env.update(8.0)
    clock.advance(0.02)
    assert env.update(9.0) < 0.9    # a smaller one right after reads as a fraction


def test_cold_start_spike_does_not_poison_the_peak_tracker():
    """The baseline starts at 0, so the first ticks of any signal look like a
    huge transient. That must neither show (WARMUP_S) nor set the peak."""
    clock = FakeClock()
    env = BandEnvelope(clock, normalize_tau_s=4.0)
    assert env.update(8.0) == 0.0  # first tick: warming up, nothing reported
    _settle(env, clock, 8.0)
    assert env.update(16.0) > 0.9  # a real 2x wub after settling reads full, not a fraction of the spike


def test_normalized_output_is_a_python_float():
    clock = FakeClock()
    env = BandEnvelope(clock, normalize_tau_s=4.0)
    assert type(env.update(1.0)) is float
