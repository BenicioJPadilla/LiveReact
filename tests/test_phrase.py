"""Tests for the Phrase Engine: bar-boundary rotation, hold, suspend, crossfade."""

from __future__ import annotations

from livereact.core.show_state import ShowSnapshot
from livereact.engines.phrase import CROSSFADE_BARS, HOLD_BARS, ROTATION_BARS, PhraseEngine
from livereact.fixtures.rig import load_rig
from livereact.scenes.catalog import bucket_for_energy


def _snap(bar: int, **kw) -> ShowSnapshot:
    base = dict(bpm=124.0, energy=0.7, bar=bar, beat_in_bar=1, beat_phase=0.0,
                fader_a=1.0, eq_low_a=1.0)
    base.update(kw)
    # bucket_for_energy reads energy_norm, not raw energy (2026-09-07, found
    # live) -- default it to match energy so existing tests that only set
    # `energy=` still exercise the bucket they intend to.
    base.setdefault("energy_norm", base["energy"])
    # snap.bucket is normally an ALREADY-DEBOUNCED value from metronome.py --
    # default it from this snapshot's own energy_norm for the same reason.
    base.setdefault("bucket", bucket_for_energy(base["energy_norm"]).value)
    return ShowSnapshot(**base)


def test_rotation_fires_once_per_boundary_not_every_tick():
    rig = load_rig()
    eng = PhraseEngine()
    # Hold at bar 0 for many ticks: no rotation yet.
    for _ in range(5):
        eng.tick(_snap(0), rig)
    assert eng.rotations == 0
    # Reach the rotation cadence; ticking repeatedly on the same bar fires once.
    for _ in range(5):
        eng.tick(_snap(ROTATION_BARS), rig)
    assert eng.rotations == 1


def test_minimum_hold_blocks_early_rotation():
    rig = load_rig()
    eng = PhraseEngine()
    eng.tick(_snap(HOLD_BARS - 1), rig)
    assert eng.rotations == 0  # below the minimum hold


def test_per_look_min_hold_bars_overrides_the_catalog_wide_floor():
    """Gap fix, 2026-09-13: Scene.min_hold_bars ("per-look override of the
    catalog-wide HOLD_BARS," scenes/base.py's own docstring) was declared
    by dozens of Phase 5 scenes but never actually consulted here -- every
    look used the flat HOLD_BARS regardless. A look with a longer-than-
    default hold (BreakLowWash, min_hold_bars=16) must not rotate away just
    because the flat HOLD_BARS=4 floor has cleared."""
    from livereact.scenes.library import BreakLowWash
    rig = load_rig()
    eng = PhraseEngine()
    eng.force_scene(BreakLowWash())
    eng.skip()  # request a rotation as soon as it's legal
    eng.tick(_snap(HOLD_BARS), rig)  # past the flat default floor...
    assert eng.rotations == 0  # ...but not past BreakLowWash's own min_hold_bars=16
    eng.tick(_snap(16), rig)  # now past BreakLowWash's own floor
    assert eng.rotations == 1


def test_scene_without_min_hold_bars_falls_back_to_the_catalog_wide_floor():
    """A pre-Bible-integration scene (no min_hold_bars override, defaults to
    None) must still respect the flat HOLD_BARS floor, unchanged from
    before this fix."""
    from livereact.scenes.library import RisingTide
    rig = load_rig()
    eng = PhraseEngine()
    eng.force_scene(RisingTide())
    eng.skip()
    eng.tick(_snap(HOLD_BARS - 1), rig)
    assert eng.rotations == 0
    eng.tick(_snap(HOLD_BARS), rig)
    assert eng.rotations == 1


def test_rotation_suspended_during_transition_and_loop():
    rig = load_rig()
    eng = PhraseEngine()
    eng.tick(_snap(ROTATION_BARS, in_transition=True), rig)
    assert eng.rotations == 0
    eng.tick(_snap(ROTATION_BARS + 1, loop_active=True), rig)
    assert eng.rotations == 0
    # Flags cleared on a fresh bar -> it rotates.
    eng.tick(_snap(ROTATION_BARS + 2), rig)
    assert eng.rotations == 1


def test_combine_interpolates_color_instead_of_max_blending():
    """Bug fix, 2026-09-13 (found via the first real hardware session):
    _combine used to take a raw per-channel max() for color/dimmer, the
    exact anti-pattern Phase 4 fixed at the cross-engine level but never
    touched here -- confirmed live to freeze at a wrong, neither-scene
    color for an entire crossfade. Must now be a real weighted lerp."""
    from livereact.merge.merge import Contribution
    rig = load_rig()
    par = rig.fixture("par_l")

    out_c = Contribution()
    par.set_color(out_c, 0.0, 0.0, 0.0)   # outgoing: black (R=0)
    in_c = Contribution()
    par.set_color(in_c, 1.0, 0.0, 0.0)    # incoming: full red (R=255)

    r_ch = par.offset + 1  # ch2 = R on this Par layout (ch1 dimmer, 2/3/4 R/G/B)
    at_0 = PhraseEngine._combine(out_c, in_c, 0.0, rig)
    at_half = PhraseEngine._combine(out_c, in_c, 0.5, rig)
    at_1 = PhraseEngine._combine(out_c, in_c, 1.0, rig)

    assert at_0.values[r_ch] == 0
    assert at_1.values[r_ch] == 255
    assert 100 <= at_half.values[r_ch] <= 155  # genuinely ~halfway, not max()'d to 255 the instant `in_c` touches it


