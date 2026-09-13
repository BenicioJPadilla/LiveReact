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


def test_loading_a_non_default_value_warns_loudly(tmp_path, caplog):
    """Found 2026-09-13 via a real hardware session: a stale warm_cool_bias=1.0
    left in config.json silently biased every fixture's color (R x0.5/B x1.5)
    for a full test with zero visibility into why -- the only prior log line
    was "Loaded settings from config.json," no indication anything
    non-default had loaded. Loading a non-default value must warn."""
    import logging
    path = str(tmp_path / "config.json")
    config.save_from(ManualParams(warm_cool_bias=1.0, laser_enable=True), path)
    loaded = ManualParams()
    with caplog.at_level(logging.WARNING):
        config.load_into(loaded, path)
    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("NON-DEFAULT" in w for w in warnings)
    assert any("warm_cool_bias=1.0" in w for w in warnings)
    assert any("laser_enable=True" in w for w in warnings)


def test_loading_all_default_values_does_not_warn(tmp_path, caplog):
    import logging
    path = str(tmp_path / "config.json")
    config.save_from(ManualParams(), path)  # every field at its own default
    loaded = ManualParams()
    with caplog.at_level(logging.WARNING):
        config.load_into(loaded, path)
    assert not any(r.levelno == logging.WARNING for r in caplog.records)
