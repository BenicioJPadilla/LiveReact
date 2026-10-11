"""engines/laser_manual.py -- the MANUAL profile (2026-10-10, Junior Crib):
scene buttons on the Show tab, off at launch."""
from __future__ import annotations

import pytest

from livereact.clock import FakeClock
from livereact.core.show_state import ShowSnapshot
from livereact.engines.laser_manual import MANUAL_SCENES, LaserManualEngine, manual_scene_names
from livereact.engines.laser_show import LASER_SCENES, scene_names
from livereact.fixtures.profiles import Laser
from livereact.fixtures.rig import LASER_PROFILES, load_rig
from livereact.merge.merge import ManualParams, finalize, merge_contributions

RIG = "rigs/junior_crib.json"


def _snap(**kw) -> ShowSnapshot:
    base = dict(bpm=124.0, bar=1, pdl_fresh=False, audio_fresh=False, bucket="break")
    base.update(kw)
    return ShowSnapshot(**base)


def _laser_bytes(frame: bytes, rig, slot: str) -> tuple[int, ...]:
    fx = rig.fixture(slot)
    return tuple(frame[fx.offset:fx.offset + 12])


def _frame(eng, rig, manual):
    c = eng.tick(_snap(), rig)
    return finalize(merge_contributions([c], rig), rig, manual, laser_on=eng.active)


def test_junior_crib_is_on_the_manual_profile_and_only_it():
    assert "manual" in LASER_PROFILES
    rig = load_rig(RIG)
    assert rig.laser_profile == "manual"
    assert [fx.address for fx in rig.by_role("laser")] == [75, 1]
    for other in ("rigs/sophias_thai_venue.json", "rigs/testing_setup.json", "rigs/josh_rig.json"):
        assert load_rig(other).laser_profile != "manual"


def test_off_at_launch_with_the_pattern_primed_on_both_heads():
    rig = load_rig(RIG)
    manual = ManualParams(laser_enable=True)
    eng = LaserManualEngine(FakeClock(), manual)
    frame = _frame(eng, rig, manual)
    assert eng.active is True and eng.primed is True and eng.scene_name == "Off" and eng.source == "manual"
    for slot in ("laser_l", "laser_r"):
        b = _laser_bytes(frame, rig, slot)
        assert b[0] == 0 and b[1:] == LASER_SCENES["Rainbow"][1:]


def test_white_and_green_are_the_rainbow_pattern_on_one_colour_band_and_sophias_list_is_untouched():
    assert manual_scene_names() == scene_names() + ["White", "Green"]
    assert "White" not in LASER_SCENES and "Green" not in LASER_SCENES
    for name, band in (("White", Laser.COLOR_WHITE), ("Green", Laser.COLOR_GREEN)):
        v = MANUAL_SCENES[name]
        assert len(v) == 12 and v[:11] == LASER_SCENES["Rainbow"][:11] and v[11] == band


@pytest.mark.parametrize("name", manual_scene_names())
def test_cueing_a_scene_lights_both_heads_with_its_exact_bytes(name):
    rig = load_rig(RIG)
    manual = ManualParams(laser_enable=True)
    eng = LaserManualEngine(FakeClock(), manual)
    eng.cue(name)
    frame = _frame(eng, rig, manual)
    for slot in ("laser_l", "laser_r"):
        assert _laser_bytes(frame, rig, slot) == MANUAL_SCENES[name]
    assert eng.scene_name == name and eng.primed is False and eng.color == MANUAL_SCENES[name][11]


def test_off_after_a_cue_kills_ch1_and_keeps_that_scene_primed():
    rig = load_rig(RIG)
    manual = ManualParams(laser_enable=True)
    eng = LaserManualEngine(FakeClock(), manual)
    eng.cue("Blue Sweep")
    eng.off()
    frame = _frame(eng, rig, manual)
    b = _laser_bytes(frame, rig, "laser_l")
    assert b[0] == 0 and eng.primed is True


def test_unknown_scene_is_refused():
    with pytest.raises(ValueError):
        LaserManualEngine(FakeClock()).cue("Nope")


def test_arm_switch_still_wins():
    rig = load_rig(RIG)
    manual = ManualParams(laser_enable=False)
    eng = LaserManualEngine(FakeClock(), manual)
    eng.cue("Rainbow")
    frame = _frame(eng, rig, manual)
    assert all(b == 0 for s in ("laser_l", "laser_r") for b in _laser_bytes(frame, rig, s))
