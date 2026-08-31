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
