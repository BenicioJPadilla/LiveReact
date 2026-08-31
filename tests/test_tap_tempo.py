"""Tests for tap-tempo BPM estimation."""

from __future__ import annotations

import pytest

from livereact.tap_tempo import MAX_BPM, TapTempo


def test_first_tap_returns_none():
    assert TapTempo().tap(0.0) is None


def test_steady_taps_estimate_bpm():
    tt = TapTempo()
    bpm = None
    for i in range(5):
        bpm = tt.tap(i * 0.5)  # 0.5 s spacing -> 120 BPM
    assert bpm == pytest.approx(120.0, abs=0.5)


def test_long_gap_resets_the_sequence():
    tt = TapTempo(timeout=2.0)
    tt.tap(0.0)
    tt.tap(0.5)
    assert tt.tap(10.0) is None  # gap > timeout -> sequence restarts, only 1 tap


def test_bpm_is_clamped():
    tt = TapTempo()
    tt.tap(0.0)
    fast = tt.tap(0.05)  # 1200 BPM raw -> clamped
    assert fast == MAX_BPM
