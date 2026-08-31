"""Tests for the scene catalog: rendering, distinctness, laser gating, buckets."""

from __future__ import annotations

from livereact.core.show_state import ShowSnapshot
from livereact.fixtures.rig import load_rig
from livereact.scenes.base import EnergyBucket
from livereact.scenes.catalog import SceneCatalog, bucket_for_energy
from livereact.scenes.library import ALL_SCENES, BeamFanLaserTunnel, DeepWashBreathe


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
