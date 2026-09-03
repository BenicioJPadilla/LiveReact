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

def paint_wash(c: Contribution, rig: Rig, r: float, g: float, b: float) -> None:
    """Set all wash fixtures to an RGB color (mood/hue only).

    Intensity is deliberately NOT set here (2026-09-02, docs/14 §5): it used
    to be, and competed via max-merge against the Reactive layer's own
    always-on beat pulse on the same channel — two independently-timed
    signals (a scene's slow/ambient level vs. the Reactive layer's fast
    per-beat ramp) fighting over which was higher each tick produced a
    jagged, stuttering composite instead of one clean rhythm (found by
    Josh live-testing: "doesn't feel like a continuous steady pulse").
    Wash dimmer is now owned exclusively by the Reactive layer, which
    already scales its pulse by the song's real energy — scenes don't need
    to separately set an ambient level on top of that.
    """
    for fx in rig.by_role("wash"):
        if isinstance(fx, (Par, WashBar)):
            fx.set_color(c, r, g, b)


def paint_spots(c: Contribution, rig: Rig, r: float, g: float, b: float, level: float) -> None:
    """Set both moving heads to a color + dimmer level (movement set separately)."""
    for fx in rig.by_role("spot"):
        fx.set_intensity(c, level)
        fx.set_color(c, r, g, b)
