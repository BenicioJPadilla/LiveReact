"""Reactive Layer — the always-on base of the show (docs/02 FR-2.1, docs/12 Phase 3).

Beat-locked intensity pulses on the washes, BPM-locked symmetric movement on the
moving heads, and frequency-driven color from the two-axis model. This is what
makes the rig feel musical even before scenes and transitions exist; it reads only
the metronome's interpolated clock, never raw packet timing.
"""

from __future__ import annotations

import math

from ..clock import Clock
from ..core.show_state import ShowSnapshot
from ..fixtures.profiles import Par, WashBar
from ..fixtures.rig import Rig
from ..merge.merge import Contribution
from .color import two_axis_color

PULSE_MIN = 0.03        # fallback-only now (see KICK_* below) — used solely when real
                        # audio isn't connected (demo mode / MIDI-only), to keep the
                        # classic beat-locked ramp as a sensible default with no audio
                        # signal to actually trace. near-zero brightness right before
                        # the next beat re-triggers the pulse.
STROBE_THRESHOLD = 0.85  # energy above which a gentle reactive strobe engages
STROBE_MAX = 0.30       # conservative cap on the reactive strobe rate (0..1)

# Direct audio-envelope-follower for wash/par brightness (docs/14 §5 REDESIGNED
# 2026-09-03, Josh, in three passes):
#
# Pass 1 replaced the mechanical per-beat ramp (gated on/off by a binary
# "are kicks present" detector) with a direct envelope follower on raw
# `audio_band_low_abs`. That fixed the flapping/stuck-off bugs (no gate left to
# flap) and cut onset-to-light lag from 50-300ms+ down to ~20ms median. BUT:
# a kick drum and a bassline occupy the SAME low-frequency band — raw
# `audio_band_low_abs` can't distinguish "loud sustained bass" from "a kick
# transient," so pass 1 lit up on the bassline too. Confirmed live (Josh: wash/
# par "followed the baseline as well," not what he wants — only the kick itself
# should drive these two fixtures).
#
# Pass 2 tracked a slow-moving BASELINE (an EMA of the raw low-band signal, too
# sluggish to be pulled around by any single kick) and drove brightness off the
# EXCESS above that baseline instead of the raw signal. Verified live: this DID
# stop the light from following a sustained bassline (confirmed — near-zero
# brightness measured while the baseline itself was clearly non-zero, i.e. real
# bass was playing and it correctly stayed dark). BUT: amplitude/frequency
# alone can't distinguish a kick from any OTHER low-register transient — Josh
# confirmed live it lit up on a synth hit that shared the same band, not just
# the kick. This is a real limitation, not a calibration miss: two different
# instruments in the same register look identical to amplitude analysis alone.
#
# Pass 3 TRIED, then REVERTED (2026-09-03, same session): gate the excess
# signal by proximity to the real beat (a short window right after each beat
# from `snap.beat_phase`), on the theory that a kick lands ON the beat and a
# stray low-end hit (the pass-2 synth false-positive) usually doesn't. This
# made things WORSE, confirmed live: Josh reported the same repeating 4-beat
# musical pattern produced visibly DIFFERENT lighting each time through the
# loop -- "inconsistently inconsistent," not even a stable wrong behavior.
# Root cause (not re-attempted without fixing this): a HARD, narrow (~150ms)
# window is extremely sensitive to small real-world beat-timing jitter --
# real PDL timing isn't identical to the millisecond even when "locked," so a
# kick landing just inside the window one cycle and just outside it the next
# (a small, normal wobble) flips from fully-lit to fully-gated. A hard cutoff
# turns small input noise into large, visible output differences -- exactly
# the wrong shape of fragility to build on. If beat-timing-based isolation is
# revisited, it needs a SOFT weighting (no hard 0/1 edge) and should be proven
# first against a synthetic repeating input offline (this project's own
# established practice, `tools/simulations/`) before ever going live with it
# again -- skipping that step this round is what let this ship.
#
# BASELINE_TAU_S is deliberately several beats long (not the ~0.33s implied by
# the old gate's per-tick alpha=0.05 at ~60Hz) so the baseline tracks the
# bassline's own slow level changes (a build, a drop) without being dragged up
# by the kicks it's supposed to be measured against.
#
# KICK_GAIN=1.0 VERIFIED reasonable against a real 60s live capture of the
# excess-over-baseline signal (2026-09-03, pass 2): p90≈1.07 (peak kicks reach
# ~full brightness without clamping the whole track), 16.8% of samples
# near-zero with real bass genuinely present underneath (confirmed isolation,
# not just quiet moments), good spread in between (p50≈0.35).
#
# Pass 4 (this version, 2026-09-03, same session, after pass 3's revert):
# Josh's own framing of what he wants: "it should only beat on the beat grid,"
# analyzing the kick to decide how bright, not whether/when to fire on a
# continuously-live signal. The difference from pass 3 that actually fixes the
# jitter problem: pass 3 gated a CONTINUOUS live envelope by a hard window —
# a live, still-changing signal straddling a moving boundary is inherently
# fragile to a few ms of timing wobble. Pass 4 instead makes ONE decision per
# beat — the PEAK (a running max, not a threshold) of the excess-over-baseline
# signal during a short window after the beat starts — and once that window
# closes, the rest of the beat is a fixed decay curve driven ONLY by
# `beat_phase`, with no live audio touching it at all. A max-over-an-interval
# doesn't care about a few ms of jitter in exactly when the peak landed inside
# the window; a fixed post-window decay literally cannot flicker or drift,
# because nothing live is driving it after that point. Confirmed live
# (2026-09-03, an 8-beat repeating loop, pass 2 measurement): real kicks in
# this project's tracks land within beat_phase 0.0-0.23, well inside a
# 0.15s-equivalent window even with tempo variation. Without a real, LOCKED
# beat clock (`pdl_fresh`), there's no beat grid to lock to at all, so this
# fails back to pass 2's continuous envelope (still isolates from a sustained
# bassline, just not beat-quantized) rather than going dark.
BASELINE_TAU_S = 1.2    # slow: several beats, so individual kicks don't drag it up
BASELINE_FLOOR = 0.05   # avoid a near-zero baseline making the ratio blow up on tiny noise
                        # during real digital silence; NOT calibrated against a genuine
                        # sustained-bass-no-kick section yet (see note above)
