"""Snare/hi-hat onset detection (`SnareOnsetDetector`, Step 1) and roll/
subdivision classification on top of it (`SnareRollDetector`, Step 2) --
build_snare_accent's two detection steps, see the plan doc's Question 7
and [[livereact-project]] memory for the full multi-step scope these are
part of. Deliberately two separate, composable classes (the caller wires
one's output into the other) rather than one combined class, so each
stays independently testable -- SnareOnsetDetector doesn't need to know
what a "bucket" or "roll" is, and SnareRollDetector doesn't need to know
anything about audio at all, only a boolean and a bucket string.

VERIFIED BY SIMULATION before being wired in here (tools/simulations/
snare_onset_sim.py, a synthetic groove with 42 known backbeat snare hits
AND 86 hi-hats sharing the SAME high band the snare's own "hiss" lives
in): the laser's kick detector own tuned ratio (`laser_trigger.py`'s
`TRIGGER_RATIO=1.8`) is NOT safe to reuse blindly here just because the
algorithm shape is the same -- at 1.8 this produced only 47.7% precision
on the synthetic track, with roughly half the false positives landing
exactly on a hi-hat, not noise (a hi-hat is real high-band energy, not a
detection artifact -- it needs a genuinely higher bar to separate from a
snare, not a bug fix). Raising the ratio to 2.6 cleanly separates a real
snare hit from routine hi-hat content: 95.5% precision, 100% recall on the
same synthetic track, 1 residual hihat-adjacent false positive out of 44
fires -- disclosed, not zero, but a real, measured order-of-magnitude
improvement, not a bigger number picked by feel. `MIN_ENERGY_FLOOR` was
swept 0.5-2.0 with no measurable effect once the rolling average has
warmed up -- kept only as a cold-start safety net, not itself load-bearing;
`REFRACTORY_S`/`ROLLING_AVG_ALPHA`/`WARMUP_S` were carried over from the
kick detector's own already-verified values, not independently re-swept
here (a real, disclosed scope limit -- revisit if Step 2's roll detection
ever needs tighter timing than these afford).

`SnareOnsetDetector` (Step 1) is deliberately thin -- a plain "did an
onset happen right now" boolean, no knowledge of BUILD-bucket gating, roll
acceleration, or the Bible's own laser-specific duty-cycle/spacing rules
(§8.5's `MIN_SPACING_S`/`MAX_DUTY` are a musical-restraint policy for a
completely different fixture, not something a raw onset detector should
own).

`SnareRollDetector` (Step 2, below) consumes that boolean plus the current
bucket and classifies whether a genuine ACCELERATING roll is in progress --
see its own class docstring for how, and `tools/simulations/
snare_roll_sim.py` for the verification (a steady backbeat never reads as
a roll despite being multiple onsets in a row; a real accelerating pattern
is correctly flagged partway through and correctly expires once the hits
stop; the BUILD-only gate holds even against the same accelerating pattern
in a different bucket).

Neither class touches the actual strobe channel. The eventual delivery
step (reusing `ReactiveLayerEngine`'s existing `_strobe_burst_gate` via a
`max()`'d combined rate, per the safety-integration note in the plan doc --
NOT a second independent strobe path) is separate, not-yet-built work.
"""

from __future__ import annotations

from ..clock import Clock
from .show_state import ShowSnapshot

TRIGGER_RATIO = 2.6       # verified by simulation -- see module docstring; deliberately NOT the kick detector's 1.8
REFRACTORY_S = 0.15       # carried over from the kick detector's own verified value, not independently swept
ROLLING_AVG_ALPHA = 0.05  # same carry-over
MIN_ENERGY_FLOOR = 1.0    # swept 0.5-2.0 in simulation with no measurable effect -- cold-start safety net only
WARMUP_S = 1.0            # same cold-start rationale as the kick detector's own WARMUP_S


class SnareOnsetDetector:
    """Stateful: call ``update(snap)`` once per tick. Returns whether a
    snare/hi-hat-band onset just occurred -- a raw signal, not yet gated to
    BUILD or shaped into a roll (see module docstring)."""

    def __init__(self, clock: Clock, ratio: float = TRIGGER_RATIO,
                 refractory_s: float = REFRACTORY_S) -> None:
        self.clock = clock
        self.ratio = ratio
        self.refractory_s = refractory_s
        self._rolling_avg = 0.0
        self._last_fire_t = -999.0
        self._fresh_since: float | None = None  # when audio most recently became fresh
        self.active = False  # exposed for the console/telemetry, same pattern as LaserOnsetDetector

    def update(self, snap: ShowSnapshot) -> bool:
        now = self.clock.monotonic()
        if not snap.audio_fresh:
            self._rolling_avg = 0.0  # don't let stale readings pollute detection on reconnect
            self._fresh_since = None
            self.active = False
            return self.active
        if self._fresh_since is None:
            self._fresh_since = now
        warmed_up = (now - self._fresh_since) >= WARMUP_S

        energy = snap.audio_band_mid_abs + snap.audio_band_high_abs
        self._rolling_avg += ROLLING_AVG_ALPHA * (energy - self._rolling_avg)

        fired = (
            warmed_up
            and energy > max(self._rolling_avg * self.ratio, MIN_ENERGY_FLOOR)
            and (now - self._last_fire_t) > self.refractory_s
        )
        if fired:
            self._last_fire_t = now
        self.active = fired
        return self.active


