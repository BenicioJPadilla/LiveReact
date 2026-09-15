"""Tests for the Reactive Layer engine."""

from __future__ import annotations

import pytest

from livereact.clock import FakeClock
from livereact.core.show_state import ShowSnapshot
from livereact.engines.palette import rgb as palette_rgb
from livereact.engines.reactive import (
    BUILD_STROBE_START, DROP_HELD_HIGH, DROP_HELD_LOW, PEAK_BOOST, STROBE_FLASH_DMX, STROBE_FLASH_START_DMX,
    STROBE_MAX,
    STROBE_TOGGLE_MAX_HZ, ReactiveLayerEngine, _StrobeClock, _drop_held_level,
)
from livereact.fixtures.profiles import WashBar
from livereact.fixtures.rig import load_rig
from livereact.scenes.catalog import bucket_for_energy


def _snap(**kw) -> ShowSnapshot:
    # drop_hit_intensity defaults to CEIL (1.0), not ShowSnapshot's own
    # production default (0.85, the FLOOR) -- 2026-09-14, when _strobe_rate
    # moved from chasing raw energy_norm to reusing this held-once value
    # (Josh's correction: strobe was reading as random flicker, not a real
    # strobe). Most existing tests only set `energy=` and implicitly want
    # "fully engaged" strobe behavior; CEIL matches that intent without
    # having to add drop_hit_intensity= to every one of them. Tests
    # exercising the FLOOR->CEIL gradient itself override it explicitly.
    base = dict(bpm=120.0, energy=0.8, fader_a=1.0, eq_low_a=1.0, eq_mid_a=0.2, eq_high_a=0.2,
                drop_hit_intensity=1.0)
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


def test_wash_color_is_the_snapshots_palette_entry_not_the_audio_bands():
    """2026-09-15 (third live capture): hue used to be re-derived from the
    dominant audio band. Now every fixture takes the phrase-frozen palette
    entry the metronome put on the snapshot (engines/palette.py) -- the
    bands can say whatever they like, tick to tick, and the color does not
    move."""
    rig = load_rig()
    eng = ReactiveLayerEngine(FakeClock())
    par = rig.fixture("par_l")  # ch1=dimmer, R,G,B at offset+1..offset+3
    r, g, b = palette_rgb("cold_steel")
    for bands in ((1.0, 0.2, 0.2), (0.2, 0.2, 1.0), (0.2, 1.0, 0.2)):
        c = eng.tick(_snap(bar=0, beat_phase=0.0, palette="cold_steel",
                           eq_low_a=bands[0], eq_mid_a=bands[1], eq_high_a=bands[2]), rig)
        assert (c.values[par.offset + 1], c.values[par.offset + 2], c.values[par.offset + 3]) == \
            (round(r * 255), round(g * 255), round(b * 255))


def test_moving_heads_take_the_palettes_spot_entry():
    """BUILD: the wash is white for the strobe and the heads carry the hue."""
    rig = load_rig()
    eng = ReactiveLayerEngine(FakeClock())
    mh = rig.fixture("mh_l")
    c = eng.tick(_snap(bar=0, beat_phase=0.0, bucket="build", energy=0.5,
                       palette="neutral_wash", palette_spot="hot_magenta"), rig)
    # The moving head is a color-WHEEL fixture (ch8 slot): compare against
    # what set_color itself would pick for the spot entry vs. the wash entry.
    from livereact.merge.merge import Contribution
    want, not_want = Contribution(), Contribution()
    mh.set_color(want, *palette_rgb("hot_magenta"))
    mh.set_color(not_want, *palette_rgb("neutral_wash"))
    assert want.values[mh.offset + 7] != not_want.values[mh.offset + 7]  # the test is meaningful
    assert c.values[mh.offset + 7] == want.values[mh.offset + 7]


def test_moving_heads_mirror_left_and_right():
    rig = load_rig()
    eng = ReactiveLayerEngine(FakeClock())
    c = eng.tick(_snap(bar=2, beat_in_bar=3, beat_phase=0.25), rig)
    mh_l, mh_r = rig.fixture("mh_l"), rig.fixture("mh_r")
    # Pan is mirrored around center (128), so the two heads sit on opposite sides.
    assert c.values[mh_l.offset] != c.values[mh_r.offset]


def test_strobe_off_outside_build_drop_and_peak_buckets():
    """Bucket gate replaced the old fixed energy_norm>0.85 threshold
    (2026-09-14, see reactive.py's STROBE_THRESHOLD retirement note) --
    strobe now only ever engages in BUILD/DROP/PEAK (PEAK included since
    it's an escalation of an already-committed DROP, not a fresh section --
    same reasoning _bucket_wash_level's own PEAK branch already uses), no
    matter how high raw energy reads in e.g. a BREAK section."""
    rig = load_rig()
    eng = ReactiveLayerEngine(FakeClock())
    c = eng.tick(_snap(energy=1.0, beat_phase=0.0, bucket="break"), rig)
    assert eng.strobe_level == 0  # strobe off -- wrong bucket, regardless of energy
    assert not eng.strobe_on


