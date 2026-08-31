"""Tests for the XDJ-XZ MIDI CC map (resolve, learn, persistence) and port match."""

from __future__ import annotations

from livereact.inputs.midi import find_midi_port
from livereact.inputs.midi_map import CcMap


def test_default_map_resolves_known_controls():
    m = CcMap()
    assert m.resolve(4, 11) == "crossfader"
    assert m.resolve(4, 17) == "fader_a"
    assert m.resolve(4, 18) == "fader_b"
    assert m.resolve(4, 2) == "eq_high_a"
    assert m.resolve(4, 3) == "eq_mid_a"
    assert m.resolve(4, 4) == "eq_low_a"
    assert m.resolve(4, 7) == "eq_high_b"
    assert m.resolve(4, 8) == "eq_mid_b"
    assert m.resolve(4, 9) == "eq_low_b"
    assert m.resolve(5, 99) is None  # unmapped


def test_assign_rebinds_a_control_to_a_new_cc():
    m = CcMap()
    m.assign(0, 7, "crossfader")          # learn crossfader on a new CC
    assert m.resolve(0, 7) == "crossfader"
    assert m.resolve(4, 11) is None       # old binding removed (one CC per control)


def test_save_and_load_round_trip(tmp_path):
    path = str(tmp_path / "midi_map.json")
    m = CcMap()
    m.assign(2, 10, "fader_a")
    m.save(path)
    loaded = CcMap.load(path)
    assert loaded.resolve(2, 10) == "fader_a"
    assert loaded.resolve(4, 11) == "crossfader"


def test_find_midi_port_matches_substring_case_insensitive():
    names = ["Some Controller", "PIONEER XDJ-XZ MIDI 1", "Other"]
    assert find_midi_port(names, "xdj") == "PIONEER XDJ-XZ MIDI 1"


def test_find_midi_port_falls_back_to_first():
    assert find_midi_port(["A", "B"], "nomatch") == "A"
    assert find_midi_port([], "x") is None
