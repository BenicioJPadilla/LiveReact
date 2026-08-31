"""Engine interface.

Engines are pure-ish functions of the world: read an immutable ShowSnapshot, write
into their own fresh Contribution, return it. They never call each other and never
mutate shared state — all coordination happens through the snapshot they read and
the merge that folds their contributions (docs/02 FR-2.4, docs/05 §5.3).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..core.show_state import ShowSnapshot
from ..fixtures.rig import Rig
from ..merge.merge import Contribution


@runtime_checkable
class Engine(Protocol):
    @property
    def name(self) -> str:
        ...

    def tick(self, snapshot: ShowSnapshot, rig: Rig) -> Contribution:
        """Produce this engine's additive contribution for one frame."""
        ...
