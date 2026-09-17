"""Tests for core/snare_trigger.py's RollRiseDetector (rebuilt 2026-09-15
night from a real capture -- see the module docstring)."""

from __future__ import annotations

from livereact.clock import FakeClock
from livereact.core.show_state import ShowSnapshot
from livereact.core.snare_trigger import MAX_HOLD_S, RollRiseDetector


def _snap(high: float, bucket: str = "build") -> ShowSnapshot:
    return ShowSnapshot(audio_fresh=True, bucket=bucket, audio_band_high_abs=high)


def _run(det: RollRiseDetector, clock: FakeClock, high: float, seconds: float, bucket: str = "build", dt: float = 0.02):
    out = False
    for _ in range(int(seconds / dt)):
        out = det.update(_snap(high, bucket))
        clock.advance(dt)
    return out


def test_a_steady_build_never_reads_as_a_roll():
    clock = FakeClock()
    det = RollRiseDetector(clock)
    assert _run(det, clock, 0.12, 6.0) is False


def test_the_recorded_roll_shape_arms_and_holds_into_the_drop():
    """The real 2026-09-15 numbers: high band 0.12 for the build, then 0.3-0.5
    (with dips to 0.16) for the last ~3.6 s, then the drop."""
    clock = FakeClock()
    det = RollRiseDetector(clock)
    _run(det, clock, 0.12, 6.0)
    assert _run(det, clock, 0.40, 0.6) is True     # arms once the rise has held ARM_S
    assert _run(det, clock, 0.16, 0.2) is True     # a dip inside the roll doesn't drop it (0.16 > 1.3 x 0.12)
    assert _run(det, clock, 0.45, 2.0) is True     # still rolling
    assert det.update(_snap(0.45, bucket="drop")) is False  # the hit lands: BUILD-only


def test_cold_start_step_does_not_arm():
    clock = FakeClock()
    det = RollRiseDetector(clock)
    assert _run(det, clock, 0.40, 0.5) is False  # inside WARMUP_S


def test_releases_when_the_level_falls_back_and_must_rise_again():
    clock = FakeClock()
    det = RollRiseDetector(clock)
    _run(det, clock, 0.12, 6.0)
    assert _run(det, clock, 0.40, 0.6) is True
    assert _run(det, clock, 0.10, 0.5) is False   # back under 1.3 x 0.12
    assert _run(det, clock, 0.12, 0.5) is False   # a mere return to the old level isn't a new roll


def test_gives_up_after_max_hold():
    clock = FakeClock()
    det = RollRiseDetector(clock)
    _run(det, clock, 0.12, 6.0)
    assert _run(det, clock, 0.40, 1.0) is True
    assert _run(det, clock, 0.40, MAX_HOLD_S) is False  # a texture, not an accent


def test_never_active_outside_a_build_even_on_the_same_rise():
    clock = FakeClock()
    det = RollRiseDetector(clock)
    _run(det, clock, 0.12, 6.0, bucket="break")
    assert _run(det, clock, 0.40, 1.0, bucket="break") is False
    assert _run(det, clock, 0.40, 1.0, bucket="drop") is False


def test_signal_loss_resets():
    clock = FakeClock()
    det = RollRiseDetector(clock)
    _run(det, clock, 0.12, 6.0)
    assert _run(det, clock, 0.40, 0.6) is True
    assert det.update(ShowSnapshot(audio_fresh=False, bucket="build", audio_band_high_abs=0.4)) is False
    assert det.ratio == 0.0


# --- density path (2026-09-17, run 5's roll that the level path can't see) --

def _dsnap(high: float, rate: float, bucket: str = "build") -> ShowSnapshot:
    return ShowSnapshot(audio_fresh=True, bucket=bucket, audio_band_high_abs=high, audio_high_onset_rate=rate)


def _drun(det: RollRiseDetector, clock: FakeClock, high: float, rate: float, seconds: float,
          bucket: str = "build", dt: float = 0.02):
    out = False
    for _ in range(int(seconds / dt)):
        out = det.update(_dsnap(high, rate, bucket))
        clock.advance(dt)
    return out


def test_a_16th_roll_by_onset_density_arms_over_8th_hats_at_a_flat_level():
    """Run 5's shape: the high band's LEVEL barely moves (spiky hats at the
    same level as the roll), but the onset rate goes from 8th-note hats
    (~4.3/s) to 16ths (~8.5/s). Density alone must arm it."""
    clock = FakeClock()
    det = RollRiseDetector(clock)
    _drun(det, clock, 0.4, 4.3, 6.0)
    assert det.path == ""
    assert _drun(det, clock, 0.4, 8.5, 0.6) is True
    assert det.path == "density"
    assert det.rate_base < 5.0  # judged against the build's own hat rate, frozen


def test_density_roll_needs_the_absolute_minimum_rate():
    """1/s -> 2.5/s is 2.5x the baseline but nowhere near a roll: a sparse
    hat picking up must not fire the accent."""
    clock = FakeClock()
    det = RollRiseDetector(clock)
    _drun(det, clock, 0.4, 1.0, 6.0)
    assert _drun(det, clock, 0.4, 2.5, 2.0) is False


def test_density_roll_needs_a_rise_over_the_builds_own_hats():
    """A build that runs 16th-note hats throughout (8.5/s, above the floor)
    is a texture, not a roll -- the rate must clear ROLL_DENSITY_RATIO x
    that baseline. At the measurement's ~12/s cap a 32nd roll still does."""
    clock = FakeClock()
    det = RollRiseDetector(clock)
    assert _drun(det, clock, 0.4, 8.5, 6.0) is False
    assert _drun(det, clock, 0.4, 12.0, 0.6) is True


def test_density_roll_releases_when_the_rate_falls_back():
    clock = FakeClock()
    det = RollRiseDetector(clock)
    _drun(det, clock, 0.4, 4.3, 6.0)
    assert _drun(det, clock, 0.4, 8.5, 0.6) is True
    assert _drun(det, clock, 0.4, 4.3, 0.3) is False   # back to hats
    assert _drun(det, clock, 0.4, 4.3, 2.0) is False   # and stays off


def test_density_path_respects_the_build_settle_and_bucket_gate():
    clock = FakeClock()
    det = RollRiseDetector(clock)
    _drun(det, clock, 0.4, 4.3, 4.0, bucket="break")
    assert _drun(det, clock, 0.4, 9.0, 1.0) is False           # inside BUILD_SETTLE_S (1.5 s)
    assert _drun(det, clock, 0.4, 9.0, 2.0, bucket="drop") is False


def test_a_level_roll_still_arms_with_the_rate_at_zero():
    """The OR: the 2026-09-15 level-only shape keeps working when the
    onset column is absent (older captures, demo)."""
    clock = FakeClock()
    det = RollRiseDetector(clock)
    _drun(det, clock, 0.12, 0.0, 6.0)
    assert _drun(det, clock, 0.40, 0.0, 0.6) is True
    assert det.path == "level"


def test_either_path_can_hold_a_roll_the_other_armed():
    """Armed by density, then the rate reading drops to hats while the
    LEVEL now clears its hold band: still a roll (path 'level')."""
    clock = FakeClock()
    det = RollRiseDetector(clock)
    _drun(det, clock, 0.12, 4.3, 6.0)
    assert _drun(det, clock, 0.12, 8.5, 0.6) is True
    assert det.path == "density"
    assert _drun(det, clock, 0.40, 4.3, 0.3) is True
    assert det.path == "level"
