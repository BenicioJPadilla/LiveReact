"""Headless tests for the scaled venue floor plan (ui/floorplan.py)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from livereact.fixtures.geometry import Point3, Venue, ft_to_m  # noqa: E402
from livereact.fixtures.rig import _rig_from_dict, load_rig  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def qapp():
    from PySide6 import QtWidgets

    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _josh_rig_with_venue():
    rig = load_rig(os.path.join(HERE, "rigs", "josh_rig.json"))
    w, l, h = ft_to_m(30), ft_to_m(40), ft_to_m(12)
    rig.venue = Venue(w, l, h, Venue.default_targets(w, l, h))
    mh, laser = rig.fixture("mh"), rig.fixture("laser")
    mh.position = Point3(ft_to_m(5), ft_to_m(2), ft_to_m(1))
    laser.position = Point3(ft_to_m(25), ft_to_m(2), laser.mount_height_m)
    rig.refresh_geometry()
    return rig


def test_plan_draws_the_default_rig_without_any_venue(qapp):
    from livereact.ui.floorplan import FloorPlanView
    from livereact.ui.visualizer import build_demo_universe

    rig = load_rig()
    view = FloorPlanView(rig, editable=False)
    assert len(view._bodies) == 8
    view.update_from_universe(rig.boot_universe())
    view.update_from_universe(build_demo_universe(rig, 1.0))   # lit, lasers in the drop window
    # every fixture lands inside the default room
    v = view.venue()
    for key in view._bodies:
        x, y = view.item_position_m(key)
        assert 0 <= x <= v.width_m and 0 <= y <= v.length_m


def test_plan_places_positioned_fixtures_to_the_centimetre(qapp):
    from livereact.ui.floorplan import FloorPlanView

    rig = _josh_rig_with_venue()
    view = FloorPlanView(rig, editable=True)
    x, y = view.item_position_m("mh")
    assert x == pytest.approx(ft_to_m(5), abs=0.01)
    assert y == pytest.approx(ft_to_m(2), abs=0.01)
    assert set(view._targets) == {"dj_booth", "dancefloor_centre", "back_wall", "ceiling_bounce"}


def test_the_real_laser_mount_is_flagged_unsafe(qapp):
    """josh_rig.json's laser sits at 0.9144 m -- below the LASER-09 3.0 m
    rule -- so the plan must say so, matching apply_safety's fail-closed."""
    from livereact.ui.floorplan import FloorPlanView

    rig = _josh_rig_with_venue()
    view = FloorPlanView(rig, editable=False)
    view.update_from_universe(rig.boot_universe())
    assert view.laser_unsafe("laser")
    rig.fixture("laser").position = Point3(ft_to_m(25), ft_to_m(2), 3.5)
    rig.fixture("laser").mount_height_m = 3.5
    rig.fixture("laser").beam_tilt_deg = 5.0
    view.update_from_universe(rig.boot_universe())
    assert not view.laser_unsafe("laser")


def test_show_tab_plan_is_not_movable_but_venue_plan_is(qapp):
    from PySide6 import QtWidgets
    from livereact.ui.floorplan import FloorPlanView

    movable = QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
    rig = _josh_rig_with_venue()
    ro = FloorPlanView(rig, editable=False)
    assert all(not (i.flags() & movable) for i in ro._bodies.values())
    assert all(not (i.flags() & movable) for i in ro._targets.values())
    rw = FloorPlanView(rig, editable=True)
    assert all(i.flags() & movable for i in rw._bodies.values())


def test_moving_head_beam_lands_where_the_geometry_says(qapp):
    """With a captured calibration, the drawn beam ends at the floor hit of
    the head's current pan/tilt."""
    from livereact.fixtures.geometry import aim
    from livereact.merge.merge import Contribution, ManualParams, render_universe
    from livereact.ui.floorplan import FloorPlanView

    import math

    rig = _josh_rig_with_venue()
    mh = rig.fixture("mh")
    mh.position = Point3(ft_to_m(5), ft_to_m(2), ft_to_m(10))   # trussed high, so the beam reaches the floor
    target = rig.venue.targets["dancefloor_centre"]
    pan01, tilt01, ok = aim(mh.position, mh.facing_deg, target, mh.calibration, mh.PAN_RANGE_DEG, mh.TILT_RANGE_DEG)
    assert ok
    c = Contribution()
    mh.set_aim(c, pan01, tilt01)
    mh.set_intensity(c, 1.0)
    uni = render_universe([c], rig, ManualParams())
    view = FloorPlanView(rig, editable=False)
    view.update_from_universe(uni)
    line = view._beams["mh"].line()
    end_x, end_y = view.from_scene(line.p2())
    # the target is 1.0 m above the floor, so the beam lands a little past it
    # on the floor -- on exactly the same bearing from the head
    want = math.atan2(target.x - mh.position.x, target.y - mh.position.y)
    got = math.atan2(end_x - mh.position.x, end_y - mh.position.y)
    assert got == pytest.approx(want, abs=math.radians(0.5))
    assert math.hypot(end_x - mh.position.x, end_y - mh.position.y) > math.hypot(target.x - mh.position.x, target.y - mh.position.y)


def test_legacy_rig_json_without_geometry_draws_from_role_side_rows(qapp):
    from livereact.ui.floorplan import FloorPlanView

    rig = _rig_from_dict({"name": "t", "slots": [
        {"slot_id": "a", "fixture_type": "rgb_par", "dmx_address": 1, "role": "wash", "side": "left"},
        {"slot_id": "b", "fixture_type": "rgb_par", "dmx_address": 5, "role": "wash", "side": "right"},
    ]})
    view = FloorPlanView(rig)
    ax, _ = view.item_position_m("a")
    bx, _ = view.item_position_m("b")
    assert ax < bx
