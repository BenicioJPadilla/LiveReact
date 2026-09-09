"""Tests for the Reactive Layer engine."""

from __future__ import annotations

import pytest

from livereact.clock import FakeClock
from livereact.core.show_state import ShowSnapshot
from livereact.engines.reactive import STROBE_MAX, ReactiveLayerEngine
from livereact.fixtures.rig import load_rig
from livereact.scenes.catalog import bucket_for_energy


def _snap(**kw) -> ShowSnapshot:
    base = dict(bpm=120.0, energy=0.8, fader_a=1.0, eq_low_a=1.0, eq_mid_a=0.2, eq_high_a=0.2)
    base.update(kw)
    # bucket_for_energy reads energy_norm, not raw energy (2026-09-07, found
    # live) -- default it to match energy so existing tests that only set
    # `energy=` still exercise the bucket they intend to, unless a test
    # explicitly passes energy_norm to test the distinction.
    base.setdefault("energy_norm", base["energy"])
    # snap.bucket is normally an ALREADY-DEBOUNCED value from metronome.py
    # (BUCKET_MIN_DWELL_S) -- these are unit tests of the engine directly, not
    # of the debounce, so default it to whatever bucket_for_energy would say
    # for this snapshot's own energy_norm, unless a test explicitly overrides
    # it to exercise a mismatch.
    base.setdefault("bucket", bucket_for_energy(base["energy_norm"]).value)
    return ShowSnapshot(**base)


def test_pulse_peaks_on_the_beat_and_decays_across_it():
    """kick_pulse/kick_level is retired as wash's default driver (2026-09-08,
    LIGHTING_BIBLE.md full-alignment build -- see reactive.py's retirement
    note) but still computed every tick for a possible future accent
    feature. This checks the retained mechanism itself still works, not
    wash's actual DMX output (see the bucket-model tests further down for
    that)."""
    rig = load_rig()
    eng = ReactiveLayerEngine(FakeClock())

    eng.tick(_snap(beat_phase=0.0), rig)
    on_beat = eng.kick_level
    eng.tick(_snap(beat_phase=0.5), rig)
    mid_beat = eng.kick_level
    eng.tick(_snap(beat_phase=0.9), rig)
    late_beat = eng.kick_level

    assert on_beat > mid_beat > late_beat  # single peak, monotonic decay


def test_color_follows_band_dominance_across_phrase_boundaries():
    """LIGHTING_BIBLE.md §3.8: hue is frozen within a phrase (see the hue-freeze
    tests below) but DOES follow real dominance once a new phrase begins."""
    rig = load_rig()
    eng = ReactiveLayerEngine(FakeClock())
    par = rig.fixture("par_l")  # ch1=dimmer, R,G,B at offset+1..offset+3

    red = eng.tick(_snap(bar=0, beat_phase=0.0, eq_low_a=1.0, eq_mid_a=0.2, eq_high_a=0.2), rig)
    assert red.values[par.offset + 1] > red.values[par.offset + 3]  # R > B

    # a new HUE_UPDATE_BARS (16) phrase begins, with a different dominant band
    cyan = eng.tick(_snap(bar=16, beat_phase=0.0, eq_high_a=1.0, eq_low_a=0.2, eq_mid_a=0.2), rig)
    assert cyan.values[par.offset + 3] > cyan.values[par.offset + 1]  # B > R


def test_hue_stays_frozen_within_the_same_phrase():
    """The actual bug this fixes (2026-09-08 audit): two_axis_color used to
    recompute hue every tick, so the dominant band flickering mid-phrase (real
    audio does this constantly) caused visible hue churn. Now it shouldn't
    change until a new HUE_UPDATE_BARS phrase begins."""
    rig = load_rig()
    eng = ReactiveLayerEngine(FakeClock())
    par = rig.fixture("par_l")

    red = eng.tick(_snap(bar=0, beat_phase=0.0, eq_low_a=1.0, eq_mid_a=0.2, eq_high_a=0.2), rig)
    assert red.values[par.offset + 1] > red.values[par.offset + 3]  # R > B

    # still bar 0 (same phrase) -- even though the dominant band has flipped
    # to high, the hue must stay frozen on low (red) until the next phrase
    still_red = eng.tick(_snap(bar=0, beat_phase=0.5, eq_high_a=1.0,
                                eq_low_a=0.2, eq_mid_a=0.2), rig)
    assert still_red.values[par.offset + 1] > still_red.values[par.offset + 3]  # still R > B


