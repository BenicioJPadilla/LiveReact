"""Tests for the Reactive Layer engine."""

from __future__ import annotations

from livereact.clock import FakeClock
from livereact.core.show_state import ShowSnapshot
from livereact.engines.reactive import ReactiveLayerEngine
from livereact.fixtures.rig import load_rig


def _snap(**kw) -> ShowSnapshot:
    base = dict(bpm=120.0, energy=0.8, fader_a=1.0, eq_low_a=1.0, eq_mid_a=0.2, eq_high_a=0.2)
    base.update(kw)
    return ShowSnapshot(**base)


def test_pulse_peaks_on_the_beat_and_decays_across_it():
    rig = load_rig()
    eng = ReactiveLayerEngine(FakeClock())
    bar = rig.fixture("bar_l")

    on_beat = eng.tick(_snap(beat_phase=0.0), rig).values[bar.offset]    # dimmer ch1
    mid_beat = eng.tick(_snap(beat_phase=0.5), rig).values[bar.offset]
    late_beat = eng.tick(_snap(beat_phase=0.9), rig).values[bar.offset]

    assert on_beat > mid_beat > late_beat  # single peak, monotonic decay


def test_color_follows_band_dominance():
    rig = load_rig()
    eng = ReactiveLayerEngine(FakeClock())
    par = rig.fixture("par_l")  # ch1=dimmer, R,G,B at offset+1..offset+3

    red = eng.tick(_snap(beat_phase=0.0, eq_low_a=1.0, eq_mid_a=0.2, eq_high_a=0.2), rig)
    assert red.values[par.offset + 1] > red.values[par.offset + 3]  # R > B

    cyan = eng.tick(_snap(beat_phase=0.0, eq_high_a=1.0, eq_low_a=0.2, eq_mid_a=0.2), rig)
    assert cyan.values[par.offset + 3] > cyan.values[par.offset + 1]  # B > R


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
    rig = load_rig()
    eng = ReactiveLayerEngine(FakeClock())
    bar = rig.fixture("bar_l")
    c = eng.tick(_snap(energy=1.0, beat_phase=0.0), rig)
    strobe = c.values[bar.offset + 1]
    assert 0 < strobe <= int(0.30 * 255) + 1  # engaged but conservatively capped


# --- kick-envelope-follower (docs/14 §5, REDESIGNED 2026-09-03) -------------
# Replaces the old beat-locked-ramp + relative-onset-gate design (which flapped
# on/off and could keep re-triggering through real silence — both confirmed
# live). Wash/par brightness now directly envelope-follows `audio_band_low_abs`:
# no onset detector, no on/off gate, so there's nothing to flap or get stuck.


def test_no_real_audio_falls_back_to_the_classic_beat_locked_pulse():
    """Demo mode / MIDI-only fallback never has real audio — there's no signal
    to trace, so it falls back to the old mechanical beat-locked ramp instead
    of going dark."""
    rig = load_rig()
    eng = ReactiveLayerEngine(FakeClock())
    bar = rig.fixture("bar_l")
    on_beat = eng.tick(_snap(audio_fresh=False, beat_phase=0.0), rig).values[bar.offset]
    late_beat = eng.tick(_snap(audio_fresh=False, beat_phase=0.9), rig).values[bar.offset]
    assert on_beat > late_beat


def test_true_silence_produces_no_brightness():
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    bar = rig.fixture("bar_l")
    for _ in range(10):
        c = eng.tick(_snap(audio_fresh=True, audio_band_low_abs=0.0), rig)
        clock.advance(0.05)
    assert c.values[bar.offset] == 0


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
    bar = rig.fixture("bar_l")
    _warm_up_baseline(eng, rig, clock, level=8.0)
    c = eng.tick(_snap(audio_fresh=True, audio_band_low_abs=8.0), rig)
    assert c.values[bar.offset] <= 2  # baseline converged; no transient excess left


def test_a_kick_above_the_bassline_still_lights_up():
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    bar = rig.fixture("bar_l")
    _warm_up_baseline(eng, rig, clock, level=8.0)
    kick = eng.tick(_snap(audio_fresh=True, audio_band_low_abs=20.0), rig).values[bar.offset]
    assert kick > 50  # a real transient above the established bassline pokes through


