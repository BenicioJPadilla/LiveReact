"""Reactive Layer — the always-on base of the show (docs/02 FR-2.1, docs/12 Phase 3).

Wash/par brightness follows LIGHTING_BIBLE.md's per-energy-state model (§5/
§9.1, 2026-09-08 full-alignment build) — a held constant at DROP, a
structural bar-position ramp at BUILD, a slow non-pulsing "breathing"
envelope at BREAKDOWN/HOLD — rather than one continuous kick-locked pulse
everywhere (see the retirement note near `HUE_UPDATE_BARS` for why, and
what's kept for a possible future accent feature). BPM-locked symmetric
movement on the moving heads and frequency-driven color from the two-axis
model (hue frozen per phrase, §3.8) round out the always-on layer. This is
what makes the rig feel musical even before scenes and transitions exist; it
reads only the metronome's interpolated clock, never raw packet timing.
"""

from __future__ import annotations

import math

from ..clock import Clock
from ..core.show_state import ShowSnapshot
from ..dynamics import musical_bar_position
from ..fixtures.profiles import Par, WashBar
from ..fixtures.rig import Rig
from ..merge.merge import Contribution
from ..scenes.base import EnergyBucket
from ..scenes.catalog import BREAK_MAX, BUILD_MAX
from .color import band_levels, two_axis_color

PULSE_MIN = 0.03        # fallback-only now (see KICK_* below) — used solely when real
                        # audio isn't connected (demo mode / MIDI-only), to keep the
                        # classic beat-locked ramp as a sensible default with no audio
                        # signal to actually trace. near-zero brightness right before
                        # the next beat re-triggers the pulse.
STROBE_THRESHOLD = 0.85  # energy_norm above which a gentle reactive strobe engages -- was
                         # raw snap.energy until 2026-09-07: same fixed-absolute-threshold
                         # flaw as the old bucket_for_energy call (see show_state.py's
                         # energy_norm docstring). Confirmed causing a real complaint via
                         # the offline replay tool: a bass-heavy track's raw energy sat
                         # above 0.85 96% of the whole song, so the strobe gate was open
                         # almost continuously (mechanical 1.5s-on/1.5s-off bursting,
                         # unrelated to the beat grid) -- read live as "turning on and off
                         # randomly, fluttering," not the intended rare accent.
# Named Hz targets from LIGHTING_BIBLE.md §13 (SAFE-01..06, corrected
# 2026-09-08 evidence-verification pass) -- kept here as the DOCUMENTED
# TARGETS, not yet a working Hz clamp: nobody has measured this specific
# wash bar's real DMX-byte-to-Hz curve (photodiode/camera count, per §11's
# own method), and fabricating one would repeat the exact mistake the
# correction pass exists to catch (see spec/conformance.md SAFE-01..06,
# spec/FINDINGS.md). Reference these names once real calibration data
# lets STROBE_MAX below be derived from an actual Hz ceiling instead of
# the conservative placeholder it is now.
SAFETY_STROBE_SUSTAINED_MAX_HZ = 4.0
SAFETY_STROBE_ABSOLUTE_MAX_HZ = 8.0
SAFETY_STROBE_FORBIDDEN_BAND_HZ = (10.0, 25.0)
SAFETY_STROBE_STRICT_MODE_MAX_HZ = 2.0
SAFETY_STROBE_RED_MAX_HZ = 3.0

STROBE_MAX = 0.15       # INTERIM CONSERVATIVE CAP (2026-09-09, Stage 6 audit
                        # fix, Josh's explicit call — see spec/FINDINGS.md
                        # SAFE-01/02/03/05/06): lowered from 0.30 (byte ~76)
                        # to 0.15 (byte ~38) specifically to sit well inside
                        # the wash bar's real manual's own documented "slow"
                        # sub-range (CH2: 0-9 off, 10-255 slow->fast) rather
                        # than assume 76 was safe. This is NOT a measured-safe
                        # value -- it's a deliberately conservative placeholder
                        # chosen because *some* margin below the old cap is
                        # strictly better than none while real Hz calibration
                        # is still outstanding. Raise it only after measuring
                        # this fixture's actual DMX-to-Hz curve, never by
                        # guessing a bigger number feels fine by eye.
