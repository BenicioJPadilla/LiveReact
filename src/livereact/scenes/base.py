"""Scene base + energy buckets + small painting helpers.

A Scene renders one *look* into a Contribution, scaled by an ``intensity`` weight
(used for crossfading). Scenes address fixtures by role/side and respect the
two-axis color rule. Only DROP scenes touch laser channels (docs/02 FR-3.2,
docs/08 §3).
"""

from __future__ import annotations

from enum import Enum

from ..core.show_state import ShowSnapshot
from ..fixtures.profiles import Par, WashBar
from ..fixtures.rig import Rig
from ..merge.merge import Contribution


class EnergyBucket(Enum):
    BREAKDOWN = "breakdown"
    BUILD = "build"
    DROP = "drop"
    HOLD = "hold"


class Scene:
    """Base class. Subclasses set name/bucket/uses_lasers and implement render()."""

    name: str = "scene"
    bucket: EnergyBucket = EnergyBucket.HOLD
    uses_lasers: bool = False

    def render(self, rig: Rig, snap: ShowSnapshot, intensity: float = 1.0) -> Contribution:
        raise NotImplementedError


# --- painting helpers shared by scenes -------------------------------------

def paint_wash(c: Contribution, rig: Rig, r: float, g: float, b: float, level: float) -> None:
    """Set all wash fixtures to an RGB at a brightness ``level`` (0..1)."""
    for fx in rig.by_role("wash"):
        if isinstance(fx, (Par, WashBar)):
            # VERIFIED ON HARDWARE: Par has a real dimmer channel, same as
            # WashBar (not "baked into color" as previously assumed).
            fx.set_intensity(c, level)
            fx.set_color(c, r, g, b)


def paint_spots(c: Contribution, rig: Rig, r: float, g: float, b: float, level: float) -> None:
    """Set both moving heads to a color + dimmer level (movement set separately)."""
    for fx in rig.by_role("spot"):
        fx.set_intensity(c, level)
        fx.set_color(c, r, g, b)
