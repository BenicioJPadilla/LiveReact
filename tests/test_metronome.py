"""Tests for the Metronome — driven deterministically with a FakeClock.

The metronome's work is in ``tick()``; tests advance the FakeClock and call
``tick()`` directly, so beat interpolation, bar inference, free-run, and energy
derivation are all asserted with no threads and no real time passing.
"""

from __future__ import annotations

import queue
import threading

import pytest

from livereact.clock import FakeClock
from livereact.core.messages import (
    AudioLevelMessage,
    BeatMessage,
    MidiControlMessage,
    StatusMessage,
    TransitionMessage,
)
from livereact.core.metronome import (
    EXIT_CONFIRM_DWELL_S,
    FAST_ENTRY_DWELL_S,
    Metronome,
    OUTRO_LOOKBACK_S,
    PER_STATE_DWELL_S,
)
from livereact.core.show_state import ShowState
from livereact.scenes.base import EnergyBucket


def _metronome(clock: FakeClock):
    return Metronome(queue.Queue(), ShowState(), clock, threading.Event())


def test_beat_phase_interpolates_between_master_beats():
    clock = FakeClock()
    m = _metronome(clock)
    m.queue.put(BeatMessage(timestamp=0.0, beat_in_bar=1, bpm=120.0, is_master=True, player=1))
    snap = m.tick()
    assert snap.bpm == 120.0
    assert snap.beat_phase == pytest.approx(0.0, abs=1e-6)
    assert not snap.free_running and snap.pdl_fresh

    clock.advance(0.25)  # halfway through a 0.5 s beat
    snap = m.tick()
    assert snap.beat_phase == pytest.approx(0.5, abs=1e-3)

    clock.advance(0.24)  # near the end of the beat
    snap = m.tick()
    assert snap.beat_phase == pytest.approx(0.98, abs=0.02)


def test_bar_increments_on_the_downbeat_wrap():
    clock = FakeClock()
    m = _metronome(clock)
    # A full bar of master beats: 2,3,4,1 -> the trailing '1' completes a bar.
    for beat in (2, 3, 4, 1):
        m.queue.put(BeatMessage(0.0, beat, 120.0, True, 1))
        m.tick()
    assert m.tick().bar == 1
    for beat in (2, 3, 4, 1):
        m.queue.put(BeatMessage(0.0, beat, 120.0, True, 1))
        m.tick()
    assert m.tick().bar == 2


def test_free_runs_when_master_beats_stop():
    clock = FakeClock()
    m = _metronome(clock)
    m.queue.put(BeatMessage(0.0, 1, 120.0, True, 1))  # beat_dur = 0.5 s
    m.tick()
    assert not m.tick().free_running  # fresh right after a beat

    # No more beats; jump well past the staleness window.
    clock.advance(1.5)
    snap = m.tick()
    assert snap.free_running and not snap.pdl_fresh
    # Phase kept advancing (beats rolled over from the clock, not stuck at 0).
    assert snap.beat_in_bar != 1 or snap.bar > 0


def test_energy_follows_fader_and_eq():
    clock = FakeClock()
    m = _metronome(clock)
    m.queue.put(MidiControlMessage(0.0, "fader_a", 1.0))
    for ctrl in ("eq_low_a", "eq_mid_a", "eq_high_a"):
        m.queue.put(MidiControlMessage(0.0, ctrl, 0.5))
    # raw = 0.6*1.0 + 0.4*0.5 = 0.8; EMA converges over many ticks.
    snap = None
    for _ in range(300):
        snap = m.tick()
    assert snap.energy == pytest.approx(0.8, abs=0.01)
    assert snap.midi_fresh


