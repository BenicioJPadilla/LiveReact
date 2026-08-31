"""Shared musical-timing helpers used by engines and scenes."""

from __future__ import annotations

import math

from .core.show_state import ShowSnapshot

DEFAULT_PULSE_TAU = 0.09  # s; exponential decay giving a ~200 ms pulse tail


def beat_pulse(snap: ShowSnapshot, tau: float = DEFAULT_PULSE_TAU) -> float:
    """1.0 on the beat, decaying exponentially across it (one peak per beat)."""
    if snap.bpm <= 0:
        return 0.0
    t_in_beat = snap.beat_phase * (60.0 / snap.bpm)
    return math.exp(-t_in_beat / tau)


def musical_bar_position(snap: ShowSnapshot) -> float:
    """Continuous position in *bars* (float), for slow scene-level movement."""
    return snap.bar + (snap.beat_in_bar - 1 + snap.beat_phase) / 4.0