def test_hue_updates_at_the_next_phrase_boundary():
    rig = load_rig()
    eng = ReactiveLayerEngine(FakeClock())
    par = rig.fixture("par_l")

    eng.tick(_snap(bar=0, beat_phase=0.0, eq_low_a=1.0, eq_mid_a=0.2, eq_high_a=0.2), rig)
    # bar 15 is still within the first 16-bar phrase -- even with high now
    # dominant, hue must stay frozen on the phrase's original pick (red)
    still_red = eng.tick(_snap(bar=15, beat_phase=0.0, eq_high_a=1.0,
                                eq_low_a=0.2, eq_mid_a=0.2), rig)
    assert still_red.values[par.offset + 1] > still_red.values[par.offset + 3]

    # bar 16 crosses into the next phrase -- now it's allowed to re-pick
    new_phrase = eng.tick(_snap(bar=16, beat_phase=0.0, eq_high_a=1.0,
                                 eq_low_a=0.2, eq_mid_a=0.2), rig)
    assert new_phrase.values[par.offset + 3] > new_phrase.values[par.offset + 1]  # B > R now


def test_moving_heads_mirror_left_and_right():
    rig = load_rig()
    eng = ReactiveLayerEngine(FakeClock())
    c = eng.tick(_snap(bar=2, beat_in_bar=3, beat_phase=0.25), rig)
    mh_l, mh_r = rig.fixture("mh_l"), rig.fixture("mh_r")
    # Pan is mirrored around center (128), so the two heads sit on opposite sides.
    assert c.values[mh_l.offset] != c.values[mh_r.offset]


def test_low_energy_keeps_strobe_off():
    rig = load_rig()
    eng = ReactiveLayerEngine(FakeClock())
    bar = rig.fixture("bar_l")
    c = eng.tick(_snap(energy=0.5, beat_phase=0.0), rig)
    assert c.values[bar.offset + 1] == 0  # strobe ch2 off below threshold


def test_high_energy_engages_capped_strobe():
    """Cap value itself is a Stage 6 audit fix (spec/FINDINGS.md SAFE-01/02/
    03/05/06): lowered from 0.30 to 0.15 as an interim conservative
    placeholder pending real Hz calibration -- import STROBE_MAX rather than
    hardcode it here, so this test can't silently drift from the real
    constant again."""
    rig = load_rig()
    eng = ReactiveLayerEngine(FakeClock())
    bar = rig.fixture("bar_l")
    c = eng.tick(_snap(energy=1.0, beat_phase=0.0), rig)
    strobe = c.values[bar.offset + 1]
    assert 0 < strobe <= int(STROBE_MAX * 255) + 1  # engaged but conservatively capped


# --- strobe burst-duration cap + minimum spacing (LIGHTING_BIBLE.md §13,
# 2026-09-08 audit; spacing CONFIRMED BUGGY then fixed same-day evening via a
# real --hardware --record capture, see [[livereact-project]] memory and
# STROBE_MIN_SPACING_S's own comment in reactive.py for the full story) ---
# Previously a sustained loud section could hold the strobe on indefinitely --
# no burst-duration limit at all. Capped at STROBE_MAX_BURST_S, then a gap --
# but the FIRST gap value (1.5s, sized to match the burst duration, not to
# space separate moments apart) let a sustained loud section re-trigger
# almost immediately, confirmed live as a continuous on/off "stutter," not a
# rare accent. STROBE_MIN_SPACING_S (8.0s) replaces it, and now applies
# whether a moment ends by hitting the cap OR by energy simply dropping first
# -- both used to be handled differently, which was itself part of the bug.


def test_strobe_cuts_off_after_the_max_burst_duration():
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    bar = rig.fixture("bar_l")
    # sustained high energy throughout -- would strobe continuously without the gate
    c = eng.tick(_snap(energy=1.0, beat_phase=0.0), rig)
    assert c.values[bar.offset + 1] > 0  # engaged at the start of the burst
    clock.advance(1.5)  # == STROBE_MAX_BURST_S
    c = eng.tick(_snap(energy=1.0, beat_phase=0.0), rig)
    assert c.values[bar.offset + 1] == 0  # forced dark once the burst limit is hit


