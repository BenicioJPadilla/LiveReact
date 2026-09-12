"""The starter scene catalog — 8 scenes across breakdown/build/drop/hold.

Adapted from docs/08 §3. Colors follow the two-axis rule (energy->brightness,
band->hue) except where a scene deliberately sets a mood color (e.g. the deep-blue
breakdown). Lasers appear only in DROP scenes (docs/08 §5), using the one
hardware-verified pattern (`Laser.set_dotted_line_sweep`, docs/14 §3,
2026-09-06) with its color and sweep speed driven by real audio (frequency ->
color, intensity -> sweep speed) — same "translate the audio directly"
principle as wash/par, not a scene-picked static look.
"""

from __future__ import annotations

import math

from ..color import hsv_to_rgb
from ..dynamics import beat_pulse, musical_bar_position
from ..core.show_state import ShowSnapshot
from ..engines.color import laser_color_for_bands, two_axis_color
from ..fixtures.profiles import Par, WashBar
from ..fixtures.rig import Rig
from ..merge.merge import Contribution
from .base import EnergyBucket, Scene, paint_spots, paint_wash


# --- breakdown / low energy (lasers OFF, strobe OFF) -----------------------

class DeepWashBreathe(Scene):
    """Whole room one deep saturated color; MHs dim, tilted up.

    NOTE (2026-09-02, docs/14 §5): the wash no longer "breathes" — wash
    intensity is now owned exclusively by the Reactive layer's beat pulse
    (see paint_wash's docstring), so this scene only sets color/mood now.
    Renaming/redesigning is a separate future call, not made yet.
    """

    name = "Deep Wash Breathe"
    bucket = EnergyBucket.BREAK

    def render(self, rig: Rig, snap: ShowSnapshot, intensity: float = 1.0) -> Contribution:
        c = Contribution()
        r, g, b = 0.1, 0.1, 0.9  # deep blue
        paint_wash(c, rig, r, g, b)
        paint_spots(c, rig, r, g, b, 0.12 * intensity)
        for fx in rig.by_role("spot"):
            fx.set_position(c, 0.5, 0.85)  # tilted up
        return c


class SlowColorCycleAmbient(Scene):
    """Soft full-rig wash whose hue drifts one step per bar; never hits white."""

    name = "Slow Color Cycle"
    bucket = EnergyBucket.BREAK

    def render(self, rig: Rig, snap: ShowSnapshot, intensity: float = 1.0) -> Contribution:
        c = Contribution()
        hue = (snap.bar * 0.1) % 1.0
        r, g, b = hsv_to_rgb(hue, 0.8, 1.0)
        paint_wash(c, rig, r, g, b)
        paint_spots(c, rig, r, g, b, 0.15 * intensity)
        return c


# --- build / rising energy (lasers OFF; strobe ramps, capped elsewhere) -----

class RisingTide(Scene):
    """Wash ramps with energy, warming toward white; MH movement climbing."""

    name = "Rising Tide"
    bucket = EnergyBucket.BUILD

    def render(self, rig: Rig, snap: ShowSnapshot, intensity: float = 1.0) -> Contribution:
        c = Contribution()
        r, g, b = two_axis_color(snap.replace(energy=1.0))  # hue from bands, full value
        # Desaturate toward white as energy climbs.
        warm = snap.energy
        r = r + (1 - r) * warm
        g = g + (1 - g) * warm
        b = b + (1 - b) * warm
        paint_wash(c, rig, r, g, b)
        paint_spots(c, rig, r, g, b, (0.5 + 0.5 * snap.energy) * intensity)
        pos = musical_bar_position(snap)
        for fx in rig.by_role("spot"):
            mirror = 1.0 if fx.side == "left" else -1.0
            fx.set_position(c, 0.5 + 0.3 * math.sin(pos * 1.5) * mirror, 0.5)
        return c