def test_build_strobe_is_continuous_and_gets_faster_across_the_build():
    """Josh, 2026-09-15 (second live test): "the strobe should be strobing
    throughout the build up and... slowly get faster." A sustained rate
    (not burst-gated) from BUILD_STROBE_START x STROBE_MAX at entry up to
    STROBE_MAX by the end of BUILD_RAMP_BARS -- never dark mid-build."""
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    eng.tick(_snap(bar=0, beat_in_bar=1, beat_phase=0.0, bucket="build"), rig)
    seen = []
    for b in (0, 2, 4, 6):
        clock.advance(3.75)  # two bars of real time -- far past STROBE_MAX_BURST_S
        eng.tick(_snap(bar=b, beat_in_bar=1, beat_phase=0.0, bucket="build"), rig)
        seen.append(eng.strobe_level)
    assert seen[0] == pytest.approx(BUILD_STROBE_START * STROBE_MAX)  # starts at the floor, not 0
    assert all(a < b for a, b in zip(seen, seen[1:]))               # monotonically faster
    assert seen[-1] == pytest.approx(STROBE_MAX)                     # reaches the ceiling by BUILD_STROBE_RAMP_BARS
    assert all(v > 0 for v in seen)                                  # never gated dark
    clock.advance(3.75)
    eng.tick(_snap(bar=8, beat_in_bar=1, beat_phase=0.0, bucket="build"), rig)
    assert eng.strobe_level == pytest.approx(STROBE_MAX)             # and holds there


def test_build_strobe_ends_on_the_hit_not_the_commit():
    """session-20260915-140630, Josh: "the strobing continued after the
    beat drop." The classifier's DROP candidate flag is up from the tick
    the hit crosses the threshold; the build strobe stops right there and
    resumes only if the candidate is withdrawn."""
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    eng.tick(_snap(bar=0, beat_in_bar=1, beat_phase=0.0, bucket="build"), rig)
    clock.advance(0.5)
    eng.tick(_snap(bar=0, beat_in_bar=2, beat_phase=0.0, bucket="build"), rig)
    assert eng.strobe_level > 0
    clock.advance(0.5)
    c = eng.tick(_snap(bar=0, beat_in_bar=3, beat_phase=0.0, bucket="build", drop_candidate=True), rig)
    assert eng.strobe_level == 0 and not eng.strobe_on
    par = rig.fixture("par_l")
    assert c.values[par.offset] > 0  # wash holds lit (its ramp level), not dark
    clock.advance(0.5)
    eng.tick(_snap(bar=0, beat_in_bar=4, beat_phase=0.0, bucket="build"), rig)  # candidate withdrawn
    assert eng.strobe_level > 0


def test_drop_tail_strobe_is_the_ceiling_regardless_of_hit_intensity():
    rig = load_rig()
    eng = ReactiveLayerEngine(FakeClock())
    _enter_drop(eng, rig, drop_hit_intensity=0.86)
    eng.tick(_snap(energy=1.0, bar=7, beat_in_bar=3, beat_phase=0.0, bucket="drop", drop_hit_intensity=0.86), rig)
    assert eng.strobe_level == pytest.approx(round(STROBE_MAX * 255) / 255)


# --- the one software strobe toggle, par + wash bar (2026-09-15, third live
# capture: par vs bar out of sync by construction, par toggle erratic while
# the rate ramped, flashes invisible early in the build) ----------------------

def _dimmers(c, rig):
    """(par_l, bar_l) ch1 dimmer bytes."""
    return c.values[rig.fixture("par_l").offset], c.values[rig.fixture("bar_l").offset]


def test_par_and_wash_bar_flash_on_the_same_frames_at_the_cap_byte():
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    bar = rig.fixture("bar_l")
    eng.tick(_snap(bar=0, beat_in_bar=1, beat_phase=0.0, bucket="build"), rig)
    seen_on = seen_off = False
    for _ in range(120):  # 3s at 40 Hz, ~1 Hz strobe at the build's start
        clock.advance(1 / 40)
        c = eng.tick(_snap(bar=0, beat_in_bar=1, beat_phase=0.0, bucket="build"), rig)
        par_d, bar_d = _dimmers(c, rig)
        assert par_d == bar_d, "par and wash bar must toggle on the same DMX frame"
        assert par_d in (0, STROBE_FLASH_START_DMX)  # a build's first bars flash at the start byte
        assert c.values[bar.offset + 1] == 0, "wash bar native ch2 strobe must never be written"
        seen_on |= par_d == STROBE_FLASH_START_DMX
        seen_off |= par_d == 0
    assert seen_on and seen_off


