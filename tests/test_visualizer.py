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


def test_demo_universe_enables_lasers_only_in_drop_window(qapp):
    rig = load_rig()
    laser = rig.fixture("laser_l")
    in_drop = build_demo_universe(rig, 1.0)     # t%16 < 4 -> drop
    out_of_drop = build_demo_universe(rig, 10.0)  # not a drop
    assert in_drop[laser.offset] != 0       # laser enabled during drop
    assert out_of_drop[laser.offset] == 0   # laser off otherwise