class Converge(Scene):
    """Spot fixtures pan from spread positions toward center as the build rises.

    GENERALIZED for any spot-fixture count (was hardcoded to exactly 2,
    side=="left"/else — broken on a 1-fixture rig, since it always took the
    same branch and the "converge from the other side" half never happened).
    With 2+ moving heads, they spread evenly outward and close in toward one
    point — same math as before for exactly 2 (verified: reduces to the
    original 0.15/0.85 spread). With exactly 1 (nothing to converge WITH),
    the same "spread/searching -> locked/still" arc is expressed instead as
    a sweep whose amplitude narrows to stillness at center — same emotional
    shape, no special hardware needed to make it read as intentional.
    """

    name = "Converge"
    bucket = EnergyBucket.BUILD

    def render(self, rig: Rig, snap: ShowSnapshot, intensity: float = 1.0) -> Contribution:
        c = Contribution()
        r, g, b = two_axis_color(snap.replace(energy=1.0))
        paint_wash(c, rig, r, g, b)
        paint_spots(c, rig, 1.0, 1.0, 1.0, (0.5 + 0.5 * snap.energy) * intensity)
        prog = max(0.0, min(1.0, snap.energy))
        spots = rig.by_role("spot")
        n = len(spots)
        if n == 1:
            pos = musical_bar_position(snap)
            amplitude = 0.35 * (1.0 - prog)  # wide search -> still, as prog rises
            pan = 0.5 + amplitude * math.sin(pos)
            spots[0].set_position(c, pan, 0.45)
        else:
            for i, fx in enumerate(spots):
                spread = (i / (n - 1)) - 0.5   # -0.5 .. +0.5, evenly across all spots
                outward = 0.5 + spread * 0.7
                pan = outward + (0.5 - outward) * prog
                fx.set_position(c, pan, 0.45)
        return c


# --- drop / peak energy (lasers MAY enable; strobe within cap) ---------------

class FullSpectrumHit(Scene):
    """Everything full; white punch on each kick, returns to band hue between;
    big fast MH moves; lasers on."""

    name = "Full Spectrum Hit"
    bucket = EnergyBucket.DROP
    uses_lasers = True

    def render(self, rig: Rig, snap: ShowSnapshot, intensity: float = 1.0) -> Contribution:
        c = Contribution()
        pulse = beat_pulse(snap)
        r, g, b = two_axis_color(snap.replace(energy=1.0))
        # White punch on the beat: lerp toward white by the pulse.
        r = r + (1 - r) * pulse
        g = g + (1 - g) * pulse
        b = b + (1 - b) * pulse
        paint_wash(c, rig, r, g, b)
        paint_spots(c, rig, r, g, b, intensity)
        pos = musical_bar_position(snap)
        for fx in rig.by_role("spot"):
            mirror = 1.0 if fx.side == "left" else -1.0
            fx.set_position(c, 0.5 + 0.45 * math.sin(pos * 4.0) * mirror, 0.4 + 0.2 * math.sin(pos * 2.0))
        for fx in rig.by_role("laser"):
            fx.set_dotted_line_sweep(c, color=laser_color_for_bands(snap), sweep_intensity=snap.energy)
        return c


class BeamFanLaserTunnel(Scene):
    """MHs in a symmetric mirror pan-fan on the beat; lasers static; wash low so
    the beams read."""

    name = "Beam Fan + Laser Tunnel"
    bucket = EnergyBucket.DROP
    uses_lasers = True

    def render(self, rig: Rig, snap: ShowSnapshot, intensity: float = 1.0) -> Contribution:
        c = Contribution()
        r, g, b = two_axis_color(snap.replace(energy=1.0))
        paint_wash(c, rig, r, g, b)
        paint_spots(c, rig, 1.0, 1.0, 1.0, intensity)
        pos = musical_bar_position(snap)
        for fx in rig.by_role("spot"):
            mirror = 1.0 if fx.side == "left" else -1.0
            fx.set_position(c, 0.5 + 0.3 * math.sin(pos * 2.0) * mirror, 0.5)
        for fx in rig.by_role("laser"):
            fx.set_dotted_line_sweep(c, color=laser_color_for_bands(snap), sweep_intensity=snap.energy)
        return c