KICK_ATTACK_S = 0.015   # fast attack, matches AudioAnalyzer's own tuned attack coefficient
                        # (fallback envelope path only, see _kick_pulse)
KICK_RELEASE_S = 0.18   # fallback envelope's release (see above)
BEAT_WINDOW_S = 0.15    # how long after each beat starts to watch for a kick's peak;
                        # NOT yet tuned by ear, chosen to comfortably cover the
                        # 0.0-0.23 beat_phase range real kicks were measured landing in

# Two more fixes from the same live session, after pass 4's timing/consistency
# was confirmed good: Josh reported the light stayed "very bright most of the
# time, not off that much," and real per-beat window-peak values (replayed
# from that same capture) explain why. Even the QUIETEST 10% of real kick
# beats had a peak excess of ~2.1 -- with the old KICK_GAIN=1.0, ANYTHING
# above excess=1.0 clamps to full brightness, so essentially every real kick
# was saturating, wiping out all contrast between a hard hit and a soft one.
KICK_GAIN = 0.236       # RECALIBRATED against real per-beat peaks from that capture:
                        # p10=2.09, p50=3.28, p90=4.23, p95=4.42 (one 83.8 outlier,
                        # a real loud transient, ignored for calibration). Gain set so
                        # p90 lands near 1.0 -- tune by ear, this project's usual caveat.
#
# Second, structural issue (not fixable by gain alone): the decay curve used to
# run across the ENTIRE rest of the beat (window close -> phase 1.0), so
# brightness only ever touched true zero for an instant right at the beat
# boundary -- there was never a real "off" period at all, by construction, no
# matter how loud or quiet the kick was. Fixed by decaying over a FIXED,
# short real-time duration instead of "whatever's left of the beat," then
# holding at true zero until the next beat's window opens -- a genuine dark
# gap every beat now, rather than a technically-nonzero glow the whole time.
KICK_DECAY_S = 0.18     # same order as the old envelope's release; NOT yet tuned by ear

