"""Tests for the scene catalog: rendering, distinctness, laser gating, buckets."""

from __future__ import annotations

from livereact.core.show_state import ShowSnapshot
from livereact.fixtures.rig import _rig_from_dict, load_rig
from livereact.scenes.base import EnergyBucket
from livereact.scenes.catalog import SceneCatalog, bucket_for_energy
from livereact.scenes.library import ALL_SCENES, BeamFanLaserTunnel, Converge, DeepWashBreathe


def _snap(**kw) -> ShowSnapshot:
    base = dict(bpm=124.0, energy=0.7, fader_a=1.0, eq_low_a=1.0, eq_mid_a=0.4, eq_high_a=0.4)
    base.update(kw)
    return ShowSnapshot(**base)


def test_eight_scenes_across_all_buckets():
    cat = SceneCatalog()
    assert len(ALL_SCENES) == 8
    for bucket in EnergyBucket:
        assert cat.bucket(bucket), f"{bucket} has no scenes"


def test_every_scene_renders_some_output():
    rig = load_rig()
    snap = _snap()
    for cls in ALL_SCENES:
        c = cls().render(rig, snap, 1.0)
        assert any(c.touched), f"{cls.__name__} rendered nothing"


def test_only_drop_scenes_touch_laser_channels():
    rig = load_rig()
    snap = _snap(energy=1.0)
    laser = rig.fixture("laser_l")
    for cls in ALL_SCENES:
        scene = cls()
        c = scene.render(rig, snap, 1.0)
        touched_laser = any(c.touched[laser.offset + i] for i in range(12))
        assert touched_laser == (scene.bucket == EnergyBucket.DROP), cls.__name__


def test_scenes_are_visually_distinct():
    rig = load_rig()
    snap = _snap()
    a = DeepWashBreathe().render(rig, snap, 1.0).values
    b = BeamFanLaserTunnel().render(rig, snap, 1.0).values
    assert a != b


def test_bucket_thresholds():
    assert bucket_for_energy(0.1) == EnergyBucket.BREAKDOWN
    assert bucket_for_energy(0.45) == EnergyBucket.BUILD
    assert bucket_for_energy(0.7) == EnergyBucket.HOLD
    assert bucket_for_energy(0.95) == EnergyBucket.DROP


def test_round_robin_avoids_repeating_current():
    cat = SceneCatalog()
    first = cat.pick(EnergyBucket.DROP)
    second = cat.pick(EnergyBucket.DROP, exclude=first)
    assert second is not first


def test_converge_two_spots_matches_original_spread():
    """Converge was generalized from a hardcoded 2-fixture L/R split to any
    fixture count — this pins down that the N=2 case still reduces to
    exactly the original 0.15/0.85 spread math."""
    rig = load_rig()  # packaged default: mh_l (left) + mh_r (right)
    prog = 0.6
    snap = _snap(energy=prog)
    c = Converge().render(rig, snap, 1.0)
    mh_l, mh_r = rig.fixture("mh_l"), rig.fixture("mh_r")
    assert c.values[mh_l.offset] == round((0.15 + 0.35 * prog) * 255)
    assert c.values[mh_r.offset] == round((0.85 - 0.35 * prog) * 255)


def test_converge_single_spot_narrows_to_center_as_energy_rises():
    """The old Converge was broken on a 1-fixture rig: both branches of
    `if side == "left"` collapse to the same one, so "converge from the
    other side" never happened. The fix expresses the same arc as a sweep
    that narrows to stillness at center instead."""
    rig = _rig_from_dict({
        "name": "single-mh",
        "slots": [{"slot_id": "mh", "fixture_type": "shehds_180w_mh",
                   "dmx_address": 1, "role": "spot", "side": "left"}],
    })
    mh = rig.fixture("mh")
    # bar=2, beat 1, phase 0 -> musical_bar_position == 2.0, away from a sin() zero-crossing
    low = _snap(energy=0.0, bar=2, beat_in_bar=1, beat_phase=0.0)
    high = _snap(energy=1.0, bar=2, beat_in_bar=1, beat_phase=0.0)
    pan_low = Converge().render(rig, low, 1.0).values[mh.offset]
    pan_high = Converge().render(rig, high, 1.0).values[mh.offset]
    assert pan_high == 128            # full energy -> amplitude 0 -> dead center
    assert abs(pan_low - 128) > 20    # low energy -> meaningfully off-center, still sweeping