# LIGHTING_BIBLE.md §5's `color{blood_red or cold_steel, unison}` for
# drop_blackout_hit -- Bible-integration Phase 5. Two fixed palettes,
# alternated by `drop_cycle` (not audio) so the choice is genuinely STATIC
# per drop (matching "reactivity: static all, nothing reacts") while still
# giving real color VARIETY across multiple drops in one set (Josh,
# 2026-09-09: "the drop doesn't have to be white... whatever the logic
# says") -- not a fixed literal, not audio-chased either.
BLOOD_RED = (0.85, 0.05, 0.02)
COLD_STEEL = (0.55, 0.70, 0.85)


class DropBlackoutHit(Scene):
    """LIGHTING_BIBLE.md §5: "the pre-drop blackout then full hit; the
    signature tech-house move." Fully static once rendered -- no beat-pulse,
    no continuous hue, no movement -- "the cut IS the effect; nothing
    reacts." The actual pre-drop blackout itself is a separate, cross-
    cutting mechanism (merge/merge.py's `drop_pending`/`build_to_drop_
    bridge`, Phase 5) that runs regardless of which scene is active; this
    class is just the static look the cut resolves TO."""

    name = "Drop Blackout Hit"
    bucket = EnergyBucket.DROP
    conflicts = frozenset({
        "Rising Tide", "Converge", "Pulse & Drift Sustain", "Locked Hold", "Build Riser Wash",
    })  # "conflicts[all build looks]"
    min_hold_bars = 8
    dark_pct = 0.10
    reactivity_note = "static all, kick_follow:false -- the cut IS the effect; nothing reacts"
    color_note = "blood_red or cold_steel, unison -- alternated by drop_cycle, not audio"

    def render(self, rig: Rig, snap: ShowSnapshot, intensity: float = 1.0) -> Contribution:
        c = Contribution()
        r, g, b = BLOOD_RED if snap.drop_cycle % 2 == 0 else COLD_STEEL
        paint_wash(c, rig, r, g, b)
        paint_spots(c, rig, r, g, b, intensity)
        for fx in rig.by_role("spot"):
            fx.set_position(c, 0.5, 0.5)  # static -- no sweep, no drift
        return c


class DropStrobeStab(Scene):
    """LIGHTING_BIBLE.md §5: "native-strobe stabs on drop accents... uses
    native strobe channel, never dimmer toggling." The actual strobe stab
    itself is already produced by ReactiveLayerEngine's own strobe channel
    (engines/reactive.py's `_strobe_rate`/`_strobe_burst_gate`, SAFE-01..06-
    capped) -- a SEPARATE physical DMX channel from color/dimmer, written
    every tick regardless of which Phrase scene is active. This look's job
    is just the color/movement CONTEXT the stab plays over: a bright,
    static-ish accent look, deliberately simple so it doesn't compete with
    the strobe channel for visual attention."""

    name = "Drop Strobe Stab"
    bucket = EnergyBucket.DROP
    min_hold_bars = 8
    dark_pct = 0.20
    reactivity_note = "audio:[strobe gated to drop-accent bars only] -- via the Reactive layer's own strobe channel, not this scene"

    def render(self, rig: Rig, snap: ShowSnapshot, intensity: float = 1.0) -> Contribution:
        c = Contribution()
        r, g, b = 1.0, 1.0, 1.0  # bright white accent -- lets the strobe channel itself read as the "stab"
        paint_wash(c, rig, r, g, b)
        paint_spots(c, rig, r, g, b, intensity)
        for fx in rig.by_role("spot"):
            fx.set_position(c, 0.5, 0.5)
        return c


