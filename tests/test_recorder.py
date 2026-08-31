"""Tests for diagnostics + session recording."""

from __future__ import annotations

import json
import os

from livereact.clock import FakeClock
from livereact.core.frame_buffer import UNIVERSE_SIZE, DmxFrameBuffer
from livereact.core.show_state import ShowSnapshot, ShowState
from livereact.diagnostics import collect_environment, format_report
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
