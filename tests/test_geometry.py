"""fixtures/geometry.py: hand-computable cases for the venue coordinate
convention, the one-point aim capture, and the laser fan height check."""

from __future__ import annotations

import pytest

from livereact.fixtures.geometry import (
    HeadCalibration,
    Point3,
    Venue,
    aim,
    beam_floor_hit,
    bearing,
    calibrate_from_capture,
    calibrate_from_two_captures,
    ft_to_m,
    m_to_ft,
    pan_tilt_to_angles,
    ray_to_rect_edge,
    wrap_deg,
    x_norm,
)

PAN, TILT = 540.0, 270.0
O = Point3(0.0, 0.0, 0.0)


def test_feet_round_trip_and_the_lasers_measured_three_feet():
    assert ft_to_m(3.0) == pytest.approx(0.9144)
    assert m_to_ft(ft_to_m(12.5)) == pytest.approx(12.5)


def test_wrap_deg():
    assert wrap_deg(190) == -170
    assert wrap_deg(-190) == 170
    assert wrap_deg(180) == 180
    assert wrap_deg(540) == 180


def test_bearing_convention_az_zero_is_into_the_crowd_clockwise_positive():
    assert bearing(O, Point3(0, 10, 0)) == (pytest.approx(0.0), pytest.approx(0.0))
    assert bearing(O, Point3(10, 0, 0))[0] == pytest.approx(90.0)     # stage-right
    assert bearing(O, Point3(-10, 0, 0))[0] == pytest.approx(-90.0)   # stage-left
    assert bearing(O, Point3(0, 10, 10))[1] == pytest.approx(45.0)    # up
    assert bearing(Point3(0, 0, 5), Point3(0, 5, 0))[1] == pytest.approx(-45.0)  # down


def test_capture_straight_ahead_at_centre_gives_zero_offsets():
    cal = calibrate_from_capture(O, 0.0, Point3(0, 10, 0), 0.5, 0.5, PAN, TILT, target_name="dj_booth")
    assert cal.captured and cal.target == "dj_booth"
    assert cal.pan_offset_deg == pytest.approx(0.0)
    assert cal.tilt_offset_deg == pytest.approx(0.0)


def test_capture_solves_the_offset_the_hardware_actually_has():
    # The head was jogged to pan01=0.6 to hit a target that is really at az 0:
    # so its pan zero is 0.1*540 = 54 deg off -> offset -54.
    cal = calibrate_from_capture(O, 0.0, Point3(0, 10, 0), 0.6, 0.5, PAN, TILT)
    assert cal.pan_offset_deg == pytest.approx(-54.0)
    az, el = pan_tilt_to_angles(0.6, 0.5, 0.0, cal, PAN, TILT)
    assert az == pytest.approx(0.0) and el == pytest.approx(0.0)


def test_aim_at_ninety_degrees_and_invert_flips_it():
    cal = HeadCalibration()
    pan, tilt, ok = aim(O, 0.0, Point3(10, 0, 0), cal, PAN, TILT)
    assert ok
    assert pan == pytest.approx(0.5 + 90 / 540)
    assert tilt == pytest.approx(0.5)
    pan_i, _, ok = aim(O, 0.0, Point3(10, 0, 0), HeadCalibration(invert_pan=True), PAN, TILT)
    assert ok and pan_i == pytest.approx(0.5 - 90 / 540)


def test_aim_respects_facing_and_elevation():
    # Body rotated 90 deg clockwise: a target straight ahead of the ROOM is at az_rel -90.
    pan, tilt, ok = aim(O, 90.0, Point3(0, 10, 10), HeadCalibration(), PAN, TILT)
    assert ok
    assert pan == pytest.approx(0.5 - 90 / 540)
    assert tilt == pytest.approx(0.5 + 45 / 270)


def test_aim_round_trips_through_capture():
    origin = Point3(1.5, 0.6, 0.3)
    booth = Point3(4.5, 0.9, 1.2)
    cal = calibrate_from_capture(origin, 0.0, booth, 0.41, 0.63, PAN, TILT, target_name="dj_booth")
    pan, tilt, ok = aim(origin, 0.0, booth, cal, PAN, TILT)
    assert ok and pan == pytest.approx(0.41) and tilt == pytest.approx(0.63)
    # and pointing the model at the captured raw values lands on the booth
    az, el = pan_tilt_to_angles(0.41, 0.63, 0.0, cal, PAN, TILT)
    exp_az, exp_el = bearing(origin, booth)
    assert az == pytest.approx(exp_az) and el == pytest.approx(exp_el)