class BuildRiserWash(Scene):
    """LIGHTING_BIBLE.md §5's canonical build: "intensity climbs across the
    build... the ramp IS the build." The actual dimmer ramp is already
    produced by ReactiveLayerEngine's own `_bucket_wash_level` BUILD branch
    (bar-position-driven, LOOK-04, confirmed correct) -- wash intensity is
    deliberately not set here at all (see `paint_wash`'s own docstring).
    This look's job is the color: `two_axis_color`, same mechanism as the
    other BUILD scenes. NOT fully implementing "static:[hue]" here -- a
    truly frozen-per-phrase hue for an individual Phrase scene (as opposed
    to the Reactive layer's own already-frozen hue) would need real
    per-scene state tracking, disclosed as a known gap rather than faked."""

    name = "Build Riser Wash"
    bucket = EnergyBucket.BUILD
    reactivity_note = "audio:[wash.dimmer tied to bar-count envelope] (via ReactiveLayerEngine, not this scene), static:[hue] -- NOT fully implemented, see class docstring"

    def render(self, rig: Rig, snap: ShowSnapshot, intensity: float = 1.0) -> Contribution:
        c = Contribution()
        r, g, b = two_axis_color(snap.replace(energy=1.0))
        paint_wash(c, rig, r, g, b)
        paint_spots(c, rig, r, g, b, 0.5 * intensity)
        return c


# --- peak (post-drop escalation, LIGHTING_BIBLE.md's genuinely new state,
# reached only via a sustained DROP -- see EnergyBucket's own docstring,
# scenes/base.py) ------------------------------------------------------------

class PeakFullRig(Scene):
    """LIGHTING_BIBLE.md §5: "everything committed" -- full-intensity spots,
    a slow synchronized fan, static hue+pan (not beat-reactive). Wash
    intensity is deliberately not set here (Reactive already holds PEAK at
    `drop_hit_intensity + PEAK_BOOST`, see engines/reactive.py)."""

    name = "Peak Full Rig"
    bucket = EnergyBucket.PEAK
    reactivity_note = "static hue+pan, kick_follow:false -- hue NOT fully frozen here, see class docstring (same disclosed gap as BuildRiserWash)"

    def render(self, rig: Rig, snap: ShowSnapshot, intensity: float = 1.0) -> Contribution:
        c = Contribution()
        r, g, b = two_axis_color(snap.replace(energy=1.0))
        paint_wash(c, rig, r, g, b)
        paint_spots(c, rig, r, g, b, intensity)  # "spot 100%"
        pos = musical_bar_position(snap)
        for fx in rig.by_role("spot"):
            mirror = 1.0 if fx.side == "left" else -1.0
            # "slow fan, period_bars 4" -- a full cycle every 4 bars, much
            # slower than DROP scenes' fast sweeps (period_bars ~0.5-1).
            fx.set_position(c, 0.5 + 0.3 * math.sin(pos * (2 * math.pi / 4.0)) * mirror, 0.5)
        return c


class PeakColorPulseClear(Scene):
    """LIGHTING_BIBLE.md §5: "bar-synced color pulse, no beams" -- a real
    per-bar emphasis pulse, distinct from Reactive's own steady PEAK hold.

    Deliberately overrides wash intensity itself (unlike every other scene
    in this catalog, which leaves that to ReactiveLayerEngine per paint_
    wash's own docstring) -- the Bible is explicit this look's reactivity IS
    "wash.dimmer on bar downbeat only, 1/bar," not a continuous ambient
    level, so it doesn't repeat the old kick-follow-vs-ambient fight (that
    was two DIFFERENT signals both chasing the SAME channel every tick; this
    is one slow, quantized pulse). DIMMER is HTP (max), so this pulse only
    becomes visible when it exceeds Reactive's own PEAK hold -- VERIFIED
    (not just theorized) across the realistic `drop_hit_intensity` range:
    at 0.85-0.90 the pulse genuinely shows (255 on-beat vs. 192-217
    off-beat), only disappearing once the hit itself is already ~0.97+
    (both sides already maxed -- a benign edge case, not a defect)."""

    name = "Peak Color Pulse Clear"
    bucket = EnergyBucket.PEAK
    reactivity_note = "audio:[wash.dimmer on bar downbeat only, 1/bar], kick_follow:false"

    def render(self, rig: Rig, snap: ShowSnapshot, intensity: float = 1.0) -> Contribution:
        c = Contribution()
        r, g, b = two_axis_color(snap.replace(energy=1.0))
        # "on bar downbeat only" -- a short pulse right at beat 1, decaying
        # across the rest of the bar, same shape as beat_pulse but gated to
        # only the bar's first beat instead of every beat.
        on_downbeat = snap.beat_in_bar == 1
        pulse = (1.0 - snap.beat_phase) if on_downbeat else 0.0
        for fx in rig.by_role("wash"):
            if isinstance(fx, (Par, WashBar)):
                fx.set_intensity(c, pulse * intensity)
                fx.set_color(c, r, g, b)
        paint_spots(c, rig, r, g, b, 0.5 * intensity)
        return c


