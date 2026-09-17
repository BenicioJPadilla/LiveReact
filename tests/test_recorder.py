"""Tests for diagnostics + session recording."""

from __future__ import annotations

import json
import os

from livereact.clock import FakeClock
from livereact.core.frame_buffer import UNIVERSE_SIZE, DmxFrameBuffer
from livereact.core.show_state import ShowSnapshot, ShowState
from livereact.core.silence import SilenceDetector
from livereact.diagnostics import collect_environment, format_report
from livereact.engines.laser import LaserEngine
from livereact.engines.phrase import PhraseEngine
from livereact.engines.reactive import ReactiveLayerEngine
from livereact.fixtures.rig import load_rig
from livereact.recorder import (
    SessionRecorder,
    create_session_dir,
    write_meta,
    write_notes_template,
    write_summary,
)


def test_collect_environment_has_expected_keys():
    env = collect_environment()
    for key in ("livereact_version", "python", "platform", "dependencies",
                "serial_ports", "midi_inputs", "prodj_link_installed", "network"):
        assert key in env
    assert "LiveReact diagnostics" in format_report(env)


def test_create_session_dir(tmp_path):
    import datetime

    d = create_session_dir(base=str(tmp_path), now=datetime.datetime(2026, 6, 7, 12, 0, 0))
    assert d.endswith("session-20260607-120000")
    assert os.path.isdir(d)


