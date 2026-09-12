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
from ..scenes.base import SAFE_DEFAULT
from .frame_buffer import DmxFrameBuffer
from .laser_trigger import LaserOnsetDetector
from .show_state import ShowState
from .silence import SilenceDetector

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
        phrase_engine=None,
        bible_failsafe_enabled: bool = False,
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
        # Named reference (2026-09-07, see [[livereact-project]] memory) so the
        # laser trigger can be gated on the ACTIVE scene's own `uses_lasers` --
        # confirmed live that without this, the laser fires happily during
        # scenes that can't even show it. Optional/defaults None (rather than
        # required) so anything constructing a bare ShowEngine without a
        # PhraseEngine (e.g. a minimal test harness) still works -- the gate
        # just falls back to LaserOnsetDetector's own default (True) then.
        self.phrase_engine = phrase_engine
        # Bible-integration Phase 1, LOOK-08/FAIL-04, gig-safe migration flag
        # (docs/bible_integration/, /Users/joshuaracimora/.claude/plans/
        # adaptive-squishing-pebble.md): off by default so the old
        # instant-hard-zero auto_blackout failsafe stays selectable until
        # explicitly enabled and approved for real hardware use. When True,
        # auto_blackout renders SAFE_DEFAULT instead of total darkness.
        self.bible_failsafe_enabled = bible_failsafe_enabled
        self._last: dict[str, Contribution] = {}
        self._last_tick_t: float | None = None  # for dt -> movement slew-limiting (LIGHTING_BIBLE.md §6.6)
        self.silence = SilenceDetector(clock)  # docs/14 §2; .active exposed for the console
        self.laser_trigger = LaserOnsetDetector(clock)  # docs/14 §3; .active exposed for the console

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
                # Bible-integration Phase 4: tag with the producing engine's
                # own Titan-tier priority (see engines/reactive.py's own
                # comment) so merge_contributions' LTP-by-priority resolution
                # has something real to sort on, not an accident of this
                # list's own order.
                contribution.priority = engine.priority
                self._last[engine.name] = contribution
            except Exception:  # noqa: BLE001 - isolate a faulty engine
                log.exception("Engine %r failed; reusing last contribution", engine.name)
                contribution = self._last.get(engine.name)
            if contribution is not None:
                contributions.append(contribution)

        if self.manual.freeze:
            return None  # hold the last published frame

        now = self.clock.monotonic()
        dt = (now - self._last_tick_t) if self._last_tick_t is not None else 1.0 / self.hz
        self._last_tick_t = now

        auto_blackout = self.silence.update(snap)
        scene_uses_lasers = self.phrase_engine._current.uses_lasers if self.phrase_engine else True
        laser_flash = self.laser_trigger.update(snap, scene_uses_lasers)
        safe_default_frame = None
        if self.bible_failsafe_enabled and auto_blackout:
            safe_default_frame = merge_contributions([SAFE_DEFAULT.render(self.rig, snap, 1.0)], self.rig)
        frame = finalize(merge_contributions(contributions, self.rig), self.rig, self.manual,
                          auto_blackout, laser_flash, dt, safe_default_frame, snap.drop_pending)
        self.frame_buffer.publish(frame)
        return frame
