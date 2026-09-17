"""Snare-roll detection for `build_snare_accent` (LIGHTING_BIBLE.md §5:
"accent flashes locked to detected snare subdivision... the snare roll is
the one place transient-following reads as intentional").

REBUILT 2026-09-15 night from the second live run (recordings/session-
20260915-212918). The original two-step design (a per-hit onset detector on
mid+high, ratio 2.6 over a 0.33 s rolling average, feeding an interval-
tightening classifier) was verified on a synthetic groove and never fired on
a real roll: in a dense build the mid+high sum sits elevated the whole time,
and a 16th-note roll (~8 hits/s at 128 BPM) is FASTER than the 0.33 s
average it was compared against -- every hit just looked like "more of the
same" (measured: ratio p90 1.21, max 1.60 across the whole build; the
detector needed 2.6). Zero onsets in the build, so the accent structurally
could not fire on real material.

What a real roll DOES look like in the recording: the high band's level
steps from ~0.13 to 0.3-0.5 at 92.1 s and stays there for the last 3.6 s
of the build, right into the drop -- a sustained RISE, not a train of
separable spikes. So this detector tracks exactly that: a fast level of the
high band against a slow baseline of what the build sounded like before,
armed when the level clears ON_RATIO x baseline, then held (baseline
frozen) until the level falls back under OFF_RATIO x that frozen baseline,
the build ends, or MAX_HOLD_S passes. BUILD-only, per the Bible's own tag.

Still band-amplitude, still not instrument identification: a riser synth
or a hat build-up that lifts the high band the same way will read as a
roll too. For the accent's purpose (something is escalating fast into the
drop) that's acceptable and disclosed, not hidden.

SECOND PATH, 2026-09-17, from run 5 (recordings/session-20260916-114402):
that track's build had spiky hats at 0.1-1.3 and its roll (218-219.6 s,
0.65-1.18) was only ~2x the build's own level -- under ON_RATIO, invisible
to the level path at any ratio that didn't also fire on the hats (replayed
at 2.0/1.7/1.5). A roll is a RATE, not a level, so inputs/audio.py now
measures high-band onset density at block rate (`audio_high_onset_rate`,
onsets/s -- the 10 Hz recorder can't see 16th notes) and this detector
also arms on DENSITY: the rate clearing both an absolute floor
(ROLL_MIN_RATE, between 8th- and 16th-note hats) and ROLL_DENSITY_RATIO x
the build's own baseline rate. The two paths share the settle/arm/hold/
max-hold machinery and are OR'd: either can arm, either can hold. Known
limit: the onset measurement caps near ~12/s, so a 32nd-note roll over
16th-note hats reads ~1.4x, not 2x -- ROLL_DENSITY_RATIO sits at 1.4 for
that. Thresholds are [CONVENTION] until the first live --record run that
logs `onset_rate` (Josh's call: validate live, no track files).
"""

from __future__ import annotations

import math

from ..clock import Clock
from .show_state import ShowSnapshot

FAST_TAU_S = 0.10      # the "now" level: a couple of roll hits
SLOW_TAU_S = 3.0       # the "before" level: a bar or two of the build so far
ON_RATIO = 2.0         # measured 2026-09-15: pre-roll 0.12 -> roll 0.3-0.5 (2.5-4x)
OFF_RATIO = 1.3        # against the FROZEN baseline, so the hold survives the roll's own dips (min 0.16 vs 0.12 base)
LEVEL_FLOOR = 0.05     # below this the high band is noise; never arm off a ratio against it
MAX_HOLD_S = 8.0       # a "roll" longer than this is a texture, not an accent
WARMUP_S = 1.0         # the fast/slow levels start at 0 -- don't arm off the cold-start step
# Two guards from replaying all five 2026-09-15 captures: without them the
# detector flicked on for 0.1-0.3 s at every build's first second (the
# section change is itself a rise against the break's baseline) and on
# scattered hats mid-build. A build's own level becomes the reference (the
# slow baseline snaps to the current level on BUILD entry) and nothing arms
# for BUILD_SETTLE_S; and the rise must HOLD for ARM_S before it counts --
# a 16th-note roll into a drop lasts bars, a stray hat lasts a tick.
BUILD_SETTLE_S = 1.5
ARM_S = 0.4
# Density path (see the module docstring's second half).
RATE_SLOW_TAU_S = 3.0      # baseline onset rate: the build's hats so far
ROLL_MIN_RATE = 6.0        # onsets/s: 8th hats are ~4.3/s at 128 BPM (4.7 at 140), 16ths ~8.5 (9.3)
ROLL_DENSITY_RATIO = 1.4   # rate vs the build's baseline rate (2x for 8ths -> 16ths; ~1.4x at the cap)
ROLL_OFF_RATIO = 1.2       # against the FROZEN baseline rate
ROLL_OFF_MIN_RATE = 4.5    # never hold on a rate under this


