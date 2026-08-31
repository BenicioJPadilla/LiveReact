"""ShowEngine: snapshot -> engines -> merge -> publish, at ~60 Hz.

The conductor. Each tick it reads one ShowState snapshot, runs every engine under
its own try/except (a crashing engine is skipped, reusing its previous contribution
— a Phrase Engine bug must never stop the Reactive Layer), merges the contributions,
applies manual params + safety, and publishes the finished frame to the double
buffer. ``freeze`` simply skips publishing, so the writer holds the last good frame
(docs/05 §5.1, §5.3).
"""

from __future__ import annotations

import logging
import threading

from ..clock import Clock, LoopTimer
from ..fixtures.rig import Rig
from ..merge.merge import (
    Contribution,
    ManualParams,
    finalize,
    merge_contributions,
)
from .frame_buffer import DmxFrameBuffer
from .show_state import ShowState

log = logging.getLogger(__name__)


class ShowEngine(threading.Thread):
    def __init__(
        self,
        show_state: ShowState,
        rig: Rig,
        frame_buffer: DmxFrameBuffer,
        engines: list,
        manual: ManualParams,
        clock: Clock,
        stop_event: threading.Event,
        hz: float = 60.0,
    ) -> None:
        super().__init__(name="show-engine", daemon=False)
        self.show_state = show_state
        self.rig = rig
        self.frame_buffer = frame_buffer
        self.engines = engines
        self.manual = manual
        self.clock = clock
        self.stop_event = stop_event
        self.hz = hz
        self._last: dict[str, Contribution] = {}

    def run(self) -> None:  # pragma: no cover - thin wrapper around tick()
        timer = LoopTimer(self.clock, self.hz)
        try:
            while not self.stop_event.is_set():
                self.tick()
                timer.wait()
        except Exception:  # noqa: BLE001
            log.exception("ShowEngine loop crashed")

    def tick(self) -> bytes | None:
        """Run one frame. Returns the published universe, or None if frozen."""
        snap = self.show_state.snapshot()

        contributions: list[Contribution] = []
        for engine in self.engines:
            try:
                contribution = engine.tick(snap, self.rig)
                self._last[engine.name] = contribution
            except Exception:  # noqa: BLE001 - isolate a faulty engine
                log.exception("Engine %r failed; reusing last contribution", engine.name)
                contribution = self._last.get(engine.name)
            if contribution is not None:
                contributions.append(contribution)

        if self.manual.freeze:
            return None  # hold the last published frame

        frame = finalize(merge_contributions(contributions, self.rig), self.rig, self.manual)
        self.frame_buffer.publish(frame)
        return frame
