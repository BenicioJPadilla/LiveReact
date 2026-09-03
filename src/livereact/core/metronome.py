"""Metronome: the single writer of the musical clock and ShowState.

It drains the input queue, holds the authoritative clock fields (bpm, beat phase,
beat-in-bar, bar), and publishes a fresh immutable snapshot every tick (~100 Hz).
This is the component that turns jittery beat *events* into a smooth, interpolated
beat *clock* — engines must read phase from here, never off raw packet arrival
(docs/05 §4.2, §7; docs/04 §4.1).

Behaviors:
  - Interpolate beat_phase between master beats from the monotonic clock.
  - Re-anchor to each master beat (hard resync); infer the bar from downbeats.
  - Free-run at the last known BPM if master beats stop arriving (graceful
    degradation, NFR-5) and flag low confidence.
  - Derive an energy estimate: real audio RMS passed through as-is (AudioAnalyzer
    already applies its own tuned attack/release envelope — smoothing it again
    here just adds latency, found by measuring real lights-vs-audio lag, docs/14
    §5), MIDI fader/EQ intent smoothed here instead, since that raw proxy is
    genuinely noisy/jumpy and has no smoothing of its own (docs/10 B8).
"""

from __future__ import annotations

import logging
import queue
import threading
from collections import deque

from ..clock import Clock, LoopTimer
from .messages import AudioLevelMessage, BeatMessage, MidiControlMessage, StatusMessage, TransitionMessage
from .show_state import ShowSnapshot, ShowState

log = logging.getLogger(__name__)

PDL_STALE_AFTER = 1.0    # seconds without a PDL message -> not fresh
MIDI_STALE_AFTER = 1.0   # seconds without a MIDI message -> not fresh
AUDIO_STALE_AFTER = 1.0  # seconds without an AudioLevelMessage -> not fresh
ENERGY_SMOOTHING = 0.05  # EMA factor per tick (~0.2 s time constant at 100 Hz) —
                         # MIDI-proxy fallback only; real audio bypasses this,
                         # see _derive_energy

# Transition detection (Phase 6): a crossfader that moves more than CROSS_MOVE
# within CROSS_WINDOW seconds — or a master-deck handoff — marks a transition,
# which then holds for TRANSITION_COOLDOWN after motion stops.
CROSS_WINDOW = 0.25
CROSS_MOVE = 0.08
TRANSITION_COOLDOWN = 0.5


