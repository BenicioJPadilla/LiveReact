"""Tests for the Metronome — driven deterministically with a FakeClock.

The metronome's work is in ``tick()``; tests advance the FakeClock and call
``tick()`` directly, so beat interpolation, bar inference, free-run, and energy
derivation are all asserted with no threads and no real time passing.
"""

from __future__ import annotations

import queue
import threading

import pytest

from livereact.clock import FakeClock
from livereact.core.messages import (
    AudioLevelMessage,
    BeatMessage,
    MidiControlMessage,
    StatusMessage,
    TransitionMessage,
)
from livereact.core.metronome import Metronome
from livereact.core.show_state import ShowState


def _metronome(clock: FakeClock):
    return Metronome(queue.Queue(), ShowState(), clock, threading.Event())


def test_beat_phase_interpolates_between_master_beats():
    clock = FakeClock()
    m = _metronome(clock)
    m.queue.put(BeatMessage(timestamp=0.0, beat_in_bar=1, bpm=120.0, is_master=True, player=1))
    snap = m.tick()
    assert snap.bpm == 120.0
    assert snap.beat_phase == pytest.approx(0.0, abs=1e-6)
    assert not snap.free_running and snap.pdl_fresh

    clock.advance(0.25)  # halfway through a 0.5 s beat
    snap = m.tick()
    assert snap.beat_phase == pytest.approx(0.5, abs=1e-3)

    clock.advance(0.24)  # near the end of the beat
    snap = m.tick()
    assert snap.beat_phase == pytest.approx(0.98, abs=0.02)


def test_bar_increments_on_the_downbeat_wrap():
    clock = FakeClock()
    m = _metronome(clock)
    # A full bar of master beats: 2,3,4,1 -> the trailing '1' completes a bar.
    for beat in (2, 3, 4, 1):
        m.queue.put(BeatMessage(0.0, beat, 120.0, True, 1))
        m.tick()
    assert m.tick().bar == 1
    for beat in (2, 3, 4, 1):
        m.queue.put(BeatMessage(0.0, beat, 120.0, True, 1))
        m.tick()
    assert m.tick().bar == 2


def test_free_runs_when_master_beats_stop():
    clock = FakeClock()
    m = _metronome(clock)
    m.queue.put(BeatMessage(0.0, 1, 120.0, True, 1))  # beat_dur = 0.5 s
    m.tick()
    assert not m.tick().free_running  # fresh right after a beat

    # No more beats; jump well past the staleness window.
    clock.advance(1.5)
    snap = m.tick()
    assert snap.free_running and not snap.pdl_fresh
    # Phase kept advancing (beats rolled over from the clock, not stuck at 0).
    assert snap.beat_in_bar != 1 or snap.bar > 0


def test_energy_follows_fader_and_eq():
    clock = FakeClock()
    m = _metronome(clock)
    m.queue.put(MidiControlMessage(0.0, "fader_a", 1.0))
    for ctrl in ("eq_low_a", "eq_mid_a", "eq_high_a"):
        m.queue.put(MidiControlMessage(0.0, ctrl, 0.5))
    # raw = 0.6*1.0 + 0.4*0.5 = 0.8; EMA converges over many ticks.
    snap = None
    for _ in range(300):
        snap = m.tick()
    assert snap.energy == pytest.approx(0.8, abs=0.01)
    assert snap.midi_fresh


def test_energy_prefers_fresh_audio_over_midi_proxy():
    """docs/14: real audio should win over the MIDI fader/EQ estimate when
    both are present — it's the actual sound, not a mixer-knob proxy."""
    clock = FakeClock()
    m = _metronome(clock)
    # MIDI would derive energy=0.8 (see test_energy_follows_fader_and_eq)...
    m.queue.put(MidiControlMessage(0.0, "fader_a", 1.0))
    for ctrl in ("eq_low_a", "eq_mid_a", "eq_high_a"):
        m.queue.put(MidiControlMessage(0.0, ctrl, 0.5))
    # ...but real audio says the room is much quieter -> that should win.
    m.queue.put(AudioLevelMessage(0.0, rms=0.2, band_low=0.5, band_mid=0.3, band_high=0.2, band_low_abs=10.0))
    snap = None
    for _ in range(300):
        snap = m.tick()
    assert snap.audio_fresh
    assert snap.energy == pytest.approx(0.2, abs=0.01)  # audio's 0.2, not MIDI's 0.8
    assert snap.audio_band_low == 0.5
    assert snap.audio_band_low_abs == 10.0