def test_combine_only_one_side_touching_is_unaffected_by_interpolation():
    """A channel only one side writes to (the overwhelmingly common case --
    most scenes never touch wash dimmer at all) must still just pass that
    value through untouched, same as before this fix."""
    from livereact.merge.merge import Contribution
    rig = load_rig()
    par = rig.fixture("par_l")

    out_c = Contribution()
    par.set_color(out_c, 0.5, 0.5, 0.5)
    in_c = Contribution()  # touches nothing

    result = PhraseEngine._combine(out_c, in_c, 0.3, rig)
    r_ch = par.offset + 1  # ch2 = R on this Par layout
    assert result.values[r_ch] == out_c.values[r_ch]


def test_crossfade_completes_and_promotes_next_scene():
    rig = load_rig()
    eng = PhraseEngine()
    start = eng._current
    eng.tick(_snap(ROTATION_BARS), rig)          # begins crossfade
    assert eng._next is not None
    # Advance past the crossfade window (in bars).
    eng.tick(_snap(ROTATION_BARS + CROSSFADE_BARS, beat_in_bar=1, beat_phase=0.0), rig)
    assert eng._next is None
    assert eng._current is not start             # promoted to the new scene


def test_skip_forces_rotation_after_minimum_hold():
    rig = load_rig()
    eng = PhraseEngine()
    eng.tick(_snap(0), rig)
    eng.skip()
    eng.tick(_snap(HOLD_BARS), rig)  # earlier than ROTATION_BARS, but past min hold
    assert eng.rotations == 1


def test_bucket_change_forces_rotation_after_minimum_hold():
    """2026-09-09 hardware capture (see [[livereact-project]] memory):
    scene rotation and bucket classification were two fully independent
    clocks -- a bucket could jump straight into DROP while the active
    scene (picked for a totally different energy state) kept running for
    up to a full ROTATION_BARS before catching up, measured as long as
    24s/14 bars on a real drop and directly producing "still blue during
    the drop." A bucket change should now prompt a rotation check on its
    own, same as an explicit skip -- still gated by HOLD_BARS, not an
    override of it."""
    rig = load_rig()
    eng = PhraseEngine()
    eng.tick(_snap(0, energy=0.2), rig)  # low energy: establishes a "breakdown" baseline bucket
    assert eng.rotations == 0
    # Energy jumps straight to a drop-level bucket, past the minimum hold
    # but nowhere near ROTATION_BARS -- should still rotate, unlike before.
    eng.tick(_snap(HOLD_BARS, energy=1.0), rig)
    assert eng.rotations == 1


def test_bucket_change_before_minimum_hold_is_still_deferred():
    """The new bucket-change trigger must not bypass the existing
    anti-whiplash floor -- it's one more reason to check, not a shortcut
    around HOLD_BARS."""
    rig = load_rig()
    eng = PhraseEngine()
    eng.tick(_snap(0, energy=0.2), rig)
    eng.tick(_snap(HOLD_BARS - 1, energy=1.0), rig)  # bucket changed, but still inside the hold
    assert eng.rotations == 0


def test_bucket_change_rotation_picks_a_scene_for_the_new_bucket():
    """Not just that it rotates sooner -- the scene it rotates TO must
    actually match the bucket that triggered it (LIGHTING_BIBLE.md's own
    per-bucket scene pools), since `_begin_rotation` reads `snap.bucket`
    fresh at fire time."""
    rig = load_rig()
    eng = PhraseEngine()
    eng.tick(_snap(0, energy=0.2), rig)
    eng.tick(_snap(HOLD_BARS, energy=1.0), rig)  # -> drop bucket
    assert eng._next is not None
    assert eng._next.bucket.value == "drop"


def test_drop_scene_emits_laser_channels_through_the_engine():
    """FullSpectrumHit (the original scene this test used) was retired in
    Phase 6 -- DropLaserPunctuation is a real, still-current DROP-bucket
    laser look, and a cleaner example besides (laser-only, no wash/spot
    noise to also account for)."""
    rig = load_rig()
    from livereact.scenes.library import DropLaserPunctuation

    eng = PhraseEngine()
    eng.force_scene(DropLaserPunctuation())
    laser = rig.fixture("laser_l")
    c = eng.tick(_snap(2, energy=1.0), rig)
    assert any(c.touched[laser.offset + i] for i in range(12))
