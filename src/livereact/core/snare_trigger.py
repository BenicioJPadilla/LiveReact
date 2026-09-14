"""Snare/hi-hat onset detection -> a boolean "did an onset just happen"
signal (build_snare_accent Step 1 -- see the plan doc's Question 7 and
[[livereact-project]] memory for the full multi-step scope this is one
piece of).

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

Step 1 ONLY, deliberately thin -- a plain "did an onset happen right now"
boolean, no knowledge of BUILD-bucket gating, roll/subdivision
acceleration, or the Bible's own laser-specific duty-cycle/spacing rules
(§8.5's `MIN_SPACING_S`/`MAX_DUTY` are a musical-restraint policy for a
completely different fixture, not something a raw onset detector should
own). Step 2 (roll detection, layered on top of this signal, tracking
inter-onset intervals to distinguish "a roll" from "one hit") and the
eventual strobe-channel delivery (reusing `ReactiveLayerEngine`'s existing
`_strobe_burst_gate` via a `max()`'d combined rate, per the safety-
integration note in the plan doc -- NOT a second independent strobe path)
are both separate, not-yet-built work.
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
