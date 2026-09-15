"""Shared musical-timing helpers used by engines and scenes."""

from __future__ import annotations

from .core.show_state import ShowSnapshot


def musical_bar_position(snap: ShowSnapshot) -> float:
    """Continuous position in *bars* (float), for slow scene-level movement."""
    return snap.bar + (snap.beat_in_bar - 1 + snap.beat_phase) / 4.0
