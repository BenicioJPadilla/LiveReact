"""Tests for the DemoDataSource — deterministic via FakeClock."""

from __future__ import annotations

import queue
import threading

from livereact.clock import FakeClock
from livereact.core.messages import (
    BeatMessage,
    MidiControlMessage,
    StatusMessage,
    TransitionMessage,
)
from livereact.inputs.demo import DemoDataSource


def _drain(q: "queue.Queue") -> list:
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except queue.Empty:
            return out


def _source(clock: FakeClock, bpm=120.0):
    return DemoDataSource(queue.Queue(), clock, threading.Event(), bpm=bpm)


def test_emits_master_beats_at_the_expected_cadence():
    clock = FakeClock()
    src = _source(clock, bpm=120.0)  # beat_dur 0.5 s -> ~21 beats over [0, 10]
    clock.advance(10.0)
    src.tick()
    beats = [m for m in _drain(src.queue) if isinstance(m, BeatMessage)]
    assert 20 <= len(beats) <= 22
    assert all(b.is_master for b in beats)
    assert {b.beat_in_bar for b in beats} == {1, 2, 3, 4}


def test_emits_midi_controls():
    clock = FakeClock()
    src = _source(clock)
    clock.advance(1.0)
    src.tick()
    midi = [m for m in _drain(src.queue) if isinstance(m, MidiControlMessage)]
    controls = {m.control for m in midi}
    assert "crossfader" in controls
    assert {"fader_a", "fader_b"} <= controls
    assert any(c.startswith("eq_") for c in controls)


def test_transition_fires_and_hands_off_the_deck():
    clock = FakeClock()
    src = _source(clock, bpm=120.0)
    # 16 bars = 64 beats = 32 s at 120 BPM -> first transition begins ~t=30 s.
    # Step in chunks so _maybe_end_transition runs after the transition starts.
    for _ in range(40):
        clock.advance(1.0)
        src.tick()
    msgs = _drain(src.queue)
    transitions = [m for m in msgs if isinstance(m, TransitionMessage)]
    assert any(t.active for t in transitions)       # a transition began
    assert any(not t.active for t in transitions)   # and ended
    # After the handoff the master deck flipped from 1 to 2.
    assert src._master_deck == 2
    statuses = [m for m in msgs if isinstance(m, StatusMessage)]
    assert any(s.master_deck == 2 for s in statuses)
