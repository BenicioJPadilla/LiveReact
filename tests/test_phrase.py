"""Tests for the Phrase Engine: bar-boundary rotation, hold, suspend, crossfade."""

from __future__ import annotations

from livereact.core.show_state import ShowSnapshot
from livereact.engines.phrase import CROSSFADE_BARS, HOLD_BARS, ROTATION_BARS, PhraseEngine
from livereact.fixtures.rig import load_rig


def _snap(bar: int, **kw) -> ShowSnapshot:
    base = dict(bpm=124.0, energy=0.7, bar=bar, beat_in_bar=1, beat_phase=0.0,
                fader_a=1.0, eq_low_a=1.0)
    base.update(kw)
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


def test_drop_scene_emits_laser_channels_through_the_engine():
    rig = load_rig()
    from livereact.scenes.library import FullSpectrumHit

    eng = PhraseEngine()
    eng.force_scene(FullSpectrumHit())
    laser = rig.fixture("laser_l")
    c = eng.tick(_snap(2, energy=1.0), rig)
    assert any(c.touched[laser.offset + i] for i in range(12))