def test_recorder_writes_state_samples(tmp_path):
    state = ShowState()
    state.publish(ShowSnapshot(bpm=128.0, bar=3, energy=0.6, crossfader=0.4))
    fb = DmxFrameBuffer()
    fb.publish(bytes([255] * 10 + [0] * (UNIVERSE_SIZE - 10)))

    rec = SessionRecorder(state, fb, FakeClock(), __import__("threading").Event(), str(tmp_path))
    rec.open()
    rec.tick()
    rec.tick()
    rec.close()

    lines = (tmp_path / "state.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    row = json.loads(lines[0])
    assert row["bpm"] == 128.0 and row["bar"] == 3
    assert row["crossfader"] == 0.4
    assert row["active_channels"] == 10
    assert rec.samples == 2


def test_recorder_without_engine_refs_still_works_unchanged():
    """The engine/rig params are all optional -- an existing caller (or test)
    that only passes the original 5 positional args must keep working exactly
    as before, with none of the new fields present."""
    state = ShowState()
    state.publish(ShowSnapshot(bpm=128.0, bar=3, energy=0.6, crossfader=0.4))
    fb = DmxFrameBuffer()

    rec = SessionRecorder(state, fb, FakeClock(), __import__("threading").Event(), None)
    rec._fh = __import__("io").StringIO()  # avoid touching the filesystem
    rec.tick()
    row = json.loads(rec._fh.getvalue())
    assert row["bpm"] == 128.0
    assert "wash_level" not in row and "scene" not in row and "laser_on" not in row


def test_recorder_captures_engine_and_rig_internals_when_given(tmp_path):
    """2026-09-07 (Josh: "I want you to be able to actually access and analyze
    the data from that run" without a separate simulated pipeline) -- when the
    real engine/rig objects are passed in, the recorder captures the SAME
    internal fields the offline replay tool's custom trace did, straight off
    the real, live objects."""
    state = ShowState()
    state.publish(ShowSnapshot(bpm=128.0, bar=3, energy=0.6, crossfader=0.4,
                                energy_norm=0.9, bucket="drop"))
    fb = DmxFrameBuffer()
    rig = load_rig()  # packaged default rig -- no real file path needed
    clock = FakeClock()
    reactive = ReactiveLayerEngine(clock)
    phrase = PhraseEngine()
    laser = LaserEngine(clock)
    silence = SilenceDetector(clock)
    fb.publish(rig.boot_universe())

    rec = SessionRecorder(
        state, fb, clock, __import__("threading").Event(), str(tmp_path),
        reactive_engine=reactive, phrase_engine=phrase, laser_engine=laser,
        silence_detector=silence, rig=rig,
    )
    rec.open()
    rec.tick()
    rec.close()

    row = json.loads((tmp_path / "state.jsonl").read_text().strip())
    assert row["energy_norm"] == 0.9
    assert row["bucket"] == "drop"
    assert row["wash_level"] == reactive.wash_level
    assert row["scene"] == phrase._current.name
    assert row["scene_uses_lasers"] == phrase._current.uses_lasers
    assert row["laser_on"] == laser.active
    assert row["laser_sweep"] == round(laser.sweep, 3)
    assert row["synth_sync"] == reactive.synth_sync_active
    assert row["synth_level"] == round(reactive.synth_level, 3)
    assert row["silence_active"] == silence.active
    # per-fixture DMX-derived fields exist for every real fixture in the rig
    for fx in rig.fixtures:
        key = fx.label.lower().replace(" ", "_")
        assert f"{key}_brightness" in row
        assert f"{key}_active" in row


def test_recorder_captures_strobe_and_snare_state_directly(tmp_path):
    """2026-09-15: the first capture after build_snare_accent landed could
    not say whether the roll fired, what the strobe byte was, or what the
    hit intensity had been -- all inferred from the par dimmer toggling.
    These are recorded straight off the live objects now, so a session
    directory is enough to replay the detectors offline."""
    state = ShowState()
    state.publish(ShowSnapshot(bpm=128.0, bar=7, beat_in_bar=3, energy=0.6, energy_norm=0.9,
                                bucket="drop", drop_hit_intensity=0.93, drop_pending=False,
                                palette="cold_steel", palette_spot="blood_red",
                                audio_fresh=True, audio_band_low_abs=4.0,
                                audio_band_mid_abs=2.5, audio_band_high_abs=1.25))
    fb = DmxFrameBuffer()
    rig = load_rig()
    clock = FakeClock()
    reactive = ReactiveLayerEngine(clock)
    uni = bytearray(rig.boot_universe())
    bar = rig.fixture("bar_l")
    uni[bar.offset + 1] = 128  # a real strobe-rate byte on the wash bar's ch2
    fb.publish(bytes(uni))

    rec = SessionRecorder(state, fb, clock, __import__("threading").Event(), str(tmp_path),
                          reactive_engine=reactive, rig=rig)
    rec.open()
    rec.tick()
    rec.close()

    row = json.loads((tmp_path / "state.jsonl").read_text().strip())
    assert row["drop_hit_intensity"] == 0.93
    assert row["drop_pending"] is False
    assert row["audio_fresh"] is True
    assert (row["band_low"], row["band_mid"], row["band_high"]) == (4.0, 2.5, 1.25)
    assert row["strobe_level"] == reactive.strobe_level
    assert row["snare_roll_active"] is False
    assert row["roll_ratio"] == round(reactive.roll_ratio, 3)
    assert row["snare_roll_active"] is False
    assert row["strobe_on"] is False
    assert (row["palette"], row["palette_spot"]) == ("cold_steel", "blood_red")
    key = bar.label.lower().replace(" ", "_")
    assert row[f"{key}_strobe"] == round(128 / 255, 3)


def test_notes_meta_and_summary_files(tmp_path):
    d = str(tmp_path)
    write_notes_template(d)
    write_meta(d, {"mode": "hardware"})
    write_summary(d, {"frames_sent": 100})

    assert "Session notes" in (tmp_path / "NOTES.md").read_text()
    meta = json.loads((tmp_path / "meta.json").read_text())
    assert meta["settings"]["mode"] == "hardware"
    assert "environment" in meta
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["frames_sent"] == 100 and "ended" in summary


def test_notes_template_not_overwritten(tmp_path):
    d = str(tmp_path)
    (tmp_path / "NOTES.md").write_text("my notes")
    write_notes_template(d)
    assert (tmp_path / "NOTES.md").read_text() == "my notes"  # preserved


def test_recorder_serializes_numpy_scalars_instead_of_dropping_the_sample(tmp_path):
    """2026-09-15 night: a numpy bool in `laser_on` cost 162 samples."""
    import numpy as np
    from livereact.recorder import _json_default
    assert _json_default(np.bool_(True)) is True
    assert _json_default(np.float64(0.5)) == 0.5
    assert json.dumps({"a": np.bool_(False), "b": np.int64(3)}, default=_json_default) == '{"a": false, "b": 3}'


def test_recorder_writes_norm_seeded(tmp_path):
    """2026-09-17: a capture must show whether an early classification came
    from the last session's persisted range or this set's own window."""
    state = ShowState()
    state.publish(ShowSnapshot(norm_seeded=True))
    fb = DmxFrameBuffer()
    fb.publish(bytes(UNIVERSE_SIZE))
    rec = SessionRecorder(state, fb, FakeClock(), __import__("threading").Event(), str(tmp_path))
    rec.open()
    rec.tick()
    rec.close()
    row = json.loads((tmp_path / "state.jsonl").read_text().strip())
    assert row["norm_seeded"] is True
