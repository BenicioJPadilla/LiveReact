"""The two-axis color model (docs/08 §1).

Two *independent* axes, by design:
  - energy  -> brightness / saturation   (perceptually grounded — keep strict)
  - EQ band dominance -> hue             (a consistency convention, NOT neuroscience)

House hue convention (tunable data, not a law): bass->red, mid->magenta/pink,
high->cyan; as the bands balance out (full-spectrum / peak), desaturate toward
white — the perceptually correct "drop" move. We deliberately do not encode any
claim that this hue mapping is how the brain works; its value is consistency.
"""

from __future__ import annotations

from ..color import hsv_to_rgb
from ..core.show_state import ShowSnapshot

# Band -> hue (0..1). Data, so a warm->cool ramp could be A/B'd later (docs/08 §1).
HUE_LOW = 0.0    # red
HUE_MID = 0.83   # magenta / pink
HUE_HIGH = 0.5   # cyan


def band_levels(snap: ShowSnapshot) -> tuple[float, float, float]:
    """EQ (low, mid, high) of the louder deck — the band intent driving hue."""
    if snap.fader_a >= snap.fader_b:
        return snap.eq_low_a, snap.eq_mid_a, snap.eq_high_a
    return snap.eq_low_b, snap.eq_mid_b, snap.eq_high_b


def two_axis_color(snap: ShowSnapshot) -> tuple[float, float, float]:
    """Return an RGB (each 0.0-1.0) from the snapshot's energy + band dominance."""
    low, mid, high = band_levels(snap)
    bands = (low, mid, high)
    hi = max(bands)
    if hi <= 0.0 or snap.energy <= 0.0:
        return (0.0, 0.0, 0.0)

    # Hue from the dominant band.
    idx = bands.index(hi)
    hue = (HUE_LOW, HUE_MID, HUE_HIGH)[idx]

    # Saturation from how *dominant* that band is: one band way up -> saturated
    # hue; all bands balanced -> desaturated toward white.
    lo = min(bands)
    saturation = 1.0 - (lo / hi)

    # Brightness from energy.
    value = max(0.0, min(1.0, snap.energy))
    return hsv_to_rgb(hue, saturation, value)