class PeakAltHitsClear(Scene):
    """LIGHTING_BIBLE.md §5: "two spots alternate snap-hits to position, no
    beams." `scaling{2:alternate L/R snap each bar}` -- generalized for this
    rig's single spot fixture the same way Converge was (MOVE-12): with
    nothing to alternate WITH, the one fixture itself snaps between two
    positions every bar, matching the "alternate, don't sweep" shape
    (`snap_alternate`, no interpolation) rather than Converge's continuous
    search."""

    name = "Peak Alt Hits Clear"
    bucket = EnergyBucket.PEAK
    dark_pct = 0.25
    reactivity_note = "static all -- snap_alternate is bar-quantized, not audio-driven"

    def render(self, rig: Rig, snap: ShowSnapshot, intensity: float = 1.0) -> Contribution:
        c = Contribution()
        r, g, b = 1.0, 1.0, 1.0
        paint_wash(c, rig, r, g, b)
        paint_spots(c, rig, r, g, b, intensity)
        spots = rig.by_role("spot")
        n = len(spots)
        for i, fx in enumerate(spots):
            # 2+ fixtures: alternate WHICH ONE is at the "hit" position each
            # bar. Exactly 1: the single fixture itself snaps between two
            # positions each bar (n==1 makes i%2 always 0, so fold the bar
            # parity in directly instead).
            parity = (int(snap.bar) + (0 if n == 1 else i)) % 2
            fx.set_position(c, 0.3 if parity == 0 else 0.7, 0.5)
        return c


# --- break family, Bible-integration Phase 5, third wave (docs/bible_
# integration/LOOK_CATALOG.md's unnumbered break_* looks, §5 lines 743-761 +
# 859-861) -- built after DROP/BUILD/PEAK per the plan's stated wave order.
# Reuses BLOOD_RED/COLD_STEEL's named-palette pattern (DEEP_BLUE, defined
# alongside them above) and the same disclosed-gap habit as BuildRiserWash/
# PeakFullRig for anything the Bible doesn't fully specify for a given look.

DEEP_BLUE = (0.1, 0.1, 0.9)  # matches DeepWashBreathe's existing inline "deep blue" literal -- named here for reuse, not a new color choice


class BreakLowWash(Scene):
    """LIGHTING_BIBLE.md §5: the default break -- "wash 15-35%, cold_steel...
    only a slow envelope earns reactivity... hue static to avoid churn... a
    break has no transients to chase."

    Wash intensity is deliberately NOT set here (same pattern as
    BuildRiserWash/PeakColorPulseClear) -- the 15-35% breathing envelope is
    already produced by ReactiveLayerEngine's own BREAK branch
    (`_bucket_wash_level`'s low-pass `_break_breath` envelope; name and
    range match this exact look). This class's job is only the color: a
    fixed cold_steel (shared constant with DropBlackoutHit's alternate drop
    color), never audio-band-driven -- "static:[hue]" per the Bible's own
    reactivity block."""

    name = "Break Low Wash"
    bucket = EnergyBucket.BREAK
    dark_pct = 0.60
    min_hold_bars = 16
    # peak_strobe_blackout isn't built yet (PEAK-family backlog) -- declared
    # here anyway per the Bible's conflicts[] pairing; harmless forward
    # reference, matches nothing until that scene exists, same bidirectional
    # conflict check SceneCatalog._conflicts already does for every pair.
    conflicts = frozenset({"Peak Strobe Blackout"})
    reactivity_note = "audio:[wash.dimmer, soft RMS breathing] (via ReactiveLayerEngine, not this scene), static:[hue], kick_follow:false"
    color_note = "cold_steel"

    def render(self, rig: Rig, snap: ShowSnapshot, intensity: float = 1.0) -> Contribution:
        c = Contribution()
        r, g, b = COLD_STEEL
        paint_wash(c, rig, r, g, b)
        paint_spots(c, rig, r, g, b, 0.25 * intensity)  # dim ambient presence -- not the focal point of a break
        return c


