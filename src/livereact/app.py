"""Application supervisor: wires the components, owns the lifecycle.

Phase 0 wiring is intentionally thin — a frame buffer, an output backend, and the
DMX writer thread, paced by a real clock and shut down cleanly on Ctrl-C or a stop
signal. Later phases attach the metronome, input sources, show engine, and UI to
the same supervisor without changing its shutdown contract.
"""

from __future__ import annotations

import logging
import os
import queue
import signal
import threading
from dataclasses import dataclass

from . import config as app_config
from .clock import Clock, RealClock
from .core.frame_buffer import DmxFrameBuffer
from .core.metronome import Metronome
from .core.show_engine import ShowEngine
from .core.show_state import ShowState
from .engines.phrase import PhraseEngine
from .engines.reactive import ReactiveLayerEngine
from .engines.transition import TransitionEngine
from .fixtures.rig import Rig, load_rig
from .inputs.demo import DemoDataSource
from .merge.merge import ManualParams
from .output.base import OutputBackend
from .output.null_log import NullLogBackend
from .output.writer import DmxWriter

log = logging.getLogger(__name__)


@dataclass
class AppConfig:
    demo: bool = True
    dmx_rate_hz: float = 40.0
    duration: float | None = None  # bounded run for testing; None = run until signal
    config_path: str | None = "config.json"  # None disables persistence
    midi_map_path: str = "midi_map.json"      # discovered XDJ CC map (hardware mode)
    pdl_interface: str | None = None          # explicit NIC for Pro DJ Link
    record: bool = False                      # record this session for analysis
    session_dir: str | None = None            # where to record (set by the CLI)
    rig_path: str | None = None               # custom rig JSON; None = packaged default_rig.json
    audio_device: str | int | None = None     # explicit audio input device; None = auto-detect "XDJ"