def test_energy_prefers_fresh_audio_over_midi_proxy():
    """docs/14: real audio should win over the MIDI fader/EQ estimate when
    both are present — it's the actual sound, not a mixer-knob proxy."""
    clock = FakeClock()
    m = _metronome(clock)
    # MIDI would derive energy=0.8 (see test_energy_follows_fader_and_eq)...
    m.queue.put(MidiControlMessage(0.0, "fader_a", 1.0))
    for ctrl in ("eq_low_a", "eq_mid_a", "eq_high_a"):
        m.queue.put(MidiControlMessage(0.0, ctrl, 0.5))
    # ...but real audio says the room is much quieter -> that should win.
    m.queue.put(AudioLevelMessage(0.0, rms=0.2, band_low=0.5, band_mid=0.3, band_high=0.2,
                                   band_low_abs=10.0, band_mid_abs=6.0, band_high_abs=4.0))
    snap = None
    for _ in range(300):
        snap = m.tick()
    assert snap.audio_fresh
    assert snap.energy == pytest.approx(0.2, abs=0.01)  # audio's 0.2, not MIDI's 0.8
    assert snap.audio_band_low == 0.5
    assert snap.audio_band_low_abs == 10.0
    # build_snare_accent Step 0 (2026-09-14): the same plumbing for mid/high
    assert snap.audio_band_mid_abs == 6.0
    assert snap.audio_band_high_abs == 4.0


def test_energy_falls_back_to_midi_when_audio_goes_stale():
    clock = FakeClock()
    m = _metronome(clock)
    m.queue.put(AudioLevelMessage(0.0, rms=0.2, band_low=0.5, band_mid=0.3, band_high=0.2,
                                   band_low_abs=10.0, band_mid_abs=6.0, band_high_abs=4.0))
    m.queue.put(MidiControlMessage(0.0, "fader_a", 1.0))
    for ctrl in ("eq_low_a", "eq_mid_a", "eq_high_a"):
        m.queue.put(MidiControlMessage(0.0, ctrl, 0.5))
    for _ in range(50):
        m.tick()
    assert m.tick().audio_fresh

    clock.advance(2.0)  # past AUDIO_STALE_AFTER, MIDI stays fresh (no separate staleness test needed here)
    snap = None
    for _ in range(300):
        snap = m.tick()
    assert not snap.audio_fresh
    assert snap.energy == pytest.approx(0.8, abs=0.01)  # falls back to the MIDI proxy


# --- adaptive energy normalization (2026-09-07, found live) ------------------
# `bucket_for_energy` should read `energy_norm`, not raw `energy` — see
# show_state.py's energy_norm docstring / livereact-project memory for why a
# fixed absolute threshold against raw RMS doesn't generalize across sessions.


def _pump_audio(m: Metronome, clock: FakeClock, rms: float, seconds: float, step: float = 0.2) -> None:
    """Feed a steady real-audio rms for `seconds` of simulated time, keeping
    audio_fresh continuously true (messages every `step`s, well under
    AUDIO_STALE_AFTER) — the shape a real live audio stream would take."""
    elapsed = 0.0
    while elapsed < seconds:
        m.queue.put(AudioLevelMessage(clock.monotonic(), rms=rms, band_low=0.5,
                                       band_mid=0.3, band_high=0.2,
                                       band_low_abs=rms * 20, band_mid_abs=rms * 12, band_high_abs=rms * 8))
        m.tick()
        clock.advance(step)
        elapsed += step


def test_energy_norm_stays_zero_during_warmup():
    """Not enough history yet (< ENERGY_NORM_MIN_SAMPLES) -> report 0.0 (the
    safe/quiet default), not a ratio computed from almost nothing."""
    clock = FakeClock()
    m = _metronome(clock)
    _pump_audio(m, clock, rms=0.6, seconds=5.0)
    assert m.tick().energy_norm == 0.0


def test_energy_norm_reaches_high_values_for_a_sustained_loud_passage():
    """The exact bug found live (2026-09-07): a sustained passage well below
    the OLD fixed DROP threshold (0.80 on raw energy) should still normalize
    high once it's genuinely the loudest thing this set has recently
    contained — that's what actually generalizes across tracks/gain staging."""
    clock = FakeClock()
    m = _metronome(clock)
    _pump_audio(m, clock, rms=0.1, seconds=60.0)   # a quiet baseline first
    _pump_audio(m, clock, rms=0.5, seconds=30.0)   # then a sustained louder passage
    snap = m.tick()
    assert snap.energy == pytest.approx(0.5, abs=0.01)  # raw energy: well under the old 0.80 cutoff
    assert snap.energy_norm > 0.8  # normalized against ITS OWN recent range: reads as a drop