class BreakSingleSpotSpecial(Scene):
    """LIGHTING_BIBLE.md §5: a single narrow spot special -- "spot 40-70%,
    position dj_booth," fully static, degrading to break_low_wash if the
    rig lacks a spot/pan_tilt capability.

    GAP, disclosed not faked: there is no "named position" mechanism
    anywhere in this codebase (only raw pan01/tilt01 -- same absence noted
    in docs/bible_integration/LOOK_CATALOG.md itself). `position dj_booth`
    is expressed here as a literal hardcoded pan/tilt guess, NOT measured
    against Josh's actual rig/DJ-booth geometry (same disclosed-placeholder
    status as the MH slew-rate constants in fixtures/profiles.py) -- re-aim
    once the real booth position relative to the rig is known."""

    name = "Break Single Spot Special"
    bucket = EnergyBucket.BREAK
    degrade_to = BreakLowWash
    dark_pct = 0.80
    min_hold_bars = 16
    reactivity_note = "static all, kick_follow:false"
    color_note = "not specified by the Bible for this look -- reuses cold_steel for family consistency with break_low_wash"

    SPOT_LEVEL = 0.55  # mid of the Bible's stated 40-70% range, not itself tuned by ear

    def render(self, rig: Rig, snap: ShowSnapshot, intensity: float = 1.0) -> Contribution:
        c = Contribution()
        r, g, b = COLD_STEEL
        paint_wash(c, rig, r, g, b)
        paint_spots(c, rig, r, g, b, self.SPOT_LEVEL * intensity)
        for fx in rig.by_role("spot"):
            fx.set_position(c, 0.5, 0.70)  # dj_booth guess: centered, angled down -- see class docstring
        return c


class BreakCeilingDrift(Scene):
    """LIGHTING_BIBLE.md §5 (techhouse): "slow ceiling-bounce tilt drift" --
    `movement{tilt_drift, sine, period_bars 8, tilt_amp 15%}`. Same sine
    approach as PeakFullRig's pan fan, just on the TILT axis, slower
    (period_bars 8 vs. 4), smaller (15% vs. 30%), and NOT mirrored L/R --
    a synchronized drift reads calmer than a fan/spread, matching "drift"
    rather than "fan" in the Bible's own wording. That sync-vs-mirror choice
    isn't itself a stated Bible detail -- disclosed as an interpretation,
    not a measured fact."""

    name = "Break Ceiling Drift"
    bucket = EnergyBucket.BREAK
    dark_pct = 0.50
    min_hold_bars = 16
    reactivity_note = "movement only (tilt_drift); no reactivity{} block given by the Bible for this look"
    color_note = "not specified by the Bible for this look -- reuses cold_steel for family consistency"

    PERIOD_BARS = 8.0
    TILT_AMP = 0.15

    def render(self, rig: Rig, snap: ShowSnapshot, intensity: float = 1.0) -> Contribution:
        c = Contribution()
        r, g, b = COLD_STEEL
        paint_wash(c, rig, r, g, b)
        paint_spots(c, rig, r, g, b, 0.30 * intensity)
        pos = musical_bar_position(snap)
        tilt = 0.5 + self.TILT_AMP * math.sin(pos * (2 * math.pi / self.PERIOD_BARS))
        for fx in rig.by_role("spot"):
            fx.set_position(c, 0.5, tilt)
        return c