def test_build_flash_brightness_climbs_to_the_cap_and_drop_tail_uses_the_cap():
    """Josh, after the fourth live test: "it can reach a higher peak ... raise
    it to 180." The build's flash byte ramps STROBE_FLASH_START_DMX -> the
    cap alongside the rate ramp; DROP/PEAK tail bursts flash at the cap."""
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    eng.tick(_snap(bar=0, beat_in_bar=1, beat_phase=0.0, bucket="build"), rig)
    assert eng.strobe_flash_dmx == STROBE_FLASH_START_DMX
    clock.advance(3.75)
    eng.tick(_snap(bar=3, beat_in_bar=1, beat_phase=0.0, bucket="build"), rig)
    assert STROBE_FLASH_START_DMX < eng.strobe_flash_dmx < STROBE_FLASH_DMX
    clock.advance(3.75)
    eng.tick(_snap(bar=6, beat_in_bar=1, beat_phase=0.0, bucket="build"), rig)
    assert eng.strobe_flash_dmx == STROBE_FLASH_DMX
    eng2 = ReactiveLayerEngine(FakeClock())
    _enter_drop(eng2, rig)
    c = eng2.tick(_snap(energy=1.0, bar=7, beat_in_bar=3, beat_phase=0.0, bucket="drop"), rig)
    assert eng2.strobe_flash_dmx == STROBE_FLASH_DMX == 180
    assert _dimmers(c, rig)[0] in (0, STROBE_FLASH_DMX)


def test_strobe_toggle_stays_regular_while_the_rate_ramps():
    """The old `(t * hz) % 1` phase jumped every tick the rate changed --
    measured live as 0.1s and 0.7s on/off runs where ~0.3s was expected.
    Accumulated phase keeps every run within one frame of 0.5/hz even as hz
    climbs continuously from 1 Hz to 4 Hz."""
    clock = FakeClock()
    clock.advance(60.0)  # the failure mode needed a large t -- start there
    sc = _StrobeClock(clock)
    dt = 1 / 40
    steps = 40 * 16  # 16s ramp
    runs = []  # [on?, length_in_frames, sum_of_hz_over_the_run]
    prev = None
    for i in range(steps):
        rate = STROBE_MAX * (0.25 + 0.75 * i / steps)
        clock.advance(dt)
        on = sc.advance(rate)
        hz = _StrobeClock.hz_for(rate)
        if prev is None or on != prev[0]:
            runs.append([on, 1, hz])
        else:
            runs[-1][1] += 1
            runs[-1][2] += hz
        prev = runs[-1]
    assert len(runs) > 60  # 1->4 Hz over 16s: ~80 half-periods
    for on, frames, hz_sum in runs[1:-1]:  # ignore the partial first/last runs
        expected = 0.5 / (hz_sum / frames) / dt  # half period at the run's own mean hz
        assert abs(frames - expected) <= 1.0, (on, frames, expected)


def test_a_fresh_strobe_moment_leads_with_a_flash():
    clock = FakeClock()
    sc = _StrobeClock(clock)
    clock.advance(0.37)  # arbitrary phase of wall time
    assert sc.advance(0.0) is False
    clock.advance(1 / 40)
    assert sc.advance(STROBE_MAX) is True  # first ON frame, regardless of when it starts


def test_toggle_hz_never_exceeds_the_sustained_safety_ceiling():
    assert _StrobeClock.hz_for(STROBE_MAX) == STROBE_TOGGLE_MAX_HZ
    assert _StrobeClock.hz_for(1.0) == STROBE_TOGGLE_MAX_HZ  # over-range rates clamp, never exceed


# --- phrase-aligned DROP/PEAK strobe (2026-09-15) --------------------------
# The held-constant rate turned the burst gate into a 9.5s clock (measured:
# 21 bursts, all 1.4-1.5s, spaced 9.4-9.6s, random beat positions). Now the
# ambient strobe only fires in the last STROBE_PHRASE_TAIL_BEATS of every
# STROBE_PHRASE_BARS-bar phrase counted from the drop's own downbeat.

def _enter_drop(eng: ReactiveLayerEngine, rig, entry_bar: int = 0, **kw):
    """Tick once at the drop's downbeat so the engine records its phrase origin."""
    return eng.tick(_snap(energy=1.0, bar=entry_bar, beat_in_bar=1, beat_phase=0.0, bucket="drop", **kw), rig)


