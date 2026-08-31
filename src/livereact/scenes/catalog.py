"""SceneCatalog: scenes grouped by energy bucket with round-robin selection.

Energy → bucket thresholds map the metronome's energy estimate to a family of
looks; within a bucket, scenes are picked round-robin (no Markov chain in v1,
docs/10 B7).
"""

from __future__ import annotations

from .base import EnergyBucket, Scene
from .library import ALL_SCENES


def bucket_for_energy(energy: float) -> EnergyBucket:
    if energy < 0.30:
        return EnergyBucket.BREAKDOWN
    if energy < 0.55:
        return EnergyBucket.BUILD
    if energy < 0.80:
        return EnergyBucket.HOLD
    return EnergyBucket.DROP


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

    def pick(self, bucket: EnergyBucket, exclude: Scene | None = None) -> Scene:
        """Round-robin within ``bucket``; avoid returning ``exclude`` if possible.

        Falls back to any non-excluded scene in any bucket if the requested bucket
        is empty, so selection never fails.
        """
        scenes = self._by_bucket[bucket]
        if not scenes:
            scenes = [s for b in EnergyBucket for s in self._by_bucket[b]]
        n = len(scenes)
        for _ in range(n):
            idx = self._rr_index[bucket] % n
            self._rr_index[bucket] = idx + 1
            candidate = scenes[idx]
            if candidate is not exclude:
                return candidate
        return scenes[0]  # only one scene available; reuse it
