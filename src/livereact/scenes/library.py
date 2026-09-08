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
    bucket = EnergyBucket.BREAKDOWN

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
    bucket = EnergyBucket.BREAKDOWN

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


# --- hold / sustain (loops, post-transition, plateaus) ----------------------

class PulseAndDriftSustain(Scene):
    """Steady mid-energy groove: wash ~65%, slow MH drift, hue holds; no strobe/laser."""

    name = "Pulse & Drift Sustain"
    bucket = EnergyBucket.HOLD

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
    bucket = EnergyBucket.HOLD

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
]
