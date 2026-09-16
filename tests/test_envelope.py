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
