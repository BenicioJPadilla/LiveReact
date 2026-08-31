"""Headless smoke test for the manual fixture-test panel (Qt offscreen)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from livereact.core.frame_buffer import DmxFrameBuffer  # noqa: E402
from livereact.fixtures.rig import load_rig  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    from PySide6 import QtWidgets

    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_panel_builds_a_slider_per_used_channel(qapp):
    from livereact.ui.fixture_test import FixtureTestPanel

    rig = load_rig()
    fb = DmxFrameBuffer()
    panel = FixtureTestPanel(rig, fb)
    assert len(panel._sliders) == 74  # one per used channel


def test_moving_a_slider_publishes_that_channel(qapp):
    from livereact.ui.fixture_test import FixtureTestPanel

    rig = load_rig()
    fb = DmxFrameBuffer()
    panel = FixtureTestPanel(rig, fb)
    panel._sliders[55].setValue(200)   # Par Left, channel 55 (index 54)
    assert fb.latest()[54] == 200


def test_flash_lights_a_single_fixture(qapp):
    from livereact.ui.fixture_test import FixtureTestPanel

    rig = load_rig()
    fb = DmxFrameBuffer()
    panel = FixtureTestPanel(rig, fb)
    panel._flash(rig.fixture("par_l"))
    frame = fb.latest()
    par = rig.fixture("par_l")
    assert any(frame[par.offset + i] for i in range(4))  # the flashed fixture is lit
