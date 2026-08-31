"""Tests for ShowState: immutable snapshots and tear-free concurrent reads."""

from __future__ import annotations

import dataclasses
import threading

import pytest

from livereact.core.show_state import ShowSnapshot, ShowState


def test_snapshot_is_frozen():
    snap = ShowSnapshot(bpm=120.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.bpm = 130.0  # type: ignore[misc]


def test_publish_then_snapshot_round_trips():
    state = ShowState()
    snap = ShowSnapshot(bpm=128.0, bar=5)
    state.publish(snap)
    assert state.snapshot() is snap
    assert state.snapshot().bpm == 128.0


def test_default_snapshot_is_sane():
    snap = ShowState().snapshot()
    assert snap.bpm == 124.0
    assert snap.free_running and not snap.pdl_fresh


def test_concurrent_reads_are_never_torn():
    """A writer publishes snapshots carrying an internal invariant (energy == bar);
    readers must only ever observe whole snapshots where the invariant holds."""
    state = ShowState()
    stop = threading.Event()
    errors: list[str] = []

    def writer():
        i = 0
        while not stop.is_set():
            i += 1
            state.publish(ShowSnapshot(bar=i, energy=float(i)))

    def reader():
        while not stop.is_set():
            s = state.snapshot()
            if s.energy != float(s.bar):  # would only fail on a torn read
                errors.append(f"torn: bar={s.bar} energy={s.energy}")
                return

    threads = [threading.Thread(target=writer)] + [
        threading.Thread(target=reader) for _ in range(4)
    ]
    for t in threads:
        t.start()
    stop.wait(0.5)
    stop.set()
    for t in threads:
        t.join(timeout=2.0)

    assert not errors, errors[:3]