# Live-confirmed good (2026-09-03): timing, contrast, and delay all checked out.
# TRIED a floor of 0.08 for "less strobe-like," then REVERTED most of it: Josh
# reported it now felt MORE delayed and MORE inconsistent. Real explanation,
# not a math bug -- the floor didn't change any timing at all, it changed
# CONTRAST: the same real attack now only climbed 0.08->0.9 instead of 0->1.0
# in the same real time, which reads as a softer/slower transition to the eye
# even though the underlying signal timing is identical. And quiet moments were
# never perfectly flat (real residual noise even between kicks) -- invisible
# against true black, but visible as a faint flicker against a raised floor.
# Contrast WAS the thing making the timing read as crisp and consistent, so
# giving it up was the wrong trade. Kept only a token floor/ceiling trim.
KICK_FLOOR = 0.02       # small enough to stay out of contrast's way
KICK_CEILING = 0.95     # small enough to stay out of contrast's way


class ReactiveLayerEngine:
    """Always-on beat/energy/color reactivity."""

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self._kick_baseline = 0.0   # slow EMA of raw audio_band_low_abs (the "bassline level")
        self._kick_env_raw = 0.0    # fast envelope of the EXCESS above baseline (pre-gain,
                                     # fallback path only -- see _kick_pulse)
        self._beat_window_peak = 0.0   # running max excess within THIS beat's detection window;
                                        # frozen (no longer updated) once the window closes, so it
                                        # drives the rest of the beat's decay untouched by live audio
        self._prev_beat_phase = 0.0    # to detect a beat boundary (phase wrapping back near 0)
        self._last_tick_t: float | None = None
        self.kick_level = 0.0       # exposed for the console: last computed 0..1 brightness

    @property
    def name(self) -> str:
        return "reactive"

    def tick(self, snap: ShowSnapshot, rig: Rig) -> Contribution:
        c = Contribution()
        r, g, b = two_axis_color(snap)
        wash_level = self._kick_pulse(snap)
        strobe = self._strobe_rate(snap)

        # --- washes: pulse on the beat, hue from the bands ---
        for fx in rig.by_role("wash"):
            if isinstance(fx, (Par, WashBar)):
                # VERIFIED ON HARDWARE: Par has a real dimmer channel, same as
                # WashBar (not "baked into color" as previously assumed — that
                # left the dimmer at 0 and the real fixture never lit).
                fx.set_intensity(c, wash_level)
                fx.set_color(c, r, g, b)
                if strobe > 0 and isinstance(fx, WashBar):  # Par has no strobe channel
                    fx.set_strobe(c, strobe)

        # --- moving heads: steady-ish dimmer, mirrored BPM-locked sweep ---
        position = self._musical_position(snap)
        for fx in rig.by_role("spot"):
            fx.set_intensity(c, snap.energy)
            fx.set_color(c, r, g, b)
            mirror = 1.0 if fx.side == "left" else -1.0
            pan = 0.5 + 0.4 * math.sin(position * 0.4) * mirror
            tilt = 0.45 + 0.15 * math.sin(position * 0.2)
            fx.set_position(c, pan, tilt)

        return c

    # ------------------------------------------------------------------ helpers
    def _beat_pulse(self, snap: ShowSnapshot) -> float:
        """1.0 right on the beat, ramping linearly down to PULSE_MIN across the
        WHOLE beat (not a short fixed decay time) — continuous felt movement
        for the full beat instead of a quick flash then a static floor."""
        if snap.bpm <= 0:
            return 0.0
        return 1.0 - (1.0 - PULSE_MIN) * snap.beat_phase

    def _strobe_rate(self, snap: ShowSnapshot) -> float:
        if snap.energy <= STROBE_THRESHOLD:
            return 0.0
        scaled = (snap.energy - STROBE_THRESHOLD) / (1.0 - STROBE_THRESHOLD)
        return min(STROBE_MAX, scaled * STROBE_MAX)

    def _musical_position(self, snap: ShowSnapshot) -> float:
        """Continuous position in beats, for smooth tempo-locked movement."""
        return snap.bar * 4 + (snap.beat_in_bar - 1) + snap.beat_phase

    def _kick_pulse(self, snap: ShowSnapshot) -> float:
        """Wash/par brightness, 0..1, driven by the KICK specifically -- not
        the bassline underneath it, and (with a real, LOCKED beat clock) only
        ON the beat grid, not any other low-end timing. See the module
        docstring above for the three earlier passes this replaces/builds on.
        No real audio (demo mode / MIDI-only fallback): the old beat-locked
        ramp, since there's no real signal to isolate a kick from at all.
        """
        now = self.clock.monotonic()
        dt = (now - self._last_tick_t) if self._last_tick_t is not None else 1 / 60
        self._last_tick_t = now

        if not snap.audio_fresh:
            self._kick_baseline = 0.0
            self._kick_env_raw = 0.0  # don't let a stale reading pollute state on reconnect
            self.kick_level = snap.energy * self._beat_pulse(snap)
            return self.kick_level

        raw = snap.audio_band_low_abs
        baseline_coeff = 1 - math.exp(-dt / BASELINE_TAU_S)
        self._kick_baseline += baseline_coeff * (raw - self._kick_baseline)
        excess = max(0.0, raw / max(self._kick_baseline, BASELINE_FLOOR) - 1.0)

        if snap.pdl_fresh and snap.bpm > 0:
            self.kick_level = self._beat_locked_kick(snap, excess)
        else:
            # no real, locked beat grid to lock to -- fall back to pass 2's
            # continuous envelope (still isolates from a sustained bassline)
            attack = 1 - math.exp(-dt / KICK_ATTACK_S)
            release = 1 - math.exp(-dt / KICK_RELEASE_S)
            coeff = attack if excess > self._kick_env_raw else release
            self._kick_env_raw += coeff * (excess - self._kick_env_raw)
            self.kick_level = max(0.0, min(1.0, self._kick_env_raw * KICK_GAIN))
        return self.kick_level

    def _beat_locked_kick(self, snap: ShowSnapshot, excess: float) -> float:
        """ONE decision per beat: the peak (running max) excess seen during a
        short window after the beat starts. Once that window closes, brightness
        decays over a FIXED, short real-time duration (KICK_DECAY_S) -- not
        "whatever's left of the beat" -- and then holds at true zero until the
        next beat's window opens, so there's a genuine dark gap every beat
        instead of a technically-nonzero glow the whole time. The decay itself
        is driven ONLY by `beat_phase`/tempo, from that already-frozen peak --
        no live audio touches it again. This is what makes it immune to the
        jitter that broke pass 3's hard gate: a max over an interval doesn't
        care about a few ms of wobble in exactly when the peak landed, and a
        fixed decay can't flicker because nothing live is driving it.
        """
        phase = snap.beat_phase
        if phase < self._prev_beat_phase - 0.5:  # wrapped -- a new beat just started
            self._beat_window_peak = 0.0
        self._prev_beat_phase = phase

        beat_dur = 60.0 / snap.bpm
        window_phase = min(0.9, BEAT_WINDOW_S / beat_dur)

        if phase <= window_phase:
            self._beat_window_peak = max(self._beat_window_peak, excess)
            level = self._beat_window_peak  # rising live during the window itself
        else:
            elapsed_s = (phase - window_phase) * beat_dur
            decay = max(0.0, 1.0 - elapsed_s / KICK_DECAY_S)
            level = self._beat_window_peak * decay  # frozen since the window closed

        level01 = max(0.0, min(1.0, level * KICK_GAIN))
        # Tightened the range a tad (Josh, 2026-09-03, after live confirmation the
        # rest of pass 4 was good): full 0->1 swings read as strobe-like. Compress
        # into [KICK_FLOOR, KICK_CEILING] instead of the full range -- everything
        # else (timing, decay shape, gain) unchanged.
        return KICK_FLOOR + (KICK_CEILING - KICK_FLOOR) * level01
