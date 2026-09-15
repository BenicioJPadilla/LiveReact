"""Audio-band helpers for the two consumers that still read frequency content
directly: the console's band meters (`band_levels`) and the laser's discrete
color macro (`laser_color_for_bands`).

History: this module used to hold `two_axis_color` -- the continuous
"energy -> brightness, dominant band -> hue" model (docs/08 §1) every scene
called per tick. That was retired on 2026-09-15 (the third live capture
measured 6-10 hue flips per second, "random colors every half beat") in
favor of the phrase-frozen palette in engines/palette.py, and deleted in the
same day's polish pass. Its hue convention (bass -> red, mid -> magenta/
purple, high -> cyan, balanced -> white) survives only in
`laser_color_for_bands` below.
"""

from __future__ import annotations

from ..core.show_state import ShowSnapshot
from ..fixtures.profiles import Laser


def band_levels(snap: ShowSnapshot) -> tuple[float, float, float]:
    """Band dominance (low, mid, high).

    VERIFIED preference order (docs/14): real audio band analysis when fresh —
    it's the actual sound, not a mixer-knob proxy. Falls back to "EQ of the
    louder deck" (the old MIDI-only estimate) when audio isn't available —
    same graceful-degradation pattern as everywhere else in this project.
    """
    if snap.audio_fresh:
        return snap.audio_band_low, snap.audio_band_mid, snap.audio_band_high
    if snap.fader_a >= snap.fader_b:
        return snap.eq_low_a, snap.eq_mid_a, snap.eq_high_a
    return snap.eq_low_b, snap.eq_mid_b, snap.eq_high_b


# Below-which a "dominant" band isn't dominant enough to earn a saturated
# color -- balanced/full-spectrum reads as white, discretized for the laser's
# fixed color macros (docs/14 §3, 2026-09-06).
LASER_COLOR_SATURATION_FLOOR = 0.15


def laser_color_for_bands(snap: ShowSnapshot) -> int:
    """Pick one of the laser's CH12 color macros from real frequency content —
    "frequency maps to color," snapped to the laser's small set of discrete
    named colors. Dominant band -> the house hue convention (low->red,
    mid->purple/magenta, high->cyan); bands too close together (no clear
    dominant one) -> white.
    """
    low, mid, high = band_levels(snap)
    bands = (low, mid, high)
    hi = max(bands)
    if hi <= 0.0:
        return Laser.COLOR_WHITE
    lo = min(bands)
    saturation = 1.0 - (lo / hi)
    if saturation < LASER_COLOR_SATURATION_FLOOR:
        return Laser.COLOR_WHITE
    idx = bands.index(hi)
    return (Laser.COLOR_RED, Laser.COLOR_PURPLE, Laser.COLOR_CYAN)[idx]
