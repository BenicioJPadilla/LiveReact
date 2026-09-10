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
    """Base class. Subclasses set name/bucket/uses_lasers and implement render().

    Schema v2 fields (2026-09-10, Bible-integration Phase 1 --
    docs/bible_integration/, /Users/joshuaracimora/.claude/plans/
    adaptive-squishing-pebble.md): additive, all default to values that make
    the 8 existing scenes behave exactly as before -- empty `requires` is
    always satisfied, `min_atmosphere_density=0.0` is always satisfied since
    `Rig.atm` is always 0.0 on this rig (no haze fixture exists), `degrade_to`
    and `conflicts` are unused until SceneCatalog.pick() is given a `rig` to
    check against. These mirror LIGHTING_BIBLE.md §5's per-look fields
    (`requires{}`, `degrade→`, `conflicts[...]`, `min_atmosphere_density`,
    `dark %`, `min_hold`, `reactivity{kick_follow, justification}`) so new
    looks can declare them without inventing new plumbing per look.
    """

    name: str = "scene"
    bucket: EnergyBucket = EnergyBucket.HOLD
    uses_lasers: bool = False

    # --- Schema v2 (Phase 1) ---
    requires: frozenset[str] = frozenset()          # capability tokens, checked against Rig.capabilities()
    min_atmosphere_density: float = 0.0             # checked against Rig.atm (always 0.0 -- no haze exists)
    degrade_to: type["Scene"] | None = None         # one-hop fallback if requires/atm aren't met
    conflicts: frozenset[str] = frozenset()         # look *names* that must not run concurrently (LOOK-06)
    min_hold_bars: int | None = None                # per-look override of the catalog-wide HOLD_BARS
    dark_pct: float = 0.0                           # LIGHTING_BIBLE.md §2.4 negative-space target (not yet enforced -- Stage 13)
    kick_follow: bool = False                       # documents reactivity{} intent; not yet enforced by the base class
    reactivity_note: str = ""                       # the Bible's own reactivity{justification:"..."} habit, for traceability
    color_note: str = ""                            # documents color{} intent (e.g. "blood_red or cold_steel") -- render() still decides the actual RGB

    def render(self, rig: Rig, snap: ShowSnapshot, intensity: float = 1.0) -> Contribution:
        raise NotImplementedError


class SafeDefault(Scene):
    """LIGHTING_BIBLE.md's universal failsafe target (§12, `LOOK-08`): "static
    40% neutral_wash, no mover motion, no laser, no fog. Baseline priority."

    Deliberately NOT part of `ALL_SCENES`/the rotation pool (`scenes/
    library.py`) -- this is a failsafe target the merge layer renders on
    request (Phase 1, `merge/merge.py`'s `finalize()`), not something
    `SceneCatalog.pick()` should ever hand out as a normal rotation choice.
    A single shared instance (`SAFE_DEFAULT` below) is what callers use.
    """

    name = "Safe Default"
    bucket = EnergyBucket.BREAKDOWN  # nominal only -- never selected via pick()
    uses_lasers = False

    def render(self, rig: Rig, snap: ShowSnapshot, intensity: float = 1.0) -> Contribution:
        c = Contribution()
        NEUTRAL_LEVEL = 0.40  # LOOK-08's own number -- a [CONVENTION] default, not measured
        for fx in rig.by_role("wash"):
            if isinstance(fx, (Par, WashBar)):
                fx.set_intensity(c, NEUTRAL_LEVEL * intensity)
                fx.set_color(c, 1.0, 1.0, 1.0)  # neutral_wash: no color bias
        # No mover motion, no laser -- deliberately untouched (stay at boot/last position).
        return c


SAFE_DEFAULT = SafeDefault()


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