def test_energy_norm_smooths_out_beat_to_beat_oscillation():
    """FOUND BY TESTING (offline replay against a real captured session):
    normalizing raw, unsmoothed per-tick energy directly flipped the bucket
    several times a second, since ordinary beat-to-beat swings are a big
    fraction of any short window's own range. Pin down the fix: alternating
    high/low rms (simulating kick pulsing) should NOT make energy_norm swing
    wildly tick to tick once warmed up."""
    clock = FakeClock()
    m = _metronome(clock)
    # a realistic quiet baseline with natural micro-variation, not a perfectly
    # flat signal -- a perfectly flat 60s input degenerately collapses this
    # project's own MIN_SPAN floor to its minimum, which isn't how real audio
    # behaves (even a "flat" bassline has some tick-to-tick variation).
    baseline = [0.25, 0.30, 0.28, 0.32, 0.27]
    for i in range(120):
        rms = baseline[i % len(baseline)]
        m.queue.put(AudioLevelMessage(clock.monotonic(), rms=rms, band_low=0.5,
                                       band_mid=0.3, band_high=0.2,
                                       band_low_abs=rms * 20, band_mid_abs=rms * 12, band_high_abs=rms * 8))
        m.tick()
        clock.advance(0.5)
    samples = []
    for i in range(40):  # ~8s of alternating high/low, faster than a real kick
        rms = 0.6 if i % 2 == 0 else 0.15
        m.queue.put(AudioLevelMessage(clock.monotonic(), rms=rms, band_low=0.5,
                                       band_mid=0.3, band_high=0.2,
                                       band_low_abs=rms * 20, band_mid_abs=rms * 12, band_high_abs=rms * 8))
        samples.append(m.tick().energy_norm)
        clock.advance(0.2)
    assert max(samples) - min(samples) < 0.35  # smoothed -- doesn't chase every toggle


def test_energy_norm_ignores_a_tiny_blip_after_extended_silence():
    """FOUND BY TESTING: without an absolute-ceiling guard, a long silent
    stretch (a track ending) followed by any small residual noise spiked
    energy_norm straight to ~1.0 ("DROP") against a near-zero range."""
    clock = FakeClock()
    m = _metronome(clock)
    _pump_audio(m, clock, rms=0.0, seconds=60.0)
    m.queue.put(AudioLevelMessage(clock.monotonic(), rms=0.08, band_low=0.5,
                                   band_mid=0.3, band_high=0.2,
                                   band_low_abs=1.6, band_mid_abs=1.0, band_high_abs=0.6))
    assert m.tick().energy_norm == 0.0


def test_energy_norm_passes_raw_energy_through_when_audio_is_stale():
    """The MIDI-fallback proxy is already a hand-built 0..1 signal (fader/EQ
    position), not a loudness measure -- adaptive rescaling doesn't apply."""
    clock = FakeClock()
    m = _metronome(clock)
    m.queue.put(MidiControlMessage(0.0, "fader_a", 1.0))
    for ctrl in ("eq_low_a", "eq_mid_a", "eq_high_a"):
        m.queue.put(MidiControlMessage(0.0, ctrl, 0.5))
    snap = None
    for _ in range(300):
        snap = m.tick()
    assert not snap.audio_fresh
    assert snap.energy_norm == pytest.approx(snap.energy, abs=1e-9)


# --- bucket debounce + hysteresis (2026-09-07, found live + via offline
# replay on a real track; RE-TUNED 2026-09-07 evening after a real
# --hardware --record capture, see [[livereact-project]] memory) ---
# bucket_for_energy flapped near its own boundaries; a candidate bucket must
# persist for BUCKET_MIN_DWELL_S before it's committed to. The dwell alone
# turned out not to be enough once tested against a real ~4min song (26
# flips, several under BUCKET_MIN_DWELL_S's old 1.0s value once compounded
# across a boundary crossed repeatedly) -- BUCKET_MIN_DWELL_S was raised
# 1.0->3.0, and `bucket_for_energy_with_hysteresis` now also requires
# clearing a boundary by HYSTERESIS_MARGIN before a candidate even starts.
# Drives _derive_bucket directly (bypassing tick()'s own _derive_energy_norm,
# which would otherwise overwrite the manually-set energy_norm each call) --
# same white-box style as the laser trigger's duty-cap tests.


