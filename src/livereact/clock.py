"""Time abstraction for the whole system.

Every loop and every piece of real-time logic depends on a ``Clock`` rather than
calling :mod:`time` directly. Production wires in :class:`RealClock`; tests wire in
:class:`FakeClock`, which lets a 90-minute show simulation run in milliseconds and
makes beat-lock / drift-correction assertions deterministic with no hardware and no
real time passing. (Analysis: docs/05 §5.2.)
"""

from __future__ import annotations

import time
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """A monotonic time source with a sleep. The only time API the app may use."""

    def monotonic(self) -> float:
        """Seconds from an arbitrary fixed point; never goes backwards."""
        ...

    def sleep(self, seconds: float) -> None:
        """Block for ``seconds`` (<= 0 returns immediately)."""
        ...


class RealClock:
    """Production clock backed by :func:`time.monotonic` / :func:`time.sleep`.

    ``sleep`` uses a hybrid strategy: sleep the bulk of the interval, then
    busy-spin the final ``SPIN_TAIL`` for low jitter. On CPython 3.11+ the
    underlying ``time.sleep`` already uses a high-resolution waitable timer on
    Windows, so the spin tail only has to absorb the last sub-millisecond. The
    spin lives here, in the real clock, so :class:`FakeClock` never executes it.
    """

    SPIN_TAIL = 0.0012  # seconds of busy-spin at the end of a sleep

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        target = time.monotonic() + seconds
        bulk = seconds - self.SPIN_TAIL
        if bulk > 0:
            time.sleep(bulk)
        # Busy-spin the remainder for precision.
        while time.monotonic() < target:
            pass


class FakeClock:
    """Deterministic clock for tests. Time advances only when you tell it to.

    ``sleep`` advances simulated time instantly, so a loop that sleeps to pace
    itself runs as fast as the CPU allows while reporting exact, drift-free
    timestamps. Use :meth:`advance` to simulate work taking wall-clock time.
    """

    def __init__(self, start: float = 0.0) -> None:
        self._t = float(start)

    def monotonic(self) -> float:
        return self._t

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            self._t += seconds

    def advance(self, seconds: float) -> None:
        """Move simulated time forward without 'sleeping' (e.g. to model work)."""
        if seconds > 0:
            self._t += seconds


class LoopTimer:
    """Drift-corrected fixed-rate scheduler.

    Call :meth:`wait` once per loop iteration. It paces against an *absolute*
    deadline grid rather than sleeping a fixed period each time, so per-iteration
    work and sleep-overshoot don't accumulate into drift. If the loop falls more
    than ``max_lag_periods`` behind (a stall), it resyncs to "now" instead of
    trying to catch up — avoiding a death-spiral of back-to-back iterations.
    """

    def __init__(self, clock: Clock, hz: float, max_lag_periods: float = 2.0) -> None:
        if hz <= 0:
            raise ValueError("hz must be positive")
        self.clock = clock
        self.period = 1.0 / hz
        self._max_lag = self.period * max_lag_periods
        self._deadline: float | None = None

    def wait(self) -> None:
        now = self.clock.monotonic()
        if self._deadline is None:
            self._deadline = now
        self._deadline += self.period
        delay = self._deadline - now
        if delay > 0:
            self.clock.sleep(delay)
        elif delay < -self._max_lag:
            # Fell too far behind; abandon the missed grid points and resync.
            self._deadline = now
