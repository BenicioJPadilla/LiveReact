"""The DMX writer thread — the one thread that must never stop.

It reads the last complete frame from the double buffer and pushes it to the output
backend at a steady rate (~40 Hz). Every per-iteration failure is contained: on a
backend error it logs, attempts a close+reopen with capped backoff, and keeps
ticking on the last good frame. No exception is allowed to escape the loop, so the
lights keep running even when everything upstream has failed. (Analysis: docs/05
§5.1, NFR-5.)

The same loop is the Enttec hot-plug (2026-10-16): a device missing at launch
or pulled mid-set is just an output that won't open yet, retried about once a
second until it's back, logged once when it goes down, every
DOWN_LOG_INTERVAL_S while it stays down, and once when it returns.
"""

from __future__ import annotations

import logging
import threading

from ..clock import Clock, LoopTimer
from ..core.frame_buffer import DmxFrameBuffer
from .base import OutputBackend

log = logging.getLogger(__name__)

DOWN_LOG_INTERVAL_S = 30.0  # a down output says so this often, not on every retry


class DmxWriter(threading.Thread):
    """Pulls published frames and writes them to a backend at a fixed rate."""

    def __init__(
        self,
        frame_buffer: DmxFrameBuffer,
        backend: OutputBackend,
        clock: Clock,
        stop_event: threading.Event,
        hz: float = 40.0,
        max_backoff: float = 1.0,  # 2.0 -> 1.0 (2026-10-16): a replugged Enttec is back within ~1 s
    ) -> None:
        super().__init__(name="dmx-writer", daemon=False)
        self.frame_buffer = frame_buffer
        self.backend = backend
        self.clock = clock
        self.stop_event = stop_event
        self.hz = hz
        self._max_backoff = max_backoff
        self._frames_sent = 0
        self._consecutive_errors = 0
        self._is_open = False
        self._down_since: float | None = None  # start of the current outage, None while healthy
        self._reopened_last = False  # the previous failure's reopen succeeded (see _handle_send_error)
        self._last_down_log = 0.0

    @property
    def frames_sent(self) -> int:
        return self._frames_sent

    @property
    def is_open(self) -> bool:
        """True once the backend's ``open()`` has succeeded (console health indicator)."""
        return self._is_open

    @property
    def output_ok(self) -> bool:
        """Open AND frames are actually going out (a wedged Enttec can reopen
        fine and still fail every write). For the console's DMX light."""
        return self._is_open and self._down_since is None

    def run(self) -> None:  # pragma: no cover - thin wrapper around _run_loop
        # Outer guard: even an unexpected error in the loop scaffolding itself
        # must not kill the thread silently without a trace.
        try:
            self._run_loop()
        except Exception:  # noqa: BLE001 - last-resort safety net
            log.exception("DMX writer loop crashed unexpectedly")
        finally:
            self._safe_close()

    def _run_loop(self) -> None:
        timer = LoopTimer(self.clock, self.hz)
        self._safe_open()
        while not self.stop_event.is_set():
            try:
                frame = self.frame_buffer.latest()
                self.backend.send(frame)
                self._frames_sent += 1
                self._consecutive_errors = 0
                self._reopened_last = False
                if self._down_since is not None:
                    log.info("DMX output back on %r after %.1f s down",
                             self.backend.name, self.clock.monotonic() - self._down_since)
                    self._down_since = None
            except Exception:  # noqa: BLE001 - writer survives all backend faults
                self._handle_send_error()
            timer.wait()
        self._safe_close()

    def _safe_open(self) -> None:
        try:
            self.backend.open()
            self._is_open = True
        except Exception:  # noqa: BLE001
            self._is_open = False
            if self._note_down():
                log.warning("Output backend %r won't open; retrying about once a second "
                            "(plug the device in any time)", self.backend.name, exc_info=True)
            else:
                log.debug("Output backend %r still won't open", self.backend.name, exc_info=True)

    def _safe_close(self) -> None:
        if not self._is_open:
            return
        try:
            self.backend.close()
        except Exception:  # noqa: BLE001
            log.exception("Error closing output backend %r", self.backend.name)
        finally:
            self._is_open = False

    def _note_down(self) -> bool:
        """Mark the output as down. True when this failure should be logged:
        the first of an outage, then one every DOWN_LOG_INTERVAL_S (a night
        without the Enttec used to log two tracebacks a second)."""
        now = self.clock.monotonic()
        if self._down_since is None:
            self._down_since = self._last_down_log = now
            return True
        if now - self._last_down_log >= DOWN_LOG_INTERVAL_S:
            self._last_down_log = now
            log.warning("DMX output still down on %r after %.0f s (%d retries)",
                        self.backend.name, now - self._down_since, self._consecutive_errors)
        return False

    def _handle_send_error(self) -> None:
        self._consecutive_errors += 1
        if self._note_down():
            log.warning("Output send failed on backend %r; reopening and retrying",
                        self.backend.name, exc_info=True)
        # Close + reopen. A reopen that works goes straight back to sending
        # (a replugged Enttec lights on the next frame); back off (capped) only
        # while the device is missing, or when it opened and failed again, so
        # a dead device never spins open/close hot.
        self._safe_close()
        self._safe_open()
        if not self._is_open or self._reopened_last:
            self.clock.sleep(min(self._max_backoff, 0.05 * self._consecutive_errors))
        self._reopened_last = self._is_open
