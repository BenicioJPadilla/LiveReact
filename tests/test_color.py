"""Tests for the two-axis color model."""

from __future__ import annotations

from livereact.color import hsv_to_rgb
from livereact.core.show_state import ShowSnapshot
from livereact.engines.color import two_axis_color


def test_hsv_primaries():
    assert hsv_to_rgb(0.0, 1.0, 1.0) == (1.0, 0.0, 0.0)        # red
    r, g, b = hsv_to_rgb(1 / 3, 1.0, 1.0)                       # green
    assert g == 1.0 and r == 0.0 and b == 0.0


def _snap(**eq) -> ShowSnapshot:
    base = dict(fader_a=1.0, fader_b=0.0, energy=1.0,
                eq_low_a=0.5, eq_mid_a=0.5, eq_high_a=0.5)
    base.update(eq)
    return ShowSnapshot(**base)


def test_bass_dominant_reads_red():
    r, g, b = two_axis_color(_snap(eq_low_a=1.0, eq_mid_a=0.2, eq_high_a=0.2))
    assert r > g and r > b


def test_high_dominant_reads_cyan():
    r, g, b = two_axis_color(_snap(eq_high_a=1.0, eq_low_a=0.2, eq_mid_a=0.2))
    assert b > r and g > r  # cyan = green+blue, low red


def test_balanced_bands_desaturate_toward_white():
    r, g, b = two_axis_color(_snap(eq_low_a=1.0, eq_mid_a=1.0, eq_high_a=1.0))
    assert min(r, g, b) > 0.8  # near white


def test_zero_energy_is_black():
    assert two_axis_color(_snap(energy=0.0, eq_low_a=1.0)) == (0.0, 0.0, 0.0)


def test_brightness_tracks_energy():
    bright = max(two_axis_color(_snap(energy=1.0, eq_low_a=1.0)))
    dim = max(two_axis_color(_snap(energy=0.3, eq_low_a=1.0)))
    assert bright > dim
