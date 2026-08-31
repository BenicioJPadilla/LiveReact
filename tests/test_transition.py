"""Tests for transition detection (metronome), the during-mix lift (TransitionEngine),
and the Phrase Engine settling into a new scene afterward."""

from __future__ import annotations

import queue
import threading

from livereact.clock import FakeClock
from livereact.core.messages import MidiControlMessage, StatusMessage
from livereact.core.metronome import TRANSITION_COOLDOWN, Metronome
from livereact.core.show_state import ShowSnapshot, ShowState
from livereact.engines.phrase import HOLD_BARS, ROTATION_BARS, PhraseEngine
from livereact.engines.transition import TransitionEngine
from livereact.fixtures.rig import load_rig


def _metronome(clock: FakeClock) -> Metronome:
    return Metronome(queue.Queue(), ShowState(), clock, threading.Event())


# --- detection (metronome) -------------------------------------------------

def test_crossfader_move_flips_transition_quickly():
    clock = FakeClock()
    m = _metronome(clock)
    m.queue.put(MidiControlMessage(0.0, "crossfader", 0.0))
    assert not m.tick().in_transition  # resting, no motion

    clock.advance(0.1)  # within the ~200 ms detection target
    m.queue.put(MidiControlMessage(0.1, "crossfader", 0.5))  # a clear move
    assert m.tick().in_transition


def test_transition_clears_after_cooldown():
    clock = FakeClock()
    m = _metronome(clock)
    m.queue.put(MidiControlMessage(0.0, "crossfader", 0.0))
    m.tick()
    clock.advance(0.1)
    m.queue.put(MidiControlMessage(0.1, "crossfader", 0.6))
    assert m.tick().in_transition

    clock.advance(TRANSITION_COOLDOWN + 0.2)  # no further motion
    assert not m.tick().in_transition


def test_master_deck_handoff_marks_a_transition():
    clock = FakeClock()
    m = _metronome(clock)
    m.queue.put(StatusMessage(0.0, on_air=(1,), master_deck=1, playing=True, loop_active=False))
    m.tick()
    m.queue.put(StatusMessage(0.0, on_air=(2,), master_deck=2, playing=True, loop_active=False))
    assert m.tick().in_transition


# --- during-mix lift (TransitionEngine) ------------------------------------

def test_transition_engine_lifts_only_during_a_mix():
    rig = load_rig()
    eng = TransitionEngine()
    par = rig.fixture("par_l")

    off = eng.tick(ShowSnapshot(in_transition=False), rig)
    assert not any(off.touched)

    on = eng.tick(ShowSnapshot(in_transition=True), rig)
    assert on.touched[par.offset]  # washes lifted
    assert on.values[par.offset] > 0


# --- Phrase Engine interaction ---------------------------------------------

def _snap(bar: int, in_transition=False) -> ShowSnapshot:
    return ShowSnapshot(bpm=124.0, energy=0.7, bar=bar, beat_in_bar=1, beat_phase=0.0,
                        fader_a=1.0, eq_low_a=1.0, in_transition=in_transition)


def test_no_rotation_during_a_transition_even_past_16_bars():
    rig = load_rig()
    eng = PhraseEngine()
    for bar in range(0, ROTATION_BARS + 8, 2):
        eng.tick(_snap(bar, in_transition=True), rig)
    assert eng.rotations == 0


def test_settles_into_a_new_scene_after_the_transition():
    rig = load_rig()
    eng = PhraseEngine()
    # A mix runs for several bars...
    for bar in range(0, HOLD_BARS + 4, 2):
        eng.tick(_snap(bar, in_transition=True), rig)
    assert eng.rotations == 0
    # ...then ends: the next downbeat settles into a fresh scene.
    eng.tick(_snap(HOLD_BARS + 5, in_transition=False), rig)
    assert eng.rotations == 1
