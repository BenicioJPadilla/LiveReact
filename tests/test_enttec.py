"""Tests for the Enttec backend's pure pieces (frame framing + port selection).
The serial I/O path is hardware-gated and not exercised here."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from livereact.core.frame_buffer import UNIVERSE_SIZE
from livereact.output.enttec import FTDI_VID, build_enttec_frame, select_enttec_port


def test_frame_has_correct_length_and_framing():
    universe = bytes(range(256)) + bytes(UNIVERSE_SIZE - 256)
    frame = build_enttec_frame(universe)
    assert len(frame) == 518               # 4 header + 1 start code + 512 + 1 end
    assert frame[0] == 0x7E and frame[-1] == 0xE7
    assert frame[1] == 0x06                # label 6 (output only)
    assert frame[2] == 0x01 and frame[3] == 0x02   # length 513, LSB/MSB
    assert frame[4] == 0x00                # DMX start code
    assert frame[5:5 + 256] == universe[:256]


def test_frame_rejects_wrong_size():
    with pytest.raises(ValueError):
        build_enttec_frame(bytes(10))


@dataclass
class _Port:
    device: str
    vid: int | None
    pid: int | None


def test_select_enttec_matches_ftdi_vid():
    ports = [_Port("COM1", 0x1234, 0x0001), _Port("COM4", FTDI_VID, 0x6001)]
    assert select_enttec_port(ports) == "COM4"


def test_select_enttec_prefers_cu_node_on_macos():
    ports = [
        _Port("/dev/tty.usbserial-A1", FTDI_VID, 0x6001),
        _Port("/dev/cu.usbserial-A1", FTDI_VID, 0x6001),
    ]
    assert select_enttec_port(ports) == "/dev/cu.usbserial-A1"


def test_select_enttec_returns_none_when_absent():
    assert select_enttec_port([_Port("COM1", 0x1234, 0x0001)]) is None