# Burst-duration limit (LIGHTING_BIBLE.md §13, 2026-09-08 audit): "assert
# strobe_burst_duration <= 1.5s then a mandatory gap." Previously the reactive
# strobe could stay continuously nonzero for as long as energy stayed above
# STROBE_THRESHOLD -- unbounded, possibly minutes during a sustained loud
# section. This IS enforceable without knowing the real Hz mapping (it's a
# software-side duty-cycle rule, not a hardware-calibration one), so fixed then.
STROBE_MAX_BURST_S = 1.5     # a single continuous strobe MOMENT runs at most this long

# STROBE_MIN_SPACING_S -- CONFIRMED BUGGY, then fixed, 2026-09-08 (real
# --hardware --record capture, see [[livereact-project]] memory): the original
# 1.5s "mandatory gap" was sized to match the burst DURATION, not to space
# separate strobe MOMENTS apart -- so during a sustained kick-heavy passage
# (energy_norm pinned above STROBE_THRESHOLD for 30+ real seconds), the very
# next tick after each 1.5s gap immediately re-triggered a new burst. Replayed
# against tonight's actual captured energy_norm sequence (not guessed): 11
# separate bursts crammed into one 36-second stretch, a continuous mechanical
# on/off/on/off cycle -- confirmed live as "the wash bar trying to keep up
# with the kicks... random stuttering," not the "rare accent" LIGHTING_BIBLE.md
# §13 wants. Second bug, same root cause, fixed here too: a burst that ended
# NATURALLY (energy dropped below threshold before hitting STROBE_MAX_BURST_S)
# used to earn NO gap at all -- only a burst that hit the duration cap did --
# so a moment ending naturally could restart on the very next tick. Both paths
# (hit-the-cap and ended-naturally) now enforce the SAME minimum spacing
# between the end of one moment and the start of the next.
STROBE_MIN_SPACING_S = 8.0    # NOT yet tuned by ear/measurement, this project's
                              # usual caveat -- long enough to break the
                              # confirmed-live chaining into visibly separate
                              # accents, short enough to still land more than
                              # once across a long loud passage.

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

# RETIRED as wash/par's default driver (2026-09-08, LIGHTING_BIBLE.md §5/§13
# full-alignment build), kept intact rather than deleted. All four passes
# above are real, hardware-verified work (see the module docstring history)
# and `_kick_pulse`/`self.kick_level` still run every tick -- just no longer
# feed wash_level below. Why: re-reading the Bible's ACTUAL drop/peak look
# definitions (not just the §13 duty-cap rule) shows kick-following was never
# meant to be the drop's main character at all -- `peak_full_rig` and
# `drop_blackout_hit` are explicitly "reactivity: static, kick_follow:false...
# the cut IS the effect, nothing reacts." The Bible's kick-follow duty cap
# (<=15%, once/bar) describes a rare ACCENT layered on a held look, not a
# continuous per-beat driver. Josh chose full Bible alignment over keeping
# this as the drop's character (a real, deliberate tradeoff — he'd previously
# verified this exact mechanism live and liked it) — see [[livereact-project]]
# for that decision. If a future "sparse accent" feature is built, this is
# the mechanism to reuse, not rebuild.