def test_drop_strobe_fires_only_in_the_tail_of_each_phrase():
    rig = load_rig()
    eng = ReactiveLayerEngine(FakeClock())
    _enter_drop(eng, rig, entry_bar=10)
    # bars 10..16 (phrase bars 0..6) -- silent on every beat, including beat 4
    for b in range(10, 17):
        for beat in (1, 2, 3, 4):
            eng.tick(_snap(energy=1.0, bar=b, beat_in_bar=beat, beat_phase=0.0, bucket="drop"), rig)
            assert eng.strobe_level == 0, (b, beat)
    # bar 17 (phrase bar 7): beats 1-2 still silent, beats 3-4 strobe
    for beat, expect in ((1, False), (2, False), (3, True), (4, True)):
        eng.tick(_snap(energy=1.0, bar=17, beat_in_bar=beat, beat_phase=0.0, bucket="drop"), rig)
        assert (eng.strobe_level > 0) is expect, beat


def test_drop_strobe_repeats_on_the_next_phrase_and_is_capped():
    """Cap value itself is Josh's explicit call (spec/FINDINGS.md SAFE-01/02/
    03/05/06 -- still an interim placeholder, still no real Hz calibration):
    raised 2026-09-14 from 0.15 to 0.75 after he watched a full 0-255 sweep
    live on the real wash bar -- import STROBE_MAX rather than hardcode it
    here, so this test can't silently drift from the real constant again."""
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    _enter_drop(eng, rig)
    eng.tick(_snap(energy=1.0, bar=7, beat_in_bar=3, beat_phase=0.0, bucket="drop"), rig)
    assert 0 < eng.strobe_level <= STROBE_MAX + 1 / 255
    clock.advance(1.0)
    eng.tick(_snap(energy=1.0, bar=8, beat_in_bar=1, beat_phase=0.0, bucket="drop"), rig)  # tail over
    clock.advance(13.0)  # ~7 bars later at 128bpm, well past STROBE_MIN_SPACING_S
    eng.tick(_snap(energy=1.0, bar=15, beat_in_bar=3, beat_phase=0.0, bucket="drop"), rig)
    assert eng.strobe_level > 0


def test_peak_keeps_the_phrase_origin_of_the_drop_it_escalated_from():
    rig = load_rig()
    eng = ReactiveLayerEngine(FakeClock())
    _enter_drop(eng, rig, entry_bar=3)
    eng.tick(_snap(energy=1.0, bar=6, beat_in_bar=1, beat_phase=0.0, bucket="peak"), rig)  # escalates
    eng.tick(_snap(energy=1.0, bar=8, beat_in_bar=4, beat_phase=0.0, bucket="peak"), rig)
    assert eng.strobe_level == 0   # bar 8 is phrase bar 5, not a tail
    eng.tick(_snap(energy=1.0, bar=10, beat_in_bar=4, beat_phase=0.0, bucket="peak"), rig)
    assert eng.strobe_level > 0    # bar 10 is phrase bar 7 -- counted from bar 3, not 6


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


def _tail(**kw):
    """A snapshot sitting in a drop's phrase tail (phrase bar 7, beat 3)
    when the drop was entered at bar 0 -- the ambient strobe WANTS to fire
    here, so these tests exercise the burst gate alone. Overridable."""
    base = dict(energy=1.0, bar=7, beat_in_bar=3, beat_phase=0.0, bucket="drop")
    base.update(kw)
    return _snap(**base)


def test_strobe_cuts_off_after_the_max_burst_duration():
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    _enter_drop(eng, rig)
    # held in the tail throughout -- would strobe continuously without the gate
    eng.tick(_tail(), rig)
    assert eng.strobe_level > 0  # engaged at the start of the burst
    clock.advance(1.5)  # == STROBE_MAX_BURST_S
    eng.tick(_tail(), rig)
    assert eng.strobe_level == 0  # forced dark once the burst limit is hit


def test_strobe_stays_off_for_the_minimum_spacing_then_resumes():
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    _enter_drop(eng, rig)
    eng.tick(_tail(), rig)
    clock.advance(1.5)
    eng.tick(_tail(), rig)  # burst cap trips here
    clock.advance(5.0)  # still well within STROBE_MIN_SPACING_S (8.0s)
    eng.tick(_tail(), rig)
    assert eng.strobe_level == 0  # still gapped, even though the tail condition holds
    clock.advance(3.1)  # now past the 8.0s minimum spacing
    eng.tick(_tail(), rig)
    assert eng.strobe_level > 0  # allowed to strobe again


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
    _enter_drop(eng, rig)
    eng.tick(_tail(), rig)
    clock.advance(0.5)  # well under the 1.5s cap
    # Leaving the phrase tail (here: the bucket exits entirely) is what ends
    # a moment "naturally" now, not a raw energy drop.
    eng.tick(_tail(bucket="break"), rig)  # bucket exits, strobe naturally off
    clock.advance(0.1)  # nowhere near STROBE_MIN_SPACING_S (8.0s)
    _enter_drop(eng, rig)  # a fresh drop lands immediately...
    eng.tick(_tail(), rig)
    assert eng.strobe_level == 0  # ...but the gate still owes spacing from the last moment
    clock.advance(8.0)  # now past the minimum spacing
    eng.tick(_tail(), rig)
    assert eng.strobe_level > 0  # allowed to strobe again


