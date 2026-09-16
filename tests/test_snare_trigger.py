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
