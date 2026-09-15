"""Laser layer -- the one authority over the laser's DMX channels.

Built 2026-09-15 from Josh's brief ("it fires after drops, specifically after
more intense drops, and the side-to-side motion of the fanning laser matches
the intensity of the wub or the stab"), replacing `core/laser_trigger.py`'s
one-beat kick-onset flash, which had fired 21 invisible times in one session
and zero visible times ever. What changed, and why:

WHEN it is on -- the whole DROP/PEAK stay, once the drop has proven itself:
  - bucket is PEAK (the metronome's escalation of a drop that sustained past
    its 8-bar dwell -- "intense" by construction), or
  - bucket is DROP and `snap.drop_hit_intensity >= LASER_MIN_HIT_INTENSITY`
    (the hit was loud enough on its own to earn the laser from the first
    tick). Measured on every 2026-09-15 capture: a track's first drop
    captured 1.0, its second 0.92-0.94 (judged against a ceiling the first
    drop already raised), and every one escalated to PEAK ~15 s in. So at
    the 0.95 threshold a first drop gets the laser on the hit, a second
    drop gets it once it has held for a phrase -- "after more intense
    drops," with the drop's own persistence as the second vote.
  This deliberately supersedes LIGHTING_BIBLE.md §8.5's "punctuation"
  numbers (<=10% of set time, >=2 phrases apart, one-beat moments): the
  correction pass retagged those `[NOT FOUND]` (no sourced figure exists),
  and Josh chose a sustained pattern through the intense part of the drop.
  "Drops and peaks only" -- the one supported part of §8.5 -- still holds.
  LASER-12's fail-closed rule holds too: no fresh audio or no fresh PDL
  means off, immediately, never a held value.

WHAT it shows -- `Laser.set_dotted_line_sweep`, the one hardware-verified
  pattern (2026-09-06: flattened line, dotted outline, horizontal sweep).
  Josh: "for right now I just want the fanning motion; more shapes for
  different sounds later."

HOW it moves -- CH7 sweep speed follows a "wub" envelope: the low band's
  excess over its own slow baseline, fast attack / slower release. This is
  the 2026-09-03 pass-2 kick/bass follower (baseline-excess isolates a
  transient from the sustained bassline under it; constants were
  calibrated then against a real capture, see `WUB_*` below) re-applied to
  a SPEED rather than an on/off decision -- the fragility that retired it
  as a brightness driver (a few ms of timing wobble flipping lit/dark)
  doesn't apply to a continuous speed value that only ever modulates an
  already-running sweep. Between wubs the sweep sits at the fixture's
  slowest confirmed speed (CH7=128), never stops.

COLOR -- the phrase-frozen palette entry (`snap.palette`), snapped to the
  nearest CH12 macro, so the laser matches the wash instead of re-picking
  from the audio bands per tick (the same per-tick-hue flicker that was
  measured on the wash and retired on 2026-09-15).

Safety is NOT here: `Laser.apply_safety` (arm switch + LASER-09 geometry, or
the operator's `--testing` mode) and `apply_laser_gate` run in
merge/merge.py's finalize() on every frame regardless of what this layer
writes.
"""

from __future__ import annotations

import math

from ..clock import Clock
from ..core.show_state import ShowSnapshot
from ..fixtures.profiles import Laser
from ..fixtures.rig import Rig
from ..merge.merge import Contribution
from ..scenes.base import EnergyBucket

# The hit must land in the top quarter of core/metronome.py's
# DROP_INTENSITY_FLOOR..CEIL range (0.85..1.0) to get the laser on the hit
# itself; anything below waits for the PEAK escalation. See the module
# docstring for the measured values this was set against.
LASER_MIN_HIT_INTENSITY = 0.95