# Hue frozen at phrase boundaries (LIGHTING_BIBLE.md §3.8, 2026-09-08 audit):
# two_axis_color() used to recompute the dominant band -- and therefore hue --
# every single tick, for every fixture this engine drives. Since the dominant
# band naturally flickers between low/mid/high during ordinary audio
# variation, this caused real hue churn (a likely contributor to the earlier
# "colors feel random/disconnected from the vibe" complaint, previously
# blamed entirely on the energy-pinning bug and never separately addressed).
# Matches PhraseEngine's own ROTATION_BARS cadence -- one shared notion of
# "a phrase," not two different clocks governing scene changes vs. color.
HUE_UPDATE_BARS = 16

# Wash/par brightness driven by energy-state (LIGHTING_BIBLE.md §5 look
# library + §9.1's per-position behavior table), replacing kick-follow as the
# default (see the retirement note above). LiveReact's own EnergyBucket has 4
# states (BREAKDOWN/BUILD/HOLD/DROP), not the Bible's 5 (BREAK/BUILD/DROP/
# PEAK/OUTRO) — DROP here covers both DROP and PEAK; HOLD has NO direct Bible
# equivalent (it's this project's own sustained-mid-energy state, between
# BUILD and DROP) and its numbers below are this project's own extrapolation,
# clearly marked, not sourced from the doc.
#
# DROP ([VERIFIED against the Bible's own look defs] `drop_blackout_hit`:
# "reactivity: static all, kick_follow:false, the cut IS the effect, nothing
# reacts"): held, near-full intensity — NOT continuously audio-tracked
# (matches "static... nothing reacts"). Bible-integration Phase 2 correction
# (2026-09-11, Josh: drop intensity should reflect how loud the real sound
# actually was, not a fixed number regardless of it): the target now comes
# from `snap.drop_hit_intensity` -- captured ONCE, in core/metronome.py, at
# the exact moment DROP was committed, then held static from there (same
# "chosen once, not chased" principle as before, just no longer a flat
# constant). See core/metronome.py's DROP_INTENSITY_FLOOR/CEIL for the range
# it's scaled within (still the Bible's stated 85-100%).

# PEAK (`peak_full_rig`: "wash 85-100%... reactivity: static hue+pan,
# kick_follow:false") -- PEAK is genuinely new (see EnergyBucket's
# docstring, scenes/base.py) and is reached only by escalating out of a
# sustained DROP, never from a raw energy level. Held static like DROP, with
# a small additive boost on top of that SAME drop's captured hit intensity
# -- "more committed than the drop" scales with how big the drop already
# was, rather than jumping to an unrelated fixed ceiling.
PEAK_BOOST = 0.03  # added to snap.drop_hit_intensity, clamped to 1.0

# BUILD (`build_riser_wash`, the Bible's own "canonical build"): "intensity
# climbs across the build... the ramp IS the build; drive it from bar
# position, not audio, to stay predictable." Structural, not audio-reactive
# at all -- deliberately the opposite of kick-follow. Phase 2: this range now
# also covers the old HOLD bucket's energy (0.55-0.80, folded in per Open
# Question #1) -- the ramp formula itself is unchanged, just a wider energy
# range now reads as "still building" rather than downgrading to a calmer
# breathing look.
BUILD_RAMP_BARS = 8.0   # the Bible's own typical build length
BUILD_LOW = 0.2         # Bible: "20->95%"
BUILD_HIGH = 0.95

# BREAK (`break_low_wash`; renamed from BREAKDOWN, Phase 2, naming match only
# -- same concept): "a break has no transients to chase, so only a slow
# envelope earns reactivity... wash 15-35%." A heavily low-pass-filtered
# version of real energy -- a slow "breathing" rise/fall, not beat-locked
# spikes. BREAK_BREATH_TAU_S itself isn't given an exact number by the doc; a
# few seconds is what "slow envelope"/"breathing" implies, NOT yet tuned by
# ear on real hardware.
BREAK_LOW = 0.15
BREAK_HIGH = 0.35
BREAK_BREATH_TAU_S = 3.0

