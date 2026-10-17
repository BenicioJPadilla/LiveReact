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
    merge_contributions_ex,
    strip_strobe,
    strobe_allowed,
)
from .frame_buffer import UNIVERSE_SIZE
from ..scenes.base import SAFE_DEFAULT
from .frame_buffer import DmxFrameBuffer
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
        laser_engine=None,
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
        # Named reference for the console/recorder (the active look's name).
        # Optional/defaults None so a bare ShowEngine without a PhraseEngine
        # (e.g. a minimal test harness) still works.
        self.phrase_engine = phrase_engine
        # engines/laser.py's LaserEngine -- the one authority over the laser
        # channels (2026-09-15). It must ALSO be in `engines` (that's where it
        # renders); this reference is for the finalize gate below, which
        # reads its `.active` after the engines have ticked. None (e.g. a
        # minimal test harness) means the gate stays closed: no laser.
        self.laser_engine = laser_engine
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

        # Freeze holds the last published frame, but blackout wins over it
        # (2026-10-16): the operator's kill switch (B, or the phone console)
        # must reach the rig even mid-hold, and a held frame may contain a
        # lit laser. With blackout set, fall through so finalize publishes
        # its all-zero frame.
        if self.manual.freeze and not self.manual.blackout:
            # Strobe off wins over freeze too (2026-10-17): a held frame may
            # have a fixture's own strobe channel running (a Space burst),
            # which would keep flashing. Re-publish it with those at 0.
            if not strobe_allowed(self.manual):
                held = self.frame_buffer.latest()
                safe = strip_strobe(held, self.rig)
                if safe != held:
                    self.frame_buffer.publish(safe)
            return None

        now = self.clock.monotonic()
        dt = (now - self._last_tick_t) if self._last_tick_t is not None else 1.0 / self.hz
        self._last_tick_t = now

        auto_blackout = self.silence.update(snap)
        # 2026-10-05: Venue-tab calibration pins mean an operator is at the
        # console jogging a REAL fixture (TESTING.md Test 5) -- usually with
        # no music, which is exactly when the no-music failsafe would black
        # the head they are trying to see ("when I go to the moving head,
        # it doesn't turn on, so I can't calibrate it" -- Josh). The pins
        # suppress auto-blackout; the operator's own blackout switch
        # (manual.blackout, finalize) still wins outright, and the silence
        # detector keeps updating so it re-engages the instant the pins clear.
        if self.manual.calibration is not None:
            auto_blackout = False
        laser_on = bool(self.laser_engine.active) if self.laser_engine is not None else False
        safe_default_frame = None
        if self.bible_failsafe_enabled and auto_blackout:
            safe_default_frame = merge_contributions([SAFE_DEFAULT.render(self.rig, snap, 1.0)], self.rig)
        merged, absolute = merge_contributions_ex(contributions, self.rig)
        # Venue-tab calibration pins (merge/merge.py's CalibrationPins,
        # 2026-09-18): overwrite the merged frame BEFORE finalize, so every
        # safety clamp and the slew limit still apply to a pinned fixture.
        pins = self.manual.calibration
        pinned: frozenset[int] = frozenset()
        if pins is not None:
            for ch, value in pins.channels.items():
                if 1 <= ch <= UNIVERSE_SIZE:
                    merged[ch - 1] = 0 if value < 0 else 255 if value > 255 else int(value)
            for slot in pins.absolute_slots:
                try:
                    off = self.rig.fixture(slot).offset
                    absolute = absolute | {off}
                    pinned = pinned | {off}
                except KeyError:
                    pass
            laser_on = laser_on or pins.laser_open
        frame = finalize(merged, self.rig, self.manual, auto_blackout, laser_on, dt,
                         safe_default_frame, snap.drop_pending, absolute_movement=absolute,
                         pinned_movement=pinned)
        self.frame_buffer.publish(frame)
        return frame
