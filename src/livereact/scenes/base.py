"""Scene base + energy buckets + small painting helpers.

A Scene renders one *look* into a Contribution, scaled by an ``intensity`` weight
(used for crossfading). Scenes address fixtures by role/side and respect the
two-axis color rule. Only DROP scenes touch laser channels (docs/02 FR-3.2,
docs/08 §3).
"""

from __future__ import annotations

from enum import Enum

from ..core.show_state import ShowSnapshot
from ..engines.palette import rgb as palette_rgb
from ..fixtures.profiles import Par, WashBar
from ..fixtures.rig import Rig
from ..merge.merge import Contribution


class EnergyBucket(Enum):
    """LIGHTING_BIBLE.md §9.8's 5-state model (Bible-integration Phase 2,
    2026-09-11 -- /Users/joshuaracimora/.claude/plans/adaptive-squishing-
    pebble.md). Replaces the old 4-state BREAKDOWN/BUILD/HOLD/DROP:
    BREAKDOWN is renamed BREAK (naming match only, same concept); HOLD
    (0.55-0.80 energy, LiveReact's own invention with no Bible equivalent)
    is REMOVED -- its energy range folds into BUILD's upper tail (Phase 2's
    Open Question #1 default: DROP should mean an actual high-energy hit,
    not "energy got moderately high," so the ambiguous middle range keeps
    reading as "still building" rather than "maybe already dropped").
    PEAK and OUTRO are genuinely new and are NOT reachable via a raw energy
    threshold at all -- see core/metronome.py's `_derive_bucket` for how
    they're actually entered (DROP escalates to PEAK on sustained dwell;
    BREAK promotes to OUTRO after a recent DROP/PEAK)."""

    BREAK = "break"
    BUILD = "build"
    DROP = "drop"
    PEAK = "peak"
    OUTRO = "outro"


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
    bucket: EnergyBucket = EnergyBucket.BUILD
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
    bucket = EnergyBucket.BREAK  # nominal only -- never selected via pick()
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


class AllDark(Scene):
    """LIGHTING_BIBLE.md §5's `all_dark`: "reserved darkness / cut. any
    mode... roles all 0... transition snap... min_hold 1 (momentary)."

    Deliberately NOT part of `ALL_SCENES`/the rotation pool -- same
    reasoning as `SafeDefault` above: a "reserved... any mode" cut is
    something an operator or a future console binding calls on request
    (e.g. via `PhraseEngine.force_scene(ALL_DARK)`), not a look
    `SceneCatalog.pick()` should ever hand out on its own. Unlike
    `build_to_drop_bridge` (a similarly cross-cutting Bible cue, but one
    with an explicit stated trigger point -- "the final bar before a drop
    release" -- already wired into `merge/merge.py`'s `finalize()`), the
    Bible gives `all_dark` no trigger condition at all beyond "any mode,"
    so no automatic firing path is wired here either -- disclosed as an
    open question, not fabricated. A single shared instance (`ALL_DARK`
    below) mirrors `SAFE_DEFAULT`'s pattern for callers."""

    name = "All Dark"
    bucket = EnergyBucket.BREAK  # nominal only -- never selected via pick()
    uses_lasers = False
    min_hold_bars = 1  # "momentary"

    def render(self, rig: Rig, snap: ShowSnapshot, intensity: float = 1.0) -> Contribution:
        c = Contribution()
        for fx in rig.by_role("wash"):
            if isinstance(fx, (Par, WashBar)):
                fx.set_intensity(c, 0.0)
        for fx in rig.by_role("spot"):
            fx.set_intensity(c, 0.0)
        # No color, no position, no laser -- "roles all 0" means every
        # intensity channel to zero; nothing else is commanded (same
        # "leave position/laser alone" restraint as SafeDefault above).
        return c


ALL_DARK = AllDark()


# --- painting helpers shared by scenes -------------------------------------

def scene_color(snap: ShowSnapshot) -> tuple[float, float, float]:
    """The wash color for this tick: the snapshot's phrase-frozen palette
    entry (engines/palette.py). Replaces the old per-scene
    `two_axis_color(snap.replace(energy=1.0))`, which re-picked hue from the
    audio bands every tick (measured live 2026-09-15 as 6-10 hue flips per
    second -- "random colors every half beat"). Scenes that want a
    deliberate fixed mood color still just pass their own RGB."""
    return palette_rgb(snap.palette)


def spot_color(snap: ShowSnapshot) -> tuple[float, float, float]:
    """Moving-head color: the palette's spot entry (differs from the wash
    only in BUILD, where the wash is white for the strobe and the heads
    carry the hue)."""
    return palette_rgb(snap.palette_spot)


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