class Metronome(threading.Thread):
    """Drains input messages and publishes the live ShowState at a fixed rate."""

    def __init__(
        self,
        input_queue: "queue.Queue",
        show_state: ShowState,
        clock: Clock,
        stop_event: threading.Event,
        hz: float = 100.0,
        log_interval: float = 1.0,
    ) -> None:
        super().__init__(name="metronome", daemon=False)
        self.queue = input_queue
        self.show_state = show_state
        self.clock = clock
        self.stop_event = stop_event
        self.hz = hz
        self._log_interval = log_interval

        # --- authoritative working state (owned solely by this thread) ---
        self._bpm = 124.0
        self._beat_anchor = clock.monotonic()  # monotonic time of the current beat
        self._beat_phase = 0.0
        self._beat_in_bar = 1
        self._bar = 0
        self._playing = False
        self._loop_active = False
        self._on_air: tuple[int, ...] = ()
        self._master_deck: int | None = None

        # transition detection
        self._cross_history: deque[tuple[float, float]] = deque()
        self._transition_until = 0.0
        self._prev_master: int | None = None

        # MIDI intent
        self._midi = {
            "crossfader": 0.5, "fader_a": 0.0, "fader_b": 0.0,
            "eq_low_a": 0.5, "eq_mid_a": 0.5, "eq_high_a": 0.5,
            "eq_low_b": 0.5, "eq_mid_b": 0.5, "eq_high_b": 0.5,
        }
        self._energy = 0.0

        # real audio (docs/14) — kept separate from _midi's fields; see
        # AudioLevelMessage's docstring for why band_low_abs stays un-normalized
        self._audio_band_low = 0.333
        self._audio_band_mid = 0.333
        self._audio_band_high = 0.334
        self._audio_band_low_abs = 0.0
        self._audio_rms = 0.0

        # freshness tracking
        self._last_beat_time: float | None = None
        self._last_pdl_time: float | None = None
        self._last_midi_time: float | None = None
        self._last_audio_time: float | None = None
        self._last_log = clock.monotonic()

    # ------------------------------------------------------------------ run loop
    def run(self) -> None:  # pragma: no cover - thin wrapper around tick()
        timer = LoopTimer(self.clock, self.hz)
        try:
            while not self.stop_event.is_set():
                self.tick()
                timer.wait()
        except Exception:  # noqa: BLE001 - never let the clock thread die silently
            log.exception("Metronome loop crashed")

    def tick(self) -> ShowSnapshot:
        """One iteration: drain queue, advance clock, derive, publish. Returns the
        snapshot it published (handy for tests)."""
        now = self.clock.monotonic()
        self._drain_queue()
        self._advance_clock(now)
        self._derive_energy(now)
        snap = self._build_snapshot(now)
        self.show_state.publish(snap)
        self._maybe_log(now, snap)
        return snap

    # ------------------------------------------------------------------ inputs
    def _drain_queue(self) -> None:
        while True:
            try:
                msg = self.queue.get_nowait()
            except queue.Empty:
                break
            self._handle(msg)

    def _handle(self, msg) -> None:
        if isinstance(msg, BeatMessage):
            self._on_beat(msg)
        elif isinstance(msg, StatusMessage):
            self._on_status(msg)
        elif isinstance(msg, MidiControlMessage):
            self._on_midi(msg)
        elif isinstance(msg, AudioLevelMessage):
            self._on_audio(msg)
        elif isinstance(msg, TransitionMessage):
            # An explicit transition signal (demo/manual). Detection is the main
            # path; this just nudges the same timer so both sources agree.
            if msg.active:
                self._transition_until = max(self._transition_until, msg.timestamp + TRANSITION_COOLDOWN)
            else:
                self._transition_until = msg.timestamp
        else:  # pragma: no cover - defensive
            log.debug("Metronome ignoring unknown message: %r", msg)

    def _on_beat(self, msg: BeatMessage) -> None:
        self._last_pdl_time = msg.timestamp
        if not msg.is_master:
            return  # only the master deck drives the clock
        if msg.bpm > 0:
            self._bpm = msg.bpm
        # Infer bar from downbeats; guard against double-counting if the free-run
        # advance already rolled us into beat 1 this cycle.
        if msg.beat_in_bar == 1 and self._beat_in_bar != 1:
            self._bar += 1
        self._beat_in_bar = msg.beat_in_bar
        self._beat_anchor = msg.timestamp  # hard resync: phase = 0 at this beat
        self._beat_phase = 0.0
        self._last_beat_time = msg.timestamp

    def _on_status(self, msg: StatusMessage) -> None:
        self._last_pdl_time = msg.timestamp
        self._on_air = msg.on_air
        # A master-deck handoff is a transition.
        if self._prev_master is not None and msg.master_deck != self._prev_master:
            self._transition_until = max(self._transition_until, msg.timestamp + TRANSITION_COOLDOWN)
        self._prev_master = msg.master_deck
        self._master_deck = msg.master_deck
        self._playing = msg.playing
        self._loop_active = msg.loop_active

    def _on_midi(self, msg: MidiControlMessage) -> None:
        self._last_midi_time = msg.timestamp
        if msg.control in self._midi:
            value = max(0.0, min(1.0, msg.value))
            self._midi[msg.control] = value
            if msg.control == "crossfader":
                self._note_crossfader(msg.timestamp, value)

    def _on_audio(self, msg: AudioLevelMessage) -> None:
        self._last_audio_time = msg.timestamp
        self._audio_band_low = msg.band_low
        self._audio_band_mid = msg.band_mid
        self._audio_band_high = msg.band_high
        self._audio_band_low_abs = msg.band_low_abs
        self._audio_rms = msg.rms

    def _note_crossfader(self, t: float, value: float) -> None:
        """Detect a transition from crossfader motion over a rolling window."""
        history = self._cross_history
        history.append((t, value))
        while history and t - history[0][0] > CROSS_WINDOW:
            history.popleft()
        if len(history) >= 2:
            values = [v for _, v in history]
            if max(values) - min(values) >= CROSS_MOVE:
                self._transition_until = max(self._transition_until, t + TRANSITION_COOLDOWN)

    # ------------------------------------------------------------------ clock
    def _advance_clock(self, now: float) -> None:
        if self._bpm <= 0:
            return
        beat_dur = 60.0 / self._bpm
        elapsed = now - self._beat_anchor
        if self._is_pdl_fresh(now) and elapsed < beat_dur:
            # Locked: interpolate within the beat (clamped so we don't roll past).
            self._beat_phase = min(0.999, elapsed / beat_dur)
            return
        # Free-run: master beats are late/absent — advance beats from the clock so
        # phase keeps moving smoothly instead of stalling.
        while elapsed >= beat_dur:
            self._beat_anchor += beat_dur
            elapsed -= beat_dur
            self._advance_one_beat()
        self._beat_phase = elapsed / beat_dur

    def _advance_one_beat(self) -> None:
        self._beat_in_bar += 1
        if self._beat_in_bar > 4:
            self._beat_in_bar = 1
        if self._beat_in_bar == 1:
            self._bar += 1

    # ------------------------------------------------------------------ derive
    def _derive_energy(self, now: float) -> None:
        # VERIFIED preference order (docs/14): real audio loudness when fresh —
        # it's actually measuring the sound, not a mixer-knob proxy. Falls back
        # to the MIDI fader/EQ estimate when audio isn't available, same
        # graceful-degradation pattern as every other input in this project.
        #
        # FOUND BY LIVE MEASUREMENT (docs/14 §5, 2026-09-01): real audio was
        # getting smoothed TWICE — once by AudioAnalyzer's own attack/release
        # envelope (already tuned to feel responsive to real transients), then
        # again here by ENERGY_SMOOTHING's ~0.2s time constant. That stacked
        # smoothing showed up as a measured ~120ms of extra lag on the moving
        # head's dimmer (which reads snap.energy directly, no beat_pulse of its
        # own) beyond the audio path's already-unavoidable capture latency.
        # Fix: real audio is already appropriately smoothed by the time it gets
        # here — pass it through as-is. Only the MIDI proxy (raw fader/EQ
        # positions, genuinely noisy/jumpy, no smoothing of its own) still
        # needs ENERGY_SMOOTHING applied here.
        if self._is_audio_fresh(now):
            self._energy = self._audio_rms
        else:
            # Louder deck's fader + how "open" its EQ is -> a coarse energy proxy.
            if self._midi["fader_a"] >= self._midi["fader_b"]:
                fader, prefix = self._midi["fader_a"], "a"
            else:
                fader, prefix = self._midi["fader_b"], "b"
            eq_open = (
                self._midi[f"eq_low_{prefix}"]
                + self._midi[f"eq_mid_{prefix}"]
                + self._midi[f"eq_high_{prefix}"]
            ) / 3.0
            raw = 0.6 * fader + 0.4 * eq_open
            self._energy += ENERGY_SMOOTHING * (raw - self._energy)

    # ------------------------------------------------------------------ health
    def _is_pdl_fresh(self, now: float) -> bool:
        return self._last_beat_time is not None and (now - self._last_beat_time) < PDL_STALE_AFTER

    def _is_midi_fresh(self, now: float) -> bool:
        return self._last_midi_time is not None and (now - self._last_midi_time) < MIDI_STALE_AFTER

    def _is_audio_fresh(self, now: float) -> bool:
        return self._last_audio_time is not None and (now - self._last_audio_time) < AUDIO_STALE_AFTER

    # ------------------------------------------------------------------ output
    def _build_snapshot(self, now: float) -> ShowSnapshot:
        return ShowSnapshot(
            t=now,
            bpm=self._bpm,
            beat_phase=self._beat_phase,
            beat_in_bar=self._beat_in_bar,
            bar=self._bar,
            playing=self._playing,
            loop_active=self._loop_active,
            on_air=self._on_air,
            master_deck=self._master_deck,
            crossfader=self._midi["crossfader"],
            fader_a=self._midi["fader_a"],
            fader_b=self._midi["fader_b"],
            eq_low_a=self._midi["eq_low_a"],
            eq_mid_a=self._midi["eq_mid_a"],
            eq_high_a=self._midi["eq_high_a"],
            eq_low_b=self._midi["eq_low_b"],
            eq_mid_b=self._midi["eq_mid_b"],
            eq_high_b=self._midi["eq_high_b"],
            audio_energy=self._audio_rms,
            audio_band_low=self._audio_band_low,
            audio_band_mid=self._audio_band_mid,
            audio_band_high=self._audio_band_high,
            audio_band_low_abs=self._audio_band_low_abs,
            energy=self._energy,
            in_transition=now < self._transition_until,
            free_running=not self._is_pdl_fresh(now),
            pdl_fresh=self._is_pdl_fresh(now),
            midi_fresh=self._is_midi_fresh(now),
            audio_fresh=self._is_audio_fresh(now),
        )

    def _maybe_log(self, now: float, snap: ShowSnapshot) -> None:
        if now - self._last_log >= self._log_interval:
            self._last_log = now
            log.info("ShowState | %s", snap.summary())
