"""Session recorder — captures what the show actually did, for later analysis.

When recording is on, a session directory collects everything needed to debug a
hardware run without being there:
  session.log   — all log output (info/warning/error + tracebacks)
  errors.log    — just warnings/errors, for a quick scan
  state.jsonl   — periodic ShowState + DMX-output samples (one JSON object/line)
  meta.json     — environment + run settings captured at startup
  summary.json  — totals written at shutdown
  NOTES.md      — a template for YOUR observations (fill this in while testing)

The state samples are the key artifact: they show whether the inputs (BPM, beat,
crossfader, EQ, freshness) and the output (active channels) behaved as expected.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import threading

from .clock import Clock, LoopTimer
from .core.frame_buffer import DmxFrameBuffer
from .core.show_state import ShowState

log = logging.getLogger(__name__)

NOTES_TEMPLATE = """# Session notes

Fill this in while testing — plain language is perfect. Then hand the whole session
folder back to Claude for analysis.

## What I was testing
(e.g. "fixture test — MH Left", "first end-to-end with the XDJ playing")

## What I expected

## What actually happened
(what looked right, what looked wrong — wrong color? wrong fixture moved? nothing lit?)

## Per-fixture observations (if doing the fixture test)
- MH Left:
- MH Right:
- Laser Left:
- Laser Right:
- Par Left:
- Par Right:
- Bar Left:
- Bar Right:

## Anything else
"""


def create_session_dir(base: str = "recordings", now: datetime.datetime | None = None) -> str:
    stamp = (now or datetime.datetime.now()).strftime("%Y%m%d-%H%M%S")
    path = os.path.join(base, f"session-{stamp}")
    os.makedirs(path, exist_ok=True)
    return path


class SessionRecorder(threading.Thread):
    """Samples ShowState + DMX output to ``state.jsonl`` at a fixed rate."""

    def __init__(
        self,
        show_state: ShowState,
        frame_buffer: DmxFrameBuffer,
        clock: Clock,
        stop_event: threading.Event,
        session_dir: str,
        hz: float = 10.0,
    ) -> None:
        super().__init__(name="recorder", daemon=False)
        self.show_state = show_state
        self.frame_buffer = frame_buffer
        self.clock = clock
        self.stop_event = stop_event
        self.session_dir = session_dir
        self.hz = hz
        self.samples = 0
        self._fh = None

    def open(self) -> None:
        self._fh = open(os.path.join(self.session_dir, "state.jsonl"), "w", encoding="utf-8")

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def tick(self) -> None:
        snap = self.show_state.snapshot()
        uni = self.frame_buffer.latest()
        record = {
            "wall": datetime.datetime.now().isoformat(timespec="milliseconds"),
            "t": round(self.clock.monotonic(), 4),
            "bpm": round(snap.bpm, 2),
            "beat": snap.beat_in_bar,
            "bar": snap.bar,
            "beat_phase": round(snap.beat_phase, 3),
            "energy": round(snap.energy, 3),
            "in_transition": snap.in_transition,
            "free_running": snap.free_running,
            "pdl_fresh": snap.pdl_fresh,
            "midi_fresh": snap.midi_fresh,
            "on_air": list(snap.on_air),
            "master_deck": snap.master_deck,
            "crossfader": round(snap.crossfader, 3),
            "fader_a": round(snap.fader_a, 3),
            "fader_b": round(snap.fader_b, 3),
            "eq_a": [round(snap.eq_low_a, 2), round(snap.eq_mid_a, 2), round(snap.eq_high_a, 2)],
            "eq_b": [round(snap.eq_low_b, 2), round(snap.eq_mid_b, 2), round(snap.eq_high_b, 2)],
            "active_channels": sum(1 for b in uni if b),
        }
        assert self._fh is not None
        self._fh.write(json.dumps(record) + "\n")
        self.samples += 1

    def run(self) -> None:  # pragma: no cover - thin wrapper around tick()
        self.open()
        timer = LoopTimer(self.clock, self.hz)
        try:
            while not self.stop_event.is_set():
                try:
                    self.tick()
                except Exception:  # noqa: BLE001 - recording must never crash a session
                    log.exception("Recorder tick failed")
                timer.wait()
        finally:
            self.close()


def write_notes_template(session_dir: str) -> None:
    path = os.path.join(session_dir, "NOTES.md")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(NOTES_TEMPLATE)


def write_meta(session_dir: str, settings: dict) -> None:
    from .diagnostics import collect_environment

    meta = {
        "started": datetime.datetime.now().isoformat(timespec="seconds"),
        "settings": settings,
        "environment": collect_environment(),
    }
    with open(os.path.join(session_dir, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)


def write_summary(session_dir: str, summary: dict) -> None:
    summary = {**summary, "ended": datetime.datetime.now().isoformat(timespec="seconds")}
    with open(os.path.join(session_dir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
