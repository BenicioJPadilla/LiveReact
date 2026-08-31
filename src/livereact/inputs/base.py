"""Input-source interface.

Every input — the demo generator now, the real Pro DJ Link + MIDI listeners in
Phase 7 — implements this same contract: it runs on its own thread and pushes
:mod:`livereact.core.messages` onto the shared queue. Because the metronome only
ever consumes that queue, a ``DemoDataSource`` and a ``LiveInput`` are perfectly
interchangeable (docs/11 §2).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class InputSource(Protocol):
    @property
    def name(self) -> str:
        ...

    def start(self) -> None:
        """Begin producing messages (typically starts a thread)."""
        ...

    def stop(self) -> None:
        """Signal the source to stop. May be a no-op if a shared stop event is used."""
        ...
