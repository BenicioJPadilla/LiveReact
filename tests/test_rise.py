"""Tests for core/rise.py's RiseDetector (2026-09-17). Shapes are the per-bar
numbers from recordings/session-20260917-154312 (run 10): flat plateau at
high 0.09 / onsets 3-4/s, then the last ~8 bars climbing to 0.18 / 8.6/s."""

from __future__ import annotations

from livereact.core.rise import (
    RISE_ARM_BARS, RISE_BASE_BARS, RISE_BASE_GAP_BARS, RISE_MAX_BARS, RISE_OFF_BARS, RiseDetector,
)

PLATEAU = (RISE_BASE_BARS + RISE_BASE_GAP_BARS) * 4


def _plateau(det, beats=PLATEAU, hi=0.09, onset=3.8):
    for _ in range(beats):
        det.on_beat(hi, onset)


def test_a_flat_plateau_is_not_a_rise():
    det = RiseDetector()
    _plateau(det, beats=PLATEAU * 2)
    assert not det.rising
    assert 0.8 < det.index < 1.25


def test_the_recorded_rise_starts_within_a_bar_and_reads_its_intensity():
    """Run 10 bars 194-200: high 0.12 -> 0.18, onsets 4.2 -> 8.6/s, over ~7 bars."""
    det = RiseDetector()
    _plateau(det)
    ramp = [(0.12, 4.2), (0.14, 5.3), (0.11, 4.0), (0.12, 4.6), (0.16, 7.9), (0.18, 8.6), (0.18, 7.9)]
    started_at = None
    for i, (hi, on) in enumerate(ramp):
        for _ in range(4):
            if det.on_beat(hi, on) and started_at is None:
                started_at = i
    assert det.rising
    assert started_at is not None and started_at <= 5  # within the climb, not after it
    assert det.index >= 1.8
    assert det.strobe01 > 0.15


def test_the_reference_freezes_when_the_rise_starts():
    det = RiseDetector()
    _plateau(det)
    for _ in range(RISE_BASE_GAP_BARS * 4 + 4):  # longer than the gap: an unfrozen reference would have caught up
        det.on_beat(0.20, 8.0)
    assert det.rising
    assert det.index > 1.8  # judged against the plateau, not against itself


def test_a_step_up_that_stops_climbing_is_a_plateau_not_a_rise():
    """2026-09-15 captures: a track's intro -> groove step read as a 45 s
    'rise' at 6-9x -- higher, but flat from the second bar on. A rise must
    keep climbing (RISE_CLIMB_RATIO over RISE_FLAT_BARS/2 bars) or it ends,
    and can't restart until the index has fallen back under RISE_OFF."""
    from livereact.core.rise import RISE_FLAT_BARS
    det = RiseDetector()
    _plateau(det)
    on = []
    for _ in range((RISE_FLAT_BARS + 6) * 4):  # the 4-bar climb window, then RISE_FLAT_BARS of flat
        on.append(det.on_beat(0.40, 8.0))  # a step: 4x, then flat
    assert on[4] and not on[-1]
    for _ in range(8):
        assert not det.on_beat(0.40, 8.0)  # still flat: no restart


def test_a_rise_ends_when_the_intensity_falls_back_or_the_drop_lands():
    det = RiseDetector()
    _plateau(det)
    for _ in range(8):
        det.on_beat(0.20, 8.0)
    assert det.rising
    for _ in range(RISE_OFF_BARS * 4 + 12):  # ~2 bars for the smoothed index to fall, then RISE_OFF_BARS
        det.on_beat(0.09, 3.8)
    assert not det.rising
    _plateau(det)
    for _ in range(8):
        det.on_beat(0.20, 8.0)
    assert det.rising
    det.drop_landed()
    assert not det.rising and det.strobe01 == 0.0


def test_a_rise_longer_than_max_is_a_texture():
    det = RiseDetector()
    _plateau(det)
    for _ in range(RISE_MAX_BARS * 4 + 4):
        det.on_beat(0.20, 8.0)
    assert not det.rising


def test_level_alone_counts_when_there_are_no_hats():
    """Old captures and hat-less music: onset baseline under ONSET_BASE_MIN
    -> the index is the high-band level ratio alone."""
    det = RiseDetector()
    _plateau(det, hi=0.10, onset=0.0)
    for _ in range(8):
        det.on_beat(0.25, 0.0)
    assert det.rising
    assert det.index > 1.6


def test_arm_ready_fires_once_after_a_strong_rise_held_long_enough():
    det = RiseDetector()
    _plateau(det)
    fired = []
    for _ in range(RISE_ARM_BARS * 4 + 8):
        det.on_beat(0.30, 10.0)
        fired.append(det.arm_ready)
    assert fired.count(True) == 1
    assert fired.index(True) < RISE_ARM_BARS * 4 + 3