# History/tighten-ratio/max-age below are verified by simulation
# (tools/simulations/snare_roll_sim.py, 2026-09-14): a scripted steady
# 2-beat backbeat pattern (a real, ordinary house/techno rhythm --
# multiple onsets in a row, same as a roll superficially looks) never
# reads as a roll at these settings, while a genuine accelerating pattern
# (quarter -> eighth -> sixteenth notes, the real shape a roll takes into
# a drop) is correctly flagged partway through and correctly turns back
# off once the hits stop. HISTORY/TIGHTEN_RATIO are not independently
# swept against a wide parameter grid the way SnareOnsetDetector's ratio
# was -- a real, disclosed scope limit for this step (the steady-vs-
# accelerating distinction is qualitatively binary here: 4 consecutive
# tightening intervals never occurs by chance in a steady pattern, so
# precise tuning matters less than for the continuous energy-ratio case).
#
# 2026-09-15 hardening, from the first real capture (recordings/session-
# 20260915-114303): the strobe channel lit at the EXACT tick BUILD committed
# on both tracks played -- 3s and 11s before their drops, on intro/break
# content -- and the ambient path is provably 0 at a BUILD entry, so this was
# the roll path. Two causes, both fixed here: (1) `_onset_times` survived
# across buckets, so hats/claps from the preceding BREAK were already a
# "history" the instant BUILD started -- history is now cleared whenever the
# bucket isn't BUILD, so a roll has to be earned inside the build; (2) the
# overall-window test alone (latest interval <= 0.7 x earliest, 3 intervals)
# is trivially satisfied by an ordinary quarter-then-two-eighths hat figure --
# now the window is longer AND every step must be non-increasing (a plateau
# is fine, a widening gap resets the pattern), which the simulation's own
# adversary set never produces but a textbook roll always does.
ROLL_HISTORY = 6           # onset times tracked -> a 5-interval window
ROLL_TIGHTEN_RATIO = 0.7   # the window's LATEST interval must be at most this fraction of its EARLIEST
ROLL_PLATEAU_TOLERANCE = 0.15  # each interval may exceed the one before it by at most this
                               # fraction (timing jitter / a plateau), otherwise it isn't a roll
ROLL_MAX_AGE_S = 0.5       # a roll "expires" (active->False) if no qualifying onset in this long


class SnareRollDetector:
    """Consumes Step 1's raw per-tick onset boolean (SnareOnsetDetector's
    own `update()` return value) and classifies whether a genuine
    ACCELERATING roll is in progress -- not just "multiple hits happened,"
    which an ordinary steady backbeat also produces. Deliberately decoupled
    from SnareOnsetDetector (composed by the caller, not owned internally)
    so each piece stays independently testable, same reasoning as keeping
    Step 1 "deliberately thin" in the first place.

    LIGHTING_BIBLE.md's own `[BUILD]` tag for `build_snare_accent` is
    enforced HERE, not in the onset detector -- a roll is only meaningful
    during a build, and gating it at this layer keeps `SnareOnsetDetector`
    itself bucket-agnostic (it doesn't need to know what a "bucket" is at
    all)."""

    def __init__(self, clock: Clock, history: int = ROLL_HISTORY,
                 tighten_ratio: float = ROLL_TIGHTEN_RATIO) -> None:
        self.clock = clock
        self.history = history
        self.tighten_ratio = tighten_ratio
        self._onset_times: list[float] = []
        self.active = False

    def update(self, onset_fired: bool, bucket: str, max_age_s: float = ROLL_MAX_AGE_S) -> bool:
        now = self.clock.monotonic()
        if bucket != "build":
            # History must be EARNED inside the build (2026-09-15, see the
            # constants' comment above) -- onsets from the preceding section
            # can't pre-load a "roll" that unmasks the instant BUILD commits.
            self._onset_times = []
            self.active = False
            return False
        if onset_fired:
            self._onset_times.append(now)
            self._onset_times = self._onset_times[-self.history:]

        fresh_enough = bool(self._onset_times) and (now - self._onset_times[-1]) <= max_age_s
        self.active = fresh_enough and self._is_accelerating()
        return self.active

    def _is_accelerating(self) -> bool:
        if len(self._onset_times) < self.history:
            return False
        intervals = [b - a for a, b in zip(self._onset_times, self._onset_times[1:])]
        # OVERALL trend across the whole window (latest interval vs. the
        # earliest one in it) -- NOT "every single consecutive pair must
        # strictly tighten." FOUND BY SIMULATION (2026-09-14): a real roll
        # naturally plateaus at each subdivision level for a couple of hits
        # before dropping to the next (quarter, quarter, eighth, eighth,
        # sixteenth...) -- requiring strict pairwise tightening at every
        # step rejected a real, textbook roll pattern outright. The window
        # must still be NON-increasing step to step within a small
        # tolerance (2026-09-15): a plateau passes, but any gap that opens
        # back up means the hits aren't accelerating into anything.
        for earlier, later in zip(intervals, intervals[1:]):
            if later > earlier * (1.0 + ROLL_PLATEAU_TOLERANCE):
                return False
        return intervals[-1] <= intervals[0] * self.tighten_ratio
