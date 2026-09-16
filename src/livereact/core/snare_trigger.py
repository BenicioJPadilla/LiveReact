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


class RollRiseDetector:
    """Stateful; call ``update(snap)`` once per tick. Returns True while a
    roll-like rise in the high band is in progress during a BUILD."""

    def __init__(self, clock: Clock, on_ratio: float = ON_RATIO, off_ratio: float = OFF_RATIO,
                 max_hold_s: float = MAX_HOLD_S, arm_s: float = ARM_S,
                 build_settle_s: float = BUILD_SETTLE_S) -> None:
        self.clock = clock
        self.on_ratio = on_ratio
        self.off_ratio = off_ratio
        self.max_hold_s = max_hold_s
        self.arm_s = arm_s
        self.build_settle_s = build_settle_s
        self._fast = 0.0
        self._slow = 0.0
        self._frozen = 0.0
        self._last_t: float | None = None
        self._fresh_since: float | None = None
        self._build_since: float | None = None   # when the current BUILD began
        self._rise_since: float | None = None    # when the level first cleared on_ratio (arming)
        self._since: float | None = None
        self.active = False
        self.ratio = 0.0  # exposed for the recorder: fast / (frozen or slow) baseline this tick

    def update(self, snap: ShowSnapshot) -> bool:
        now = self.clock.monotonic()
        dt = (now - self._last_t) if self._last_t is not None else 1 / 60
        self._last_t = now
        if not snap.audio_fresh:
            self._fast = self._slow = self._frozen = 0.0
            self._fresh_since = self._build_since = self._rise_since = self._since = None
            self.active = False
            self.ratio = 0.0
            return False
        raw = float(snap.audio_band_high_abs)
        if self._fresh_since is None:
            self._fresh_since = now
            self._fast = self._slow = raw  # start converged, not from 0
        self._fast += (1 - math.exp(-dt / FAST_TAU_S)) * (raw - self._fast)

        if snap.bucket != "build":
            # Keep the slow baseline tracking outside a build; never active.
            self._slow += (1 - math.exp(-dt / SLOW_TAU_S)) * (raw - self._slow)
            self.active = False
            self._build_since = self._rise_since = self._since = None
            self.ratio = self._fast / max(self._slow, LEVEL_FLOOR)
            return False

        if self._build_since is None:
            self._build_since = now
            self._slow = self._fast  # the build's own level is the reference, not the break's
        if not self.active:
            if self._rise_since is None:
                # Not arming: the slow baseline tracks the build.
                self._slow += (1 - math.exp(-dt / SLOW_TAU_S)) * (raw - self._slow)
                base = max(self._slow, LEVEL_FLOOR)
                self.ratio = self._fast / base
                settled = (now - self._fresh_since) >= WARMUP_S and (now - self._build_since) >= self.build_settle_s
                if settled and self._fast >= self.on_ratio * base:
                    self._rise_since = now
                    self._frozen = base  # freeze here: the rise is judged against the level BEFORE it
            else:
                # Arming: the level must stay in the hold band (off_ratio x the
                # frozen base) for arm_s -- a roll's own dips (measured 0.16 vs
                # a 0.12 base) must not cancel it, a one-tick hat must.
                self.ratio = self._fast / self._frozen
                if self._fast < self.off_ratio * self._frozen:
                    self._rise_since = None
                elif now - self._rise_since >= self.arm_s:
                    self.active = True
                    self._since = now
                    self._rise_since = None
        else:
            self.ratio = self._fast / self._frozen
            too_long = self._since is not None and (now - self._since) >= self.max_hold_s
            if self._fast < self.off_ratio * self._frozen or too_long:
                self.active = False
                self._since = None
                self._slow = self._fast  # a second roll must rise again from where this one left off
        return bool(self.active)