def test_bucket_starts_at_break():
    clock = FakeClock()
    m = _metronome(clock)
    assert m.tick().bucket == "break"


def test_bucket_ignores_a_brief_upward_blip_below_fast_entry_dwell():
    """Bible-integration Phase 2: entering a higher-energy bucket uses the
    short FAST_ENTRY_DWELL_S (~0.94s at the nominal 128 BPM), not the old
    flat 3.0s -- but a blip shorter than even that should still never
    commit."""
    clock = FakeClock()
    m = _metronome(clock)
    m._energy_norm = 0.9  # DROP-range
    m._derive_bucket(clock.monotonic())
    clock.advance(0.3)  # well under FAST_ENTRY_DWELL_S -- a blip, not a real change
    m._derive_bucket(clock.monotonic())
    m._energy_norm = 0.0  # back to BREAK-range before the blip could commit
    clock.advance(0.1)
    m._derive_bucket(clock.monotonic())
    assert m._base_committed.value == "break"  # never actually changed


def test_bucket_commits_after_persisting_past_fast_entry_dwell():
    clock = FakeClock()
    m = _metronome(clock)
    m._energy_norm = 0.9  # DROP-range
    m._derive_bucket(clock.monotonic())
    clock.advance(1.0)  # past FAST_ENTRY_DWELL_S (~0.94s), still DROP-range the whole time
    m._derive_bucket(clock.monotonic())
    assert m._bucket_committed.value == "drop"


def test_bucket_candidate_restarts_if_a_different_bucket_appears_first():
    """A candidate that gets pre-empted by a THIRD bucket before committing
    must restart its own dwell timer, not inherit the first candidate's
    elapsed time."""
    clock = FakeClock()
    m = _metronome(clock)
    m._energy_norm = 0.5  # BUILD-range candidate begins (base starts at BREAK)
    m._derive_bucket(clock.monotonic())
    clock.advance(0.5)  # close to FAST_ENTRY_DWELL_S (~0.94s), but not quite
    m._energy_norm = 0.9  # DROP-range -- pre-empts the BUILD candidate; still "up" from
                           # base=BREAK (hasn't committed to BUILD yet), so still fast-entry
    m._derive_bucket(clock.monotonic())
    clock.advance(0.5)  # would have been enough time for the ORIGINAL (BUILD) candidate
    m._derive_bucket(clock.monotonic())
    assert m._base_committed.value == "break"  # DROP candidate restarted, hasn't dwelled long enough yet
    clock.advance(0.6)  # now past FAST_ENTRY_DWELL_S since DROP became the candidate
    m._derive_bucket(clock.monotonic())
    assert m._bucket_committed.value == "drop"


def test_bucket_hovering_within_the_margin_of_a_boundary_never_becomes_a_candidate():
    """The actual live bug (2026-09-07 real capture): energy_norm can sit
    within a hair of a boundary for a real stretch of a song. Once settled in
    BUILD, hovering just above/below BUILD_MAX (0.80) without ever clearing
    it by HYSTERESIS_MARGIN_UP must never commit to DROP -- the committed
    bucket should just stay put, however long real time passes."""
    clock = FakeClock()
    m = _metronome(clock)
    m._energy_norm = 0.65  # squarely BUILD, nowhere near a boundary
    m._derive_bucket(clock.monotonic())
    clock.advance(1.0)  # past FAST_ENTRY_DWELL_S -- BUILD is now the committed bucket
    m._derive_bucket(clock.monotonic())
    assert m._bucket_committed.value == "build"

    for energy in (0.78, 0.81, 0.79, 0.82, 0.80):  # all within +-0.03 of BUILD_MAX=0.80,
                                                     # i.e. inside the +-0.05 HYSTERESIS_MARGIN_UP
        m._energy_norm = energy
        m._derive_bucket(clock.monotonic())
        clock.advance(1.0)
    assert m._bucket_committed.value == "build"  # never even started a real DROP candidate


