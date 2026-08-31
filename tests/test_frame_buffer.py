"""Tests for the double-buffered DMX frame buffer."""

from __future__ import annotations

import pytest

from livereact.core.frame_buffer import UNIVERSE_SIZE, DmxFrameBuffer


def test_starts_with_blackout_frame():
    buf = DmxFrameBuffer()
    frame = buf.latest()
    assert len(frame) == UNIVERSE_SIZE
    assert frame == bytes(UNIVERSE_SIZE)  # all zeros


def test_publish_then_latest_round_trips():
    buf = DmxFrameBuffer()
    frame = bytes([255] + [0] * (UNIVERSE_SIZE - 1))
    buf.publish(frame)
    assert buf.latest() == frame


def test_keep_last_frame_when_nothing_new_published():
    buf = DmxFrameBuffer()
    first = bytes([1] * UNIVERSE_SIZE)
    buf.publish(first)
    assert buf.latest() == first
    # No new publish -> the writer keeps seeing the last good frame.
    assert buf.latest() == first


def test_publish_copies_so_caller_mutation_is_isolated():
    buf = DmxFrameBuffer()
    work = bytearray(UNIVERSE_SIZE)
    work[0] = 100
    buf.publish(work)
    work[0] = 200  # mutate the caller's buffer after publishing
    assert buf.latest()[0] == 100  # published frame is unaffected


def test_publish_rejects_wrong_length():
    buf = DmxFrameBuffer()
    with pytest.raises(ValueError):
        buf.publish(bytes(10))
    with pytest.raises(ValueError):
        buf.publish(bytes(UNIVERSE_SIZE + 1))