def test_strobe_stays_off_for_the_minimum_spacing_then_resumes():
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    bar = rig.fixture("bar_l")
    eng.tick(_snap(energy=1.0, beat_phase=0.0), rig)
    clock.advance(1.5)
    eng.tick(_snap(energy=1.0, beat_phase=0.0), rig)  # burst cap trips here
    clock.advance(5.0)  # still well within STROBE_MIN_SPACING_S (8.0s)
    c = eng.tick(_snap(energy=1.0, beat_phase=0.0), rig)
    assert c.values[bar.offset + 1] == 0  # still gapped, even though energy is still high
    clock.advance(3.1)  # now past the 8.0s minimum spacing
    c = eng.tick(_snap(energy=1.0, beat_phase=0.0), rig)
    assert c.values[bar.offset + 1] > 0  # allowed to strobe again


def test_strobe_ending_naturally_also_earns_the_minimum_spacing():
    """THE ACTUAL CONFIRMED BUG (2026-09-08 real capture): a moment ending
    naturally (energy drops below threshold before hitting the duration cap)
    used to earn NO spacing at all -- only hitting the cap did -- so a
    sustained kick-heavy passage could re-trigger on literally the next tick.
    Replayed against real captured energy_norm: 11 separate bursts crammed
    into 36 real seconds. Both paths must now enforce the same spacing."""
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    bar = rig.fixture("bar_l")
    eng.tick(_snap(energy=1.0, beat_phase=0.0), rig)
    clock.advance(0.5)  # well under the 1.5s cap
    eng.tick(_snap(energy=0.5, beat_phase=0.0), rig)  # energy drops, strobe naturally off
    clock.advance(0.1)  # nowhere near STROBE_MIN_SPACING_S (8.0s)
    c = eng.tick(_snap(energy=1.0, beat_phase=0.0), rig)
    assert c.values[bar.offset + 1] == 0  # gated -- a natural end earns spacing too now
    clock.advance(8.0)  # now past the minimum spacing
    c = eng.tick(_snap(energy=1.0, beat_phase=0.0), rig)
    assert c.values[bar.offset + 1] > 0  # allowed to strobe again


# --- kick-envelope-follower (docs/14 §5, REDESIGNED 2026-09-03) -------------
# Replaces the old beat-locked-ramp + relative-onset-gate design (which flapped
# on/off and could keep re-triggering through real silence — both confirmed
# live). Wash/par brightness now directly envelope-follows `audio_band_low_abs`:
# no onset detector, no on/off gate, so there's nothing to flap or get stuck.


def test_no_real_audio_falls_back_to_the_classic_beat_locked_pulse():
    """Demo mode / MIDI-only fallback never has real audio — there's no signal
    to trace, so kick_level (retained mechanism, see the test above) falls
    back to the old mechanical beat-locked ramp instead of going dark."""
    rig = load_rig()
    eng = ReactiveLayerEngine(FakeClock())
    eng.tick(_snap(audio_fresh=False, beat_phase=0.0), rig)
    on_beat = eng.kick_level
    eng.tick(_snap(audio_fresh=False, beat_phase=0.9), rig)
    late_beat = eng.kick_level
    assert on_beat > late_beat


def test_true_silence_produces_no_brightness():
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    for _ in range(10):
        eng.tick(_snap(audio_fresh=True, audio_band_low_abs=0.0), rig)
        clock.advance(0.05)
    assert eng.kick_level == 0


def _warm_up_baseline(eng: ReactiveLayerEngine, rig, clock: FakeClock,
                       level: float, ticks: int = 300, dt: float = 0.02, **snap_kw) -> None:
    """Run enough ticks on a STEADY low-band level (~5x BASELINE_TAU_S) to let
    the slow baseline converge close to it, simulating an ongoing bassline
    with no kick transient riding on top."""
    for _ in range(ticks):
        eng.tick(_snap(audio_fresh=True, audio_band_low_abs=level, **snap_kw), rig)
        clock.advance(dt)


def test_a_sustained_bassline_alone_does_not_light_the_wash():
    """The actual bug from live testing (2026-09-03): the previous design (raw
    magnitude, no baseline) lit up on a sustained bassline directly, which
    Josh explicitly does not want -- only the kick itself should drive these
    two fixtures. Once the baseline has converged on a steady bass level, that
    same level should produce ~no brightness."""
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    _warm_up_baseline(eng, rig, clock, level=8.0)
    eng.tick(_snap(audio_fresh=True, audio_band_low_abs=8.0), rig)
    assert eng.kick_level <= 0.01  # baseline converged; no transient excess left


