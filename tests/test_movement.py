"""scenes/movement.py -- the post-drop moving-head shapes, anchored on the crowd (2026-10-05)."""
from __future__ import annotations

import pytest

from livereact.core.show_state import ShowSnapshot
from livereact.fixtures.geometry import HeadCalibration
from livereact.fixtures.rig import load_rig
from livereact.merge.merge import Contribution
from livereact.scenes import movement as mv

A = mv.FALLBACK_ANCHORS


def _snap(bar: int = 0, beat_in_bar: int = 1, beat_phase: float = 0.0, **kw) -> ShowSnapshot:
    base = dict(bpm=130.0, bar=bar, beat_in_bar=beat_in_bar, beat_phase=beat_phase,
                energy=0.9, energy_norm=0.9, bucket="drop")
    base.update(kw)
    return ShowSnapshot(**{k: v for k, v in base.items() if k in ShowSnapshot.__dataclass_fields__})


def _ticks(bars: int = 8, per_beat: int = 8):
    for bar in range(bars):
        for beat in range(1, 5):
            for i in range(per_beat):
                yield _snap(bar=bar, beat_in_bar=beat, beat_phase=i / per_beat)


ALL = [mv.fan, mv.beat_chase, mv.cross, mv.kick_lift, mv.crowd_sweep]


@pytest.mark.parametrize("fn", ALL)
@pytest.mark.parametrize("speed", [1.0, mv.PEAK_SPEED])
def test_every_shape_stays_inside_the_pan_tilt_range(fn, speed):
    for snap in _ticks():
        for side in ("left", "right"):
            pan, tilt = fn(snap, side, A, speed)
            assert 0.0 <= pan <= 1.0 and 0.0 <= tilt <= 1.0


@pytest.mark.parametrize("fn", ALL)
def test_every_shape_keeps_the_beam_off_the_stand_at_least_80_percent_of_the_time(fn):
    """Josh, run 185803: 'after the drop it spends too much time pointing
    down and not at the crowd'. The time-budget rule: on the crowd side of
    the crowd/stand midpoint for >= 80 % of ticks (a lift AWAY from the
    stand counts as crowd side)."""
    mid = (A.crowd_tilt + A.stand_tilt) / 2
    for side in ("left", "right"):
        tilts = [fn(s, side, A)[1] for s in _ticks()]
        on_stand = sum(1 for t in tilts if (t - mid) * A.up < 0)
        assert on_stand / len(tilts) <= mv.STAND_BUDGET, (fn.__name__, side, on_stand / len(tilts))


@pytest.mark.parametrize("fn", [mv.fan, mv.cross, mv.crowd_sweep, mv.kick_lift])
def test_continuous_shapes_mirror_left_and_right_about_the_crowd(fn):
    for snap in _ticks(2):
        pl, _ = fn(snap, "left", A)
        pr, _ = fn(snap, "right", A)
        assert pl - A.crowd_pan == pytest.approx(-(pr - A.crowd_pan), abs=1e-9)


@pytest.mark.parametrize("fn", [mv.fan, mv.cross, mv.crowd_sweep])
def test_continuous_shapes_actually_move_within_a_bar(fn):
    pans = {round(fn(s, "left", A)[0], 3) for s in _ticks(1)}
    assert len(pans) > 8  # not a parked head


def test_fan_returns_to_the_same_position_every_two_bars():
    assert mv.fan(_snap(bar=0), "left", A) == pytest.approx(mv.fan(_snap(bar=2), "left", A))


def test_fan_tilt_runs_a_half_cycle_behind_pan():
    s = _snap(bar=0, beat_in_bar=3, beat_phase=0.0)  # quarter of a 2-bar period
    pan, tilt = mv.fan(s, "left", A)
    assert pan == pytest.approx(A.crowd_pan + mv.FAN_PAN_AMP)
    assert tilt == pytest.approx(A.crowd_tilt - mv.FAN_TILT_AMP)


def test_beat_chase_holds_within_a_beat_and_moves_between_beats():
    within = {mv.beat_chase(_snap(beat_in_bar=1, beat_phase=p), "left", A) for p in (0.0, 0.3, 0.6, 0.9)}
    assert len(within) == 1
    seq = [mv.beat_chase(_snap(beat_in_bar=b), "left", A) for b in (1, 2, 3, 4)]
    assert len(set(seq)) >= 2