def test_roll_accent_has_its_own_gate_so_an_ambient_gap_cannot_silence_it():
    """2026-09-15: with one shared gate, any burst imposed the full 8s gap
    on the roll path too -- on the real capture that covered most of an
    11s build. The roll's gate is separate: an ambient DROP burst that
    just ended must not block a roll confirmed in a BUILD right after."""
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    _enter_drop(eng, rig)
    eng.tick(_tail(), rig)
    clock.advance(1.5)
    eng.tick(_tail(), rig)  # ambient burst cap trips -> ambient gate now owes 8s
    clock.advance(0.1)
    _warm_up_snare(eng, clock, rig)  # in BUILD from here on
    fired = False
    for interval in (0.45, 0.45, 0.30, 0.30, 0.20, 0.20):
        clock.advance(interval)
        c = eng.tick(_snap(energy=0.001, beat_phase=0.0, bucket="build",
                            audio_fresh=True, audio_band_mid_abs=20.0, audio_band_high_abs=20.0), rig)
        fired = fired or eng.strobe_level >= round(STROBE_MAX * 255) / 255 - 1e-9
    assert eng.snare_roll_active
    assert fired  # well inside the ambient gate's 8s gap, and still visible


# --- build_snare_accent delivery (2026-09-14): _snare_accent_strobe_rate
# combines this same energy-correlated strobe path with a second, roll-
# triggered one (core/snare_trigger.py's SnareOnsetDetector/SnareRollDetector,
# Steps 0-2, each verified independently by simulation) via max(), BEFORE the
# single _strobe_burst_gate call above -- see reactive.py's own method
# docstring for why that ordering matters. Energy is kept at 0.001 (was 0.3
# under the old fixed energy_norm>0.85 threshold, which 0.3 safely sat below
# regardless of bucket) throughout these tests specifically so any strobe
# output observed can only be coming from the roll path, not the ambient
# energy-correlated one -- 2026-09-14's bucket-gated redesign makes even
# BUILD/DROP's own ambient strobe nonzero at any energy above ~0.002, so 0.3
# would now bleed into these "roll path only" assertions.

def _warm_up_snare(eng: ReactiveLayerEngine, clock: FakeClock, rig) -> None:
    """Run the engine past SnareOnsetDetector's own WARMUP_S on a steady,
    non-spiking signal -- same rationale as test_snare_trigger.py's own
    _warm_up (a cold rolling average reads as a false spike otherwise)."""
    for _ in range(60):  # 60 * 0.02s = 1.2s, safely past WARMUP_S=1.0
        eng.tick(_snap(energy=0.001, beat_phase=0.0, bucket="build",
                        audio_fresh=True, audio_band_mid_abs=1.0, audio_band_high_abs=1.0), rig)
        clock.advance(0.02)


def test_a_real_accelerating_roll_engages_the_strobe_channel_via_the_roll_path():
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    _warm_up_snare(eng, clock, rig)

    fired_strobe = False
    # ROLL_HISTORY=6 -- needs 6 onset times (5 gaps) before _is_accelerating
    # even evaluates. The first spike here just seeds history; the five
    # gaps that follow are the actual roll shape being tested (non-
    # increasing, plateaus allowed; overall tightening 0.20 <= 0.45*0.7).
    clock.advance(0.5)
    eng.tick(_snap(energy=0.001, beat_phase=0.0, bucket="build",
                    audio_fresh=True, audio_band_mid_abs=20.0, audio_band_high_abs=20.0), rig)
    for interval in (0.45, 0.45, 0.30, 0.30, 0.20):
        clock.advance(interval)
        c = eng.tick(_snap(energy=0.001, beat_phase=0.0, bucket="build",
                            audio_fresh=True, audio_band_mid_abs=20.0, audio_band_high_abs=20.0), rig)
        # BUILD's own sustained strobe sits well below the ceiling this early
        # in the ramp (BUILD_STROBE_START); only the roll reaches STROBE_MAX.
        if eng.strobe_level >= round(STROBE_MAX * 255) / 255 - 1e-9:
            fired_strobe = True
    assert eng.snare_roll_active  # the roll is confirmed active by the last hit
    assert fired_strobe  # and it actually reached the real strobe channel, not just the flag