def test_a_kick_above_the_bassline_still_lights_up():
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    _warm_up_baseline(eng, rig, clock, level=8.0)
    eng.tick(_snap(audio_fresh=True, audio_band_low_abs=20.0), rig)
    assert eng.kick_level > 0.15  # a real transient above the established bassline pokes through


def test_excess_decays_back_toward_baseline_after_the_transient_passes():
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    _warm_up_baseline(eng, rig, clock, level=8.0)
    eng.tick(_snap(audio_fresh=True, audio_band_low_abs=20.0), rig)
    peak = eng.kick_level
    clock.advance(0.15)  # a beat's worth of gap, bass returns to its normal level
    eng.tick(_snap(audio_fresh=True, audio_band_low_abs=8.0), rig)
    assert eng.kick_level < peak


# A beat-timing gate (only let a transient register in a short window after
# each real beat) was tried and REVERTED here (2026-09-03, same session) --
# it made output non-deterministic against a repeating musical pattern (see
# the module docstring's "Pass 3 TRIED, then REVERTED" note).
#
# --- pass 4: peak-and-hold, locked to the beat grid (2026-09-03) ------------
# The structural fix: decide the peak ONCE per beat (a running max within a
# window, not a threshold on a live signal), then freeze it -- the rest of
# the beat is a fixed decay off `beat_phase` alone, untouched by live audio.
# Only engages with a real, LOCKED beat clock (`pdl_fresh=True`); otherwise
# falls back to pass 2's continuous envelope (tests above, which don't set
# pdl_fresh, already cover that path).


def test_a_kick_in_the_window_rises_live_when_pdl_is_locked():
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    _warm_up_baseline(eng, rig, clock, level=8.0)
    eng.tick(_snap(audio_fresh=True, pdl_fresh=True, bpm=120.0, beat_phase=0.0,
                    audio_band_low_abs=20.0), rig)
    assert eng.kick_level > 0.15


def test_a_beat_with_no_real_kick_stays_near_the_floor_when_pdl_is_locked():
    """"Dark" means KICK_FLOOR now, not literal zero -- the range was
    deliberately tightened (2026-09-03) so it doesn't read as strobe-like."""
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    _warm_up_baseline(eng, rig, clock, level=8.0)
    eng.tick(_snap(audio_fresh=True, pdl_fresh=True, bpm=120.0, beat_phase=0.0,
                    audio_band_low_abs=8.0), rig)  # no excess over baseline
    assert eng.kick_level <= 0.05  # near KICK_FLOOR (0.02), not literal zero


def test_after_the_window_closes_new_audio_is_ignored_until_the_next_beat():
    """The actual fix for pass 3's jitter bug: once the detection window closes,
    NOTHING live can change this beat's brightness anymore -- confirmed here by
    feeding a huge new spike late in the beat and showing it's ignored."""
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    _warm_up_baseline(eng, rig, clock, level=8.0)

    eng.tick(_snap(audio_fresh=True, pdl_fresh=True, bpm=120.0, beat_phase=0.0,
                    audio_band_low_abs=12.0), rig)  # a real kick, within the window
    eng.tick(_snap(audio_fresh=True, pdl_fresh=True, bpm=120.0, beat_phase=0.5,
                    audio_band_low_abs=0.0), rig)
    decaying = eng.kick_level
    # a huge NEW spike arrives late in the same beat, well past the window -- must be ignored
    eng.tick(_snap(audio_fresh=True, pdl_fresh=True, bpm=120.0, beat_phase=0.6,
                    audio_band_low_abs=50.0), rig)
    assert eng.kick_level < decaying  # still just decaying along the fixed curve, unaffected


def test_the_next_beats_window_reopens_and_can_register_a_new_kick():
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    _warm_up_baseline(eng, rig, clock, level=8.0)

    eng.tick(_snap(audio_fresh=True, pdl_fresh=True, bpm=120.0, beat_phase=0.0,
                    audio_band_low_abs=12.0), rig)
    eng.tick(_snap(audio_fresh=True, pdl_fresh=True, bpm=120.0, beat_phase=0.9,
                    audio_band_low_abs=0.0), rig)  # decayed most of the way through
    # next beat starts (phase wraps back to ~0) with a fresh kick
    eng.tick(_snap(audio_fresh=True, pdl_fresh=True, bpm=120.0, beat_phase=0.0,
                    audio_band_low_abs=20.0), rig)
    assert eng.kick_level > 0.15


