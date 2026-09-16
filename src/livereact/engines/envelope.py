"""BandEnvelope -- a baseline-excess envelope follower for one audio band.

The one piece of the 2026-09-03 kick-follow work that keeps getting reused:
track a SLOW baseline (EMA, several beats long) of a band's raw magnitude,
and follow the EXCESS above it with a fast attack / slower release. The
baseline-excess step is what isolates a transient (a kick, a wub, a stab)
from the sustained content underneath it in the same band -- verified live
on 2026-09-03 (near-zero output while a real bassline played, lit on the
kicks). What it cannot do, also verified live: tell two instruments in the
same band apart by amplitude.

Constants (the defaults below) were calibrated then against a real 60 s
capture: excess-over-baseline p10=2.09, p50=3.28, p90=4.23 -> gain set so
p90 lands near 1.0. Attack/release are inputs/audio.py's own VU-style pair.

Consumers: engines/laser.py (low band -> CH7 sweep speed) and
engines/reactive.py's Synth Sync (mid band -> wash dimmer, 2026-09-15).
"""

from __future__ import annotations

import math

from ..clock import Clock

BASELINE_TAU_S = 1.2   # slow: several beats, so one transient can't drag the baseline up
BASELINE_FLOOR = 0.05  # keeps the ratio sane during real digital silence
ATTACK_S = 0.015
RELEASE_S = 0.18
GAIN = 0.236
# Self-normalization (2026-09-15 night, first live laser run): the excess
# signal is SONG-dependent -- on a track with a sustained bassline the
# low band's excess over its baseline peaked at ~0.5 in a real drop
# (recordings/session-20260915-211607: sweep p50 0.06, p90 0.11 at gain
# 0.236), so a fixed gain left the laser crawling. With `normalize_tau_s`
# set, the output is the excess divided by a decaying peak-hold of itself:
# the loudest recent transient reads as 1.0 whatever its absolute size,
# and the peak forgets over a couple of bars so a quieter passage's own
# hits read full again. `normalize_floor` keeps residual noise from being
# amplified to full when nothing transient has happened recently.
NORMALIZE_TAU_S = 4.0
NORMALIZE_FLOOR = 0.25
# Cold start: the baseline begins at 0, so the first fraction of a second of
# any signal reads as an enormous "excess" (the same trap the old onset
# detectors hit, docs/14). Report 0 and don't let that spike into the peak
# tracker until the baseline has had time to converge.
WARMUP_S = 1.0


class BandEnvelope:
    """Stateful; call `update(raw, fresh)` once per tick with the band's
    un-normalized magnitude (`audio_band_*_abs`). Returns 0..1. `fresh=False`
    resets the state so a stale reading never shapes the first frames after
    the audio reconnects."""

    def __init__(self, clock: Clock, baseline_tau_s: float = BASELINE_TAU_S,
                 baseline_floor: float = BASELINE_FLOOR, attack_s: float = ATTACK_S,
                 release_s: float = RELEASE_S, gain: float = GAIN,
                 normalize_tau_s: float | None = None, normalize_floor: float = NORMALIZE_FLOOR) -> None:
        self.clock = clock
        self.baseline_tau_s = baseline_tau_s
        self.baseline_floor = baseline_floor
        self.attack_s = attack_s
        self.release_s = release_s
        self.gain = gain
        self.normalize_tau_s = normalize_tau_s  # None -> plain gain; a tau -> divide by a decaying peak-hold
        self.normalize_floor = normalize_floor
        self._baseline = 0.0
        self._env = 0.0
        self._peak = 0.0
        self._last_t: float | None = None
        self._fresh_since: float | None = None
        self.level = 0.0  # last returned value, for telemetry

    def update(self, raw: float, fresh: bool = True) -> float:
        now = self.clock.monotonic()
        dt = (now - self._last_t) if self._last_t is not None else 1 / 60
        self._last_t = now
        if not fresh:
            self._baseline = 0.0
            self._env = 0.0
            self._peak = 0.0
            self._fresh_since = None
            self.level = 0.0
            return 0.0
        if self._fresh_since is None:
            self._fresh_since = now
        self._baseline += (1 - math.exp(-dt / self.baseline_tau_s)) * (raw - self._baseline)
        excess = max(0.0, raw / max(self._baseline, self.baseline_floor) - 1.0)
        tau = self.attack_s if excess > self._env else self.release_s
        self._env += (1 - math.exp(-dt / tau)) * (excess - self._env)
        if now - self._fresh_since < WARMUP_S:
            self.level = 0.0  # see WARMUP_S
            return 0.0
        if self.normalize_tau_s is None:
            self.level = max(0.0, min(1.0, self._env * self.gain))
        else:
            self._peak *= math.exp(-dt / self.normalize_tau_s)
            self._peak = max(self._peak, self._env)
            self.level = max(0.0, min(1.0, self._env / max(self._peak, self.normalize_floor)))
        return float(self.level)