class BreakColorHoldClear(Scene):
    """LIGHTING_BIBLE.md §5: the simplest break look -- "deep_blue," fully
    static. Clear-air variant (atm 0.0). Same static-position pattern as
    DropBlackoutHit (no sweep, no drift -- the look itself is the effect)."""

    name = "Break Color Hold Clear"
    bucket = EnergyBucket.BREAK
    dark_pct = 0.50
    min_hold_bars = 16
    reactivity_note = "static all -- \"fully static,\" no reactivity{} block given by the Bible for this look"
    color_note = "deep_blue"

    def render(self, rig: Rig, snap: ShowSnapshot, intensity: float = 1.0) -> Contribution:
        c = Contribution()
        r, g, b = DEEP_BLUE
        paint_wash(c, rig, r, g, b)
        paint_spots(c, rig, r, g, b, 0.30 * intensity)
        for fx in rig.by_role("spot"):
            fx.set_position(c, 0.5, 0.5)  # static -- no sweep, no drift
        return c


# --- outro family, Bible-integration Phase 5, fourth wave (docs/bible_
# integration/LOOK_CATALOG.md §5, lines 837-842) -- OUTRO was, until now, a
# genuinely new state with zero scenes (same starting point PEAK was in
# before its own wave -- see EnergyBucket's own docstring/the old "assert
# not cat.bucket(EnergyBucket.OUTRO)" test this wave removes).

WARM_WHITE = (1.0, 0.85, 0.65)
DEEP_AMBER = (0.85, 0.45, 0.05)


class OutroFadeWash(Scene):
    """LIGHTING_BIBLE.md §5: "the set winding down -- wash fades 40% to 15%
    over the outro." Wash intensity is deliberately NOT set here (same
    pattern as BreakLowWash/BuildRiserWash/PeakColorPulseClear) -- the
    40->15% descending fade is already produced by ReactiveLayerEngine's own
    OUTRO branch (`_bucket_wash_level`'s `OUTRO_HIGH`/`OUTRO_LOW`/
    `OUTRO_FADE_BARS`, confirmed by name/range/direction match against this
    exact look). This class's job is only the color.

    color{warm_white or deep_amber} -- the Bible offers either; unlike
    DropBlackoutHit's blood_red/cold_steel (a deliberate Josh-directed
    alternation-by-drop_cycle design call), there's no equivalent signal or
    steer for OUTRO, so this fixes on warm_white as a single default rather
    than inventing an alternation rule with nothing to key it off. DEEP_AMBER
    is still defined and named here (not used) as the Bible's other named
    option, should a real reason to pick it later come up."""

    name = "Outro Fade Wash"
    bucket = EnergyBucket.OUTRO
    dark_pct = 0.60
    min_hold_bars = 16
    reactivity_note = "audio:[wash.dimmer descending 40%->15% envelope] (via ReactiveLayerEngine, not this scene), static:[hue]"
    color_note = "warm_white or deep_amber -- warm_white chosen as the fixed default, see class docstring"

    def render(self, rig: Rig, snap: ShowSnapshot, intensity: float = 1.0) -> Contribution:
        c = Contribution()
        r, g, b = WARM_WHITE
        paint_wash(c, rig, r, g, b)
        paint_spots(c, rig, r, g, b, 0.30 * intensity)
        return c