def test_beat_chase_alternates_which_head_moves_on_each_beat():
    prev = {side: mv.beat_chase(_snap(bar=0, beat_in_bar=1), side, A) for side in ("left", "right")}
    moved_per_beat = []
    for bar, beat in [(0, 2), (0, 3), (0, 4), (1, 1), (1, 2), (1, 3)]:
        cur = {side: mv.beat_chase(_snap(bar=bar, beat_in_bar=beat), side, A) for side in ("left", "right")}
        moved = tuple(side for side in ("left", "right") if cur[side] != prev[side])
        moved_per_beat.append(moved)
        prev = cur
    assert all(len(m) == 1 for m in moved_per_beat), moved_per_beat
    assert moved_per_beat[0] != moved_per_beat[1]


def test_beat_chase_visits_the_stand_one_beat_in_eight():
    stand = (A.stand_pan, A.stand_tilt)
    for side in ("left", "right"):
        # one sample per beat over 8 bars = 32 beats, this head moves on 16 of them
        beats = [mv.beat_chase(_snap(bar=b, beat_in_bar=k), side, A) for b in range(8) for k in (1, 2, 3, 4)]
        assert beats.count(stand) == 4, (side, beats.count(stand))   # 32 beats / 8
        assert len(set(beats)) == 5


def test_beat_chase_longest_jump_lands_within_one_beat_under_the_slew_limit():
    """crowd-out -> stand at 130 BPM (0.46 s/beat): pan 260 deg/s over 540, tilt 200 over 270."""
    beat_s = 60.0 / 130.0
    pan_jump = abs((A.crowd_pan + mv.CHASE_PAN_STEP) - A.stand_pan)
    tilt_jump = abs(A.crowd_tilt - A.stand_tilt)
    assert pan_jump * 540.0 / 260.0 <= beat_s
    assert tilt_jump * 270.0 / 200.0 <= beat_s


def test_kick_lift_kicks_away_from_the_stand_at_the_hit_and_falls_back_to_the_crowd():
    tilts = [mv.kick_lift(_snap(beat_phase=p), "left", A)[1] for p in (0.0, 0.25, 0.5, 0.75, 0.99)]
    away = [(t - A.crowd_tilt) * A.up for t in tilts]       # positive = away from the stand
    assert away == sorted(away, reverse=True) and away[0] == pytest.approx(mv.LIFT_TILT_KICK)
    assert away[-1] == pytest.approx(0.0, abs=1e-3)
    assert mv.LIFT_TILT_KICK * 270.0 / 200.0 <= 60.0 / 130.0 * 0.5  # up in under half a beat


def test_crowd_sweep_is_a_triangle_not_a_sine():
    pans = [mv.crowd_sweep(_snap(bar=0, beat_in_bar=1, beat_phase=p), "left", A)[0] for p in (0.0, 0.25, 0.5, 0.75)]
    deltas = [b - a for a, b in zip(pans, pans[1:])]
    assert all(d == pytest.approx(deltas[0]) for d in deltas)


@pytest.mark.parametrize("fn", [mv.beat_chase, mv.kick_lift])
def test_beat_locked_shapes_ignore_the_peak_speed_multiplier(fn):
    for snap in _ticks(2):
        assert fn(snap, "left", A, 1.0) == fn(snap, "left", A, mv.PEAK_SPEED)


def test_drop_movement_cycles_one_shape_per_eight_bar_block_from_the_drop():
    names = [mv.drop_movement_name(_snap(bar=20 + 8 * i, drop_start_bar=20)) for i in range(6)]
    assert names == ["fan", "beat_chase", "cross", "kick_lift", "crowd_sweep", "fan"]
    assert {mv.drop_movement_name(_snap(bar=20 + b, drop_start_bar=20)) for b in range(8)} == {"fan"}


