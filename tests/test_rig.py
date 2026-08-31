"""Tests for the rig loader: the packaged default rig, role/side lookups, the
channel-kind map, boot universe, and overlap/overflow validation."""

from __future__ import annotations

import pytest

from livereact.fixtures.profiles import ChannelKind
from livereact.fixtures.rig import RigError, _rig_from_dict, load_rig


def test_default_rig_loads_with_eight_fixtures_and_74_channels():
    rig = load_rig()
    assert len(rig.fixtures) == 8
    assert rig.channel_count() == 74


def test_role_and_side_lookups():
    rig = load_rig()
    assert len(rig.by_role("spot")) == 2
    assert len(rig.by_role("laser")) == 2
    assert len(rig.by_role("wash")) == 4  # 2 pars + 2 bars
    assert len(rig.by_side("left")) == 4
    assert len(rig.by_role_side("wash", "right")) == 2
    assert rig.fixture("mh_l").label == "MH Left"


def test_channel_kind_map_matches_addresses():
    rig = load_rig()
    # MH Left at address 1: ch6 (index 5) is the dimmer.
    assert rig.kind_at(5) == ChannelKind.DIMMER
    # Laser Left at address 31: all channels are LASER-kind.
    assert rig.kind_at(30) == ChannelKind.LASER
    # Par Left at address 55 (index 54): ch1 is the dimmer, ch2 is COLOR (R).
    assert rig.kind_at(54) == ChannelKind.DIMMER
    assert rig.kind_at(55) == ChannelKind.COLOR


def test_boot_universe_has_moving_heads_centered():
    rig = load_rig()
    boot = rig.boot_universe()
    assert boot[0] == 128   # MH Left pan center
    assert boot[2] == 80    # MH Left tilt down
    assert boot[5] == 0     # MH Left dimmer off
    assert boot[30] == 0    # Laser Left CH1 off


def test_overlapping_addresses_raise():
    bad = {
        "name": "bad",
        "slots": [
            {"slot_id": "a", "fixture_type": "rgb_par", "dmx_address": 1, "role": "wash", "side": "left"},
            {"slot_id": "b", "fixture_type": "rgb_par", "dmx_address": 3, "role": "wash", "side": "right"},
        ],
    }
    with pytest.raises(RigError):
        _rig_from_dict(bad)


def test_overflow_past_512_raises():
    bad = {
        "name": "bad",
        "slots": [
            {"slot_id": "a", "fixture_type": "shehds_180w_mh", "dmx_address": 500, "role": "spot", "side": "left"},
        ],
    }
    with pytest.raises(RigError):
        _rig_from_dict(bad)


def test_unknown_fixture_type_raises():
    bad = {"name": "bad", "slots": [{"slot_id": "a", "fixture_type": "nope", "dmx_address": 1}]}
    with pytest.raises(RigError):
        _rig_from_dict(bad)
