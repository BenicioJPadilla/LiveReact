"""Laser layer -- the one authority over the laser's DMX channels.

Built 2026-09-15 from Josh's brief ("it fires after drops, specifically after
more intense drops, and the side-to-side motion of the fanning laser matches
the intensity of the wub or the stab"), replacing `core/laser_trigger.py`'s
one-beat kick-onset flash. Rebuilt 2026-09-16 after the third live run
(recordings/session-20260916-110050): the kick-spike flash version fired
104 times in one track -- every kick in a drop clears a 1.8x spike ratio,
so it ran at the refractory limit through every DROP and PEAK. Josh: "we
should be pretty conservative with the laser... only cued at peak
intensity moments... not firing over and over again." Raising the ratio
does not help (15 ticks in the whole run cleared 2.5x, one cleared 3x,
and those are random loud kicks, not moments).

WHEN it is on -- one SWEEP per LASER_BLOCK_BARS-bar block, and only in PEAK:
  - gate: bucket is PEAK (a drop that has held full energy past its 8-bar
    dwell -- see core/metronome.py's escalation) AND the drop's held
    `drop_hit_intensity` is at least LASER_MIN_HIT_INTENSITY. Plain DROP
    never fires: the strobe owns the hit, the laser owns the peak.
  - trigger: the first bar of every LASER_BLOCK_BARS-bar block counted
    from the phrase origin (`snap.drop_start_bar`, the same origin the
    phrase-tail strobe burst uses in engines/reactive.py). The first block
    boundary is the PEAK escalation itself when the escalation lands on
    one (it does when the DROP dwell is exactly 8 bars). A 16-bar peak
    gets two sweeps; the third live run would have had ~4 instead of 104.
  - each sweep lasts LASER_SWEEP_BARS -- long enough for the fan to
    actually travel (Josh: "I want the dots to sweep so it's a fan," not
    "the dots just go out"), short enough to stay punctuation.
  LASER-12's fail-closed rule holds: no fresh audio or no fresh PDL means
  off, immediately, and any open sweep closes.

"Only certain songs" (Josh, same run) is NOT decided here and cannot be:
energy_norm re-normalizes over ~90 s, so every track's biggest drop reads
1.0 eventually, and drop_hit_intensity measures the hit's rise, not "is
this the big tune of the set." That call is the operator's: the console's
Arm lasers switch (L) is no longer persisted between runs, so the laser is
disarmed at every launch and armed per track by hand.

WHAT it shows -- `Laser.set_dotted_line_sweep`, the one hardware-verified
  pattern (2026-09-06: flattened line, dotted outline, horizontal sweep).
  Between sweeps, while the gate is open, the same pattern is written
  PRIMED (CH1 = 0, off) so the unit holds the line before it lights: the
  third run's 0.24 s flashes from an all-zero universe showed the unit's
  default circle instead. Unverified whether priming is what fixes that;
  the bar-long sweep is the second line of defense (the 2026-09-06
  verification was sustained and showed the line).

HOW it moves -- CH7 sweep speed follows a "wub" envelope: the low band's
  excess over its own slow baseline, fast attack / slower release (the
  2026-09-03 pass-2 kick/bass follower, see engines/envelope.py), applied
  to a SPEED rather than an on/off decision. The fan idles at
  LASER_SWEEP_BASE (mid-band speed, the one Josh liked on 2026-09-06),
  never stops; the envelope is self-normalized so the loudest recent wub
  reads full on any song.

COLOR -- the phrase-frozen palette entry (`snap.palette`), snapped to the
nearest CH12 macro, so the laser matches the wash.

Safety is NOT here: `Laser.apply_safety` (arm switch + LASER-09 geometry, or
the operator's `--testing` mode) and `apply_laser_gate` run in
merge/merge.py's finalize() on every frame regardless of what this layer
writes.
"""

from __future__ import annotations

from ..clock import Clock
from ..core.show_state import ShowSnapshot
from .envelope import NORMALIZE_TAU_S, BandEnvelope
from ..fixtures.profiles import Laser
from ..fixtures.rig import Rig
from ..merge.merge import Contribution
from ..scenes.base import EnergyBucket

# The held hit must land in the top quarter of core/metronome.py's
# DROP_INTENSITY_FLOOR..CEIL range (0.85..1.0). Measured on the 2026-09-15/16
# captures: first drops 1.0, second drops 0.88-0.97, a mixed-in track 0.92.
LASER_MIN_HIT_INTENSITY = 0.95

