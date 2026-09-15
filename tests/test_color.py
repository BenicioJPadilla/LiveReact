"""Tests for the audio-band helpers (engines/color.py)."""

from __future__ import annotations

from livereact.core.show_state import ShowSnapshot
from livereact.engines.color import band_levels, laser_color_for_bands
from livereact.fixtures.profiles import Laser


def _snap(**eq) -> ShowSnapshot:
    base = dict(fader_a=1.0, fader_b=0.0, energy=1.0,
                eq_low_a=0.5, eq_mid_a=0.5, eq_high_a=0.5)
    base.update(eq)
    return ShowSnapshot(**base)


def test_band_levels_prefers_fresh_real_audio_over_midi_eq():
    """docs/14: real audio band analysis wins over the MIDI-EQ proxy when fresh."""
    snap = ShowSnapshot(
        eq_low_a=0.9, eq_mid_a=0.1, eq_high_a=0.1,  # MIDI says "bass"...
        audio_band_low=0.1, audio_band_mid=0.1, audio_band_high=0.8,  # ...audio says "high"
        audio_fresh=True,
    )
    assert band_levels(snap) == (0.1, 0.1, 0.8)


def test_band_levels_falls_back_to_midi_eq_when_audio_stale():
    snap = ShowSnapshot(
        eq_low_a=0.9, eq_mid_a=0.1, eq_high_a=0.1,
        audio_band_low=0.1, audio_band_mid=0.1, audio_band_high=0.8,
        audio_fresh=False,
    )
    assert band_levels(snap) == (0.9, 0.1, 0.1)


# --- laser_color_for_bands (docs/14 §3, 2026-09-06) --------------------------
# "Frequency maps to color," snapped to the laser's small set of discrete
# CH12 macros instead of a continuous RGB blend.


def test_laser_reads_red_when_bass_dominant():
    color = laser_color_for_bands(_snap(eq_low_a=1.0, eq_mid_a=0.2, eq_high_a=0.2))
    assert color == Laser.COLOR_RED


def test_laser_reads_cyan_when_high_dominant():
    color = laser_color_for_bands(_snap(eq_high_a=1.0, eq_low_a=0.2, eq_mid_a=0.2))
    assert color == Laser.COLOR_CYAN


def test_laser_reads_purple_when_mid_dominant():
    color = laser_color_for_bands(_snap(eq_mid_a=1.0, eq_low_a=0.2, eq_high_a=0.2))
    assert color == Laser.COLOR_PURPLE


def test_laser_reads_white_when_bands_are_balanced():
    color = laser_color_for_bands(_snap(eq_low_a=1.0, eq_mid_a=1.0, eq_high_a=1.0))
    assert color == Laser.COLOR_WHITE