def test_aim_picks_the_wrap_nearest_the_captured_pan():
    # az_rel +170 is reachable as pan 0.5+170/540 or 0.5+(170-360)/540; a
    # capture near the low end should prefer the second.
    cal = HeadCalibration(pan01=0.1, target="x")
    pan, _, ok = aim(O, 0.0, Point3(10, -56.7, 0), cal, PAN, TILT)  # az ~ +170
    assert ok and pan < 0.5


def test_aim_unreachable_tilt_reports_it():
    # 270 deg of tilt spans +-135; a target requiring > +135 does not exist,
    # but a tilt OFFSET can push it out of range.
    cal = HeadCalibration(tilt_offset_deg=-100.0)
    _, tilt, ok = aim(O, 0.0, Point3(0, 1, 10), cal, PAN, TILT)  # el ~ 84 -> raw 184 > 135
    assert not ok and tilt == 1.0


def test_beam_floor_hit():
    hit = beam_floor_hit(Point3(0, 0, 3), 0.0, -45.0)
    assert hit is not None
    assert (hit.x, hit.y, hit.z) == (pytest.approx(0.0), pytest.approx(3.0), 0.0)
    assert beam_floor_hit(Point3(0, 0, 3), 0.0, 10.0) is None


def test_ray_to_rect_edge():
    assert ray_to_rect_edge((5, 0), 0.0, 10, 20) == pytest.approx(20.0)
    assert ray_to_rect_edge((5, 0), 90.0, 10, 20) == pytest.approx(5.0)
    assert ray_to_rect_edge((5, 5), -90.0, 10, 20) == pytest.approx(5.0)



def test_x_norm_and_default_targets():
    assert x_norm(0.0, 9.0) == -1.0
    assert x_norm(4.5, 9.0) == 0.0
    assert x_norm(9.0, 9.0) == 1.0
    t = Venue.default_targets(9.0, 12.0, 3.6)
    assert set(t) == {"dj_booth", "dancefloor_centre", "back_wall", "ceiling_bounce"}
    assert t["dancefloor_centre"].x == 4.5 and t["ceiling_bounce"].z == 3.6


def test_two_point_capture_solves_a_mirrored_pan_and_a_shorter_tilt_travel():
    # A head hung upside down at 5.5 m: its real pan runs the OTHER way and its
    # real tilt travel is 180 deg, not the profile's 270. Simulate the hardware
    # with those truths, "jog" onto two targets, and check the solve recovers
    # them and then aims a third target exactly.
    origin = Point3(2.6, 1.1, 5.5)
    true_k_pan, true_k_tilt = -540.0, 180.0
    true_off_pan, true_off_tilt = 30.0, -20.0

    def hardware_raw(target):
        az, el = bearing(origin, target)
        return 0.5 + (az - true_off_pan) / true_k_pan, 0.5 + (el - true_off_tilt) / true_k_tilt

    a, b, c = Point3(0.0, 7.6, 0.9), Point3(7.6, 7.6, 0.9), Point3(3.8, 15.0, 2.0)
    pa, ta = hardware_raw(a)
    pb, tb = hardware_raw(b)
    cal = calibrate_from_two_captures(origin, 0.0, a, pa, ta, b, pb, tb, PAN, TILT, "edge_l", "edge_r")
    assert cal.invert_pan is True and cal.invert_tilt is False
    assert cal.pan_range_deg == pytest.approx(540.0, abs=1e-6)
    assert cal.tilt_range_deg == pytest.approx(180.0, abs=1e-6)
    assert cal.target == "edge_l" and cal.target2 == "edge_r"
    # verify aim at a THIRD target lands where the hardware really needs to be
    pc, tc = hardware_raw(c)
    pan, tilt, ok = aim(origin, 0.0, c, cal, PAN, TILT)
    assert ok
    assert pan == pytest.approx(pc, abs=1e-6)
    assert tilt == pytest.approx(tc, abs=1e-6)
    # and the one-point capture on A alone would have sent the pan the WRONG way
    one = calibrate_from_capture(origin, 0.0, a, pa, ta, PAN, TILT)
    pan1, _, _ = aim(origin, 0.0, c, one, PAN, TILT)
    assert (pan1 - pa) * (pc - pa) < 0


def test_two_point_capture_keeps_profile_range_when_an_axis_barely_moved():
    origin = Point3(0, 0, 5)
    a, b = Point3(-5, 5, 0), Point3(5, 5, 0)   # same elevation -> tilt identical
    cal = calibrate_from_two_captures(origin, 0.0, a, 0.3, 0.6, b, 0.7, 0.6, PAN, TILT)
    assert cal.pan_range_deg == pytest.approx(90.0 / 0.4)
    assert cal.tilt_range_deg is None
    assert cal.invert_tilt is False
    pan, tilt, ok = aim(origin, 0.0, b, cal, PAN, TILT)
    assert pan == pytest.approx(0.7) and tilt == pytest.approx(0.6)