def test_a_steady_non_accelerating_onset_pattern_never_engages_the_strobe_channel():
    """The actual adversary this whole feature exists to reject (same one
    SnareRollDetector's own unit test targets): repeated onsets at a
    constant, non-tightening spacing -- an ordinary backbeat, not a roll --
    must never reach the strobe channel via this path."""
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    _warm_up_snare(eng, clock, rig)

    reached_roll_level = False
    for _ in range(6):  # constant spacing, well over onset refractory -- never tightens
        clock.advance(0.4)
        c = eng.tick(_snap(energy=0.001, beat_phase=0.0, bucket="build",
                            audio_fresh=True, audio_band_mid_abs=20.0, audio_band_high_abs=20.0), rig)
        # BUILD has its own slow sustained strobe (BUILD_STROBE_START); a
        # roll would jump the channel to the STROBE_MAX ceiling instead.
        if eng.strobe_level >= round(STROBE_MAX * 255) / 255 - 1e-9:
            reached_roll_level = True
    assert not eng.snare_roll_active
    assert not reached_roll_level


def test_the_same_accelerating_roll_is_ignored_outside_the_build_bucket():
    """LIGHTING_BIBLE.md's own [BUILD] tag, enforced end-to-end here, not
    just at SnareRollDetector's own unit-test layer."""
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)
    _warm_up_snare(eng, clock, rig)

    fired_strobe = False
    for interval in (0.45, 0.45, 0.30, 0.30, 0.20):
        clock.advance(interval)
        # drop_hit_intensity pinned to DROP_INTENSITY_FLOOR (0.85) and the
        # snapshot kept off a phrase tail (bar 0, beat 1) -- so DROP's own
        # ambient _strobe_rate path can't bleed into this "roll path only"
        # assertion.
        c = eng.tick(_snap(energy=0.001, beat_phase=0.0, bucket="drop",  # NOT build
                            drop_hit_intensity=0.85,
                            audio_fresh=True, audio_band_mid_abs=20.0, audio_band_high_abs=20.0), rig)
        if eng.strobe_level > 0:
            fired_strobe = True
    assert not eng.snare_roll_active
    assert not fired_strobe


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
    false" -- DROP must NOT vary with beat_phase or kick data at all,
    EXCEPT the deliberate beat-4 accent flash (Josh's own directed design
    call, 2026-09-13, see BEAT4_FLASH_PEAK/_beat4_flash) -- both ticks here
    are on beat_in_bar 1 (the `_snap` default), so the flash never engages
    and this invariant holds exactly as before."""
    rig = load_rig()
    eng = ReactiveLayerEngine(FakeClock())
    bar = rig.fixture("bar_l")
    on_beat = eng.tick(_snap(energy=0.9, beat_phase=0.0, audio_band_low_abs=50.0, drop_hit_intensity=0.9), rig)
    late_beat = eng.tick(_snap(energy=0.9, beat_phase=0.9, audio_band_low_abs=0.0, drop_hit_intensity=0.9), rig)
    assert on_beat.values[bar.offset] == late_beat.values[bar.offset] > 0
    assert eng.wash_level == pytest.approx(_drop_held_level(0.9))  # held, not the raw hit


def test_drop_and_peak_flash_on_beat_four_but_not_other_beats():
    """Josh, 2026-09-13 (after two real hardware sessions): DROP/PEAK wash
    was "relatively static" and read as dull with only the moving head
    beating -- explicit ask: flash on beat 4, not every beat, not
    overkill. HTP-style: only ever raises the level above the held base,
    never dims it."""
    rig = load_rig()
    bar = rig.fixture("bar_l")

    for bucket, kwargs in [("drop", dict(drop_hit_intensity=0.5)), ("peak", dict(drop_hit_intensity=0.5))]:
        eng = ReactiveLayerEngine(FakeClock())
        beat1 = eng.tick(_snap(energy=0.9, bucket=bucket, beat_in_bar=1, beat_phase=0.0, **kwargs), rig)
        beat3 = eng.tick(_snap(energy=0.9, bucket=bucket, beat_in_bar=3, beat_phase=0.0, **kwargs), rig)
        beat4_start = eng.tick(_snap(energy=0.9, bucket=bucket, beat_in_bar=4, beat_phase=0.0, **kwargs), rig)
        beat4_late = eng.tick(_snap(energy=0.9, bucket=bucket, beat_in_bar=4, beat_phase=0.9, **kwargs), rig)

        assert beat1.values[bar.offset] == beat3.values[bar.offset]  # untouched on non-4 beats
        assert beat4_start.values[bar.offset] > beat1.values[bar.offset], bucket  # flash raises it
        assert beat4_start.values[bar.offset] > beat4_late.values[bar.offset], bucket  # decays across beat 4 itself
        assert beat4_late.values[bar.offset] >= beat1.values[bar.offset], bucket  # HTP -- never dips below the held base


def test_beat_four_flash_is_a_visible_excursion_not_a_sliver():
    """FOUND LIVE (recordings/session-20260915-114303): mean wash-bar
    brightness on beat 4 was 0.965 vs 0.964 on beats 1-3 -- the flash
    was mathematically invisible against a held level of 0.92-1.0.
    Now the held level leaves headroom (DROP_HELD_*) and the flash peaks
    at full, falling back to held over BEAT4_FLASH_DECAY_PHASE of the
    beat, so it's still clearly above held a third of the way in."""
    rig = load_rig()
    bar = rig.fixture("bar_l")
    for hit in (0.85, 1.0):  # quietest and loudest confirmed drops alike
        eng = ReactiveLayerEngine(FakeClock())
        held = eng.tick(_snap(energy=1.0, bucket="drop", beat_in_bar=1, beat_phase=0.0, drop_hit_intensity=hit), rig)
        peak = eng.tick(_snap(energy=1.0, bucket="drop", beat_in_bar=4, beat_phase=0.0, drop_hit_intensity=hit), rig)
        third = eng.tick(_snap(energy=1.0, bucket="drop", beat_in_bar=4, beat_phase=0.2, drop_hit_intensity=hit), rig)
        assert peak.values[bar.offset] == 255, hit
        assert peak.values[bar.offset] - held.values[bar.offset] >= 90, hit   # >=35% of full scale
        assert third.values[bar.offset] - held.values[bar.offset] >= 40, hit  # still clearly up, 1/3 in


