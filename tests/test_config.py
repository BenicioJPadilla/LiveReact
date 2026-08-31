"""Tests for the tiny config persistence layer."""

from __future__ import annotations

from livereact import config
from livereact.merge.merge import ManualParams


def test_save_then_load_round_trips(tmp_path):
    path = str(tmp_path / "config.json")
    m = ManualParams(master_brightness=0.7, strobe_cap=0.3, warm_cool_bias=-0.5, laser_enable=True)
    config.save_from(m, path)

    loaded = ManualParams()
    assert config.load_into(loaded, path) is True
    assert loaded.master_brightness == 0.7
    assert loaded.strobe_cap == 0.3
    assert loaded.warm_cool_bias == -0.5
    assert loaded.laser_enable is True


def test_load_missing_file_keeps_defaults(tmp_path):
    m = ManualParams()
    assert config.load_into(m, str(tmp_path / "nope.json")) is False
    assert m.master_brightness == 1.0  # untouched


def test_momentary_state_is_not_persisted(tmp_path):
    path = str(tmp_path / "config.json")
    config.save_from(ManualParams(blackout=True, freeze=True, strobe_burst=True), path)
    loaded = ManualParams()
    config.load_into(loaded, path)
    assert not loaded.blackout and not loaded.freeze and not loaded.strobe_burst