def test_midi_and_transition_and_status_update_state():
    clock = FakeClock()
    m = _metronome(clock)
    m.queue.put(MidiControlMessage(0.0, "crossfader", 0.8))
    m.queue.put(TransitionMessage(0.0, active=True))
    m.queue.put(StatusMessage(0.0, on_air=(2,), master_deck=2, playing=True, loop_active=True))
    snap = m.tick()
    assert snap.crossfader == pytest.approx(0.8)
    assert snap.in_transition is True
    assert snap.on_air == (2,) and snap.master_deck == 2 and snap.loop_active

    m.queue.put(TransitionMessage(0.0, active=False))
    assert m.tick().in_transition is False


# --- Bible-integration Phase 2: legal transition matrix, PEAK/OUTRO overlay,
# manual override, drop marker (2026-09-11) -----------------------------------

def test_legal_transition_matrix_rejects_drop_falling_back_to_build():
    """LIGHTING_BIBLE.md §9.8 (TIME-13): DROP -> BUILD is explicitly illegal
    -- a real drop doesn't downgrade back to "still building." It must
    resolve through BREAK instead, however long BUILD-range energy persists."""
    clock = FakeClock()
    m = _metronome(clock)
    m._energy_norm = 0.9  # commit to DROP
    m._derive_bucket(clock.monotonic())
    clock.advance(EXIT_CONFIRM_DWELL_S + 1.0)
    m._derive_bucket(clock.monotonic())
    assert m._base_committed == EnergyBucket.DROP

    m._energy_norm = 0.5  # BUILD-range -- the illegal downgrade
    for _ in range(10):
        clock.advance(EXIT_CONFIRM_DWELL_S + 1.0)
        m._derive_bucket(clock.monotonic())
    assert m._base_committed == EnergyBucket.DROP  # never became BUILD, however long this persists

    m._energy_norm = 0.1  # BREAK-range -- DROP -> BREAK IS legal
    clock.advance(PER_STATE_DWELL_S[EnergyBucket.DROP])  # DROP's own floor must clear before any exit
    m._derive_bucket(clock.monotonic())
    clock.advance(EXIT_CONFIRM_DWELL_S + 1.0)
    m._derive_bucket(clock.monotonic())
    assert m._base_committed == EnergyBucket.BREAK


def test_drop_escalates_to_peak_after_sustained_dwell():
    clock = FakeClock()
    m = _metronome(clock)
    m._energy_norm = 0.9
    m._derive_bucket(clock.monotonic())
    clock.advance(FAST_ENTRY_DWELL_S + 0.5)
    m._derive_bucket(clock.monotonic())
    assert m._bucket_committed == EnergyBucket.DROP  # not yet -- hasn't sustained DROP's own dwell

    clock.advance(PER_STATE_DWELL_S[EnergyBucket.DROP])  # now past DROP's own floor, still DROP-range
    m._derive_bucket(clock.monotonic())
    assert m._bucket_committed == EnergyBucket.PEAK
    assert m._base_committed == EnergyBucket.DROP  # base classifier itself is untouched by the overlay


def test_break_promotes_to_outro_after_a_recent_drop_then_reverts():
    clock = FakeClock()
    m = _metronome(clock)
    m._energy_norm = 0.9  # commit to DROP -- sets _last_drop_or_peak_t
    m._derive_bucket(clock.monotonic())
    clock.advance(EXIT_CONFIRM_DWELL_S + 1.0)
    m._derive_bucket(clock.monotonic())
    assert m._bucket_committed == EnergyBucket.DROP

    m._energy_norm = 0.1  # fall legally to BREAK
    clock.advance(PER_STATE_DWELL_S[EnergyBucket.DROP])  # DROP's own floor must clear before any exit
    m._derive_bucket(clock.monotonic())
    clock.advance(EXIT_CONFIRM_DWELL_S + 1.0)
    m._derive_bucket(clock.monotonic())
    assert m._base_committed == EnergyBucket.BREAK
    # Sustained-dwell requirement (2026-09-13, found via the first real
    # hardware session): OUTRO promotion now requires BREAK to have ALREADY
    # sat past its own PER_STATE_DWELL_S first (same symmetry as DROP->PEAK
    # above), so a break barely a moment old doesn't get immediately
    # mislabeled OUTRO just because a drop happened recently -- confirmed
    # NOT promoted yet, right at BREAK's commit.
    assert m._bucket_committed == EnergyBucket.BREAK

    clock.advance(PER_STATE_DWELL_S[EnergyBucket.BREAK])  # BREAK's own floor now clears too
    m._derive_bucket(clock.monotonic())
    assert m._bucket_committed == EnergyBucket.OUTRO  # NOW promoted -- sustained AND a drop was recent


