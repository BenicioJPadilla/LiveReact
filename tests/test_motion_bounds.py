"""Raw motion box for moving heads (2026-10-10, Junior Crib)."""
import tempfile

from livereact.core.frame_buffer import UNIVERSE_SIZE
from livereact.fixtures.profiles import MotionBounds, MovingHead
from livereact.fixtures.rig import load_rig, save_rig
from livereact.merge.merge import ManualParams, finalize


def _uni():
    return bytearray(UNIVERSE_SIZE)


def _write(mh, uni, pan01, tilt01):
    for i, v in ((mh.offset, pan01), (mh.offset + 2, tilt01)):
        v16 = round(v * 65535); uni[i] = v16 >> 8; uni[i + 1] = v16 & 0xFF


def _pan_tilt(mh, uni):
    return ((uni[mh.offset] << 8 | uni[mh.offset + 1]) / 65535,
            (uni[mh.offset + 2] << 8 | uni[mh.offset + 3]) / 65535)


def test_envelope_grows_from_captured_points():
    b = MotionBounds.point(0.3, 0.6).include(0.7, 0.6).include(0.5, 0.2).include(0.5, 0.65)
    assert b == MotionBounds(0.3, 0.7, 0.2, 0.65)


def test_relative_scene_motion_is_remapped_to_fill_the_box():
    mh = MovingHead(1, "MH", "spot", "left")
    mh.bounds = MotionBounds(0.3, 0.7, 0.2, 0.6)
    mh.home_pan, mh.home_tilt = 0.9, 0.9     # must be ignored once a box exists
    for raw, want in ((0.0, (0.3, 0.2)), (1.0, (0.7, 0.6)), (0.5, (0.5, 0.4))):
        uni = _uni()
        _write(mh, uni, raw, raw)
        mh.apply_home_position(uni)
        pan, tilt = _pan_tilt(mh, uni)
        assert abs(pan - want[0]) < 1e-3 and abs(tilt - want[1]) < 1e-3


def test_absolute_aim_is_clamped_into_the_box_not_remapped():
    mh = MovingHead(1, "MH", "spot", "left")
    mh.bounds = MotionBounds(0.3, 0.7, 0.2, 0.6)
    uni = _uni(); _write(mh, uni, 0.95, 0.05); mh.apply_home_position(uni, absolute=True)
    assert _pan_tilt(mh, uni) == (__import__("pytest").approx(0.7, abs=1e-3), __import__("pytest").approx(0.2, abs=1e-3))
    uni = _uni(); _write(mh, uni, 0.5, 0.5); mh.apply_home_position(uni, absolute=True)
    pan, tilt = _pan_tilt(mh, uni)
    assert abs(pan - 0.5) < 1e-3 and abs(tilt - 0.5) < 1e-3   # inside: untouched


def test_finalize_skips_the_box_for_a_pinned_head_so_edges_can_be_captured():
    rig = load_rig("rigs/junior_crib.json")
    mh = rig.fixture("mh_l")
    mh.bounds = MotionBounds(0.3, 0.7, 0.2, 0.6)
    merged = _uni(); _write(mh, merged, 1.0, 1.0)
    boxed = finalize(bytearray(merged), rig, ManualParams(), dt=10.0)
    assert boxed[mh.offset] == round(0.7 * 65535) >> 8
    pinned = finalize(bytearray(merged), rig, ManualParams(), dt=10.0,
                      pinned_movement=frozenset({mh.offset}))
    assert pinned[mh.offset] == 255 and pinned[mh.offset + 2] == 255


def test_bounds_round_trip_through_the_rig_file():
    rig = load_rig("rigs/junior_crib.json")
    rig.fixture("mh_r").bounds = MotionBounds(0.3123, 0.7, 0.2, 0.6)
    rig.fixture("mh_l").bounds = None
    p = tempfile.mktemp(suffix=".json"); save_rig(rig, p)
    back = load_rig(p)
    assert back.fixture("mh_r").bounds == MotionBounds(0.3123, 0.7, 0.2, 0.6)
    assert back.fixture("mh_l").bounds is None