def test_energy_falls_back_to_midi_when_audio_goes_stale():
    clock = FakeClock()
    m = _metronome(clock)
    m.queue.put(AudioLevelMessage(0.0, rms=0.2, band_low=0.5, band_mid=0.3, band_high=0.2, band_low_abs=10.0))
    m.queue.put(MidiControlMessage(0.0, "fader_a", 1.0))
    for ctrl in ("eq_low_a", "eq_mid_a", "eq_high_a"):
        m.queue.put(MidiControlMessage(0.0, ctrl, 0.5))
    for _ in range(50):
        m.tick()
    assert m.tick().audio_fresh

    clock.advance(2.0)  # past AUDIO_STALE_AFTER, MIDI stays fresh (no separate staleness test needed here)
    snap = None
    for _ in range(300):
        snap = m.tick()
    assert not snap.audio_fresh
    assert snap.energy == pytest.approx(0.8, abs=0.01)  # falls back to the MIDI proxy


# --- adaptive energy normalization (2026-09-07, found live) ------------------
# `bucket_for_energy` should read `energy_norm`, not raw `energy` — see
# show_state.py's energy_norm docstring / livereact-project memory for why a
# fixed absolute threshold against raw RMS doesn't generalize across sessions.


def _pump_audio(m: Metronome, clock: FakeClock, rms: float, seconds: float, step: float = 0.2) -> None:
    """Feed a steady real-audio rms for `seconds` of simulated time, keeping
    audio_fresh continuously true (messages every `step`s, well under
    AUDIO_STALE_AFTER) — the shape a real live audio stream would take."""
    elapsed = 0.0
    while elapsed < seconds:
        m.queue.put(AudioLevelMessage(clock.monotonic(), rms=rms, band_low=0.5,
                                       band_mid=0.3, band_high=0.2, band_low_abs=rms * 20))
        m.tick()
        clock.advance(step)
        elapsed += step


def test_energy_norm_stays_zero_during_warmup():
    """Not enough history yet (< ENERGY_NORM_MIN_SAMPLES) -> report 0.0 (the
    safe/quiet default), not a ratio computed from almost nothing."""
    clock = FakeClock()
    m = _metronome(clock)
    _pump_audio(m, clock, rms=0.6, seconds=5.0)
    assert m.tick().energy_norm == 0.0


def test_energy_norm_reaches_high_values_for_a_sustained_loud_passage():
    """The exact bug found live (2026-09-07): a sustained passage well below
    the OLD fixed DROP threshold (0.80 on raw energy) should still normalize
    high once it's genuinely the loudest thing this set has recently
    contained — that's what actually generalizes across tracks/gain staging."""
    clock = FakeClock()
    m = _metronome(clock)
    _pump_audio(m, clock, rms=0.1, seconds=60.0)   # a quiet baseline first
    _pump_audio(m, clock, rms=0.5, seconds=30.0)   # then a sustained louder passage
    snap = m.tick()
    assert snap.energy == pytest.approx(0.5, abs=0.01)  # raw energy: well under the old 0.80 cutoff
    assert snap.energy_norm > 0.8  # normalized against ITS OWN recent range: reads as a drop


def test_energy_norm_smooths_out_beat_to_beat_oscillation():
    """FOUND BY TESTING (offline replay against a real captured session):
    normalizing raw, unsmoothed per-tick energy directly flipped the bucket
    several times a second, since ordinary beat-to-beat swings are a big
    fraction of any short window's own range. Pin down the fix: alternating
    high/low rms (simulating kick pulsing) should NOT make energy_norm swing
    wildly tick to tick once warmed up."""
    clock = FakeClock()
    m = _metronome(clock)
    # a realistic quiet baseline with natural micro-variation, not a perfectly
    # flat signal -- a perfectly flat 60s input degenerately collapses this
    # project's own MIN_SPAN floor to its minimum, which isn't how real audio
    # behaves (even a "flat" bassline has some tick-to-tick variation).
    baseline = [0.25, 0.30, 0.28, 0.32, 0.27]
    for i in range(120):
        rms = baseline[i % len(baseline)]
        m.queue.put(AudioLevelMessage(clock.monotonic(), rms=rms, band_low=0.5,
                                       band_mid=0.3, band_high=0.2, band_low_abs=rms * 20))
        m.tick()
        clock.advance(0.5)
    samples = []
    for i in range(40):  # ~8s of alternating high/low, faster than a real kick
        rms = 0.6 if i % 2 == 0 else 0.15
        m.queue.put(AudioLevelMessage(clock.monotonic(), rms=rms, band_low=0.5,
                                       band_mid=0.3, band_high=0.2, band_low_abs=rms * 20))
        samples.append(m.tick().energy_norm)
        clock.advance(0.2)
    assert max(samples) - min(samples) < 0.35  # smoothed -- doesn't chase every toggle


