"""DemoDataSource: synthetic "music" with no hardware.

Produces exactly the message stream a real PDL+MIDI rig would: master beats at a
steady BPM, periodic transport status, a slowly breathing energy curve expressed
through fader/EQ MIDI, and periodic transitions (crossfader sweep + deck handoff)
and loops. This is the substrate the whole engine/scene layer is built against
(docs/11 §2, docs/12 Phase 1).

Like the metronome and writer, the work is in a testable ``tick()``; ``run()`` just
paces it on the injected clock.
"""

from __future__ import annotations

import logging
import math
import queue
import threading

from ..clock import Clock, LoopTimer
from ..core.messages import (
    BeatMessage,
    MidiControlMessage,
    StatusMessage,
    TransitionMessage,
)
from .base import InputSource

log = logging.getLogger(__name__)

MIDI_RATE_HZ = 30.0            # how often to emit MIDI control updates
TRANSITION_EVERY_BARS = 16     # start a transition on this bar cadence
TRANSITION_SECONDS = 2.0       # crossfader sweep duration
LOOP_EVERY_BARS = 24           # engage a loop on this bar cadence
LOOP_BARS = 4                  # loop length in bars


class DemoDataSource(threading.Thread, InputSource):
    """Generates a believable synthetic input stream onto the message queue."""

    def __init__(
        self,
        output_queue: "queue.Queue",
        clock: Clock,
        stop_event: threading.Event,
        bpm: float = 124.0,
        tick_hz: float = 100.0,
    ) -> None:
        super().__init__(name="demo-source", daemon=False)
        self.queue = output_queue
        self.clock = clock
        self.stop_event = stop_event
        self.bpm = bpm
        self.tick_hz = tick_hz

        now = clock.monotonic()
        self._started_at = now
        self._next_beat_time = now
        self._beat_index = 0           # total beats emitted
        self._bar = 0
        self._last_midi = now

        # deck / transport state
        self._master_deck = 1
        self._on_air: tuple[int, ...] = (1,)

        # transition state
        self._in_transition = False
        self._transition_start = 0.0
        self._transition_end = 0.0
        self._cross_target = 0.0       # crossfader resting position (0=A, 1=B)

        # loop state
        self._loop_active = False
        self._loop_release_bar = -1

    @property
    def name(self) -> str:
        return "demo"

    def stop(self) -> None:
        # Uses the app's shared stop_event; nothing source-specific to do.
        pass

    # ------------------------------------------------------------------ run loop
    def run(self) -> None:  # pragma: no cover - thin wrapper around tick()
        timer = LoopTimer(self.clock, self.tick_hz)
        try:
            while not self.stop_event.is_set():
                self.tick()
                timer.wait()
        except Exception:  # noqa: BLE001
            log.exception("DemoDataSource loop crashed")

    def tick(self) -> None:
        now = self.clock.monotonic()
        self._emit_due_beats(now)
        self._maybe_end_transition(now)
        self._emit_midi(now)

    # ------------------------------------------------------------------ beats
    def _emit_due_beats(self, now: float) -> None:
        beat_dur = 60.0 / self.bpm
        while now >= self._next_beat_time:
            self._beat_index += 1
            beat_in_bar = (self._beat_index - 1) % 4 + 1
            ts = self._next_beat_time
            self._put(BeatMessage(ts, beat_in_bar, self.bpm, is_master=True, player=self._master_deck))
            if beat_in_bar == 1:
                self._bar += 1
                self._on_downbeat(ts)
            self._put(self._status(ts))
            self._next_beat_time += beat_dur

    def _on_downbeat(self, ts: float) -> None:
        # Kick off a transition on the cadence (unless one is already running).
        if self._bar > 0 and self._bar % TRANSITION_EVERY_BARS == 0 and not self._in_transition:
            self._begin_transition(ts)
        # Engage / release loops on their own cadence.
        if self._bar > 0 and self._bar % LOOP_EVERY_BARS == 0 and not self._loop_active:
            self._loop_active = True
            self._loop_release_bar = self._bar + LOOP_BARS
            self._put(self._status(ts))
        elif self._loop_active and self._bar >= self._loop_release_bar:
            self._loop_active = False
            self._put(self._status(ts))

    # ------------------------------------------------------------------ transitions
    def _begin_transition(self, ts: float) -> None:
        self._in_transition = True
        self._transition_start = ts
        self._transition_end = ts + TRANSITION_SECONDS
        self._put(TransitionMessage(ts, active=True))

    def _maybe_end_transition(self, now: float) -> None:
        if self._in_transition and now >= self._transition_end:
            self._in_transition = False
            # Hand off to the other deck.
            self._master_deck = 2 if self._master_deck == 1 else 1
            self._on_air = (self._master_deck,)
            self._cross_target = 1.0 if self._master_deck == 2 else 0.0
            self._put(TransitionMessage(now, active=False))
            self._put(self._status(now))

    # ------------------------------------------------------------------ midi
    def _emit_midi(self, now: float) -> None:
        if now - self._last_midi < 1.0 / MIDI_RATE_HZ:
            return
        self._last_midi = now
        t = now - self._started_at
        energy = 0.5 + 0.4 * math.sin(t * 0.05)  # slow breathing curve

        # Crossfader: sweep across the transition window, else rest at target.
        if self._in_transition:
            span = max(1e-6, self._transition_end - self._transition_start)
            progress = (now - self._transition_start) / span
            start = 0.0 if self._master_deck == 1 else 1.0
            end = 1.0 - start
            cross = start + (end - start) * max(0.0, min(1.0, progress))
        else:
            cross = self._cross_target

        # Faders: the master deck rides up with energy; the other sits low.
        fader_a = energy if self._master_deck == 1 else energy * 0.2
        fader_b = energy if self._master_deck == 2 else energy * 0.2

        # EQ: highs climb with energy, lows stay present (a generic build feel).
        high = 0.4 + 0.5 * energy
        mid = 0.5
        low = 0.6

        for control, value in (
            ("crossfader", cross),
            ("fader_a", fader_a), ("fader_b", fader_b),
            ("eq_low_a", low), ("eq_mid_a", mid), ("eq_high_a", high),
            ("eq_low_b", low), ("eq_mid_b", mid), ("eq_high_b", high),
        ):
            self._put(MidiControlMessage(now, control, value))

    # ------------------------------------------------------------------ helpers
    def _status(self, ts: float) -> StatusMessage:
        return StatusMessage(
            timestamp=ts,
            on_air=self._on_air,
            master_deck=self._master_deck,
            playing=True,
            loop_active=self._loop_active,
        )

    def _put(self, msg) -> None:
        self.queue.put(msg)
