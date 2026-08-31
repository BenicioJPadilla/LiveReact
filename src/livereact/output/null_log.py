"""Null output backend: accepts frames and periodically logs throughput.

The default backend for demo mode and for proving the spine in Phase 0 — no
hardware, no drivers. It measures effective frame rate so you can confirm the
writer is holding a steady cadence.
"""

from __future__ import annotations

import logging

from .base import OutputBackend

log = logging.getLogger(__name__)


class NullLogBackend(OutputBackend):
    """Discards frames but counts them and logs an FPS/digest line periodically."""

    def __init__(self, log_every: int = 40) -> None:
        # 40 frames ~= once per second at the default 40 Hz writer rate.
        self._log_every = max(1, log_every)
        self._count = 0

    @property
    def name(self) -> str:
        return "null-log"

    def open(self) -> None:
        log.info("NullLogBackend open (frames will be discarded)")

    def send(self, universe: bytes) -> None:
        self._count += 1
        if self._count % self._log_every == 0:
            active = sum(1 for b in universe if b)
            log.info(
                "DMX frame #%d sent | %d/%d channels active",
                self._count,
                active,
                len(universe),
            )

    def close(self) -> None:
        log.info("NullLogBackend closed after %d frames", self._count)

    @property
    def frames_sent(self) -> int:
        return self._count
