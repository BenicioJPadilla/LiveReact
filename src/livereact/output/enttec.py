"""Enttec DMX USB Pro output backend.

⚠️ UNTESTED ON HARDWARE — written from the Enttec Widget API spec (docs/04 §5.2)
and verified by unit tests for the parts that don't need a device (frame framing,
port selection). The serial open/write path must be confirmed on the real Enttec.

The DmxWriter already provides the never-stops, self-healing reopen loop around
this backend (docs/05 §5.1), so this class only has to open a port, frame each
universe, and write it.
"""

from __future__ import annotations

import logging

from ..core.frame_buffer import UNIVERSE_SIZE
from .base import OutputBackend

log = logging.getLogger(__name__)

FTDI_VID = 0x0403                      # Enttec uses an FTDI chip
FTDI_PIDS = {0x6001, 0x6010, 0x6014, 0x6015}
LABEL_OUTPUT_ONLY = 0x06               # "Output Only Send DMX Packet"
WRITE_TIMEOUT_S = 0.5                  # a 518-byte frame takes ~1 ms; a write still
                                       # pending after this is a wedged or vanished
                                       # device, so raise and let the writer reopen
                                       # instead of blocking the 40 Hz loop forever


def build_enttec_frame(universe: bytes) -> bytes:
    """Frame a 512-byte universe for the Enttec (label 6). Returns 518 bytes.

    Wire format: 0x7E label len_LSB len_MSB [start_code=0x00 + 512 data] 0xE7
    (docs/04 §5.2).
    """
    if len(universe) != UNIVERSE_SIZE:
        raise ValueError(f"universe must be {UNIVERSE_SIZE} bytes, got {len(universe)}")
    payload = b"\x00" + universe       # DMX start code + channel data = 513 bytes
    n = len(payload)
    return bytes([0x7E, LABEL_OUTPUT_ONLY, n & 0xFF, (n >> 8) & 0xFF]) + payload + bytes([0xE7])


def select_enttec_port(ports) -> str | None:
    """Pick the Enttec serial device from ``serial.tools.list_ports`` entries.

    Matches by FTDI VID (not by name), and prefers the macOS ``cu.*`` node over
    ``tty.*`` (the tty node blocks on open — docs/04 §5.3). ``ports`` items need
    ``device``/``vid``/``pid`` attributes.
    """
    matches = [p for p in ports if getattr(p, "vid", None) == FTDI_VID]
    if not matches:
        return None
    for p in matches:  # prefer cu.* on macOS
        dev = getattr(p, "device", "") or ""
        if "cu." in dev:
            return dev
    return getattr(matches[0], "device", None)


class EnttecSerialBackend(OutputBackend):
    def __init__(self, port: str | None = None, baud: int = 57600) -> None:
        self._port_hint = port
        self._baud = baud
        self._serial = None
        self._port: str | None = None
        self._logged_port: str | None = None

    @property
    def name(self) -> str:
        return f"enttec-serial({self._port or self._port_hint or 'auto'})"

    def open(self) -> None:
        import serial  # lazy: only needed in hardware mode
        from serial.tools import list_ports

        # Once a port has worked, reopens go back to THAT port only (2026-10-16):
        # the writer now retries all night, and some other FTDI cable plugged in
        # mid-set must never be handed a DMX stream. macOS (cu.usbserial-<serial
        # number>) and Windows' FTDI driver keep the name across a replug.
        self._port = self._port_hint or self._port or select_enttec_port(list_ports.comports())
        if not self._port:
            raise RuntimeError("No Enttec DMX USB Pro found (no FTDI device on the bus)")
        # timeout=0 -> non-blocking reads (none are made); the chip clocks DMX
        # itself. Writes are bounded by WRITE_TIMEOUT_S, see above.
        self._serial = serial.Serial(self._port, baudrate=self._baud, timeout=0,
                                     write_timeout=WRITE_TIMEOUT_S)
        if self._port != self._logged_port:  # the writer reports reconnects itself
            log.info("Enttec opened on %s", self._port)
            self._logged_port = self._port

    def send(self, universe: bytes) -> None:
        if self._serial is None:
            raise RuntimeError("Enttec port not open")
        self._serial.write(build_enttec_frame(universe))

    def close(self) -> None:
        if self._serial is not None:
            try:
                try:
                    # A write that timed out may have left half a packet queued;
                    # drop it rather than send it ahead of the next frame.
                    self._serial.reset_output_buffer()
                except Exception:  # noqa: BLE001 - a vanished device can't be flushed
                    pass
                self._serial.close()
            finally:
                self._serial = None
