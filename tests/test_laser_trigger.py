"""Tests for LaserOnsetDetector (docs/14 §3) — driven deterministically with a
FakeClock, same pattern as the Metronome/SilenceDetector tests."""

from __future__ import annotations

from livereact.clock import FakeClock
from livereact.core.laser_trigger import LaserOnsetDetector
from livereact.core.show_state import ShowSnapshot
from livereact.scenes.catalog import bucket_for_energy

WARMUP_TICKS = 60  # 60 * 0.02s = 1.2s, safely past the detector's 1.0s warmup gate


def _snap(**kw) -> ShowSnapshot:
    # energy defaults high (intense) so the existing spike-detection tests
    # below aren't also implicitly testing the intensity gate; pdl_fresh
    # defaults True so they aren't implicitly testing the PDL-loss gate
    # either (that gets its own dedicated tests further down).
    base = dict(bpm=120.0, audio_fresh=True, pdl_fresh=True, audio_band_low_abs=0.0, energy=1.0)
    base.update(kw)
    # bucket_for_energy reads energy_norm, not raw energy (2026-09-07, found
    # live) -- default it to match energy so existing tests that only set
    # `energy=` still exercise the DROP gate they intend to.
    base.setdefault("energy_norm", base["energy"])
    # snap.bucket is normally an ALREADY-DEBOUNCED value from metronome.py --
    # default it from this snapshot's own energy_norm for the same reason.
    base.setdefault("bucket", bucket_for_energy(base["energy_norm"]).value)
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
    """docs/14 §3 (Josh, 2026-09-01), now via the DROP-bucket gate (2026-09-08,
    LIGHTING_BIBLE.md §8.5): a real bass spike during a QUIET song/section
    must not fire, even though it's a perfectly genuine relative spike. Only
    the drop bucket should."""
    clock = FakeClock()
    d = LaserOnsetDetector(clock)
    _warm_up(d, clock, audio_band_low_abs=1.0, energy=0.2)  # quiet song throughout
    assert d.update(_snap(audio_band_low_abs=10.0, energy=0.2)) is False  # a real spike, still quiet overall


def test_a_spike_during_an_intense_section_does_trigger():
    clock = FakeClock()
    d = LaserOnsetDetector(clock)
    _warm_up(d, clock, audio_band_low_abs=1.0, energy=0.9)  # DROP bucket throughout
    assert d.update(_snap(audio_band_low_abs=10.0, energy=0.9)) is True


def test_intensity_dropping_mid_song_stops_new_triggers():
    """A spike that would otherwise fire must not trigger once the song's
    overall energy has genuinely dropped out of the DROP bucket, even if the
    scene hasn't rotated."""
    clock = FakeClock()
    d = LaserOnsetDetector(clock)
    _warm_up(d, clock, audio_band_low_abs=1.0, energy=0.9)
    assert d.update(_snap(audio_band_low_abs=10.0, energy=0.3)) is False  # energy has since dropped


# --- PDL-loss force-off (LIGHTING_BIBLE.md §12, 2026-09-08) ------------------
# "Laser forces OFF on ANY signal loss — never hold last value." Previously
# only audio_fresh was checked; a PDL-only dropout (audio still fresh) used to
# slip through this gate entirely.


def test_fails_closed_when_pdl_is_not_fresh_even_with_audio_fine():
    clock = FakeClock()
    d = LaserOnsetDetector(clock)
    assert d.update(_snap(pdl_fresh=False, audio_band_low_abs=100.0, energy=1.0)) is False


def test_pdl_loss_closes_an_already_open_flash_window_immediately():
    clock = FakeClock()
    d = LaserOnsetDetector(clock, flash_beats=4.0)  # a long window, well past the next tick
    _warm_up(d, clock, audio_band_low_abs=1.0)
    assert d.update(_snap(audio_band_low_abs=10.0)) is True  # triggers, window should stay open a while
    # PDL drops out mid-flash -- must close immediately, not ride out the window
    assert d.update(_snap(pdl_fresh=False, audio_band_low_abs=10.0)) is False


def test_pdl_loss_does_not_reset_the_audio_rolling_average():
    """Unlike audio loss, a PDL-only dropout shouldn't discard already-valid
    audio state -- only the flash decision itself is gated."""
    clock = FakeClock()
    d = LaserOnsetDetector(clock)
    _warm_up(d, clock, audio_band_low_abs=50.0)  # a loud, steady baseline
    d.update(_snap(pdl_fresh=False))
    assert d._rolling_avg != 0.0


def test_pdl_returning_allows_triggers_again():
    clock = FakeClock()
    d = LaserOnsetDetector(clock)
    _warm_up(d, clock, audio_band_low_abs=1.0)
    d.update(_snap(pdl_fresh=False, audio_band_low_abs=10.0))
    assert d.active is False
    assert d.update(_snap(pdl_fresh=True, audio_band_low_abs=10.0)) is True


# --- musical role / duty cycle (LIGHTING_BIBLE.md §8.5, 2026-09-08) ---------
# Three gates layered on top of onset detection: DROP-bucket only (tested
# above, replacing the old MIN_INTENSITY check), minimum spacing between
# separate laser "moments", and a cumulative <=10%-of-elapsed-time duty cap.


def test_minimum_spacing_blocks_a_new_moment_too_soon():
    clock = FakeClock()
    d = LaserOnsetDetector(clock, min_spacing_s=120.0)
    _warm_up(d, clock, audio_band_low_abs=1.0, energy=0.9)
    assert d.update(_snap(audio_band_low_abs=10.0, energy=0.9)) is True  # first moment fires
    clock.advance(0.6)  # past the ~0.5s flash window (bpm=120, flash_beats=1.0)
    assert d.update(_snap(audio_band_low_abs=1.0, energy=0.9)) is False  # window closed
    clock.advance(60.0)  # well under the 120s spacing requirement
    assert d.update(_snap(audio_band_low_abs=10.0, energy=0.9)) is False  # blocked -- too soon


def test_minimum_spacing_allows_a_new_moment_once_spaced_out():
    clock = FakeClock()
    d = LaserOnsetDetector(clock, min_spacing_s=120.0)
    _warm_up(d, clock, audio_band_low_abs=1.0, energy=0.9)
    d.update(_snap(audio_band_low_abs=10.0, energy=0.9))
    clock.advance(0.6)
    d.update(_snap(audio_band_low_abs=1.0, energy=0.9))
    clock.advance(121.0)  # past the 120s spacing requirement
    assert d.update(_snap(audio_band_low_abs=10.0, energy=0.9)) is True


def test_duty_cap_blocks_a_trigger_once_the_budget_is_spent():
    """Directly sets the cumulative counters rather than simulating hundreds
    of ticks -- deterministic, and tests the gating condition itself."""
    clock = FakeClock()
    d = LaserOnsetDetector(clock, min_spacing_s=0.0)
    _warm_up(d, clock, audio_band_low_abs=1.0, energy=0.9)
    d._total_elapsed_s = 100.0
    d._total_flash_s = 20.0  # 20% -- already over the default 10% budget
    assert d.update(_snap(audio_band_low_abs=10.0, energy=0.9)) is False


def test_duty_cap_allows_a_trigger_once_diluted_back_under_budget():
    clock = FakeClock()
    d = LaserOnsetDetector(clock, min_spacing_s=0.0)
    _warm_up(d, clock, audio_band_low_abs=1.0, energy=0.9)
    d._total_elapsed_s = 1000.0
    d._total_flash_s = 20.0  # 2% -- well under the default 10% budget
    assert d.update(_snap(audio_band_low_abs=10.0, energy=0.9)) is True