LASER_BLOCK_BARS = 8       # one sweep per block of this many bars (the Bible's phrase unit)
LASER_SWEEP_BARS = 1.0     # how long one sweep stays lit
FLASH_MIN_ENERGY = 1e-6

# CH7 sweep = LASER_SWEEP_BASE + (1 - LASER_SWEEP_BASE) * wub. First live run
# (2026-09-15 night, recordings/session-20260915-211607): with the sweep
# driven by the raw envelope alone it sat at 0.06 (CH7 ~136, the bottom of
# the 128-255 speed band) -- Josh: "static, slowly moving to the right and
# left, very slow... it should be more of like a fan." The speed he liked on
# 2026-09-06 was CH7 ~190-215 (sweep_intensity = energy ~0.5-0.7), so the
# fan now idles there and the wub envelope -- self-normalized, see
# engines/envelope.py's NORMALIZE_* -- adds speed on top.
LASER_SWEEP_BASE = 0.5

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
    docstring's WHEN section. bool(): drop_hit_intensity can arrive as a
    numpy float64 and a numpy bool is not JSON-serializable (the recorder
    dropped 162 samples on this comparison during the first live run)."""
    return bool(EnergyBucket(snap.bucket) == EnergyBucket.PEAK
                and snap.drop_hit_intensity >= LASER_MIN_HIT_INTENSITY)


class LaserEngine:
    """Stateful (block counter + sweep window + wub envelope); tick once per
    ShowEngine frame."""

    # Above Phrase (50): whatever look is up, this layer owns the laser
    # channels (LTP by priority in merge/merge.py). Below Transition (100),
    # which never touches them anyway.
    priority = 60

    def __init__(self, clock: Clock, block_bars: int = LASER_BLOCK_BARS,
                 sweep_bars: float = LASER_SWEEP_BARS) -> None:
        self.clock = clock
        self.block_bars = block_bars
        self.sweep_bars = sweep_bars
        self._wub = BandEnvelope(clock, normalize_tau_s=NORMALIZE_TAU_S)
        self._sweep_until = 0.0
        self._entry_bar: int | None = None   # phrase origin fallback when the snapshot has none
        self._last_origin: int | None = None  # the origin _last_block counts from
        self._last_block: int | None = None  # the block index the current/last sweep fired in --
        # kept across a gate close (a PEAK->DROP->PEAK blip from the overlay's
        # hysteresis must not re-fire the same block), reset when the origin
        # changes (a new drop)
        self.active = False          # exposed for the console/recorder/finalize gate: a sweep is open
        self.primed = False          # gate open, pattern written with CH1 off, waiting for the next block
        self.wub = 0.0               # this tick's normalized 0..1 wub envelope
        self.sweep = 0.0             # this tick's 0..1 CH7 sweep intensity (base + wub), what is sent
        self.color = Laser.COLOR_WHITE

    @property
    def name(self) -> str:
        return "laser"

    def _close(self, now: float) -> None:
        self._sweep_until = now
        self._entry_bar = None
        self.active = False
        self.primed = False

    def tick(self, snap: ShowSnapshot, rig: Rig) -> Contribution:
        c = Contribution()
        now = self.clock.monotonic()
        self.wub = self._wub.update(snap.audio_band_low_abs, snap.audio_fresh)
        self.sweep = LASER_SWEEP_BASE + (1.0 - LASER_SWEEP_BASE) * self.wub
        self.color = laser_color_for_palette(snap.palette)
        # LASER-12: any signal loss -> off now, never a held value.
        if not (snap.audio_fresh and snap.pdl_fresh) or not laser_wanted(snap):
            self._close(now)
            return c  # untouched channels stay at the boot zeros; finalize zeroes CH1 too
        if self._entry_bar is None:
            self._entry_bar = snap.bar
        origin = snap.drop_start_bar if snap.drop_start_bar is not None else self._entry_bar
        if origin != self._last_origin:
            self._last_origin = origin
            self._last_block = None
        bars_in = snap.bar - origin
        if bars_in >= 0 and bars_in % self.block_bars == 0:
            block = bars_in // self.block_bars
            if block != self._last_block:
                self._last_block = block
                beat = 60.0 / snap.bpm if snap.bpm > 0 else 0.5
                self._sweep_until = now + self.sweep_bars * 4.0 * beat
        self.active = bool(now < self._sweep_until)
        self.primed = not self.active
        for fx in rig.by_role("laser"):
            fx.set_dotted_line_sweep(c, color=self.color, sweep_intensity=self.sweep, lit=self.active)
        return c
