"""Tests for the Reactive Layer engine."""

from __future__ import annotations

from livereact.core.show_state import ShowSnapshot
from livereact.engines.reactive import ReactiveLayerEngine
from livereact.fixtures.rig import load_rig


def _snap(**kw) -> ShowSnapshot:
    base = dict(bpm=120.0, energy=0.8, fader_a=1.0, eq_low_a=1.0, eq_mid_a=0.2, eq_high_a=0.2)
    base.update(kw)
    return ShowSnapshot(**base)


def test_pulse_peaks_on_the_beat_and_decays_across_it():
    rig = load_rig()
    eng = ReactiveLayerEngine()
    bar = rig.fixture("bar_l")

    on_beat = eng.tick(_snap(beat_phase=0.0), rig).values[bar.offset]    # dimmer ch1
    mid_beat = eng.tick(_snap(beat_phase=0.5), rig).values[bar.offset]
    late_beat = eng.tick(_snap(beat_phase=0.9), rig).values[bar.offset]

    assert on_beat > mid_beat > late_beat  # single peak, monotonic decay


def test_color_follows_band_dominance():
    rig = load_rig()
    eng = ReactiveLayerEngine()
    par = rig.fixture("par_l")  # ch1=dimmer, R,G,B at offset+1..offset+3

    red = eng.tick(_snap(beat_phase=0.0, eq_low_a=1.0, eq_mid_a=0.2, eq_high_a=0.2), rig)
    assert red.values[par.offset + 1] > red.values[par.offset + 3]  # R > B

    cyan = eng.tick(_snap(beat_phase=0.0, eq_high_a=1.0, eq_low_a=0.2, eq_mid_a=0.2), rig)
    assert cyan.values[par.offset + 3] > cyan.values[par.offset + 1]  # B > R


def test_moving_heads_mirror_left_and_right():
    rig = load_rig()
    eng = ReactiveLayerEngine()
    c = eng.tick(_snap(bar=2, beat_in_bar=3, beat_phase=0.25), rig)
    mh_l, mh_r = rig.fixture("mh_l"), rig.fixture("mh_r")
    # Pan is mirrored around center (128), so the two heads sit on opposite sides.
    assert c.values[mh_l.offset] != c.values[mh_r.offset]


def test_low_energy_keeps_strobe_off():
    rig = load_rig()
    eng = ReactiveLayerEngine()
    bar = rig.fixture("bar_l")
    c = eng.tick(_snap(energy=0.5, beat_phase=0.0), rig)
    assert c.values[bar.offset + 1] == 0  # strobe ch2 off below threshold


def test_high_energy_engages_capped_strobe():
    rig = load_rig()
    eng = ReactiveLayerEngine()
    bar = rig.fixture("bar_l")
    c = eng.tick(_snap(energy=1.0, beat_phase=0.0), rig)
    strobe = c.values[bar.offset + 1]
    assert 0 < strobe <= int(0.30 * 255) + 1  # engaged but conservatively capped