def test_a_fast_recovering_break_never_gets_promoted_to_outro_at_all():
    """The actual bug found live, 2026-09-13: on a real energetic track,
    drops recur every 15-20 bars, so most breaks recover into a new build
    well before BREAK's own 8-bar dwell floor -- those must never be
    mislabeled OUTRO at all, not just delayed. Confirmed against the real
    capture: OUTRO's share of one real session dropped from 31.4% to
    16.5%, BREAK correctly rose to 45.4%, once this fix landed."""
    clock = FakeClock()
    m = _metronome(clock)
    m._energy_norm = 0.9  # commit to DROP
    m._derive_bucket(clock.monotonic())
    clock.advance(EXIT_CONFIRM_DWELL_S + 1.0)
    m._derive_bucket(clock.monotonic())

    m._energy_norm = 0.1  # fall to BREAK
    clock.advance(PER_STATE_DWELL_S[EnergyBucket.DROP])
    m._derive_bucket(clock.monotonic())
    clock.advance(EXIT_CONFIRM_DWELL_S + 1.0)
    m._derive_bucket(clock.monotonic())
    assert m._base_committed == EnergyBucket.BREAK
    assert m._bucket_committed == EnergyBucket.BREAK  # not OUTRO, correctly

    # Recovers into a new build well before BREAK's 8-bar floor -- a real,
    # ordinary breather between drops, not the set ending.
    clock.advance(1.0)
    m._energy_norm = 0.5
    m._derive_bucket(clock.monotonic())
    clock.advance(FAST_ENTRY_DWELL_S + 0.5)
    m._derive_bucket(clock.monotonic())
    assert m._base_committed == EnergyBucket.BUILD
    assert m._bucket_committed == EnergyBucket.BUILD  # never touched OUTRO at any point


def test_outro_does_not_illegally_block_a_real_second_build():
    """Deliberate deviation from the Bible's literal "OUTRO has no legal
    exit" (see the module-level comment in metronome.py): this system can't
    tell a real ending from a mid-song breather, so a genuine energy rise is
    allowed to simply un-promote OUTRO rather than illegally blocking a real
    second build/drop in the same track."""
    clock = FakeClock()
    m = _metronome(clock)
    m._energy_norm = 0.9
    m._derive_bucket(clock.monotonic())
    clock.advance(EXIT_CONFIRM_DWELL_S + 1.0)
    m._derive_bucket(clock.monotonic())
    m._energy_norm = 0.1
    clock.advance(PER_STATE_DWELL_S[EnergyBucket.DROP])  # DROP's own floor must clear before any exit
    m._derive_bucket(clock.monotonic())
    clock.advance(EXIT_CONFIRM_DWELL_S + 1.0)
    m._derive_bucket(clock.monotonic())
    clock.advance(PER_STATE_DWELL_S[EnergyBucket.BREAK])  # BREAK's own sustained-dwell floor (2026-09-13 fix)
    m._derive_bucket(clock.monotonic())
    assert m._bucket_committed == EnergyBucket.OUTRO

    m._energy_norm = 0.5  # a real second build starting, well within the lookback window
    m._derive_bucket(clock.monotonic())  # registers the candidate
    clock.advance(FAST_ENTRY_DWELL_S + 0.5)
    m._derive_bucket(clock.monotonic())  # confirms it
    assert m._base_committed == EnergyBucket.BUILD
    assert m._bucket_committed == EnergyBucket.BUILD  # not stuck in OUTRO


