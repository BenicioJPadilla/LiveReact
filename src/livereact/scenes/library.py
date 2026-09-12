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
]