def test_identical_repeating_beats_produce_identical_output():
    """The exact property pass 3 violated, confirmed live on a repeating 8-beat
    loop (Josh: "inconsistently inconsistent"). Feed the SAME two-beat pattern
    twice and require the second repetition to match the first at each
    corresponding phase."""
    # Checks eng.kick_level (the retained mechanism, see the retirement note
    # in reactive.py) rather than wash's actual DMX output -- with the
    # bucket-driven model, _snap()'s default energy=0.8 lands in DROP, whose
    # output is a flat constant regardless of the kick pattern, which would
    # make this determinism check trivially/vacuously true against wash's
    # real output now.
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    _warm_up_baseline(eng, rig, clock, level=8.0)

    def play_one_beat(kick_abs: float) -> list[float]:
        out = []
        for phase in (0.0, 0.05, 0.15, 0.3, 0.5, 0.7, 0.9):
            abs_level = kick_abs if phase == 0.0 else 8.0
            eng.tick(_snap(audio_fresh=True, pdl_fresh=True, bpm=120.0,
                            beat_phase=phase, audio_band_low_abs=abs_level), rig)
            out.append(eng.kick_level)
        return out

    first_pass = [play_one_beat(20.0), play_one_beat(8.0)]   # beat with kick, beat without
    second_pass = [play_one_beat(20.0), play_one_beat(8.0)]  # the identical pattern again
    assert first_pass == second_pass


# --- bucket-driven wash/par model (LIGHTING_BIBLE.md §5/§9.1, 2026-09-08) ---
# Replaces kick-follow as wash/par's default (see reactive.py's retirement
# note): DROP is a held constant, BUILD ramps structurally from bar position,
# BREAKDOWN/HOLD get a slow non-pulsing "breathing" envelope.


def test_drop_bucket_holds_a_constant_intensity_regardless_of_beat():
    """peak_full_rig/drop_blackout_hit: "reactivity: static, kick_follow:
    false" -- DROP must NOT vary with beat_phase or kick data at all."""
    rig = load_rig()
    eng = ReactiveLayerEngine(FakeClock())
    bar = rig.fixture("bar_l")
    on_beat = eng.tick(_snap(energy=0.9, beat_phase=0.0, audio_band_low_abs=50.0), rig)
    late_beat = eng.tick(_snap(energy=0.9, beat_phase=0.9, audio_band_low_abs=0.0), rig)
    assert on_beat.values[bar.offset] == late_beat.values[bar.offset] == 202  # DROP_INTENSITY=0.9


def test_build_bucket_ramps_from_bar_position_not_audio():
    """build_riser_wash: "the ramp IS the build; drive it from bar position,
    not audio" -- climbs over BUILD_RAMP_BARS (8) regardless of kick data.
    Checks eng.wash_level (the continuous pre-gamma-curve value) directly --
    the actual DMX byte goes through a nonlinear curve (LIGHTING_BIBLE.md
    §3.7), so a naive linear byte comparison would be testing the wrong
    thing (found via testing)."""
    rig = load_rig()
    eng = ReactiveLayerEngine(FakeClock())

    eng.tick(_snap(energy=0.4, bar=0, beat_in_bar=1, beat_phase=0.0,
                    audio_band_low_abs=0.0), rig)
    start = eng.wash_level
    eng.tick(_snap(energy=0.4, bar=4, beat_in_bar=1, beat_phase=0.0,
                    audio_band_low_abs=999.0), rig)  # audio ignored
    mid = eng.wash_level
    eng.tick(_snap(energy=0.4, bar=8, beat_in_bar=1, beat_phase=0.0,
                    audio_band_low_abs=0.0), rig)
    full = eng.wash_level

    assert start == 0.2                    # BUILD_LOW
    assert mid == pytest.approx(0.575)     # halfway: 0.2 + 0.5*(0.95-0.2)
    assert full == 0.95                    # BUILD_HIGH
    assert start < mid < full