def test_excess_decays_back_toward_baseline_after_the_transient_passes():
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    bar = rig.fixture("bar_l")
    _warm_up_baseline(eng, rig, clock, level=8.0)
    peak = eng.tick(_snap(audio_fresh=True, audio_band_low_abs=20.0), rig).values[bar.offset]
    clock.advance(0.15)  # a beat's worth of gap, bass returns to its normal level
    decayed = eng.tick(_snap(audio_fresh=True, audio_band_low_abs=8.0), rig).values[bar.offset]
    assert decayed < peak


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
    bar = rig.fixture("bar_l")
    _warm_up_baseline(eng, rig, clock, level=8.0)
    lvl = eng.tick(_snap(audio_fresh=True, pdl_fresh=True, bpm=120.0, beat_phase=0.0,
                          audio_band_low_abs=20.0), rig).values[bar.offset]
    assert lvl > 50


def test_a_beat_with_no_real_kick_stays_near_the_floor_when_pdl_is_locked():
    """"Dark" means KICK_FLOOR now, not literal zero -- the range was
    deliberately tightened (2026-09-03) so it doesn't read as strobe-like."""
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    bar = rig.fixture("bar_l")
    _warm_up_baseline(eng, rig, clock, level=8.0)
    lvl = eng.tick(_snap(audio_fresh=True, pdl_fresh=True, bpm=120.0, beat_phase=0.0,
                          audio_band_low_abs=8.0), rig).values[bar.offset]  # no excess over baseline
    assert lvl <= 25  # near KICK_FLOOR (0.08 -> ~20/255), not literal zero


def test_after_the_window_closes_new_audio_is_ignored_until_the_next_beat():
    """The actual fix for pass 3's jitter bug: once the detection window closes,
    NOTHING live can change this beat's brightness anymore -- confirmed here by
    feeding a huge new spike late in the beat and showing it's ignored."""
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    bar = rig.fixture("bar_l")
    _warm_up_baseline(eng, rig, clock, level=8.0)

    eng.tick(_snap(audio_fresh=True, pdl_fresh=True, bpm=120.0, beat_phase=0.0,
                    audio_band_low_abs=12.0), rig)  # a real kick, within the window
    decaying = eng.tick(_snap(audio_fresh=True, pdl_fresh=True, bpm=120.0, beat_phase=0.5,
                               audio_band_low_abs=0.0), rig).values[bar.offset]
    # a huge NEW spike arrives late in the same beat, well past the window -- must be ignored
    late_spike = eng.tick(_snap(audio_fresh=True, pdl_fresh=True, bpm=120.0, beat_phase=0.6,
                                 audio_band_low_abs=50.0), rig).values[bar.offset]
    assert late_spike < decaying  # still just decaying along the fixed curve, unaffected


def test_the_next_beats_window_reopens_and_can_register_a_new_kick():
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    bar = rig.fixture("bar_l")
    _warm_up_baseline(eng, rig, clock, level=8.0)

    eng.tick(_snap(audio_fresh=True, pdl_fresh=True, bpm=120.0, beat_phase=0.0,
                    audio_band_low_abs=12.0), rig)
    eng.tick(_snap(audio_fresh=True, pdl_fresh=True, bpm=120.0, beat_phase=0.9,
                    audio_band_low_abs=0.0), rig)  # decayed most of the way through
    # next beat starts (phase wraps back to ~0) with a fresh kick
    next_beat = eng.tick(_snap(audio_fresh=True, pdl_fresh=True, bpm=120.0, beat_phase=0.0,
                                audio_band_low_abs=20.0), rig).values[bar.offset]
    assert next_beat > 50


def test_identical_repeating_beats_produce_identical_output():
    """The exact property pass 3 violated, confirmed live on a repeating 8-beat
    loop (Josh: "inconsistently inconsistent"). Feed the SAME two-beat pattern
    twice and require the second repetition to match the first at each
    corresponding phase."""
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    bar = rig.fixture("bar_l")
    _warm_up_baseline(eng, rig, clock, level=8.0)

    def play_one_beat(kick_abs: float) -> list[int]:
        out = []
        for phase in (0.0, 0.05, 0.15, 0.3, 0.5, 0.7, 0.9):
            abs_level = kick_abs if phase == 0.0 else 8.0
            out.append(eng.tick(_snap(audio_fresh=True, pdl_fresh=True, bpm=120.0,
                                       beat_phase=phase, audio_band_low_abs=abs_level),
                                 rig).values[bar.offset])
        return out

    first_pass = [play_one_beat(20.0), play_one_beat(8.0)]   # beat with kick, beat without
    second_pass = [play_one_beat(20.0), play_one_beat(8.0)]  # the identical pattern again
    assert first_pass == second_pass
