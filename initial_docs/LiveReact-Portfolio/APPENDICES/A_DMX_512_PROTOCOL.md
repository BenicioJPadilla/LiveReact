# A — DMX-512 Protocol Reference

A short technical reference for the DMX-512 wire protocol and the Enttec DMX USB Pro Widget API. The Domain Primer (`01_DOMAIN_PRIMER.md`) covers the conceptual model; this is the wire detail.

---

## DMX-512 wire format

DMX-512 is defined by ANSI E1.11 (originally USITT DMX512/1990, refined in 2008). Key parameters:

| Property | Value |
|---|---|
| Physical layer | EIA-485 differential pair (RS-485) |
| Connector | 5-pin XLR (formally) or 3-pin XLR (common in practice) |
| Bit rate | 250 kbps |
| Frame | 11 bits per byte (1 start, 8 data, 2 stop) |
| Universe size | 512 channels (bytes) |
| Refresh rate | ~44 Hz max for a full 512-byte universe |
| Termination | 120Ω across the differential pair at the last device |

### Packet structure

A DMX packet consists of:

1. **BREAK** — Mark After Break (MAB): pull the line low for ≥88 μs.
2. **MAB** — Mark After Break: pull high for ≥8 μs.
3. **Start Code (SC)** — One byte. `0x00` = "standard dimmer data" (the case we care about). Other codes exist (RDM, ASCII text, system info) but LiveReact only uses 0x00.
4. **Data slots** — Up to 512 bytes, one per channel. Channel 1 is the byte immediately after the start code.
5. **Mark Between Slots (MBS)** — Optional gap between bytes; for our purposes irrelevant since the Enttec handles it.

A complete frame at the receiving end of a fixture looks like:

```
[BREAK][MAB][0x00][CH1 byte][CH2 byte][CH3 byte] ... [CH512 byte]
```

### Channel byte semantics

Each byte is 0–255. The **meaning** of each byte is determined entirely by the receiving fixture. The protocol doesn't care if channel 1 is "red" or "pan" or "smoke output" — it's whatever the fixture decides.

This is why **fixture profiles** exist in software: they map the byte position to a semantic name (`channel_offset=1 → "red"` for an RGBW par, `channel_offset=1 → "pan"` for a moving head).

### Addressing

Each fixture is configured with a **start address** (1–512). It reads its own slice of channels starting at that address. A 4-channel RGBW par at start address 5 reads channels 5, 6, 7, and 8 from the packet.

### Topology

DMX-512 is a **daisy-chain bus**, not a star or mesh:

```
Host → Fixture 1 → Fixture 2 → ... → Fixture N → [120Ω terminator]
```

Each fixture has DMX-IN and DMX-OUT XLR sockets wired internally as a pass-through. Up to 32 fixtures per chain (electrical limit of RS-485). For more, use a DMX splitter/booster.

### Refresh rate math

At 250 kbps with 11 bits per byte, each byte takes 44 μs to transmit. A full 512-byte universe + start code + break/MAB is about:

```
512 bytes × 44 μs + ~100 μs overhead ≈ 22.6 ms
```

So the theoretical max refresh rate is ~44 Hz. Most professional gear targets 30–44 Hz; below 25 Hz fixtures may show visible flicker.

### Termination

The last fixture in the chain needs a **120Ω resistor** across the differential pair (pins 2 and 3 of the XLR for a 3-pin connection). Without it, signals reflect back up the line and cause intermittent flicker or "ghosting" on long chains. Commercial terminators are male XLR plugs with the resistor soldered inside.

---

## Enttec DMX USB Pro — Widget API

The Enttec DMX USB Pro is a USB-to-DMX adapter. From the host's perspective it appears as a serial port (FTDI USB-to-serial chip) speaking a documented packet protocol.

### Connection parameters