class App:
    """Owns the threads and the single stop event; guarantees clean shutdown."""

    def __init__(
        self,
        config: AppConfig | None = None,
        clock: Clock | None = None,
        backend: OutputBackend | None = None,
    ) -> None:
        self.config = config or AppConfig()
        self.clock = clock or RealClock()
        self.stop_event = threading.Event()

        # --- output pipeline (Phase 0; real Enttec in hardware mode) ---
        self.frame_buffer = DmxFrameBuffer()
        self.backend = backend or self._build_backend()
        self.writer = DmxWriter(
            self.frame_buffer,
            self.backend,
            self.clock,
            self.stop_event,
            hz=self.config.dmx_rate_hz,
        )

        # --- input pipeline (Phase 1; real PDL+MIDI in hardware mode) ---
        self.input_queue: "queue.Queue" = queue.Queue()
        self.show_state = ShowState()
        self.metronome = Metronome(self.input_queue, self.show_state, self.clock, self.stop_event)
        self.sources = self._build_sources()

        # --- show pipeline (Phases 3-4): snapshot -> engines -> merge -> frame buffer ---
        self.rig: Rig = load_rig(self.config.rig_path)
        self.manual = ManualParams()
        if self.config.config_path:
            app_config.load_into(self.manual, self.config.config_path)
        # In demo mode, simulate the operator arming lasers before the set so drop
        # scenes can show them. Lasers still boot off and only fire in drop scenes;
        # real/hardware mode leaves them disarmed until the operator arms (safety).
        if self.config.demo:
            self.manual.laser_enable = True
        self.phrase_engine = PhraseEngine()
        self.reactive_engine = ReactiveLayerEngine(self.clock)
        # Order matters: Reactive base, then Phrase (scene movement/laser win via
        # last-write), then Transition (its lift max-merges over the held look).
        self.engines = [self.reactive_engine, self.phrase_engine, TransitionEngine()]
        self.show_engine = ShowEngine(
            self.show_state, self.rig, self.frame_buffer, self.engines,
            self.manual, self.clock, self.stop_event,
            phrase_engine=self.phrase_engine,
        )

        # Core engine threads (always present). Input sources are managed separately
        # since some (e.g. MIDI) aren't threads themselves.
        self._core_threads: list[threading.Thread] = [
            self.metronome, self.show_engine, self.writer,
        ]

        # --- optional session recording (for hardware testing / feedback) ---
        self.recorder = None
        if self.config.record and self.config.session_dir:
            self._setup_recording(self.config.session_dir)

    def _setup_recording(self, session_dir: str) -> None:
        from .recorder import SessionRecorder, write_meta, write_notes_template

        write_notes_template(session_dir)
        write_meta(session_dir, {
            "mode": "demo" if self.config.demo else "hardware",
            "dmx_rate_hz": self.config.dmx_rate_hz,
            "pdl_interface": self.config.pdl_interface,
        })
        self.recorder = SessionRecorder(
            self.show_state, self.frame_buffer, self.clock, self.stop_event, session_dir,
            reactive_engine=self.reactive_engine, phrase_engine=self.phrase_engine,
            laser_trigger=self.show_engine.laser_trigger, silence_detector=self.show_engine.silence,
            rig=self.rig,
        )
        self._core_threads.append(self.recorder)
        log.info("Recording session to %s", session_dir)

    # ------------------------------------------------------------------ wiring
    def _build_backend(self) -> OutputBackend:
        """NullLog in demo; the Enttec in hardware mode, falling back to NullLog
        (with a warning) if no device is present so the app still runs."""
        if self.config.demo:
            return NullLogBackend(log_every=int(self.config.dmx_rate_hz))
        try:
            from serial.tools import list_ports

            from .output.enttec import EnttecSerialBackend, select_enttec_port

            if select_enttec_port(list_ports.comports()):
                return EnttecSerialBackend()
            log.warning("Hardware mode: no Enttec detected; output will be logged only.")
        except Exception:  # noqa: BLE001
            log.exception("Hardware mode: Enttec backend unavailable — logging output only.")
        return NullLogBackend(log_every=int(self.config.dmx_rate_hz))

    def _build_sources(self) -> list:
        """DemoDataSource in demo; real PDL + MIDI listeners in hardware mode."""
        if self.config.demo:
            return [DemoDataSource(self.input_queue, self.clock, self.stop_event)]

        from .inputs.audio import AudioAnalyzer
        from .inputs.midi import MidiListener
        from .inputs.midi_map import CcMap
        from .inputs.prodj import ProDjLinkListener

        cc_map = CcMap()
        if self.config.midi_map_path and os.path.exists(self.config.midi_map_path):
            try:
                cc_map = CcMap.load(self.config.midi_map_path)
            except Exception:  # noqa: BLE001
                log.warning("Could not load MIDI map %s; using defaults", self.config.midi_map_path)
        return [
            ProDjLinkListener(self.input_queue, self.clock, self.stop_event,
                              interface=self.config.pdl_interface),
            MidiListener(self.input_queue, self.clock, cc_map),
            AudioAnalyzer(self.input_queue, self.clock, self.stop_event,
                          device=self.config.audio_device),
        ]

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        log.info(
            "Starting LiveReact (mode=%s, dmx=%.0f Hz, backend=%s)",
            "demo" if self.config.demo else "hardware",
            self.config.dmx_rate_hz,
            self.backend.name,
        )
        for t in self._core_threads:
            t.start()
        for source in self.sources:
            try:
                source.start()
            except Exception:  # noqa: BLE001 - a failed input must not abort startup
                log.exception("Input source %r failed to start; continuing without it", source.name)

    def shutdown(self) -> None:
        if self.stop_event.is_set():
            return
        log.info("Shutting down...")
        self.stop_event.set()
        for source in self.sources:
            try:
                source.stop()
            except Exception:  # noqa: BLE001
                log.exception("Error stopping source %r", source.name)
        threads = self._core_threads + [s for s in self.sources if isinstance(s, threading.Thread)]
        for t in threads:
            t.join(timeout=3.0)
            if t.is_alive():
                log.warning("Thread %s did not stop within timeout", t.name)
        if self.config.config_path:
            app_config.save_from(self.manual, self.config.config_path)
        if self.recorder is not None and self.config.session_dir:
            from .recorder import write_summary

            write_summary(self.config.session_dir, {
                "frames_sent": self.writer.frames_sent,
                "state_samples": self.recorder.samples,
            })
        log.info("Shutdown complete (%d frames sent)", self.writer.frames_sent)

    def serve(self) -> None:
        """Start threads and block until a stop signal, Ctrl-C, or duration end."""
        self.install_signal_handlers()
        self.start()
        try:
            if self.config.duration is not None:
                self.stop_event.wait(self.config.duration)
            else:
                # Wake periodically so the main thread stays responsive to signals.
                while not self.stop_event.wait(0.25):
                    pass
        except KeyboardInterrupt:
            log.info("KeyboardInterrupt received")
        finally:
            self.shutdown()

    def install_signal_handlers(self) -> None:
        def handler(signum, _frame):
            log.info("Received signal %s", signum)
            self.stop_event.set()

        # signal.signal only works on the main thread; ignore if not (e.g. tests).
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError, AttributeError):
                pass
