"""SceneCatalog: scenes grouped by energy bucket with round-robin selection.

Energy → bucket thresholds map the metronome's energy estimate to a family of
looks; within a bucket, scenes are picked round-robin (no Markov chain in v1,
docs/10 B7).
"""

from __future__ import annotations

from ..fixtures.rig import Rig
from .base import EnergyBucket, Scene
from .library import ALL_SCENES


# Named so other modules (e.g. engines/reactive.py's per-bucket wash model,
# LIGHTING_BIBLE.md §5/§9.1) can normalize energy *within* a bucket's own
# range without duplicating these numbers and risking drift.
BREAKDOWN_MAX = 0.30
BUILD_MAX = 0.55
HOLD_MAX = 0.80

# Bucket-boundary hysteresis (2026-09-07 real --hardware --record session,
# see [[livereact-project]] memory): BUCKET_MIN_DWELL_S alone (metronome.py)
# only guards against a candidate committing too QUICKLY -- it does nothing
# once a bucket has already committed. A real ~4min capture showed 26 bucket
# flips, mostly DROP<->HOLD/BUILD ping-pong every few (as little as ~1.2s)
# seconds -- energy_norm spending a long stretch hovering right at a boundary
# (DROP sat at 45% of a real song, far more than any actual "drop" section),
# re-triggering a fresh dwell-timer race each time it crossed back. Josh's
# own words: the wash bar "turning off and fluttering... doing some
# randomness." Fix: once a bucket is committed, energy must clear the
# boundary by MARGIN in the direction of travel before even becoming a new
# candidate -- not just touch it. `bucket_for_energy` itself (stateless,
# tested directly in several places) is left untouched; this wraps it with
# the committed bucket as the anchor, used only by metronome.py's debounce.
HYSTERESIS_MARGIN = 0.05

_BUCKET_ORDER = (EnergyBucket.BREAKDOWN, EnergyBucket.BUILD, EnergyBucket.HOLD, EnergyBucket.DROP)
_BUCKET_BOUNDARIES = (BREAKDOWN_MAX, BUILD_MAX, HOLD_MAX)  # boundary i sits between order[i]/order[i+1]


def bucket_for_energy(energy: float) -> EnergyBucket:
    if energy < BREAKDOWN_MAX:
        return EnergyBucket.BREAKDOWN
    if energy < BUILD_MAX:
        return EnergyBucket.BUILD
    if energy < HOLD_MAX:
        return EnergyBucket.HOLD
    return EnergyBucket.DROP


def bucket_for_energy_with_hysteresis(
    energy: float, committed: EnergyBucket, margin: float = HYSTERESIS_MARGIN
) -> EnergyBucket:
    """Like `bucket_for_energy`, but anchored on the currently-committed
    bucket: a boundary only counts as crossed once `energy` clears it by
    `margin` in the direction of travel, so hovering within `margin` of a
    boundary (found live, see above) can't even start a new debounce
    candidate. Walks one boundary at a time from `committed` toward wherever
    `energy` actually is, so a big jump (e.g. a real drop) still resolves to
    the right bucket in one call, not just the adjacent one."""
    idx = _BUCKET_ORDER.index(committed)
    while idx < len(_BUCKET_BOUNDARIES) and energy >= _BUCKET_BOUNDARIES[idx] + margin:
        idx += 1
    while idx > 0 and energy < _BUCKET_BOUNDARIES[idx - 1] - margin:
        idx -= 1
    return _BUCKET_ORDER[idx]


class SceneCatalog:
    def __init__(self, scenes: list[Scene] | None = None) -> None:
        instances = scenes if scenes is not None else [cls() for cls in ALL_SCENES]
        self._by_bucket: dict[EnergyBucket, list[Scene]] = {b: [] for b in EnergyBucket}
        for scene in instances:
            self._by_bucket[scene.bucket].append(scene)
        self._rr_index: dict[EnergyBucket, int] = {b: 0 for b in EnergyBucket}

    def bucket(self, bucket: EnergyBucket) -> list[Scene]:
        return self._by_bucket[bucket]

    def default(self) -> Scene:
        """A calm starting scene."""
        for bucket in (EnergyBucket.BREAKDOWN, EnergyBucket.HOLD, EnergyBucket.BUILD, EnergyBucket.DROP):
            if self._by_bucket[bucket]:
                return self._by_bucket[bucket][0]
        raise ValueError("catalog has no scenes")

    def pick(self, bucket: EnergyBucket, rig: Rig | None = None, exclude: Scene | None = None) -> Scene:
        """Round-robin within ``bucket``; avoid returning ``exclude`` if possible.

        Falls back to any non-excluded scene in any bucket if the requested bucket
        is empty, so selection never fails.

        ``rig`` (Bible-integration Phase 1, optional/default None): when given,
        applies LIGHTING_BIBLE.md §5's `requires{}`/`min_atmosphere_density`
        capability gate before round-robining, walking one `degrade_to` hop on
        failure (LOOK-01; recursive-degrade beyond one hop and conflict
        arbitration are NOT specified anywhere in the Bible -- see this
        project's plan doc's Open Questions #3/#4 for the deliberately
        conservative defaults applied here: one hop only, then fall back to
        round-robin among whatever's actually eligible, never hard-fail).
        Omitting ``rig`` (the default) skips this gate entirely -- existing
        callers that don't pass a rig get byte-identical behavior to before
        this parameter existed.
        """
        scenes = self._by_bucket[bucket]
        if not scenes:
            scenes = [s for b in EnergyBucket for s in self._by_bucket[b]]
        if rig is not None:
            scenes = self._capability_filter(scenes, rig)
        n = len(scenes)
        for _ in range(n):
            idx = self._rr_index[bucket] % n
            self._rr_index[bucket] = idx + 1
            candidate = scenes[idx]
            if candidate is not exclude:
                return candidate
        return scenes[0]  # only one scene available; reuse it

    @staticmethod
    def _eligible(scene: Scene, rig: Rig) -> bool:
        return scene.requires <= rig.capabilities() and rig.atm >= scene.min_atmosphere_density

    def _capability_filter(self, scenes: list[Scene], rig: Rig) -> list[Scene]:
        """Replace each ineligible scene with its one-hop `degrade_to` target
        (if that target is itself eligible), then drop anything still
        ineligible. Never returns an empty list while ANY scene anywhere in
        the catalog is eligible (falls back to the full flattened catalog,
        same "selection never fails" guarantee `pick()` already makes)."""
        result: list[Scene] = []
        for scene in scenes:
            if self._eligible(scene, rig):
                result.append(scene)
                continue
            if scene.degrade_to is not None:
                degraded = self._instance_of(scene.degrade_to)
                if degraded is not None and self._eligible(degraded, rig):
                    result.append(degraded)
        if result:
            return result
        # Nothing in this bucket is eligible even after degrading -- fall back
        # to any eligible scene anywhere, same spirit as the empty-bucket case
        # above (never fail to select something).
        everything = [s for b in EnergyBucket for s in self._by_bucket[b]]
        eligible_anywhere = [s for s in everything if self._eligible(s, rig)]
        return eligible_anywhere or scenes  # scenes as an absolute last resort (old behavior)

    def _instance_of(self, scene_type: type[Scene]) -> Scene | None:
        """Find the catalog's own instance of a `degrade_to` target type, so
        degrading reuses the same instance (and its round-robin state)
        rather than constructing a bare, un-registered one."""
        for b in EnergyBucket:
            for s in self._by_bucket[b]:
                if type(s) is scene_type:
                    return s
        return None
