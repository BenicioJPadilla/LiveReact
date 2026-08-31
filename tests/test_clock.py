"""Tests for the clock abstraction and the drift-corrected loop timer."""

from __future__ import annotations

import pytest

from livereact.clock import Clock, FakeClock, LoopTimer, RealClock


def test_fakeclock_advances_only_on_sleep_or_advance():
    c = FakeClock(start=10.0)
    assert c.monotonic() == 10.0
    c.sleep(1.5)
    assert c.monotonic() == 11.5
    c.sleep(-1.0)  # negative sleep is a no-op
    assert c.monotonic() == 11.5
    c.advance(0.5)
    assert c.monotonic() == 12.0


def test_clocks_satisfy_protocol():
    assert isinstance(FakeClock(), Clock)
    assert isinstance(RealClock(), Clock)


def test_loop_timer_paces_at_fixed_rate():
    c = FakeClock()
    timer = LoopTimer(c, hz=40)  # 25 ms period
    for _ in range(10):
        timer.wait()
    # 10 ticks at 25 ms each, drift-free.
    assert c.monotonic() == pytest.approx(10 * 0.025)


def test_loop_timer_corrects_for_slow_work():
    c = FakeClock()
    timer = LoopTimer(c, hz=10)  # 100 ms period
    timer.wait()
    assert c.monotonic() == pytest.approx(0.1)
    # Simulate the loop body taking 50 ms of real work...
    c.advance(0.05)  # now at 0.15
    timer.wait()
    # ...the timer should sleep only the remaining 50 ms to stay on the grid.
    assert c.monotonic() == pytest.approx(0.2)


def test_loop_timer_resyncs_after_a_stall():
    c = FakeClock()
    timer = LoopTimer(c, hz=10, max_lag_periods=2.0)  # max lag 200 ms
    timer.wait()  # -> 0.1
    # A long stall pushes us far past the deadline grid.
    c.advance(0.5)  # now 0.6, deadline grid is at 0.2 -> 0.4 s behind
    timer.wait()
    # Too far behind: resync to "now" rather than firing a burst of catch-up ticks.
    assert c.monotonic() == pytest.approx(0.6)


def test_loop_timer_rejects_nonpositive_rate():
    with pytest.raises(ValueError):
        LoopTimer(FakeClock(), hz=0)
