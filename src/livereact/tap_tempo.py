"""Tap-tempo: estimate BPM from operator taps — the emergency clock when Pro DJ
Link isn't available (docs/10 C6).

Pure and testable: feed it monotonic timestamps, get back a BPM estimate. The
console turns each tap into a master BeatMessage so the metronome locks to it.
"""

from __future__ import annotations

MIN_BPM = 40.0
MAX_BPM = 220.0


class TapTempo:
    def __init__(self, timeout: float = 2.0, max_intervals: int = 6) -> None:
        self.timeout = timeout          # gap (s) that resets a tap sequence
        self.max_intervals = max_intervals
        self._taps: list[float] = []

    def reset(self) -> None:
        self._taps.clear()

    def tap(self, now: float) -> float | None:
        """Record a tap; return the current BPM estimate, or None if not enough taps."""
        if self._taps and (now - self._taps[-1]) > self.timeout:
            self._taps.clear()  # too long since the last tap: start over
        self._taps.append(now)
        # Keep only the most recent taps.
        if len(self._taps) > self.max_intervals + 1:
            self._taps = self._taps[-(self.max_intervals + 1):]
        if len(self._taps) < 2:
            return None
        avg_interval = (self._taps[-1] - self._taps[0]) / (len(self._taps) - 1)
        if avg_interval <= 0:
            return None
        bpm = 60.0 / avg_interval
        return max(MIN_BPM, min(MAX_BPM, bpm))
