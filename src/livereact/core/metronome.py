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
import math
import queue
import threading
from collections import deque

from ..clock import Clock, LoopTimer
from ..scenes.base import EnergyBucket
from ..scenes.catalog import bucket_for_energy
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

# Adaptive energy normalization (2026-09-07, FOUND LIVE, see [[livereact-project]]
# memory): `bucket_for_energy` used to be fed raw `energy` directly, compared
# against FIXED absolute thresholds (0.30/0.55/0.80). Real audio's `energy` is
# raw mic RMS run through `ENERGY_GAIN`, a manually hand-tuned constant
# calibrated against one specific night's mixer gain staging (inputs/audio.py) —
# it does NOT adapt to a different session's gain staging or a different
# track's mastering loudness. Confirmed live (2026-09-07): a whole real ~5.5min
# session's energy topped out at 0.666 — the 0.80 DROP threshold never fired
# ONCE, even during what was audibly the drop. `energy_norm` instead rescales
# `energy` against THIS SET's own recent loudness range (a rolling percentile
# window), so "DROP" means "near the top of what's actually been playing,"
# genre/mastering/gain-staging independent — this is what actually answers
# "how do we recognize the drop in every song."
ENERGY_NORM_SMOOTH_TAU_S = 3.0        # EMA smoothing BEFORE normalizing -- roughly
                                       # a beat or two at house/techno tempo.
                                       # FOUND BY TESTING (offline replay against
                                       # a real captured session, 2026-09-07):
                                       # normalizing the raw, unsmoothed per-tick
                                       # energy directly flipped the bucket several
                                       # times PER SECOND -- ordinary beat-to-beat
                                       # amplitude swings are a big fraction of any
                                       # short window's own range. Smoothing first
                                       # makes the classification reflect a song
                                       # SECTION's character, not one kick.
ENERGY_NORM_WINDOW_S = 90.0           # how far back to look for "this set's recent
                                       # range" -- roughly 2-3 phrases: long enough
                                       # that one kick/riser can't move it, short
                                       # enough to adapt within a single track.
ENERGY_NORM_SAMPLE_INTERVAL_S = 1.0   # how often to add to/recompute the rolling
                                       # window -- doesn't need per-tick precision,
                                       # and keeps the window small (~90 samples)
                                       # so sorting it every time stays cheap.
ENERGY_NORM_MIN_SAMPLES = 20          # require ~20s of real history before trusting
                                       # the normalized value at all -- same warmup
                                       # principle as the laser trigger's WARMUP_S.
                                       # Report 0.0 (BREAKDOWN, the safe default)
                                       # before this, not a meaningless ratio.
ENERGY_NORM_MIN_SPAN = 0.10           # floor on (ceiling - floor) -- avoids the
                                       # ratio blowing up when the set's been flat.
ENERGY_NORM_MIN_CEILING = 0.05        # if nothing above this has happened
                                       # recently, the set is genuinely silent --
                                       # report 0.0 rather than let a tiny residual
                                       # blip normalize to ~1.0 against a near-zero
                                       # range. FOUND BY TESTING: without this, a
                                       # track ending (a long stretch at energy=0)
                                       # followed by any small noise spiked
                                       # energy_norm straight to ~1.0 ("DROP").