def test_build_ramp_restarts_on_a_fresh_entry():
    """Leaving BUILD and re-entering later must restart the ramp from
    BUILD_LOW, not continue from wherever it left off. Re-entry now crosses
    the bucket-change CROSSFADE (2026-09-07, see WASH_CROSSFADE_TAU_S in
    reactive.py) since this is a DROP->BUILD transition, not a DROP entry --
    so the immediate value blends toward BUILD_LOW rather than snapping,
    settling there once WASH_TRANSITION_WINDOW_S has passed."""
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)

    eng.tick(_snap(energy=0.4, bar=0, beat_in_bar=1, beat_phase=0.0), rig)
    eng.tick(_snap(energy=0.4, bar=8, beat_in_bar=1, beat_phase=0.0), rig)  # ramp completes
    eng.tick(_snap(energy=0.9, bar=9, beat_in_bar=1, beat_phase=0.0), rig)  # a drop happens
    assert eng.wash_level == 0.9  # DROP_INTENSITY -- entering DROP always snaps instantly

    clock.advance(0.05)
    eng.tick(_snap(energy=0.4, bar=20, beat_in_bar=1, beat_phase=0.0), rig)  # BUILD re-entered
    just_after = eng.wash_level
    assert 0.2 < just_after < 0.9  # blending toward BUILD_LOW, not yet snapped either way

    clock.advance(2.0)  # past WASH_TRANSITION_WINDOW_S -- blend has settled
    eng.tick(_snap(energy=0.4, bar=20, beat_in_bar=1, beat_phase=0.0), rig)
    assert eng.wash_level == 0.2  # back to BUILD_LOW, not still at BUILD_HIGH/DROP


def test_breakdown_bucket_breathes_slowly_toward_its_range():
    """break_low_wash: "a break has no transients to chase, so only a slow
    envelope earns reactivity" -- rises gradually, never instantly, and
    never leaves the Bible's stated 15-35% range."""
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)

    eng.tick(_snap(energy=0.25, beat_phase=0.0), rig)
    first = eng.wash_level
    for _ in range(50):
        clock.advance(0.5)
        eng.tick(_snap(energy=0.25, beat_phase=0.0), rig)
    settled = eng.wash_level

    assert first < settled  # rose over time, didn't jump instantly
    for value in (first, settled):
        assert 0.15 <= value <= 0.35


def test_non_drop_bucket_change_crossfades_instead_of_snapping():
    """The generalized fix (2026-09-07 real --hardware --record capture, see
    [[livereact-project]] memory): NOT just BUILD's own restart (see the test
    above) -- ANY bucket change other than entering DROP should blend, not
    snap. The confirmed-live capture's flutter was dominated by DROP<->HOLD/
    BUILD swings, but the mechanism applies to every non-DROP seam, e.g. a
    real HOLD->BREAKDOWN drop-off."""
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)

    # settle into HOLD at a clearly mid-range level
    for _ in range(20):
        eng.tick(_snap(energy=0.65, beat_phase=0.0), rig)
        clock.advance(0.5)
    # one more tick right after the loop's last advance, so _last_bucket_tick_t
    # reflects "now" -- otherwise the upcoming small clock.advance(0.05) would
    # actually hand the crossfade the loop's full unconsumed 0.5s dt instead
    eng.tick(_snap(energy=0.65, beat_phase=0.0), rig)
    settled_hold = eng.wash_level
    assert 0.35 <= settled_hold <= 0.65

    # drop straight to BREAKDOWN
    clock.advance(0.05)
    eng.tick(_snap(energy=0.15, beat_phase=0.0), rig)
    just_after = eng.wash_level
    assert just_after > 0.35  # still blending down, not snapped into BREAKDOWN's own range yet

    clock.advance(2.0)  # past WASH_TRANSITION_WINDOW_S -- blend has settled
    eng.tick(_snap(energy=0.15, beat_phase=0.0), rig)
    assert eng.wash_level <= 0.35  # now genuinely settled into BREAKDOWN's range


def test_hold_bucket_breathes_faster_than_breakdown():
    """This project's own extrapolation (no direct Bible state) -- same
    principle as breakdown, brighter range, faster time constant."""
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)

    eng.tick(_snap(energy=0.65, beat_phase=0.0), rig)
    for _ in range(20):
        clock.advance(0.5)
        eng.tick(_snap(energy=0.65, beat_phase=0.0), rig)
    assert 0.35 <= eng.wash_level <= 0.65