def test_manual_bucket_override_takes_priority_and_is_consumed_once():
    clock = FakeClock()
    m = _metronome(clock)
    m._energy_norm = 0.0  # would otherwise settle at BREAK
    m.request_manual_bucket(EnergyBucket.DROP)
    m._derive_bucket(clock.monotonic())
    assert m._bucket_committed == EnergyBucket.DROP
    assert m._manual_bucket_override is None  # consumed

    # a further tick with no new override falls back to the automated classifier,
    # which holds at DROP (just committed, hasn't dwelled long enough to move again)
    m._derive_bucket(clock.monotonic())
    assert m._base_committed == EnergyBucket.DROP


def test_drop_marker_fires_after_a_qualifying_dip_and_rebound():
    clock = FakeClock()
    m = _metronome(clock)
    m._energy_norm = 0.9
    m._derive_drop_marker(clock.monotonic())
    assert m.drop_cycle == 0

    m._energy_norm = 0.02  # dip below DIP_THRESHOLD
    m._derive_drop_marker(clock.monotonic())
    clock.advance(1.5)  # >= MIN_DIP_S -- a qualifying dip, not just a normal beat gap
    m._derive_drop_marker(clock.monotonic())

    m._energy_norm = 0.85  # rebound, above REBOUND_THRESHOLD, within the rebound window
    m._derive_drop_marker(clock.monotonic())
    assert m.drop_cycle == 1
    assert m._drop_marker_pulse is True

    m._derive_drop_marker(clock.monotonic())  # next tick -- the pulse is one-shot
    assert m._drop_marker_pulse is False
    assert m.drop_cycle == 1  # doesn't keep re-firing


def test_drop_marker_path1_ignores_a_short_gap_but_path2_still_catches_the_real_rise():
    """A short gap (well under MIN_DIP_S) correctly doesn't qualify for the
    quiet-then-rebound path (path 1) -- but Josh's correction means that's
    NOT the only path: a genuinely sharp rise counts on its own (path 2),
    regardless of whether the dip before it was long enough to "count" as a
    real cut. This is intentional, not a bug -- see _derive_drop_marker's
    own docstring (an OR, not an AND, between the two paths)."""
    clock = FakeClock()
    m = _metronome(clock)
    m._energy_norm = 0.9
    m._derive_drop_marker(clock.monotonic())

    m._energy_norm = 0.02
    m._derive_drop_marker(clock.monotonic())
    clock.advance(0.2)  # well under MIN_DIP_S -- doesn't qualify path 1's dip requirement
    m._derive_drop_marker(clock.monotonic())

    m._energy_norm = 0.85  # still a genuinely sharp rise from 0.02 -- path 2 catches it
    m._derive_drop_marker(clock.monotonic())
    assert m.drop_cycle == 1
    assert m._drop_marker_pulse is True


def test_drop_marker_does_not_fire_on_an_ordinary_gradual_rise():
    """Neither path should fire for energy that just gradually climbs --
    path 1 needs a real qualifying dip first, and path 2 needs the rise
    itself to clear SHARP_RISE_DELTA within SHARP_RISE_WINDOW_S, not just
    any increase."""
    clock = FakeClock()
    m = _metronome(clock)
    for energy in (0.3, 0.4, 0.5, 0.6, 0.7):  # a gradual build, well under SHARP_RISE_DELTA per step
        m._energy_norm = energy
        m._derive_drop_marker(clock.monotonic())
        clock.advance(1.0)
    assert m.drop_cycle == 0
    assert m._drop_marker_pulse is False


# --- Bible-integration Phase 3: beat-quantized DROP release -----------------

def test_drop_commits_immediately_when_already_on_a_downbeat():
    clock = FakeClock()
    m = _metronome(clock)
    m._beat_in_bar = 1  # _metronome()'s own default, spelled out here for clarity
    m._energy_norm = 0.9
    m._derive_bucket(clock.monotonic())
    clock.advance(FAST_ENTRY_DWELL_S + 0.1)
    m._derive_bucket(clock.monotonic())
    assert m._base_committed == EnergyBucket.DROP  # no wait needed -- already aligned
    assert not m._pending_drop_release


