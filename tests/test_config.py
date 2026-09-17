"""Tests for the tiny config persistence layer."""

from __future__ import annotations

from livereact import config
from livereact.merge.merge import ManualParams


def test_save_then_load_round_trips(tmp_path):
    path = str(tmp_path / "config.json")
    m = ManualParams(master_brightness=0.7, strobe_cap=0.3, warm_cool_bias=-0.5)
    config.save_from(m, path)

    loaded = ManualParams()
    assert config.load_into(loaded, path) is True
    assert loaded.master_brightness == 0.7
    assert loaded.strobe_cap == 0.3
    assert loaded.warm_cool_bias == -0.5


def test_laser_arming_is_never_persisted(tmp_path):
    """2026-09-16: a saved laser_enable=True armed the laser at every launch
    (third live run: it fired on every track). Arming is per run, per track,
    by hand -- and a stale key left in an older config.json is ignored."""
    import json
    path = str(tmp_path / "config.json")
    config.save_from(ManualParams(laser_enable=True), path)
    loaded = ManualParams()
    config.load_into(loaded, path)
    assert loaded.laser_enable is False
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"laser_enable": True, "master_brightness": 0.5}, fh)
    stale = ManualParams()
    config.load_into(stale, path)
    assert stale.laser_enable is False and stale.master_brightness == 0.5


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
    config.save_from(ManualParams(warm_cool_bias=1.0, strobe_cap=0.5), path)
    loaded = ManualParams()
    with caplog.at_level(logging.WARNING):
        config.load_into(loaded, path)
    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("NON-DEFAULT" in w for w in warnings)
    assert any("warm_cool_bias=1.0" in w for w in warnings)
    assert any("strobe_cap=0.5" in w for w in warnings)


def test_loading_all_default_values_does_not_warn(tmp_path, caplog):
    import logging
    path = str(tmp_path / "config.json")
    config.save_from(ManualParams(), path)  # every field at its own default
    loaded = ManualParams()
    with caplog.at_level(logging.WARNING):
        config.load_into(loaded, path)
    assert not any(r.levelno == logging.WARNING for r in caplog.records)


# --- energy_norm seed (2026-09-17) -------------------------------------------

FP = {"gain": 5.0, "audio_device": "None"}


def test_energy_norm_seed_round_trips_with_its_fingerprint(tmp_path):
    path = str(tmp_path / "config.json")
    rec = config.energy_norm_record(0.1234, 0.5678, FP)
    config.save_from(ManualParams(), path, energy_norm=rec)
    assert config.energy_norm_seed(path, FP) == (0.1234, 0.5678)


def test_energy_norm_seed_is_dropped_when_the_gain_or_device_differs(tmp_path, caplog):
    """The saved range is only a range for the SAME gain staging: the laptop
    mic fallback or a re-gained mixer must start cold, not against last
    week's XDJ line level."""
    path = str(tmp_path / "config.json")
    config.save_from(ManualParams(), path, energy_norm=config.energy_norm_record(0.1, 0.5, FP))
    assert config.energy_norm_seed(path, {"gain": 1.4, "audio_device": "None"}) is None
    assert config.energy_norm_seed(path, {"gain": 5.0, "audio_device": "MacBook Pro Microphone"}) is None
    assert config.energy_norm_seed(path, FP) == (0.1, 0.5)


def test_saving_without_a_seed_keeps_the_existing_one(tmp_path):
    """A demo run, or a real session that never finished warming up, saves
    the operator settings but must not erase the last good seed."""
    path = str(tmp_path / "config.json")
    config.save_from(ManualParams(), path, energy_norm=config.energy_norm_record(0.1, 0.5, FP))
    config.save_from(ManualParams(master_brightness=0.6), path)  # no seed given
    assert config.energy_norm_seed(path, FP) == (0.1, 0.5)
    loaded = ManualParams()
    config.load_into(loaded, path)
    assert loaded.master_brightness == 0.6


def test_a_missing_or_corrupt_seed_is_none(tmp_path):
    import json
    path = str(tmp_path / "config.json")
    assert config.energy_norm_seed(path, FP) is None
    config.save_from(ManualParams(), path)
    assert config.energy_norm_seed(path, FP) is None
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"energy_norm": {"floor": "x", "ceiling": 0.5, "fingerprint": FP}}, fh)
    assert config.energy_norm_seed(path, FP) is None
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"energy_norm": {"floor": 0.6, "ceiling": 0.5, "fingerprint": FP}}, fh)
    assert config.energy_norm_seed(path, FP) is None  # floor above ceiling


def test_demo_mode_never_reads_or_writes_a_seed(tmp_path):
    """Synthetic demo data isn't a venue; its range must not seed a real
    show, and a saved real seed must not be read by a demo run."""
    from livereact.app import App, AppConfig
    path = str(tmp_path / "config.json")
    config.save_from(ManualParams(), path, energy_norm=config.energy_norm_record(0.1, 0.5, FP))
    app = App(AppConfig(demo=True, config_path=path, duration=0.01))
    assert app.metronome._seed_range is None
    app.metronome._energy_history.extend([0.3] * 60)  # pretend it warmed up
    app.start()
    app.shutdown()
    assert config.energy_norm_seed(path, FP) == (0.1, 0.5)  # untouched