# Wub/stab envelope on `audio_band_low_abs`. Baseline-excess constants are
# the 2026-09-03 calibration (real 60 s capture: excess p10=2.09, p50=3.28,
# p90=4.23 -> gain set so p90 lands near 1.0); attack/release are
# inputs/audio.py's own VU-style pair, so the sweep can follow a 2-8 Hz wub.
WUB_BASELINE_TAU_S = 1.2   # slow: several beats, so one wub can't drag the baseline up
WUB_BASELINE_FLOOR = 0.05  # keeps the ratio sane during real digital silence
WUB_ATTACK_S = 0.015
WUB_RELEASE_S = 0.18
WUB_GAIN = 0.236

# engines/palette.py names -> Laser.COLOR_* macros (fixtures/profiles.py).
PALETTE_TO_LASER: dict[str, int] = {
    "blood_red": Laser.COLOR_RED,
    "deep_amber": Laser.COLOR_YELLOW,
    "acid_yellow": Laser.COLOR_YELLOW,
    "toxic_green": Laser.COLOR_GREEN,
    "cyan_ice": Laser.COLOR_CYAN,
    "cold_steel": Laser.COLOR_BLUE,
    "deep_blue": Laser.COLOR_BLUE,
    "uv_violet": Laser.COLOR_PURPLE,
    "hot_magenta": Laser.COLOR_PURPLE,
    "warm_white": Laser.COLOR_WHITE,
    "neutral_wash": Laser.COLOR_WHITE,
}


def laser_color_for_palette(name: str) -> int:
    return PALETTE_TO_LASER.get(name, Laser.COLOR_WHITE)


def laser_wanted(snap: ShowSnapshot) -> bool:
    """The musical gate alone (no signal-health check) -- see the module
    docstring's WHEN section."""
    bucket = EnergyBucket(snap.bucket)
    if bucket == EnergyBucket.PEAK:
        return True
    return bucket == EnergyBucket.DROP and snap.drop_hit_intensity >= LASER_MIN_HIT_INTENSITY


class LaserEngine:
    """Stateful (the wub envelope); tick once per ShowEngine frame."""

    # Above Phrase (50): whatever look is up, this layer owns the laser
    # channels (LTP by priority in merge/merge.py). Below Transition (100),
    # which never touches them anyway.
    priority = 60

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self._baseline = 0.0
        self._env = 0.0
        self._last_t: float | None = None
        self.active = False          # exposed for the console/recorder/finalize gate
        self.sweep = 0.0             # this tick's 0..1 sweep-speed intensity
        self.color = Laser.COLOR_WHITE

    @property
    def name(self) -> str:
        return "laser"

    def tick(self, snap: ShowSnapshot, rig: Rig) -> Contribution:
        c = Contribution()
        self.sweep = self._wub_envelope(snap)
        self.color = laser_color_for_palette(snap.palette)
        # LASER-12: any signal loss -> off now, never a held value.
        self.active = snap.audio_fresh and snap.pdl_fresh and laser_wanted(snap)
        if not self.active:
            return c  # untouched channels stay at the boot zeros; finalize zeroes them too
        for fx in rig.by_role("laser"):
            fx.set_dotted_line_sweep(c, color=self.color, sweep_intensity=self.sweep)
        return c

    def _wub_envelope(self, snap: ShowSnapshot) -> float:
        now = self.clock.monotonic()
        dt = (now - self._last_t) if self._last_t is not None else 1 / 60
        self._last_t = now
        if not snap.audio_fresh:
            self._baseline = 0.0
            self._env = 0.0  # a stale reading must not shape the first frames after reconnect
            return 0.0
        raw = snap.audio_band_low_abs
        self._baseline += (1 - math.exp(-dt / WUB_BASELINE_TAU_S)) * (raw - self._baseline)
        excess = max(0.0, raw / max(self._baseline, WUB_BASELINE_FLOOR) - 1.0)
        coeff = 1 - math.exp(-dt / (WUB_ATTACK_S if excess > self._env else WUB_RELEASE_S))
        self._env += coeff * (excess - self._env)
        return max(0.0, min(1.0, self._env * WUB_GAIN))