class OutroSingleBeam(Scene):
    """LIGHTING_BIBLE.md §5: "the set's very last light -- one spot,
    ceiling_bounce, dim." `requires{spot, atm 0.0}` names only a spot, no
    wash -- unlike every other scene in this file (which paints wash
    regardless of what the look's own roles{} block mentions, e.g.
    PeakColorPulseClear/BuildRiserWash still touch spots even though their
    roles only name wash), this one deliberately does NOT paint the wash at
    all: the whole point of a single last beam is everything else already
    dark (`dark 80%`), so lighting the wash here would fight the look's own
    intent rather than just being redundant.

    "one spot" is also taken literally, not "all spot fixtures" -- if a
    future rig ever has 2+ spots, only the first is lit; this codebase's
    only spot fixture today (`mh_l`) makes that indistinguishable from
    "the spot," but the distinction is real and worth keeping explicit
    (same discipline as Converge/PeakAltHitsClear's N-fixture handling).

    GAP, disclosed not faked: "ceiling_bounce" is another named-position
    case with no mechanism in this codebase (same absence as
    BreakSingleSpotSpecial's `dj_booth`) -- expressed as a literal tilt
    value reusing this codebase's own existing "tilted up" convention
    (DeepWashBreathe's `0.85`), not measured against real ceiling geometry."""

    name = "Outro Single Beam"
    bucket = EnergyBucket.OUTRO
    dark_pct = 0.80
    min_hold_bars = 16
    reactivity_note = "static all -- no reactivity{} block given by the Bible for this look"
    color_note = "not specified by the Bible for this look -- reuses warm_white for family consistency with Outro Fade Wash"

    DIM_LEVEL = 0.25  # "dim" -- an unmeasured pick, same magnitude as BREAK family's ambient levels

    def render(self, rig: Rig, snap: ShowSnapshot, intensity: float = 1.0) -> Contribution:
        c = Contribution()
        r, g, b = WARM_WHITE
        spots = rig.by_role("spot")[:1]  # "one spot," literally -- see class docstring
        for fx in spots:
            fx.set_intensity(c, self.DIM_LEVEL * intensity)
            fx.set_color(c, r, g, b)
            fx.set_position(c, 0.5, 0.85)  # ceiling_bounce guess: centered, tilted up -- see class docstring
        return c


# --- hold / sustain (loops, post-transition, plateaus) ----------------------

class PulseAndDriftSustain(Scene):
    """Steady mid-energy groove: wash ~65%, slow MH drift, hue holds; no strobe/laser."""

    name = "Pulse & Drift Sustain"
    bucket = EnergyBucket.BUILD  # HOLD removed, Phase 2 -- folded into BUILD's upper tail

    def render(self, rig: Rig, snap: ShowSnapshot, intensity: float = 1.0) -> Contribution:
        c = Contribution()
        r, g, b = two_axis_color(snap.replace(energy=1.0))
        paint_wash(c, rig, r, g, b)
        paint_spots(c, rig, r, g, b, 0.6 * intensity)
        pos = musical_bar_position(snap)
        for fx in rig.by_role("spot"):
            mirror = 1.0 if fx.side == "left" else -1.0
            fx.set_position(c, 0.5 + 0.2 * math.sin(pos * 0.5) * mirror, 0.5)
        return c


class LockedHold(Scene):
    """A calm steady look: single hue, minimal movement. Used during loops and the
    mandatory post-transition hold."""

    name = "Locked Hold"
    bucket = EnergyBucket.BUILD  # HOLD removed, Phase 2 -- folded into BUILD's upper tail

    def render(self, rig: Rig, snap: ShowSnapshot, intensity: float = 1.0) -> Contribution:
        c = Contribution()
        r, g, b = two_axis_color(snap.replace(energy=1.0))
        paint_wash(c, rig, r, g, b)
        paint_spots(c, rig, r, g, b, 0.4 * intensity)
        for fx in rig.by_role("spot"):
            fx.set_position(c, 0.5, 0.5)
        return c


ALL_SCENES: list[type[Scene]] = [
    DeepWashBreathe,
    SlowColorCycleAmbient,
    RisingTide,
    Converge,
    FullSpectrumHit,
    BeamFanLaserTunnel,
    PulseAndDriftSustain,
    LockedHold,
    # Bible-integration Phase 5, first wave -- BUILD/DROP families:
    DropBlackoutHit,
    DropStrobeStab,
    BuildRiserWash,
    # Bible-integration Phase 5, second wave -- PEAK family:
    PeakFullRig,
    PeakColorPulseClear,
    PeakAltHitsClear,
    # Bible-integration Phase 5, third wave -- BREAK family:
    BreakLowWash,
    BreakSingleSpotSpecial,
    BreakCeilingDrift,
    BreakColorHoldClear,
    # Bible-integration Phase 5, fourth wave -- OUTRO family:
    OutroFadeWash,
    OutroSingleBeam,
]
