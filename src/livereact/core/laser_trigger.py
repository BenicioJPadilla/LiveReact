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

Extended to PDL too (2026-09-08, LIGHTING_BIBLE.md §12 audit): "Laser forces
OFF on ANY signal loss — never hold last value" is a hard rule, not just an
audio-specific one. A PDL dropout with audio still fresh used to slip through
this gate entirely (only the separate, ~3s-delayed auto_blackout would
eventually catch it) — now PDL loss closes any open flash window immediately,
same as audio loss, since `snap.bpm`/beat timing (used below for the flash
duration) can't be trusted without it either.

Hard on/off flash window, not a decaying envelope (unlike the reactive
layer's beat-pulse): a laser's mode channel is a discrete pattern selector,
not a continuous dimmer — there's no clean analog for "fading" it, so a
flat flash window for a fixed number of beats is the more honest fit.

Absolute intensity gate added (Josh, 2026-09-01), then SUPERSEDED (2026-09-08,
LIGHTING_BIBLE.md §8.5 full-alignment build): the ratio-based spike check
above is RELATIVE — it fires on a genuine bass spike regardless of whether
the song overall is quiet or intense, since it only compares against its
OWN recent rolling average. A raw `snap.energy >= 0.7` threshold used to be
the fix for that ("intense parts only"). Now replaced by the SAME debounced
`snap.bucket` the wash/par model reads (`EnergyBucket.DROP` or `PEAK`) — one
shared notion of "is this actually a drop," not two different intensity
concepts living side by side. This is also now what the Bible's own §8.5
wants literally: "lasers are punctuation, not continuous texture... drops and
peaks only."

Musical role / duty cycle, full alignment (2026-09-08, LIGHTING_BIBLE.md
§8.5): three things layered on top of the onset detection above, in the
same spirit as the wash/par bucket-model build the same session --
- **Gated to DROP/PEAK** (see above) -- was a looser `MIN_INTENSITY=0.7` before.
- **Minimum spacing between separate laser moments** (`MIN_SPACING_S`, the
  Bible's "≥2 phrases (~2 min) so it stays special") -- distinct from
  `REFRACTORY_S` below, which only guards against re-triggering WITHIN a
  moment that just closed, not spacing separate moments apart.
- **≤10% of total elapsed time** (`MAX_DUTY`) -- a genuine cumulative duty
  tracker (elapsed time since this detector was constructed, and how much of
  that was spent actively flashing), not just a per-burst cap.
NOT built: the Bible's "except one build-climax reveal" exception -- a
deliberate scope cut, flagged rather than silently skipped.

Scene-awareness gate (2026-09-07, CONFIRMED live via a real --hardware
--record capture, see [[livereact-project]] memory): this detector and
`PhraseEngine`'s scene rotation were fully independent systems that had never
been wired together -- a real session showed ALL 21 laser flashes that
session firing during two BREAK looks (both `uses_lasers=False`; one of them,
"Slow Color Cycle", has since been deleted), meaning every one was invisible yet still spent the
`MIN_SPACING_S`/`MAX_DUTY` budget above for nothing. `update()` now takes an
explicit `scene_uses_lasers` flag (the caller's job to supply the active
scene's own value -- this module still has no scene knowledge of its own,
same separation-of-concerns as everything else here) and gates on it
alongside the DROP/spacing/duty checks. Defaults to True so every existing
caller/test that doesn't pass it keeps its prior (scene-unaware) behavior.
"""

from __future__ import annotations

from ..clock import Clock
from ..scenes.base import EnergyBucket
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
# FOUND BY TESTING, not by reasoning about it up front: the rolling average
# starts at 0.0, so for the first ~20-60 ticks after startup (or every time
# audio reconnects from stale — it resets too, see update() below) ANY
# steady, non-spiking signal looks like "a huge spike vs. a near-zero
# average" and false-triggers, even a perfectly constant bassline. A
# dedicated unit test aimed at something else (the intensity gate) caught
# this by accident. Fix: suppress triggering entirely until the rolling
# average has had time to actually converge.
WARMUP_S = 1.0
# LIGHTING_BIBLE.md §8.5, NOT itself precisely specified by the doc beyond
# "~2 min" -- 120s matches the Bible's own global constant for a 32-bar
# phrase at house tempo (~58-61s/phrase * 2). Long relative to a dev/testing
# session's iteration speed (this is a live-show default, not a bench-test
# one) -- override via the constructor when actively probing hardware.
MIN_SPACING_S = 120.0
MAX_DUTY = 0.10           # LIGHTING_BIBLE.md §8.5: "active <=10% of set time"


class LaserOnsetDetector:
    """Stateful: call ``update(snap)`` once per ShowEngine tick."""

    def __init__(self, clock: Clock, ratio: float = TRIGGER_RATIO,
                 refractory_s: float = REFRACTORY_S, flash_beats: float = FLASH_BEATS,
                 min_spacing_s: float = MIN_SPACING_S, max_duty: float = MAX_DUTY) -> None:
        self.clock = clock
        self.ratio = ratio
        self.refractory_s = refractory_s
        self.flash_beats = flash_beats
        self.min_spacing_s = min_spacing_s
        self.max_duty = max_duty
        self._rolling_avg = 0.0
        self._last_fire_t = -999.0
        self._flash_until = 0.0
        self._fresh_since: float | None = None  # when audio most recently became fresh
        self._last_tick_t: float | None = None
        self._total_elapsed_s = 0.0   # time since this detector was constructed
        self._total_flash_s = 0.0     # cumulative time spent actively flashing
        self._last_flash_end_t = -1e9  # far in the past -- the first-ever flash isn't spacing-gated
        self.active = False  # exposed for the console

    def update(self, snap: ShowSnapshot, scene_uses_lasers: bool = True) -> bool:
        """Returns whether the laser flash gate should be open right now.
        `scene_uses_lasers` -- whether the currently-active scene can even
        show a laser at all (see the scene-awareness note above); defaults to
        True so existing callers/tests that don't pass it are unaffected."""
        now = self.clock.monotonic()
        dt = (now - self._last_tick_t) if self._last_tick_t is not None else 0.0
        self._last_tick_t = now
        self._total_elapsed_s += dt

        if not snap.audio_fresh:
            self._rolling_avg = 0.0  # don't let stale readings pollute detection on reconnect
            self._fresh_since = None
            if self.active:
                self._last_flash_end_t = now  # cut short -- start the spacing cooldown now
            self.active = False
            return self.active
        if not snap.pdl_fresh:
            # Bible §12: force off on ANY signal loss, not just audio. Audio's
            # own rolling-average state is still valid (don't reset it), but
            # nothing may flash without a trustworthy beat clock.
            if self.active:
                self._last_flash_end_t = now
            self.active = False
            self._flash_until = now  # close an already-open window immediately
            return self.active
        if self._fresh_since is None:
            self._fresh_since = now

        energy = snap.audio_band_low_abs
        self._rolling_avg += ROLLING_AVG_ALPHA * (energy - self._rolling_avg)
        warmed_up = (now - self._fresh_since) >= WARMUP_S

        # snap.bucket -- an ALREADY-DEBOUNCED bucket_for_energy(energy_norm),
        # computed once in metronome.py (BUCKET_MIN_DWELL_S there), not a fresh
        # call here -- see show_state.py's bucket/energy_norm docstrings for
        # why (a fixed absolute DROP threshold against raw RMS doesn't
        # generalize across sessions/tracks, and an undebounced check flaps
        # near the boundary; both found live 2026-09-07).
        # DROP *and* PEAK: PEAK is core/metronome.py's escalation of a
        # sustained DROP (the most intense stretch of it), not a separate
        # state the laser should go dark for. Was `== DROP` only until the
        # 2026-09-15 polish pass -- a straight bug against the docstring's
        # own "drops and peaks only".
        in_drop = EnergyBucket(snap.bucket) in (EnergyBucket.DROP, EnergyBucket.PEAK)
        spaced_out = (now - self._last_flash_end_t) >= self.min_spacing_s
        under_duty = self._total_elapsed_s <= 0.0 or \
            (self._total_flash_s / self._total_elapsed_s) < self.max_duty

        if (warmed_up
                and scene_uses_lasers      # confirmed live: don't spend the budget on an invisible fire
                and in_drop                # LIGHTING_BIBLE.md §8.5: drops (and peaks) only
                and spaced_out              # "...≥2 phrases apart so it stays special"
                and under_duty              # "...active <=10% of set time"
                and energy > max(self._rolling_avg * self.ratio, MIN_ENERGY_FLOOR)
                and (now - self._last_fire_t) > self.refractory_s):
            self._last_fire_t = now
            beat_dur = 60.0 / snap.bpm if snap.bpm > 0 else 0.5
            self._flash_until = now + self.flash_beats * beat_dur

        was_active = self.active
        self.active = now < self._flash_until
        if was_active and not self.active:
            self._last_flash_end_t = now
        if self.active:
            self._total_flash_s += dt
        return self.active