def test_held_drop_level_stays_at_or_under_the_strobe_brightness_cap():
    """A strobe burst clamps ch1 to WashBar.STROBE_BRIGHTNESS_CAP_DMX at
    finalize (Josh, 2026-09-14). With the held level above that byte, each
    burst read live as a ~45% brightness CUT ("they just strobe and then
    turn off really quick"). The held level's top of range must render at
    or near the cap so a burst is never a visible dim."""
    rig = load_rig()
    bar = rig.fixture("bar_l")
    eng = ReactiveLayerEngine(FakeClock())
    c = eng.tick(_snap(energy=1.0, bucket="drop", beat_in_bar=1, beat_phase=0.0, drop_hit_intensity=1.0), rig)
    assert c.values[bar.offset] <= WashBar.STROBE_BRIGHTNESS_CAP_DMX + 2


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
    eng.tick(_snap(energy=0.9, bar=9, beat_in_bar=1, beat_phase=0.0, drop_hit_intensity=0.9), rig)  # a drop happens
    assert eng.wash_level == pytest.approx(_drop_held_level(0.9))  # entering DROP always snaps instantly

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
    [[livereact-project]] memory): ANY bucket change other than entering
    DROP or PEAK should blend, not snap. Bible-integration Phase 2 (HOLD
    removed): reworked to use BUILD (ramped up to its ceiling) -> BREAK as
    the large-gap pair, since HOLD no longer exists as a bucket at all."""
    clock = FakeClock()
    rig = load_rig()
    eng = ReactiveLayerEngine(clock)

    # settle into BUILD, ramped all the way to its ceiling (BUILD_HIGH=0.95)
    eng.tick(_snap(energy=0.5, bar=0, beat_in_bar=1, beat_phase=0.0, bucket="build"), rig)
    for bar in range(1, 9):
        clock.advance(0.5)
        eng.tick(_snap(energy=0.5, bar=bar, beat_in_bar=1, beat_phase=0.0, bucket="build"), rig)
    # one more tick right after the loop's last advance, so _last_bucket_tick_t
    # reflects "now" -- otherwise the upcoming small clock.advance(0.05) would
    # actually hand the crossfade the loop's full unconsumed 0.5s dt instead
    eng.tick(_snap(energy=0.5, bar=8, beat_in_bar=1, beat_phase=0.0, bucket="build"), rig)
    settled_build = eng.wash_level
    assert settled_build >= 0.9  # ramped to (near) BUILD_HIGH=0.95

    # drop straight to BREAK
    clock.advance(0.05)
    eng.tick(_snap(energy=0.15, beat_phase=0.0, bucket="break"), rig)
    just_after = eng.wash_level
    assert just_after > 0.5  # still blending down, not snapped into BREAK's own range yet

    clock.advance(2.0)  # past WASH_TRANSITION_WINDOW_S -- blend has settled
    eng.tick(_snap(energy=0.15, beat_phase=0.0, bucket="break"), rig)
    assert eng.wash_level <= 0.35  # now genuinely settled into BREAK's range


def test_old_hold_range_energy_now_ramps_like_build():
    """Bible-integration Phase 2, Open Question #1's default: HOLD (the old
    0.55-0.80 energy range, no Bible equivalent) is REMOVED -- that range now
    folds into BUILD's upper tail, so it should follow BUILD's bar-position
    ramp, not a fixed breathing envelope. energy=0.65 used to mean "HOLD";
    it's squarely inside BUILD's range now (0.30-0.80)."""
    rig = load_rig()
    eng = ReactiveLayerEngine(FakeClock())

    eng.tick(_snap(energy=0.65, bar=0, beat_in_bar=1, beat_phase=0.0, bucket="build"), rig)
    start = eng.wash_level
    eng.tick(_snap(energy=0.65, bar=8, beat_in_bar=1, beat_phase=0.0, bucket="build"), rig)
    full = eng.wash_level

    assert start == 0.2   # BUILD_LOW, at entry -- not a breathing-envelope value
    assert full == 0.95   # BUILD_HIGH, after a full ramp -- confirms it's really following BUILD


def test_peak_holds_a_constant_intensity_above_drop():
    """Bible-integration Phase 2 (+ 2026-09-11 correction): PEAK is
    genuinely new, reached only by escalating out of a sustained DROP
    (core/metronome.py) -- static like DROP, with a small additive boost on
    top of that SAME drop's captured hit intensity ("more committed than
    the drop" scales with how big the drop already was)."""
    rig = load_rig()
    eng = ReactiveLayerEngine(FakeClock())
    eng.tick(_snap(energy=1.0, bucket="peak", drop_hit_intensity=0.9), rig)
    assert eng.wash_level == pytest.approx(_drop_held_level(0.9) + PEAK_BOOST)
    assert eng.wash_level > _drop_held_level(0.9)  # brighter than the drop it escalated from


