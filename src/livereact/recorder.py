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


def _json_default(value):
    """numpy scalars (bool_/float64/int64) aren't JSON-serializable by default;
    .item() gives the plain Python equivalent. Anything else is a real bug --
    let it raise so it shows up in errors.log."""
    item = getattr(value, "item", None)
    if callable(item):
        return item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


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
        reactive_engine=None,
        phrase_engine=None,
        laser_engine=None,
        silence_detector=None,
        rig=None,
    ) -> None:
        """The engine/rig references are all optional (default None) so a
        minimal recorder — or an existing test that doesn't care about them —
        still works unchanged. When given (2026-09-07, Josh: "I want you to be
        able to actually access and analyze the data from that run" without
        needing a separate simulated pipeline — the earlier `replay_song.py`
        approach couldn't match real PDL/MIDI timing, so instead of building a
        message-capture-and-replay system, this just records the SAME internal
        fields directly off the real, live objects during an actual
        `--hardware --record` session), each tick also captures energy_norm,
        bucket, wash/strobe level, palette, laser/silence state, the active scene,
        and per-fixture DMX-derived state for the whole rig — no separate
        simulation needed, and no fidelity question at all: this IS the live
        run, not an approximation of one."""
        super().__init__(name="recorder", daemon=False)
        self.show_state = show_state
        self.frame_buffer = frame_buffer
        self.clock = clock
        self.stop_event = stop_event
        self.session_dir = session_dir
        self.hz = hz
        self.reactive_engine = reactive_engine
        self.phrase_engine = phrase_engine
        self.laser_engine = laser_engine
        self.silence_detector = silence_detector
        self.rig = rig
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
            "energy_norm": round(snap.energy_norm, 4),
            "bucket": snap.bucket,
            # 2026-09-15: the first post-build_snare_accent capture couldn't
            # answer "did the roll fire / did the strobe byte move / what was
            # the hit intensity" at all -- every one of those had to be
            # inferred from the par dimmer toggling. Recorded directly now.
            "drop_hit_intensity": round(snap.drop_hit_intensity, 4),
            "drop_pending": snap.drop_pending,
            "audio_fresh": snap.audio_fresh,
            "band_low": round(snap.audio_band_low_abs, 4),   # the SnareOnsetDetector /
            "band_mid": round(snap.audio_band_mid_abs, 4),   # kick-follow inputs, so a
            "band_high": round(snap.audio_band_high_abs, 4), # session can be replayed offline
            "palette": snap.palette,            # phrase-frozen palette entries (engines/palette.py)
            "palette_spot": snap.palette_spot,
        }
        # Engine/rig internals -- all optional (see __init__): each guarded
        # separately so a partially-wired recorder (or a future engine that
        # doesn't expose one of these) still records what it can.
        if self.reactive_engine is not None:
            record["wash_level"] = round(self.reactive_engine.wash_level, 4)
            record["strobe_level"] = round(self.reactive_engine.strobe_level, 4)
            # 2026-09-15: every automated strobe is a software dimmer toggle
            # on par + wash bar (engines/reactive.py's _StrobeClock), so the
            # per-fixture `*_strobe` fields below (the wash bar's native ch2)
            # stay 0 -- `strobe_level` (the rate) and `strobe_on` (this
            # tick's flash phase) are the truth about strobing.
            record["strobe_on"] = self.reactive_engine.strobe_on
            record["snare_onset"] = self.reactive_engine.snare_onset_active
            record["snare_roll_active"] = self.reactive_engine.snare_roll_active
            record["synth_sync"] = self.reactive_engine.synth_sync_active  # operator Synth Sync mode on (and audio fresh)
            record["synth_level"] = round(self.reactive_engine.synth_level, 3)  # the mid-band envelope driving the wash
        if self.phrase_engine is not None:
            record["scene"] = self.phrase_engine._current.name
            record["scene_uses_lasers"] = self.phrase_engine._current.uses_lasers
        if self.laser_engine is not None:
            record["laser_on"] = self.laser_engine.active        # engines/laser.py: DROP/PEAK gate open
            record["laser_sweep"] = round(self.laser_engine.sweep, 3)  # the wub envelope driving CH7
        if self.silence_detector is not None:
            record["silence_active"] = self.silence_detector.active
        if self.rig is not None:
            for fx in self.rig.fixtures:
                key = fx.label.lower().replace(" ", "_")
                vs = fx.visual_state(uni)
                record[f"{key}_r"] = vs.r
                record[f"{key}_g"] = vs.g
                record[f"{key}_b"] = vs.b
                record[f"{key}_brightness"] = round(vs.brightness, 3)
                record[f"{key}_pan"] = round(vs.pan, 3)
                record[f"{key}_tilt"] = round(vs.tilt, 3)
                record[f"{key}_active"] = vs.active
                record[f"{key}_strobe"] = round(vs.strobe, 3)
        assert self._fh is not None
        self._fh.write(json.dumps(record, default=_json_default) + "\n")
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