| Setting | Value |
|---|---|
| Port (macOS) | `/dev/tty.usbserial-XXXX` or `/dev/cu.usbserial-XXXX` |
| Port (Linux) | `/dev/ttyUSB0` typically |
| Baud rate | 250000 (per DMX spec, but the chip's USB layer is faster) |
| Data bits | 8 |
| Stop bits | 2 |
| Parity | None |

In practice when using `pyserial`, the Enttec accepts most baud rate settings — the chip handles DMX-side timing internally.

### Widget API packet format

Each command to the Enttec is wrapped in a frame:

```
[0x7E][label][LSB][MSB][...payload...][0xE7]
```

| Byte | Meaning |
|---|---|
| `0x7E` | Start delimiter |
| `label` | Command type (1 byte) |
| `LSB`, `MSB` | Payload length (2 bytes, little-endian) |
| `...` | Payload bytes (length specified above) |
| `0xE7` | End delimiter |

### The command we care about: "Output Only Send DMX Packet Request" (label 6)

For LiveReact, the only command needed is **label 6**: send a DMX packet.

Full frame for a 512-byte universe:

```
Byte 0:    0x7E              (start delimiter)
Byte 1:    0x06              (label = "Output Only Send DMX Packet")
Byte 2:    0x01              (length LSB) — payload is 513 bytes
Byte 3:    0x02              (length MSB) — 0x0201 = 513
Byte 4:    0x00              (DMX start code — always 0x00 for standard data)
Bytes 5–516: [512 DMX channel bytes]
Byte 517:  0xE7              (end delimiter)
```

Total frame size: **518 bytes**.

### Python example

```python
import serial

def build_enttec_frame(universe: bytes) -> bytes:
    """Build an Enttec USB Pro DMX output frame.
    
    universe: 512-byte channel data (channel 1 first).
    """
    assert len(universe) == 512
    payload = b'\x00' + universe  # start code + channels
    length = len(payload)
    frame = bytes([0x7E, 0x06, length & 0xFF, (length >> 8) & 0xFF]) \
            + payload \
            + bytes([0xE7])
    return frame

# Send a frame
universe = bytearray(512)
universe[0] = 255  # channel 1 = full
ser = serial.Serial('/dev/tty.usbserial-XXXX', 250000, timeout=0)
ser.write(build_enttec_frame(bytes(universe)))
```

### Frame timing

Send frames at 30–44 Hz. Don't send faster — the Enttec will buffer and stress the DMX-side timing. A simple writer thread:

```python
import time
TARGET_INTERVAL = 1.0 / 40.0  # 25 ms = 40 Hz

while running:
    frame = build_enttec_frame(bytes(universe_buffer))
    ser.write(frame)
    time.sleep(TARGET_INTERVAL)
```

A `monotonic()`-based scheduler is more accurate than `sleep()` alone if jitter matters:

```python
next_send = time.monotonic()
while running:
    ser.write(build_enttec_frame(bytes(universe_buffer)))
    next_send += TARGET_INTERVAL
    sleep_for = next_send - time.monotonic()
    if sleep_for > 0:
        time.sleep(sleep_for)
```

### Other Widget API commands (not used)

For completeness, the Enttec supports:
- Label 3: Get Widget Parameters
- Label 4: Set Widget Parameters
- Label 8: Receive DMX Packet (we're output-only)
- Label 9: Send RDM Packet (not used)
- Label 13: Get/Set Serial Number

LiveReact only ever sends label 6. The startup default parameters are fine.

### Failure modes

- **`SerialException` on `ser.write`** — USB connection dropped. Retry once, then log and continue. The DMX writer thread should never crash.
- **Frame writes succeed but lights don't update** — Likely the DMX chain has a bad connection or unterminated end. Confirm with a separate test tool.
- **Lights flicker uniformly** — Refresh rate too slow, or USB latency causing irregular gaps. Use a `monotonic`-based scheduler.
- **One specific fixture is unresponsive** — DMX address mismatch, channel mode mismatch on the fixture, or bad cable to that fixture.

### Spec references

- Enttec DMX USB Pro Widget API spec: https://www.enttec.com/wp-content/uploads/2022/11/dmx_usb_pro_api_spec_1_44.pdf
- ANSI E1.11 (DMX-512-A): published by ESTA, available for purchase. The Wikipedia "DMX512" article summarizes the wire format adequately for our purposes.

---

## Quick reference card

| Topic | Value |
|---|---|
| Universe size | 512 channels (bytes) |
| Bit rate | 250 kbps |
| Refresh rate | 30–44 Hz |
| Termination | 120Ω at last fixture |
| Enttec frame size | 518 bytes (header 4 + start code 1 + payload 512 + end 1) |
| Enttec output command | Label 6, payload length 513 |
| Start code (standard data) | `0x00` |
| Frame delimiters | `0x7E` start, `0xE7` end |