class RollRiseDetector:
    """Stateful; call ``update(snap)`` once per tick. Returns True while a
    roll-like rise in the high band -- in level or in onset density -- is in
    progress during a BUILD."""

    def __init__(self, clock: Clock, on_ratio: float = ON_RATIO, off_ratio: float = OFF_RATIO,
                 max_hold_s: float = MAX_HOLD_S, arm_s: float = ARM_S,
                 build_settle_s: float = BUILD_SETTLE_S,
                 min_rate: float = ROLL_MIN_RATE, density_ratio: float = ROLL_DENSITY_RATIO,
                 off_rate_ratio: float = ROLL_OFF_RATIO, off_min_rate: float = ROLL_OFF_MIN_RATE) -> None:
        self.clock = clock
        self.on_ratio = on_ratio
        self.off_ratio = off_ratio
        self.max_hold_s = max_hold_s
        self.arm_s = arm_s
        self.build_settle_s = build_settle_s
        self.min_rate = min_rate
        self.density_ratio = density_ratio
        self.off_rate_ratio = off_rate_ratio
        self.off_min_rate = off_min_rate
        self._fast = 0.0
        self._slow = 0.0
        self._frozen = 0.0
        self._rate_slow = 0.0     # baseline onset rate (density path)
        self._rate_frozen = 0.0
        self._last_t: float | None = None
        self._fresh_since: float | None = None
        self._build_since: float | None = None   # when the current BUILD began
        self._rise_since: float | None = None    # when a rise first cleared its threshold (arming)
        self._since: float | None = None
        self.active = False
        self.ratio = 0.0  # exposed for the recorder: fast / (frozen or slow) level baseline this tick
        self.rate = 0.0       # this tick's onset rate (onsets/s)
        self.rate_base = 0.0  # the baseline it's judged against (frozen while arming/active)
        self.path = ""        # which path(s) currently clear their threshold: level / density / both

    def _reset(self) -> None:
        self._fast = self._slow = self._frozen = 0.0
        self._rate_slow = self._rate_frozen = 0.0
        self._fresh_since = self._build_since = self._rise_since = self._since = None
        self.active = False
        self.ratio = self.rate = self.rate_base = 0.0
        self.path = ""

    @staticmethod
    def _path(level: bool, dense: bool) -> str:
        return {(True, True): "both", (True, False): "level", (False, True): "density"}.get((level, dense), "")

    def update(self, snap: ShowSnapshot) -> bool:
        now = self.clock.monotonic()
        dt = (now - self._last_t) if self._last_t is not None else 1 / 60
        self._last_t = now
        if not snap.audio_fresh:
            self._reset()
            return False
        raw = float(snap.audio_band_high_abs)
        rate = float(snap.audio_high_onset_rate)
        self.rate = rate
        if self._fresh_since is None:
            self._fresh_since = now
            self._fast = self._slow = raw  # start converged, not from 0
            self._rate_slow = rate
        self._fast += (1 - math.exp(-dt / FAST_TAU_S)) * (raw - self._fast)
        slow_coeff = 1 - math.exp(-dt / SLOW_TAU_S)
        rate_coeff = 1 - math.exp(-dt / RATE_SLOW_TAU_S)

        if snap.bucket != "build":
            # Keep the baselines tracking outside a build; never active.
            self._slow += slow_coeff * (raw - self._slow)
            self._rate_slow += rate_coeff * (rate - self._rate_slow)
            self.active = False
            self._build_since = self._rise_since = self._since = None
            self.ratio = self._fast / max(self._slow, LEVEL_FLOOR)
            self.rate_base = self._rate_slow
            self.path = ""
            return False

        if self._build_since is None:
            self._build_since = now
            self._slow = self._fast  # the build's own level is the reference, not the break's
            self._rate_slow = rate   # same for its hat density
        if not self.active:
            if self._rise_since is None:
                # Not arming: both baselines track the build.
                self._slow += slow_coeff * (raw - self._slow)
                self._rate_slow += rate_coeff * (rate - self._rate_slow)
                base = max(self._slow, LEVEL_FLOOR)
                self.ratio = self._fast / base
                self.rate_base = self._rate_slow
                settled = (now - self._fresh_since) >= WARMUP_S and (now - self._build_since) >= self.build_settle_s
                level_on = self._fast >= self.on_ratio * base
                dense_on = rate >= max(self.min_rate, self.density_ratio * self._rate_slow)
                self.path = self._path(level_on, dense_on)
                if settled and (level_on or dense_on):
                    self._rise_since = now
                    self._frozen = base  # freeze here: the rise is judged against the level BEFORE it
                    self._rate_frozen = self._rate_slow
            else:
                # Arming: the rise must stay in its hold band for arm_s -- a
                # roll's own dips (measured 0.16 vs a 0.12 base) must not
                # cancel it, a one-tick hat must.
                level_hold, dense_hold = self._holds(rate)
                if not (level_hold or dense_hold):
                    self._rise_since = None
                elif now - self._rise_since >= self.arm_s:
                    self.active = True
                    self._since = now
                    self._rise_since = None
        else:
            level_hold, dense_hold = self._holds(rate)
            too_long = self._since is not None and (now - self._since) >= self.max_hold_s
            if not (level_hold or dense_hold) or too_long:
                self.active = False
                self._since = None
                self._slow = self._fast  # a second roll must rise again from where this one left off
                self._rate_slow = rate
        return bool(self.active)

    def _holds(self, rate: float) -> tuple[bool, bool]:
        """Whether each path still clears its (frozen-baseline) hold band."""
        self.ratio = self._fast / self._frozen
        self.rate_base = self._rate_frozen
        level_hold = self._fast >= self.off_ratio * self._frozen
        dense_hold = rate >= max(self.off_min_rate, self.off_rate_ratio * self._rate_frozen)
        self.path = self._path(level_hold, dense_hold)
        return level_hold, dense_hold
