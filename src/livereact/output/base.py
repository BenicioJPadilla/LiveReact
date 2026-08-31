"""Output backend interface.

DMX output lives behind this interface so the same engine can drive an Enttec over
serial, an Art-Net/sACN node over UDP, or a null/log sink for hardware-free demo
and tests — chosen at wiring time, never known to the engine. (Analysis: docs/05
§5.5, docs/07.)
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class OutputBackend(Protocol):
    """A sink for 512-byte DMX universes, driven by the DMX writer thread."""

    @property
    def name(self) -> str:
        """Human-readable backend name for logs/UI."""
        ...

    def open(self) -> None:
        """Acquire the device/socket. May raise; the writer handles failures."""
        ...

    def send(self, universe: bytes) -> None:
        """Transmit one 512-byte universe. May raise on device failure."""
        ...

    def close(self) -> None:
        """Release the device/socket. Must not raise."""
        ...
