"""ShowState: the single shared bus between the metronome and the engines/UI.

Modeled as a single-slot publisher of an immutable ``ShowSnapshot`` (the same
atomic-reference-swap pattern as the DMX frame buffer). The metronome is the sole
writer; it builds a complete frozen snapshot each tick and publishes it. Readers
get the latest snapshot with no lock held afterwards and no possibility of a torn
read — every field they see came from the same instant (docs/05 §4.1, §4.2).

Field provenance (docs/04 §4.3) is documented per field below:
  measured      = comes straight off PDL/MIDI
  interpolated  = computed locally between events (beat_phase)
  inferred      = derived heuristically (bar, energy, in_transition)
Note: absolute track position is intentionally absent — the XDJ-XZ does not
transmit it (docs/04 §4.1), so no feature may depend on it.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class ShowSnapshot:
    """An immutable, tear-free view of the show at one instant."""

    t: float = 0.0                       # monotonic time this snapshot was built

    # --- musical clock ---
    bpm: float = 124.0                   # measured (default until first beat)
    beat_phase: float = 0.0              # interpolated, 0.0-1.0 within the beat
    beat_in_bar: int = 1                 # measured, 1-4
    bar: int = 0                         # inferred (counts downbeats)

    # --- transport / decks ---
    playing: bool = False                # measured
    loop_active: bool = False            # measured
    on_air: tuple[int, ...] = ()         # measured
    master_deck: int | None = None       # measured

    # --- MIDI intent (measured, normalized 0.0-1.0) ---
    crossfader: float = 0.5
    fader_a: float = 0.0
    fader_b: float = 0.0
    eq_low_a: float = 0.5
    eq_mid_a: float = 0.5
    eq_high_a: float = 0.5
    eq_low_b: float = 0.5
    eq_mid_b: float = 0.5
    eq_high_b: float = 0.5

    # --- real audio (measured, docs/14) — kept SEPARATE from the MIDI-intent
    # fields above deliberately (provenance): these come from actually analyzing
    # the sound, not mixer-knob position. band_low/mid/high are normalized
    # fractions for color; band_low_abs is the low band's un-normalized energy,
    # for the laser onset trigger specifically — VERIFIED these must stay two
    # separate signals (tools/simulations/audio_pipeline_sim_v2.py), not one
    # derived from the other.
    audio_energy: float = 0.0
    audio_band_low: float = 0.333
    audio_band_mid: float = 0.333
    audio_band_high: float = 0.334
    audio_band_low_abs: float = 0.0

    # --- derived ---
    energy: float = 0.0                  # inferred 0.0-1.0
    in_transition: bool = False          # inferred / synthetic

    # --- health / confidence ---
    free_running: bool = True            # clock free-running (no recent master beat)
    pdl_fresh: bool = False              # a PDL message arrived recently
    midi_fresh: bool = False             # a MIDI message arrived recently
    audio_fresh: bool = False            # an AudioLevelMessage arrived recently

    def summary(self) -> str:
        """One-line human summary for periodic logging."""
        clock = "free-run" if self.free_running else "locked"
        return (
            f"bpm={self.bpm:5.1f} bar={self.bar:>4} beat={self.beat_in_bar} "
            f"phase={self.beat_phase:.2f} energy={self.energy:.2f} "
            f"transition={'Y' if self.in_transition else 'n'} "
            f"clock={clock} pdl={'fresh' if self.pdl_fresh else 'STALE'} "
            f"midi={'fresh' if self.midi_fresh else 'stale'} "
            f"audio={'fresh' if self.audio_fresh else 'stale'}"
        )

    def replace(self, **changes) -> "ShowSnapshot":
        return replace(self, **changes)


class ShowState:
    """Thread-safe holder of the latest immutable :class:`ShowSnapshot`."""

    def __init__(self, initial: ShowSnapshot | None = None) -> None:
        self._lock = threading.Lock()
        self._current = initial or ShowSnapshot()

    def publish(self, snapshot: ShowSnapshot) -> None:
        """Atomically make ``snapshot`` current. Called only by the metronome."""
        with self._lock:
            self._current = snapshot

    def snapshot(self) -> ShowSnapshot:
        """Return the latest snapshot (immutable; safe to read without the lock)."""
        with self._lock:
            return self._current