# OUTRO (`outro_fade_wash`: "wash 40->15%") -- Bible-integration Phase 2:
# genuinely new, reached only by promoting out of BREAK after a recent
# DROP/PEAK (see core/metronome.py's `_derive_bucket`), never from a raw
# energy level. A slow, one-way bar-position-driven fade (same mechanism
# shape as BUILD's ramp, just descending) rather than a breathing envelope --
# "warm fade, decreasing intensity" is a one-time decay, not an ongoing
# oscillation.
OUTRO_FADE_BARS = 16.0  # matches outro_fade_wash's own min_hold
OUTRO_HIGH = 0.40
OUTRO_LOW = 0.15

# Crossfade across a BUCKET CHANGE itself (2026-09-07, first real --hardware
# --record capture, see [[livereact-project]] memory): each branch above
# computes its own brightness independently, so a bucket flip used to just
# overwrite `self.wash_level` outright -- a real capture showed jumps up to
# |0.67| in a single ~40ms tick (e.g. DROP's held 0.9 landing straight on
# BUILD's freshly-reset 0.2 the instant BUILD was re-entered). Combined with
# 26 bucket flips in one real ~4min song, that read exactly like Josh's live
# report: the wash bar "turning off and fluttering... doing some randomness."
# Fix: blend `wash_level` toward the new bucket's target over
# WASH_CROSSFADE_TAU_S instead of snapping, for every transition EXCEPT
# entering DROP -- LIGHTING_BIBLE.md's own peak_full_rig/drop_blackout_hit
# looks are explicit that "the cut IS the effect," so a drop landing should
# stay a hard, instant hit; every other seam (including LEAVING drop) gets
# smoothed. This is a blend on the SEAM only, not a permanent filter -- once
# WASH_TRANSITION_WINDOW_S has passed, control reverts to the bucket's own
# formula directly, so BUILD's ramp/HOLD's & BREAKDOWN's breathing behave
# exactly as before (and their own existing tests still hold) once settled.
WASH_CROSSFADE_TAU_S = 0.6
WASH_TRANSITION_WINDOW_S = 3 * WASH_CROSSFADE_TAU_S  # ~95% converged by then


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
        self._strobe_burst_start: float | None = None  # when the current continuous burst began
        self._strobe_gap_until: float = 0.0             # can't strobe again until this time
        self._hue_idx = 0           # frozen hue-anchor band index (0=low/1=mid/2=high)
        self._hue_update_bar: int | None = None  # which HUE_UPDATE_BARS bucket _hue_idx was picked in
        self._prev_bucket: EnergyBucket | None = None    # to detect a bucket change
        self._build_entry_pos: float | None = None       # musical position (bars) BUILD was entered at
        self._break_breath = 0.0        # slow low-pass envelope, BREAK's "breathing"
        self._outro_entry_pos: float | None = None  # bar position OUTRO was entered at, for its fade
        self._last_bucket_tick_t: float | None = None    # dt for the breathing envelopes above
        self.wash_level = 0.0       # exposed for the console/tests: last computed 0..1 wash/par level
        self._wash_transition_until = 0.0  # see WASH_CROSSFADE_TAU_S above -- 0.0 means "no
                                            # active blend," which also correctly makes the
                                            # very first tick ever a direct assignment (any
                                            # real monotonic clock reads > 0.0)

    @property
    def name(self) -> str:
        return "reactive"

    def tick(self, snap: ShowSnapshot, rig: Rig) -> Contribution:
        c = Contribution()
        self._maybe_update_hue(snap)
        r, g, b = two_axis_color(snap, hue_idx=self._hue_idx)
        self._kick_pulse(snap)  # still computed every tick (see the retirement note
                                 # above) -- kept "live" for `self.kick_level` and any
                                 # future accent feature, just not used for wash_level
        wash_level = self._bucket_wash_level(snap)
        strobe = self._strobe_burst_gate(self._strobe_rate(snap))

        # --- washes: bucket-driven brightness (LIGHTING_BIBLE.md §5/§9.1), hue from the bands ---
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
        if snap.energy_norm <= STROBE_THRESHOLD:
            return 0.0
        scaled = (snap.energy_norm - STROBE_THRESHOLD) / (1.0 - STROBE_THRESHOLD)
        return min(STROBE_MAX, scaled * STROBE_MAX)

    def _strobe_burst_gate(self, rate: float) -> float:
        """Cap a single continuous strobe MOMENT at STROBE_MAX_BURST_S, then
        enforce STROBE_MIN_SPACING_S before the next one can start (LIGHTING_
        BIBLE.md §13) — CONFIRMED BUGGY then fixed 2026-09-08 (see
        STROBE_MIN_SPACING_S's own comment above for the full story): a moment
        ending EITHER way (hit the duration cap, or energy simply dropped
        below threshold first) now earns the same minimum spacing before a new
        one is allowed to start, so a sustained loud section can't chain
        moments back-to-back with only a token gap between them."""
        now = self.clock.monotonic()
        if now < self._strobe_gap_until:
            return 0.0  # serving the minimum spacing before a new moment can start
        if rate <= 0.0:
            if self._strobe_burst_start is not None:
                # the moment just ended naturally -- this earns the same
                # cooldown as hitting the duration cap (both are "the moment
                # is over," just two different reasons for it ending)
                self._strobe_burst_start = None
                self._strobe_gap_until = now + STROBE_MIN_SPACING_S
            return 0.0
        if self._strobe_burst_start is None:
            self._strobe_burst_start = now
        if now - self._strobe_burst_start >= STROBE_MAX_BURST_S:
            self._strobe_gap_until = now + STROBE_MIN_SPACING_S
            self._strobe_burst_start = None
            return 0.0
        return rate

    def _musical_position(self, snap: ShowSnapshot) -> float:
        """Continuous position in beats, for smooth tempo-locked movement."""
        return snap.bar * 4 + (snap.beat_in_bar - 1) + snap.beat_phase

    def _maybe_update_hue(self, snap: ShowSnapshot) -> None:
        """Re-pick the frozen hue-anchor band only when we've crossed into a
        new HUE_UPDATE_BARS bucket (LIGHTING_BIBLE.md §3.8) -- otherwise leave
        `self._hue_idx` exactly as it was, so two_axis_color's hue stays fixed
        for the whole phrase regardless of how the live audio bounces around
        tick to tick."""
        bucket = int(snap.bar) // HUE_UPDATE_BARS
        if bucket == self._hue_update_bar:
            return
        self._hue_update_bar = bucket
        low, mid, high = band_levels(snap)
        bands = (low, mid, high)
        if max(bands) > 0.0:
            self._hue_idx = bands.index(max(bands))

    def _bucket_wash_level(self, snap: ShowSnapshot) -> float:
        """Wash/par brightness per LIGHTING_BIBLE.md's per-energy-state model
        (see the module-level constants above for exactly what's Bible-
        sourced vs. this project's own extrapolation for PEAK/OUTRO's exact
        numbers). Replaces kick-follow as the default driver -- see the
        retirement note above `HUE_UPDATE_BARS`."""
        now = self.clock.monotonic()
        dt = (now - self._last_bucket_tick_t) if self._last_bucket_tick_t is not None else 1 / 60
        self._last_bucket_tick_t = now

        # snap.bucket -- an ALREADY-DEBOUNCED, already-escalated (PEAK/OUTRO
        # included) bucket, computed once in metronome.py, NOT a fresh call
        # here. energy_norm itself (vs. raw snap.energy) matters too --
        # bucket thresholds are meaningless against a fixed absolute number
        # tuned to one mixer gain staging (found live 2026-09-07: a real drop
        # never crossed the old raw-energy DROP threshold at all). See
        # show_state.py's bucket/energy_norm docstrings.
        energy_bucket = EnergyBucket(snap.bucket)
        # BARS, not beats -- `_musical_position` (used by MH movement) is
        # beat-denominated; a "BUILD_RAMP_BARS" ramp needs the bar-denominated
        # helper instead, or it completes 4x too fast (found via testing).
        pos = musical_bar_position(snap)
        # Unguarded (fires on the very first tick too, prev_bucket=None ->
        # always "entering" -- matches this ramp's pre-existing behavior of
        # always starting a fresh BUILD from a real entry point, not just on
        # a later re-entry).
        entering_new_bucket = energy_bucket != self._prev_bucket
        if entering_new_bucket and energy_bucket == EnergyBucket.BUILD:
            self._build_entry_pos = pos
        if entering_new_bucket and energy_bucket == EnergyBucket.OUTRO:
            self._outro_entry_pos = pos
        # Crossfade-arming is guarded on `self._prev_bucket is not None`,
        # UNLIKE the build-entry reset above: the engine's very first tick
        # ever has no meaningful prior state to blend FROM, and must land
        # exactly on its bucket's target (existing tests rely on this) --
        # which `now >= self._wash_transition_until` already gives it for
        # free (0.0 initial value) as long as this stays unarmed that tick.
        # DROP and PEAK both stay instant snaps (not just DROP) -- PEAK is an
        # escalation of an already-instant DROP hit, not a fresh transition
        # that should ease in.
        if self._prev_bucket is not None and entering_new_bucket and energy_bucket not in (
            EnergyBucket.DROP, EnergyBucket.PEAK,
        ):
            # (Re-)arm the crossfade window -- see WASH_CROSSFADE_TAU_S above.
            self._wash_transition_until = now + WASH_TRANSITION_WINDOW_S
        self._prev_bucket = energy_bucket

        if energy_bucket == EnergyBucket.DROP:
            target = snap.drop_hit_intensity  # how loud THIS hit was, captured once (core/metronome.py)
        elif energy_bucket == EnergyBucket.PEAK:
            target = min(1.0, snap.drop_hit_intensity + PEAK_BOOST)
        elif energy_bucket == EnergyBucket.BUILD:
            entry = self._build_entry_pos if self._build_entry_pos is not None else pos
            progress = max(0.0, min(1.0, (pos - entry) / BUILD_RAMP_BARS))
            target = BUILD_LOW + (BUILD_HIGH - BUILD_LOW) * progress
        elif energy_bucket == EnergyBucket.OUTRO:
            entry = self._outro_entry_pos if self._outro_entry_pos is not None else pos
            progress = max(0.0, min(1.0, (pos - entry) / OUTRO_FADE_BARS))
            target = OUTRO_HIGH + (OUTRO_LOW - OUTRO_HIGH) * progress  # descending
        else:  # BREAK
            # Normalize energy WITHIN this bucket's own range (0..BREAK_MAX)
            # before using it as the breathing target -- using the raw value
            # directly (found via testing) can never actually reach
            # BREAK_HIGH, since it's capped below BREAK_MAX by definition of
            # being in this bucket at all. energy_norm, not raw snap.energy --
            # same reasoning as the bucket boundary above, this threshold
            # means nothing against a fixed absolute number.
            breath_target = min(1.0, snap.energy_norm / BREAK_MAX)
            coeff = 1 - math.exp(-dt / BREAK_BREATH_TAU_S)
            self._break_breath += coeff * (breath_target - self._break_breath)
            target = BREAK_LOW + (BREAK_HIGH - BREAK_LOW) * self._break_breath

        if energy_bucket in (EnergyBucket.DROP, EnergyBucket.PEAK) or now >= self._wash_transition_until:
            self.wash_level = target  # settled, or a deliberately-instant DROP/PEAK cut
        else:
            crossfade_coeff = 1 - math.exp(-dt / WASH_CROSSFADE_TAU_S)
            self.wash_level += crossfade_coeff * (target - self.wash_level)
        return self.wash_level

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
