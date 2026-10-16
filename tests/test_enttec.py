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


def test_open_bounds_writes_so_a_wedged_device_cannot_stall_the_writer(monkeypatch):
    import serial

    from livereact.output.enttec import WRITE_TIMEOUT_S, EnttecSerialBackend

    seen = {}

    class FakeSerial:
        def __init__(self, port, **kwargs):
            seen["port"], seen["kwargs"] = port, kwargs

    monkeypatch.setattr(serial, "Serial", FakeSerial)
    EnttecSerialBackend(port="/dev/cu.usbserial-TEST").open()
    assert seen["port"] == "/dev/cu.usbserial-TEST"
    assert seen["kwargs"]["write_timeout"] == WRITE_TIMEOUT_S


def test_reopen_sticks_to_the_port_that_worked(monkeypatch):
    """After a pull, a different FTDI device on the bus must not get the DMX
    stream: the backend waits for its own port to come back."""
    import serial
    from serial.tools import list_ports

    from livereact.output.enttec import EnttecSerialBackend

    opened = []

    class FakeSerial:
        def __init__(self, port, **kwargs):
            opened.append(port)

        def reset_output_buffer(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(serial, "Serial", FakeSerial)
    ports = [_Port("/dev/cu.usbserial-ENTTEC", FTDI_VID, 0x6001)]
    monkeypatch.setattr(list_ports, "comports", lambda: ports)
    backend = EnttecSerialBackend()
    backend.open()
    backend.close()
    ports[:] = [_Port("/dev/cu.usbserial-OTHER", FTDI_VID, 0x6015)]  # Enttec pulled, another FTDI in
    backend.open()
    assert opened == ["/dev/cu.usbserial-ENTTEC", "/dev/cu.usbserial-ENTTEC"]
