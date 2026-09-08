"""Phrase Engine — rotates scenes on inferred bar boundaries with crossfades.

Despite the name there is no real phrase *detection* (the XDJ-XZ doesn't transmit
song structure, docs/04 §4.1); this rotates the active scene on a fixed bar cadence
— exactly what the spec intends. Rules (docs/08 §4, docs/12 Phase 4):
  - rotate every ROTATION_BARS inferred bars; crossfade over CROSSFADE_BARS
  - enforce a minimum HOLD_BARS after any change (no "slot-machine" whiplash)
  - suspend starting new rotations while in a transition or a loop
  - a bar boundary fires a rotation once, not repeatedly while the bar holds
"""

from __future__ import annotations

import logging

from ..core.show_state import ShowSnapshot
from ..dynamics import musical_bar_position
from ..fixtures.profiles import ChannelKind
from ..fixtures.rig import Rig
from ..merge.merge import Contribution
from ..scenes.base import EnergyBucket, Scene
from ..scenes.catalog import SceneCatalog

log = logging.getLogger(__name__)

ROTATION_BARS = 16   # rotate the look on this cadence
CROSSFADE_BARS = 2   # crossfade duration
HOLD_BARS = 4        # minimum hold after any change


class PhraseEngine:
    def __init__(self, catalog: SceneCatalog | None = None) -> None:
        self.catalog = catalog or SceneCatalog()
        self._current: Scene = self.catalog.default()
        self._next: Scene | None = None
        self._crossfade_start_pos = 0.0
        self._last_change_bar = 0
        self._last_bar_seen = -1
        self._skip_requested = False
        self._was_in_transition = False
        self.rotations = 0  # for tests/telemetry

    @property
    def name(self) -> str:
        return "phrase"

    @property
    def current_scene_name(self) -> str:
        if self._next is not None:
            return f"{self._current.name} -> {self._next.name}"
        return self._current.name

    # --- UI / test hooks ---
    def skip(self) -> None:
        """Force a rotation at the next bar (still respects the minimum hold)."""
        self._skip_requested = True

    def force_scene(self, scene: Scene) -> None:
        """Jump straight to a specific scene (no crossfade) — for testing/override."""
        self._current = scene
        self._next = None

    # --- per-frame ---
    def tick(self, snap: ShowSnapshot, rig: Rig) -> Contribution:
        self._detect_settle(snap)
        self._maybe_rotate(snap)
        self._advance_crossfade(snap)
        return self._render(snap, rig)

    def _detect_settle(self, snap: ShowSnapshot) -> None:
        # When a mix ends, settle into a fresh look on the next downbeat (docs/08 §4).
        if self._was_in_transition and not snap.in_transition:
            self._skip_requested = True
        self._was_in_transition = snap.in_transition

    def _maybe_rotate(self, snap: ShowSnapshot) -> None:
        # Only act on a *new* bar so a boundary fires once, not every tick.
        if snap.bar == self._last_bar_seen:
            return
        self._last_bar_seen = snap.bar

        if self._next is not None:
            return  # already crossfading
        if snap.in_transition or snap.loop_active:
            return  # suspend rotations during a mix or loop

        bars_since_change = snap.bar - self._last_change_bar
        if bars_since_change < HOLD_BARS:
            return  # enforce the minimum hold

        if self._skip_requested or bars_since_change >= ROTATION_BARS:
            self._begin_rotation(snap)

    def _begin_rotation(self, snap: ShowSnapshot) -> None:
        # snap.bucket -- an ALREADY-DEBOUNCED, already-adaptively-rescaled
        # bucket_for_energy(energy_norm), computed once in metronome.py (see
        # BUCKET_MIN_DWELL_S there), not a fresh call here. Same reasoning as
        # reactive.py and laser_trigger.py: one shared notion of "what bucket
        # is this," not independently (and previously drift-prone) recomputed
        # per engine (found live 2026-09-07, see show_state.py's bucket
        # docstring).
        bucket = EnergyBucket(snap.bucket)
        self._next = self.catalog.pick(bucket, exclude=self._current)
        self._crossfade_start_pos = musical_bar_position(snap)
        self._skip_requested = False
        self.rotations += 1
        log.info("Scene rotate -> %s (bucket=%s)", self._next.name, bucket.value)

    def _advance_crossfade(self, snap: ShowSnapshot) -> None:
        if self._next is None:
            return
        if self._progress(snap) >= 1.0:
            self._current = self._next
            self._next = None
            self._last_change_bar = snap.bar

    def _progress(self, snap: ShowSnapshot) -> float:
        elapsed = musical_bar_position(snap) - self._crossfade_start_pos
        return max(0.0, min(1.0, elapsed / CROSSFADE_BARS))

    def _render(self, snap: ShowSnapshot, rig: Rig) -> Contribution:
        if self._next is None:
            return self._current.render(rig, snap, 1.0)
        progress = self._progress(snap)
        out_c = self._current.render(rig, snap, 1.0 - progress)
        in_c = self._next.render(rig, snap, progress)
        return self._combine(out_c, in_c, progress, rig)

    @staticmethod
    def _combine(out_c: Contribution, in_c: Contribution, progress: float, rig: Rig) -> Contribution:
        """Blend two scene contributions: brightness/color crossfade by weighted
        max; movement and laser channels switch at the midpoint (linear blending a
        pan value sweeps through center; blending a laser mode value could land in a
        wrong/unsafe range)."""
        result = Contribution()
        for ch in range(len(result.values)):
            ot, it = out_c.touched[ch], in_c.touched[ch]
            if not ot and not it:
                continue
            kind = rig.kind_at(ch)
            if kind in (ChannelKind.MOVEMENT, ChannelKind.LASER):
                if it and progress >= 0.5:
                    value = in_c.values[ch]
                elif ot:
                    value = out_c.values[ch]
                else:
                    value = in_c.values[ch]
            else:
                value = max(out_c.values[ch] if ot else 0, in_c.values[ch] if it else 0)
            result.set(ch + 1, value)
        return result
