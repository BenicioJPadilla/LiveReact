"""Headless smoke test for the PySide6 visualizer.

Runs Qt with the 'offscreen' platform so no display is needed. We can't assert on
pixels here; the fixture->visual mapping logic is covered by test_fixtures. This
just proves the widgets construct and update against real universes without error.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from livereact.fixtures.rig import load_rig  # noqa: E402
from livereact.ui.visualizer import (  # noqa: E402
    VisualizerWindow,
    build_demo_universe,
)


@pytest.fixture(scope="module")
def qapp():
    from PySide6 import QtWidgets

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def test_window_constructs_and_updates(qapp):
    rig = load_rig()
    win = VisualizerWindow(rig)
    win.update_from_universe(rig.boot_universe())
    # A couple of animation frames, including a 'drop' window (t in [0,4) enables lasers).
    for t in (0.5, 2.0, 8.0, 12.0):
        win.update_from_universe(build_demo_universe(rig, t))
    # Inspector row count == number of used channels (74).
    assert win.inspector.rowCount() == 74


def test_demo_universe_lasers_flash_within_the_drop_window_not_held_on(qapp):
    """docs/14 §3: within a drop window the laser should flash near beat-like
    pulse peaks, not stay continuously on for the whole window (the old,
    pre-onset-gate behavior this test used to check for)."""
    rig = load_rig()
    laser = rig.fixture("laser_l")
    samples = [build_demo_universe(rig, i * 0.05)[laser.offset] for i in range(80)]  # t = 0..4s
    assert any(v != 0 for v in samples), "laser never flashed within the drop window"
    assert any(v == 0 for v in samples), "laser held on for the whole drop window"
    out_of_drop = build_demo_universe(rig, 10.0)  # not a drop at all
    assert out_of_drop[laser.offset] == 0
