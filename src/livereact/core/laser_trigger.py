"""Laser onset/transient detection -> a brief flash gate (docs/14 §3).

VERIFIED BY SIMULATION before this was built (tools/simulations/
audio_pipeline_sim_v2.py, 61 known kick times in a synthetic house track):
overall/whole-signal RMS onset detection barely works for kick-driven
triggering (3.3% recall) — a sidechained bassline keeps the rolling average
elevated continuously, so an individual kick's contribution to *overall*
loudness isn't a big enough relative jump. Low-band ENERGY — the absolute
signal, `audio_band_low_abs`, NOT the normalized `audio_band_low` fraction
used for color, which saturates near-constant during a groove and loses
almost all its contrast — is far better: 80-87% recall, 94-98% precision at
ratio=1.8, refractory=0.15s. Both used here as-verified, not re-guessed.

Fail-closed by design (Josh, 2026-09-01): if real audio isn't connected
(`audio_fresh` is False), the laser never flashes — same "off unless
explicitly confirmed" philosophy as the rest of the laser safety path. This
is a deliberate trade-off: testing the laser's flash behavior specifically
now requires real audio connected, not just an armed drop scene.

Hard on/off flash window, not a decaying envelope (unlike the reactive
layer's beat-pulse): a laser's mode channel is a discrete pattern selector,
not a continuous dimmer — there's no clean analog for "fading" it, so a
flat flash window for a fixed number of beats is the more honest fit.

Absolute intensity gate added (Josh, 2026-09-01): the ratio-based spike check
above is RELATIVE — it fires on a genuine bass spike regardless of whether
the song overall is quiet or intense, since it only compares against its
OWN recent rolling average. That's not what Josh wants: lasers only during
actually intense parts (e.g. after a loud drop), never during a quiet song
or a quiet section. Fix: require BOTH a real relative spike (already-
verified onset detection) AND the song's overall energy (`snap.energy` — the
same field that already drives scene/bucket selection, so "intense" means
the same thing everywhere in the show, not two different notions) to
already be high. A quiet song's occasional kick still won't fire; only a
spike during an already-loud section will.
"""

from __future__ import annotations

from ..clock import Clock
from .show_state import ShowSnapshot

TRIGGER_RATIO = 1.8       # verified by simulation
REFRACTORY_S = 0.15       # verified by simulation
ROLLING_AVG_ALPHA = 0.05  # matches the simulation's onset detector exactly
FLASH_BEATS = 1.0         # how long the gate stays open after a trigger, in beats
# Minimum absolute energy to ever trigger — guards the cold-start case (rolling
# average starts at 0, so ratio*0=0 would trivially trigger on any signal at
# all). NOT calibrated against real audio_band_low_abs magnitudes yet — verify
# once tested live and raise if pure silence/noise floor still fires.
MIN_ENERGY_FLOOR = 1e-6
# The song's overall real-time energy (snap.energy, 0..1) must be at least
# this high for a bass spike to count at all — "intense parts only," not a
# quiet song's occasional kick. Same threshold family as bucket_for_energy's
# DROP cutoff (~0.95) but intentionally a bit looser here, since requiring
# the FULL drop threshold on top of an already-armed drop-bucket scene would
# make the gate nearly redundant with scene selection itself. Tune by ear.
MIN_INTENSITY = 0.7
# FOUND BY TESTING, not by reasoning about it up front: the rolling average
# starts at 0.0, so for the first ~20-60 ticks after startup (or every time
# audio reconnects from stale — it resets too, see update() below) ANY
# steady, non-spiking signal looks like "a huge spike vs. a near-zero
# average" and false-triggers, even a perfectly constant bassline. A
# dedicated unit test aimed at something else (the intensity gate) caught
# this by accident. Fix: suppress triggering entirely until the rolling
# average has had time to actually converge.
WARMUP_S = 1.0


class LaserOnsetDetector:
    """Stateful: call ``update(snap)`` once per ShowEngine tick."""

    def __init__(self, clock: Clock, ratio: float = TRIGGER_RATIO,
                 refractory_s: float = REFRACTORY_S, flash_beats: float = FLASH_BEATS,
                 min_intensity: float = MIN_INTENSITY) -> None:
        self.clock = clock
        self.ratio = ratio
        self.refractory_s = refractory_s
        self.flash_beats = flash_beats
        self.min_intensity = min_intensity
        self._rolling_avg = 0.0
        self._last_fire_t = -999.0
        self._flash_until = 0.0
        self._fresh_since: float | None = None  # when audio most recently became fresh
        self.active = False  # exposed for the console

    def update(self, snap: ShowSnapshot) -> bool:
        """Returns whether the laser flash gate should be open right now."""
        now = self.clock.monotonic()

        if not snap.audio_fresh:
            self._rolling_avg = 0.0  # don't let stale readings pollute detection on reconnect
            self._fresh_since = None
            self.active = False
            return self.active
        if self._fresh_since is None:
            self._fresh_since = now

        energy = snap.audio_band_low_abs
        self._rolling_avg += ROLLING_AVG_ALPHA * (energy - self._rolling_avg)
        warmed_up = (now - self._fresh_since) >= WARMUP_S

        if (warmed_up
                and snap.energy >= self.min_intensity  # intense parts only — see module docstring
                and energy > max(self._rolling_avg * self.ratio, MIN_ENERGY_FLOOR)
                and (now - self._last_fire_t) > self.refractory_s):
            self._last_fire_t = now
            beat_dur = 60.0 / snap.bpm if snap.bpm > 0 else 0.5
            self._flash_until = now + self.flash_beats * beat_dur

        self.active = now < self._flash_until
        return self.active