def test_drop_waits_for_the_next_downbeat_when_confirmed_mid_bar():
    """LIGHTING_BIBLE.md's own language ("releases on the downbeat") --
    Bible-integration Phase 3 (D1 in docs/bible_integration/
    SPEC_DEVIATIONS.md): a confirmed DROP doesn't commit the instant its
    dwell timer clears if that happens mid-bar -- it waits for beat 1."""
    clock = FakeClock()
    m = _metronome(clock)
    m._beat_in_bar = 3  # mid-bar
    m._energy_norm = 0.9
    m._derive_bucket(clock.monotonic())
    clock.advance(FAST_ENTRY_DWELL_S + 0.1)
    m._derive_bucket(clock.monotonic())
    assert m._base_committed != EnergyBucket.DROP  # confirmed, but not released yet
    assert m._pending_drop_release

    m._beat_in_bar = 4  # still not a downbeat
    m._derive_bucket(clock.monotonic())
    assert m._base_committed != EnergyBucket.DROP
    assert m._pending_drop_release

    m._beat_in_bar = 1  # the next real downbeat arrives
    m._derive_bucket(clock.monotonic())
    assert m._base_committed == EnergyBucket.DROP
    assert not m._pending_drop_release


def test_pending_drop_release_cancels_if_energy_backs_off_first():
    clock = FakeClock()
    m = _metronome(clock)
    m._beat_in_bar = 3
    m._energy_norm = 0.9
    m._derive_bucket(clock.monotonic())
    clock.advance(FAST_ENTRY_DWELL_S + 0.1)
    m._derive_bucket(clock.monotonic())
    assert m._pending_drop_release

    m._energy_norm = 0.3  # the sound itself backed off before the downbeat arrived
    m._derive_bucket(clock.monotonic())
    assert not m._pending_drop_release

    m._beat_in_bar = 1  # even once a downbeat does arrive, nothing to release anymore
    m._derive_bucket(clock.monotonic())
    assert m._base_committed != EnergyBucket.DROP


# --- Bible-integration Phase 3: transition_likely heuristic -----------------

def test_transition_likely_after_a_typically_long_peak():
    from livereact.core.metronome import TYPICAL_EXTENDED_PEAK_S
    clock = FakeClock()
    m = _metronome(clock)
    m._energy_norm = 0.9
    m._derive_bucket(clock.monotonic())
    clock.advance(FAST_ENTRY_DWELL_S + 0.1)
    m._derive_bucket(clock.monotonic())
    assert m._base_committed == EnergyBucket.DROP
    assert not m.transition_likely  # hasn't been dwelling long yet

    clock.advance(TYPICAL_EXTENDED_PEAK_S + 1.0)
    m._derive_bucket(clock.monotonic())
    assert m.transition_likely


def test_transition_likely_after_several_drops_in_one_track():
    from livereact.core.metronome import TRANSITION_LIKELY_DROP_CYCLE_THRESHOLD
    clock = FakeClock()
    m = _metronome(clock)
    m.drop_cycle = TRANSITION_LIKELY_DROP_CYCLE_THRESHOLD
    m._energy_norm = 0.1  # squarely BREAK -- not dwelling in DROP/PEAK at all
    m._derive_bucket(clock.monotonic())
    assert m.transition_likely  # drop_cycle alone is enough, independent of dwell time


def test_drop_cycle_resets_on_a_track_transition():
    clock = FakeClock()
    m = _metronome(clock)
    m._energy_norm = 0.9
    m._derive_drop_marker(clock.monotonic())
    m._energy_norm = 0.02
    m._derive_drop_marker(clock.monotonic())
    clock.advance(1.5)
    m._derive_drop_marker(clock.monotonic())
    m._energy_norm = 0.85
    m._derive_drop_marker(clock.monotonic())
    assert m.drop_cycle == 1

    m.queue.put(TransitionMessage(clock.monotonic(), active=True))
    m.tick()
    assert m.drop_cycle == 0
