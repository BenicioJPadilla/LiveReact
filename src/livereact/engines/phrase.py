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
        self._last_bucket_seen: str | None = None
        self._skip_requested = False
        self._was_in_transition = False
        self.rotations = 0  # for tests/telemetry

    # LIGHTING_BIBLE.md §2.3's Titan tiers (Bible-integration Phase 4) --
    # see engines/reactive.py's own priority comment for the full tier list.
    priority = 50

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
        self._maybe_rotate(snap, rig)
        self._advance_crossfade(snap)
        return self._render(snap, rig)

    def _detect_settle(self, snap: ShowSnapshot) -> None:
        # When a mix ends, settle into a fresh look on the next downbeat (docs/08 §4).
        if self._was_in_transition and not snap.in_transition:
            self._skip_requested = True
        self._was_in_transition = snap.in_transition

    def _maybe_rotate(self, snap: ShowSnapshot, rig: Rig) -> None:
        # Only act on a *new* bar so a boundary fires once, not every tick.
        if snap.bar == self._last_bar_seen:
            return
        self._last_bar_seen = snap.bar

        # A real energy-state change (e.g. into DROP) should prompt a fresh
        # rotation check on its own timeline, not wait for the next scheduled
        # ROTATION_BARS boundary -- CONFIRMED live (2026-09-09 hardware
        # capture, see [[livereact-project]] memory) that scene rotation and
        # bucket classification were otherwise two fully independent clocks:
        # a bucket could jump straight into DROP while the active scene
        # (chosen for a totally different energy state, e.g. the calm
        # `Deep Wash Breathe`) kept running for up to a full ROTATION_BARS=16
        # bars before catching up -- measured as long as 24s/14 bars on a
        # real drop, directly producing "still blue during the drop."
        # Reuses the existing `_skip_requested` flag/path (same as an
        # explicit operator skip or a DJ-transition-end), so this does NOT
        # bypass the HOLD_BARS anti-whiplash floor below -- it's still
        # subject to the exact same minimum hold as every other trigger
        # here, just one more legitimate reason to ask for a rotation check.
        if self._last_bucket_seen is not None and snap.bucket != self._last_bucket_seen:
            self._skip_requested = True
        self._last_bucket_seen = snap.bucket

        if self._next is not None:
            return  # already crossfading
        if snap.in_transition or snap.loop_active:
            return  # suspend rotations during a mix or loop

        # Bible-integration gap fix (2026-09-13, found during a Phase 1-6
        # re-audit): `Scene.min_hold_bars` ("per-look override of the
        # catalog-wide HOLD_BARS," scenes/base.py's own docstring) has been
        # populated by dozens of Phase 5 scenes with real Bible-specified
        # values (e.g. BreakLowWash=16, DropBlinderClear=4, AllDark=1) but
        # was NEVER actually consulted here -- every look used the same
        # flat HOLD_BARS=4 floor regardless of what it declared. Fixed:
        # the CURRENTLY-HELD look's own min_hold_bars now gates how long it
        # must be shown before any rotation away from it, falling back to
        # the catalog-wide HOLD_BARS when a scene doesn't override it (the
        # 8 pre-Bible-integration scenes, which never set this field).
        hold_bars = self._current.min_hold_bars if self._current.min_hold_bars is not None else HOLD_BARS
        bars_since_change = snap.bar - self._last_change_bar
        if bars_since_change < hold_bars:
            return  # enforce the minimum hold

        if self._skip_requested or bars_since_change >= ROTATION_BARS:
            self._begin_rotation(snap, rig)

    def _begin_rotation(self, snap: ShowSnapshot, rig: Rig) -> None:
        # snap.bucket -- an ALREADY-DEBOUNCED, already-adaptively-rescaled
        # bucket_for_energy(energy_norm), computed once in metronome.py (see
        # BUCKET_MIN_DWELL_S there), not a fresh call here. Same reasoning as
        # reactive.py and laser_trigger.py: one shared notion of "what bucket
        # is this," not independently (and previously drift-prone) recomputed
        # per engine (found live 2026-09-07, see show_state.py's bucket
        # docstring).
        bucket = EnergyBucket(snap.bucket)
        # `rig` threaded through (Bible-integration Phase 1) so pick() can
        # apply requires{}/min_atmosphere_density capability gating -- a
        # no-op for all 8 pre-Phase-1 scenes (empty requires, 0.0 atm
        # requirement, always satisfied), real once Phase 5 adds looks that
        # actually declare requires{}.
        self._next = self.catalog.pick(bucket, rig, exclude=self._current)
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
