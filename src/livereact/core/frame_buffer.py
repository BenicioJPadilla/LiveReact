"""Double-buffered DMX universe — the publish/consume boundary between the show
engine and the DMX writer.

This is the mechanism that makes the spec's "the DMX writer never stops" promise
true (Analysis: docs/05 §5.1). The engine renders a complete frame and *publishes*
it atomically; the writer always reads the last *complete* published frame. If the
engine stalls or throws, nothing new is published and the writer keeps emitting the
last good frame — the rig holds steady instead of flickering or going dark.
"""

from __future__ import annotations

import threading

UNIVERSE_SIZE = 512  # DMX-512: one universe is 512 channels


class DmxFrameBuffer:
    """Thread-safe single-slot publisher of a 512-byte DMX universe.

    Frames are stored as immutable ``bytes``; publishing is a single reference
    swap under a short lock, so the writer can never observe a half-written frame.
    Starts holding an all-zero (blackout) frame so the writer has something valid
    to emit before the engine produces its first frame.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._published: bytes = bytes(UNIVERSE_SIZE)

    def publish(self, frame: bytes | bytearray) -> None:
        """Atomically make ``frame`` the current universe.

        Copies into immutable ``bytes`` so a caller reusing a ``bytearray`` work
        buffer can't mutate an already-published frame out from under the writer.
        """
        frame = bytes(frame)  # copy + immutability
        if len(frame) != UNIVERSE_SIZE:
            raise ValueError(
                f"DMX frame must be exactly {UNIVERSE_SIZE} bytes, got {len(frame)}"
            )
        with self._lock:
            self._published = frame

    def latest(self) -> bytes:
        """Return the most recently published frame (keep-last-frame semantics)."""
        with self._lock:
            return self._published