def test_peak_intensity_scales_with_the_drop_it_escalated_from():
    """2026-09-11 correction: PEAK isn't a fixed ceiling -- a bigger drop
    escalates to a brighter PEAK than a smaller one."""
    rig = load_rig()
    quiet_peak = ReactiveLayerEngine(FakeClock())
    quiet_peak.tick(_snap(energy=1.0, bucket="peak", drop_hit_intensity=0.85), rig)
    loud_peak = ReactiveLayerEngine(FakeClock())
    loud_peak.tick(_snap(energy=1.0, bucket="peak", drop_hit_intensity=1.0), rig)
    assert loud_peak.wash_level > quiet_peak.wash_level
    assert loud_peak.wash_level == pytest.approx(DROP_HELD_HIGH + PEAK_BOOST)  # top of the held range, plus the boost


def test_drop_intensity_reflects_the_actual_hit_not_a_fixed_constant():
    """2026-09-11 correction: a bigger real hit renders brighter than a
    smaller one, both still classified DROP."""
    rig = load_rig()
    quiet_drop = ReactiveLayerEngine(FakeClock())
    quiet_drop.tick(_snap(energy=0.85, bucket="drop", drop_hit_intensity=0.85), rig)
    loud_drop = ReactiveLayerEngine(FakeClock())
    loud_drop.tick(_snap(energy=1.0, bucket="drop", drop_hit_intensity=1.0), rig)
    assert loud_drop.wash_level > quiet_drop.wash_level
    # 2026-09-15: rendered onto the DROP_HELD_* range, not the raw hit --
    # the raw 0.85-1.0 left no headroom for the beat-4 accent (see reactive.py)
    assert quiet_drop.wash_level == pytest.approx(DROP_HELD_LOW)
    assert loud_drop.wash_level == pytest.approx(DROP_HELD_HIGH)


def test_outro_fades_down_from_bar_position_not_audio():
    """outro_fade_wash: "wash 40->15%" -- a one-way bar-position-driven
    decay, same mechanism shape as BUILD's ramp, just descending."""
    rig = load_rig()
    eng = ReactiveLayerEngine(FakeClock())

    eng.tick(_snap(energy=0.1, bar=0, beat_in_bar=1, beat_phase=0.0, bucket="outro"), rig)
    start = eng.wash_level
    eng.tick(_snap(energy=0.1, bar=16, beat_in_bar=1, beat_phase=0.0, bucket="outro"), rig)
    full = eng.wash_level

    assert start == 0.40           # OUTRO_HIGH, at entry
    assert abs(full - 0.15) < 1e-9  # OUTRO_LOW, after a full fade (OUTRO_FADE_BARS=16)
