"""Tests for LaserOnsetDetector (docs/14 §3) — driven deterministically with a
FakeClock, same pattern as the Metronome/SilenceDetector tests."""

from __future__ import annotations

from livereact.clock import FakeClock
from livereact.core.laser_trigger import LaserOnsetDetector
from livereact.core.show_state import ShowSnapshot

WARMUP_TICKS = 60  # 60 * 0.02s = 1.2s, safely past the detector's 1.0s warmup gate


def _snap(**kw) -> ShowSnapshot:
    # energy defaults high (intense) so the existing spike-detection tests
    # below aren't also implicitly testing the intensity gate; the intensity
    # gate gets its own dedicated tests further down.
    base = dict(bpm=120.0, audio_fresh=True, audio_band_low_abs=0.0, energy=1.0)
    base.update(kw)
    return ShowSnapshot(**base)


def _warm_up(d: LaserOnsetDetector, clock: FakeClock, **snap_kw) -> None:
    """Run the detector past its warmup gate on a steady, non-spiking signal."""
    for _ in range(WARMUP_TICKS):
        d.update(_snap(**snap_kw))
        clock.advance(0.02)


def test_fails_closed_when_audio_is_not_connected():
    """docs/14 §3: no confirmed real audio = never flash, even with a huge
    reading — a stale/fabricated value must not fire the gate."""
    clock = FakeClock()
    d = LaserOnsetDetector(clock)
    assert d.update(_snap(audio_fresh=False, audio_band_low_abs=100.0)) is False


def test_warmup_gate_suppresses_false_triggers_on_a_steady_signal_at_startup():
    """FOUND BY TESTING (docs/14, 2026-09-01): the rolling average starts at
    0.0, so without a warmup guard, any steady non-spiking signal looks like
    a huge spike for the first several ticks after startup — a dedicated
    test aimed at something else caught this by accident. This test pins the
    fix down directly: a perfectly constant signal must never trigger, even
    right at t=0."""
    clock = FakeClock()
    d = LaserOnsetDetector(clock)
    fired = False
    for _ in range(WARMUP_TICKS):
        if d.update(_snap(audio_band_low_abs=5.0)):  # constant, never spikes
            fired = True
        clock.advance(0.02)
    assert fired is False


def test_steady_energy_does_not_trigger():
    """A continuous, non-spiking signal (e.g. a sustained bassline) should
    not fire — only a genuine spike above the rolling average should."""
    clock = FakeClock()
    d = LaserOnsetDetector(clock)
    result = False
    for _ in range(80):  # past warmup, still steady throughout
        result = d.update(_snap(audio_band_low_abs=10.0))
        clock.advance(0.02)
    assert result is False


def test_a_real_spike_above_the_rolling_average_triggers_a_flash():
    clock = FakeClock()
    d = LaserOnsetDetector(clock)
    _warm_up(d, clock, audio_band_low_abs=1.0)
    # a sudden spike, well above baseline * ratio
    assert d.update(_snap(audio_band_low_abs=10.0)) is True


def test_flash_window_closes_after_flash_beats_elapses():
    clock = FakeClock()
    d = LaserOnsetDetector(clock, flash_beats=1.0)
    _warm_up(d, clock, audio_band_low_abs=1.0)
    assert d.update(_snap(bpm=120.0, audio_band_low_abs=10.0)) is True  # triggers; beat_dur=0.5s
    clock.advance(0.3)
    assert d.update(_snap(audio_band_low_abs=1.0)) is True   # still within the 0.5s flash window
    clock.advance(0.3)
    assert d.update(_snap(audio_band_low_abs=1.0)) is False  # window has closed


def test_refractory_period_prevents_immediate_re_trigger():
    clock = FakeClock()
    d = LaserOnsetDetector(clock, refractory_s=0.15, flash_beats=0.01)  # tiny flash window
    _warm_up(d, clock, audio_band_low_abs=1.0)
    assert d.update(_snap(audio_band_low_abs=10.0)) is True
    clock.advance(0.05)  # window has closed (flash_beats tiny) but still inside refractory
    # another spike arrives, but refractory hasn't elapsed -> shouldn't re-trigger a NEW window
    d.update(_snap(audio_band_low_abs=10.0))
    clock.advance(0.5)
    assert d.update(_snap(audio_band_low_abs=1.0)) is False  # confirms no new window was opened


def test_rolling_average_resets_when_audio_goes_stale():
    """A stale reading must not let a high rolling average silently persist
    and suppress/skew detection once audio reconnects."""
    clock = FakeClock()
    d = LaserOnsetDetector(clock)
    _warm_up(d, clock, audio_band_low_abs=50.0)  # a loud, steady baseline
    d.update(_snap(audio_fresh=False))
    assert d._rolling_avg == 0.0


def test_a_quiet_songs_occasional_kick_does_not_trigger():
    """docs/14 §3 (Josh, 2026-09-01): the whole point of the intensity gate —
    a real bass spike during a QUIET song/section must not fire, even though
    it's a perfectly genuine relative spike. Only intense parts should."""
    clock = FakeClock()
    d = LaserOnsetDetector(clock, min_intensity=0.7)
    _warm_up(d, clock, audio_band_low_abs=1.0, energy=0.2)  # quiet song throughout
    assert d.update(_snap(audio_band_low_abs=10.0, energy=0.2)) is False  # a real spike, still quiet overall


def test_a_spike_during_an_intense_section_does_trigger():
    clock = FakeClock()
    d = LaserOnsetDetector(clock, min_intensity=0.7)
    _warm_up(d, clock, audio_band_low_abs=1.0, energy=0.9)  # intense section throughout
    assert d.update(_snap(audio_band_low_abs=10.0, energy=0.9)) is True


def test_intensity_dropping_mid_song_stops_new_triggers():
    """A spike that would otherwise fire must not trigger once the song's
    overall energy has genuinely dropped, even if the scene hasn't rotated."""
    clock = FakeClock()
    d = LaserOnsetDetector(clock, min_intensity=0.7)
    _warm_up(d, clock, audio_band_low_abs=1.0, energy=0.9)
    assert d.update(_snap(audio_band_low_abs=10.0, energy=0.3)) is False  # energy has since dropped
