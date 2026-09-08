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
from ..fixtures.profiles import Laser

# Band -> hue (0..1). Data, so a warm->cool ramp could be A/B'd later (docs/08 §1).
HUE_LOW = 0.0    # red
HUE_MID = 0.83   # magenta / pink
HUE_HIGH = 0.5   # cyan


def band_levels(snap: ShowSnapshot) -> tuple[float, float, float]:
    """Band dominance (low, mid, high) driving hue.

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


def two_axis_color(snap: ShowSnapshot, hue_idx: int | None = None) -> tuple[float, float, float]:
    """Return an RGB (each 0.0-1.0) from the snapshot's energy + band dominance.

    `hue_idx` (LIGHTING_BIBLE.md §3.8, 2026-09-08 audit): pass a frozen
    hue-anchor band index (0=low, 1=mid, 2=high) to keep HUE fixed while
    saturation/brightness keep reacting live — "choose hue on phrase
    boundaries only... hue frozen for the whole phrase; only saturation and
    distribution move within it," to eliminate frame-to-frame hue churn as
    the dominant band flickers during normal audio variation. `None` (the
    default) keeps the original continuous-hue behavior unchanged, for
    callers that haven't adopted phrase-frozen hue yet (e.g. individual
    scenes) — see `ReactiveLayerEngine` for the one caller that has.
    """
    low, mid, high = band_levels(snap)
    bands = (low, mid, high)
    hi = max(bands)
    if hi <= 0.0 or snap.energy <= 0.0:
        return (0.0, 0.0, 0.0)
    lo = min(bands)

    idx = bands.index(hi) if hue_idx is None else hue_idx
    hue = (HUE_LOW, HUE_MID, HUE_HIGH)[idx]

    # Saturation from how dominant the biggest band is over the smallest --
    # overall spread, deliberately independent of which band idx anchors the
    # hue. (An anchor-relative formula was tried and rejected: it collapsed
    # to white the instant the true dominant band shifted away from a frozen
    # hue's own band, which defeats the point of freezing hue in the first
    # place -- saturation should keep tracking real audio "peakiness," not
    # whether the frozen pick still happens to be the current max.)
    saturation = 1.0 - (lo / hi)

    value = max(0.0, min(1.0, snap.energy))
    return hsv_to_rgb(hue, saturation, value)


# Below-which a "dominant" band isn't dominant enough to earn a saturated
# color -- balanced/full-spectrum reads as white, same desaturation idea as
# two_axis_color's saturation term above, just discretized for the laser's
# fixed color macros (docs/14 §3, 2026-09-06).
LASER_COLOR_SATURATION_FLOOR = 0.15


def laser_color_for_bands(snap: ShowSnapshot) -> int:
    """Pick one of the laser's CH12 color macros from real frequency content —
    "frequency maps to color," same principle as two_axis_color, just snapped
    to the laser's small set of discrete named colors instead of a continuous
    RGB blend. Dominant band -> the SAME hue convention as two_axis_color
    (low->red, mid->purple/magenta, high->cyan); bands too close together
    (no clear dominant one) -> white, matching two_axis_color's own
    desaturate-toward-white behavior for a balanced/full-spectrum moment.
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