def test_drop_movement_before_any_drop_counts_blocks_from_bar_zero():
    assert mv.drop_movement_name(_snap(bar=3, drop_start_bar=None)) == "fan"
    assert mv.drop_movement_name(_snap(bar=9, drop_start_bar=None)) == "beat_chase"


def test_peak_runs_the_continuous_shapes_twice_as_fast():
    s0 = _snap(bar=0, drop_start_bar=0)
    s1 = _snap(bar=0, beat_in_bar=3, drop_start_bar=0)  # half a bar: PEAK fan back at its zero crossing
    assert mv.drop_movement(s0, "left", A, peak=True) == pytest.approx(mv.drop_movement(s1, "left", A, peak=True))
    assert mv.drop_movement(s0, "left", A) != pytest.approx(mv.drop_movement(s1, "left", A))


# --- anchors -------------------------------------------------------------------
def test_uncalibrated_head_uses_the_fallback_anchors_and_a_raw_position():
    rig = load_rig("rigs/testing_setup.json")
    mh = rig.fixture("mh_r")
    assert mv.anchors_for(rig, mh) is mv.FALLBACK_ANCHORS
    c = Contribution()
    mv.apply_drop_movement(c, rig, _snap())
    assert c.touched[mh.offset] and not (c.absolute_movement & set(range(mh.offset, mh.offset + 4)))


def test_fallback_crowd_is_a_lower_tilt_than_the_stand():
    """What session-20261005-185803 showed on Josh's truss: the stand aims
    sit at tilt 0.70-0.81 and the one 'widened' moment was the lowest tilt."""
    assert A.crowd_tilt < A.stand_tilt and A.up == -1.0


def _calibrate(rig):
    for slot in ("mh_l", "mh_r"):
        fx = rig.fixture(slot)
        fx.calibration = HeadCalibration(target="dj_booth", pan01=0.5, tilt01=0.65)
    return rig


def test_calibrated_head_anchors_come_from_the_venue_targets_and_are_written_as_an_absolute_aim():
    rig = _calibrate(load_rig("rigs/testing_setup.json"))
    mh = rig.fixture("mh_r")
    a = mv.anchors_for(rig, mh)
    assert a.absolute
    assert (a.crowd_pan, a.crowd_tilt) != (a.stand_pan, a.stand_tilt)
    c = Contribution()
    mv.apply_drop_movement(c, rig, _snap())
    assert set(range(mh.offset, mh.offset + 4)) <= c.absolute_movement  # finalize skips the +-10% home remap


def test_calibrated_heads_fan_opens_outward_from_the_crowd_aim():
    """Each head fans about ITS OWN crowd aim, mirrored by side (MOVE-01/02)."""
    rig = _calibrate(load_rig("rigs/testing_setup.json"))
    l, r = rig.fixture("mh_l"), rig.fixture("mh_r")
    al, ar = mv.anchors_for(rig, l), mv.anchors_for(rig, r)
    s = _snap(bar=0, beat_in_bar=3)  # pan at its extreme
    pl = mv.fan(s, l.side, al)[0] - al.crowd_pan
    pr = mv.fan(s, r.side, ar)[0] - ar.crowd_pan
    assert pl == pytest.approx(-pr) and pl != 0


# --- the looks -------------------------------------------------------------------
def test_drop_strobe_stab_heads_are_no_longer_parked():
    from livereact.scenes.library import DropStrobeStab
    rig = load_rig()
    mh = rig.fixture("mh_l")
    scene = DropStrobeStab()
    pans = {scene.render(rig, s, 1.0).values[mh.offset] for s in _ticks(1)}
    assert len(pans) > 4


def test_drop_strobe_stab_mirrors_the_two_heads():
    from livereact.scenes.library import DropStrobeStab
    rig = load_rig()
    l, r = rig.fixture("mh_l"), rig.fixture("mh_r")
    c = DropStrobeStab().render(rig, _snap(bar=0, beat_in_bar=2, beat_phase=0.5), 1.0)
    pan_l = (c.values[l.offset] << 8 | c.values[l.offset + 1]) / 65535
    pan_r = (c.values[r.offset] << 8 | c.values[r.offset + 1]) / 65535
    assert pan_l - 0.5 == pytest.approx(-(pan_r - 0.5), abs=2e-3)