def test_energy_norm_ignores_a_tiny_blip_after_extended_silence():
    """FOUND BY TESTING: without an absolute-ceiling guard, a long silent
    stretch (a track ending) followed by any small residual noise spiked
    energy_norm straight to ~1.0 ("DROP") against a near-zero range."""
    clock = FakeClock()
    m = _metronome(clock)
    _pump_audio(m, clock, rms=0.0, seconds=60.0)
    m.queue.put(AudioLevelMessage(clock.monotonic(), rms=0.08, band_low=0.5,
                                   band_mid=0.3, band_high=0.2, band_low_abs=1.6))
    assert m.tick().energy_norm == 0.0


def test_energy_norm_passes_raw_energy_through_when_audio_is_stale():
    """The MIDI-fallback proxy is already a hand-built 0..1 signal (fader/EQ
    position), not a loudness measure -- adaptive rescaling doesn't apply."""
    clock = FakeClock()
    m = _metronome(clock)
    m.queue.put(MidiControlMessage(0.0, "fader_a", 1.0))
    for ctrl in ("eq_low_a", "eq_mid_a", "eq_high_a"):
        m.queue.put(MidiControlMessage(0.0, ctrl, 0.5))
    snap = None
    for _ in range(300):
        snap = m.tick()
    assert not snap.audio_fresh
    assert snap.energy_norm == pytest.approx(snap.energy, abs=1e-9)


# --- bucket debounce (2026-09-07, found live + via offline replay on a real
# track) --- bucket_for_energy flapped near its own boundaries; a candidate
# bucket must now persist for BUCKET_MIN_DWELL_S before it's committed to.
# Drives _derive_bucket directly (bypassing tick()'s own _derive_energy_norm,
# which would otherwise overwrite the manually-set energy_norm each call) --
# same white-box style as the laser trigger's duty-cap tests.


def test_bucket_starts_at_breakdown():
    clock = FakeClock()
    m = _metronome(clock)
    assert m.tick().bucket == "breakdown"


def test_bucket_ignores_a_brief_blip_below_the_dwell_time():
    clock = FakeClock()
    m = _metronome(clock)
    m._energy_norm = 0.9  # DROP-range
    m._derive_bucket(clock.monotonic())
    clock.advance(0.5)  # well under BUCKET_MIN_DWELL_S -- a blip, not a real change
    m._derive_bucket(clock.monotonic())
    m._energy_norm = 0.0  # back to BREAKDOWN-range before the blip could commit
    clock.advance(0.1)
    m._derive_bucket(clock.monotonic())
    assert m._bucket_committed.value == "breakdown"  # never actually changed


def test_bucket_commits_after_persisting_past_the_dwell_time():
    clock = FakeClock()
    m = _metronome(clock)
    m._energy_norm = 0.9  # DROP-range
    m._derive_bucket(clock.monotonic())
    clock.advance(1.1)  # past BUCKET_MIN_DWELL_S, still DROP-range the whole time
    m._derive_bucket(clock.monotonic())
    assert m._bucket_committed.value == "drop"


def test_bucket_candidate_restarts_if_a_different_bucket_appears_first():
    """A candidate that gets pre-empted by a THIRD bucket before committing
    must restart its own dwell timer, not inherit the first candidate's
    elapsed time."""
    clock = FakeClock()
    m = _metronome(clock)
    m._energy_norm = 0.9  # DROP-range candidate begins
    m._derive_bucket(clock.monotonic())
    clock.advance(0.9)  # close to committing, but not quite
    m._energy_norm = 0.6  # HOLD-range -- a different candidate pre-empts DROP
    m._derive_bucket(clock.monotonic())
    clock.advance(0.9)  # would have been enough time for the ORIGINAL candidate
    m._derive_bucket(clock.monotonic())
    assert m._bucket_committed.value == "breakdown"  # HOLD hasn't dwelled long enough yet
    clock.advance(0.2)  # now past 1.0s since HOLD became the candidate
    m._derive_bucket(clock.monotonic())
    assert m._bucket_committed.value == "hold"


def test_midi_and_transition_and_status_update_state():
    clock = FakeClock()
    m = _metronome(clock)
    m.queue.put(MidiControlMessage(0.0, "crossfader", 0.8))
    m.queue.put(TransitionMessage(0.0, active=True))
    m.queue.put(StatusMessage(0.0, on_air=(2,), master_deck=2, playing=True, loop_active=True))
    snap = m.tick()
    assert snap.crossfader == pytest.approx(0.8)
    assert snap.in_transition is True
    assert snap.on_air == (2,) and snap.master_deck == 2 and snap.loop_active

    m.queue.put(TransitionMessage(0.0, active=False))
    assert m.tick().in_transition is False