# Bucket debounce (2026-09-07, FOUND LIVE + via tools/simulations/replay_song.py
# on a real track): `bucket_for_energy` is a stateless boundary check on
# `energy_norm`, and energy_norm -- even smoothed -- can sit within a hair of
# 0.30/0.55/0.80 for a real stretch of a song. Measured values a THOUSANDTH
# apart (0.2992 vs 0.3009) crossing a boundary repeatedly, and it visibly broke
# the reactive layer's own output: a real DROP passage dropping back to
# BREAKDOWN for a couple of ticks then jumping straight back, and a BUILD ramp
# (meant to run ~14s/8 bars) getting pre-empted by HOLD/DROP after under 2
# seconds -- Josh's own live report: "no buildup... the wash bar would turn off
# and be on its own random rhythm." Same "make ONE decision, then hold it"
# principle as reactive.py's beat-locked kick pass 4 and the laser's own
# spacing/duty gate, applied to bucket classification itself: a candidate
# bucket must PERSIST for BUCKET_MIN_DWELL_S before it's actually committed to,
# not flip the instant a boundary is crossed. Computed HERE (not independently
# by each of reactive.py/laser_trigger.py/phrase.py) for the same reason
# energy_norm itself is centralized -- one shared notion of "what bucket are we
# in," not three copies that could drift apart.
#
# LIMIT, stated plainly: this kills RAPID flapping (the diagnosed failure mode
# -- blips of a few ticks up to ~2s). It does NOT guarantee a real drop can
# never be interrupted -- if energy_norm itself genuinely dips for several real
# seconds, this will still (correctly) commit to a lower bucket. Re-check
# against real playback after this lands rather than assuming it's fully solved.
BUCKET_MIN_DWELL_S = 1.0


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

        # adaptive energy normalization state (see ENERGY_NORM_* above) — owned
        # solely by this thread, same as everything else here.
        self._energy_smooth = 0.0
        self._energy_history: deque[float] = deque(
            maxlen=int(ENERGY_NORM_WINDOW_S / ENERGY_NORM_SAMPLE_INTERVAL_S)
        )
        self._energy_floor = 0.0
        self._energy_ceiling = 0.0
        self._last_norm_tick_t: float | None = None
        self._last_energy_sample_t: float | None = None
        self._energy_norm = 0.0

        # bucket debounce state (see BUCKET_MIN_DWELL_S above)
        self._bucket_committed = EnergyBucket.BREAKDOWN  # safe default: the calm/quiet state
        self._bucket_candidate: EnergyBucket | None = None
        self._bucket_candidate_since: float | None = None

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
        self._derive_energy_norm(now)
        self._derive_bucket(now)
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

    def _derive_energy_norm(self, now: float) -> None:
        """Rescale `self._energy` against this SET's own recent loudness range
        (see the ENERGY_NORM_* constants above for the full "why"). Real-audio
        only: the MIDI fallback proxy (fader/EQ position) is already a
        hand-built 0..1 signal, not a loudness measure, so it passes through
        unscaled — adaptive rescaling doesn't mean anything for that path."""
        if not self._is_audio_fresh(now):
            self._energy_norm = self._energy
            return

        dt = (now - self._last_norm_tick_t) if self._last_norm_tick_t is not None else 0.0
        self._last_norm_tick_t = now
        coeff = 1 - math.exp(-dt / ENERGY_NORM_SMOOTH_TAU_S) if dt > 0 else 0.0
        self._energy_smooth += coeff * (self._energy - self._energy_smooth)

        if (self._last_energy_sample_t is None
                or now - self._last_energy_sample_t >= ENERGY_NORM_SAMPLE_INTERVAL_S):
            self._last_energy_sample_t = now
            self._energy_history.append(self._energy_smooth)
            vals = sorted(self._energy_history)
            n = len(vals)
            self._energy_floor = vals[int(0.10 * (n - 1))]
            self._energy_ceiling = vals[int(0.90 * (n - 1))]

        if (len(self._energy_history) < ENERGY_NORM_MIN_SAMPLES
                or self._energy_ceiling < ENERGY_NORM_MIN_CEILING):
            self._energy_norm = 0.0  # not enough history yet, or genuinely silent recently
            return

        span = max(self._energy_ceiling - self._energy_floor, ENERGY_NORM_MIN_SPAN)
        self._energy_norm = max(0.0, min(1.0, (self._energy_smooth - self._energy_floor) / span))

    def _derive_bucket(self, now: float) -> None:
        """Debounce bucket_for_energy's output (see BUCKET_MIN_DWELL_S above):
        a candidate bucket must persist for BUCKET_MIN_DWELL_S before it's
        actually committed to, instead of flipping the instant energy_norm
        crosses a boundary."""
        raw = bucket_for_energy(self._energy_norm)
        if raw == self._bucket_committed:
            self._bucket_candidate = None
            self._bucket_candidate_since = None
            return
        if raw != self._bucket_candidate:
            self._bucket_candidate = raw
            self._bucket_candidate_since = now
            return
        if now - self._bucket_candidate_since >= BUCKET_MIN_DWELL_S:
            self._bucket_committed = raw
            self._bucket_candidate = None
            self._bucket_candidate_since = None

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
            energy_norm=self._energy_norm,
            bucket=self._bucket_committed.value,
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
