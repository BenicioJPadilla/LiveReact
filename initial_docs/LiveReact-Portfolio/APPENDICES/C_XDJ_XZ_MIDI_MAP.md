# C — XDJ-XZ MIDI Map

The MIDI Control Change (CC) numbers that LiveReact reads from the XDJ-XZ. **This is a working reference, not Pioneer's official spec** — values were verified by Josh against his unit during v2 Phase 1. If a value here doesn't match what you see, trust your device and update this doc.

---

## How to verify a CC number yourself

When in doubt, run this and move the control you're investigating:

```python
import mido

ports = mido.get_input_names()
xdj_port = next(p for p in ports if 'XDJ' in p or 'Pioneer' in p)
print(f"Listening on {xdj_port}")

with mido.open_input(xdj_port) as inp:
    for msg in inp:
        if msg.type == 'control_change':
            print(f"CC ch={msg.channel} cc={msg.control} value={msg.value}")
        elif msg.type == 'note_on':
            print(f"NOTE ON ch={msg.channel} note={msg.note} velocity={msg.velocity}")
```

Move one control at a time, note which CC fires.

---

## Channel layout

The XDJ-XZ uses **multiple MIDI channels** (1-indexed in MIDI spec, 0-indexed in `mido`):

| MIDI Channel | Surface area |
|---|---|
| 0 (ch 1) | Deck 1 controls |
| 1 (ch 2) | Deck 2 controls |
| 2 (ch 3) | Deck 3 controls (layered) |
| 3 (ch 4) | Deck 4 controls (layered) |
| 4 (ch 5) | Effects section |
| 5 (ch 6) | Mixer (channel faders, crossfader, master, EQs) |
| 6 (ch 7) | Performance pads |

LiveReact cares mostly about **channel 6** (mixer) for fader/crossfader/EQ state, and channels 0/1 for deck-specific play/cue buttons.

---

## Mixer section (MIDI ch 6) — primary for LiveReact

| Control | Type | CC# | Range | Notes |
|---|---|---|---|---|
| Channel 1 Fader | CC | 23 | 0–127 | Linear |
| Channel 2 Fader | CC | 24 | 0–127 | Linear |
| Channel 3 Fader | CC | 25 | 0–127 | (layered deck) |
| Channel 4 Fader | CC | 26 | 0–127 | (layered deck) |
| Crossfader | CC | 31 | 0–127 | 0 = full A, 127 = full B |
| Master Level | CC | 8 | 0–127 | |
| Booth Level | CC | 9 | 0–127 | |
| Headphone Mix | CC | 11 | 0–127 | |
| Headphone Level | CC | 10 | 0–127 | |
| Ch1 EQ Low | CC | 15 | 0–127 | 64 = neutral |
| Ch1 EQ Mid | CC | 16 | 0–127 | 64 = neutral |
| Ch1 EQ High | CC | 17 | 0–127 | 64 = neutral |
| Ch1 Trim | CC | 14 | 0–127 | |
| Ch1 Filter | CC | 18 | 0–127 | 64 = off, < 64 = LPF, > 64 = HPF |
| Ch2 EQ Low | CC | 19 | 0–127 | |
| Ch2 EQ Mid | CC | 20 | 0–127 | |
| Ch2 EQ High | CC | 21 | 0–127 | |
| Ch2 Trim | CC | 13 | 0–127 | |
| Ch2 Filter | CC | 22 | 0–127 | |

**Note:** The exact CC numbers here are based on Josh's verified unit. Pioneer's mapping has been observed to vary slightly between firmware versions and between MIDI mode settings on the XDJ. Verify on the actual unit.

### Mapping CC values to ShowState fields

```python
# fader values 0..127 → 0.0..1.0
def cc_to_unit(cc_value: int) -> float:
    return cc_value / 127.0

# EQ knobs are 64 = neutral. Map to a -1..+1 or 0..1 range.
# LiveReact uses 0..1 where 0.5 = neutral.
def cc_to_eq(cc_value: int) -> float:
    return cc_value / 127.0  # 64/127 ≈ 0.504, close enough

# Crossfader: 0 = full A, 0.5 = center, 1.0 = full B
def cc_to_crossfader(cc_value: int) -> float:
    return cc_value / 127.0
```

---

## Deck 1 (MIDI ch 1) — secondary

| Control | Type | CC# / Note# | Notes |
|---|---|---|---|
| Play/Pause | Note On | 11 | Velocity 127 on press |
| Cue | Note On | 12 | |
| Sync | Note On | 88 | |
| Beat Sync Master | Note On | 92 | |
| Loop In | Note On | 16 | |
| Loop Out | Note On | 17 | |
| Reloop / Exit | Note On | 80 | |
| Tempo Slider | CC | 0 (14-bit, LSB on CC 32) | High-resolution; use both bytes for full range |
| Jog Wheel | CC | 35 | Relative value, jog touch sensor sends note 96 |
| Pitch Bend +/- | Note On | 95, 94 | |
| Hot Cue 1–8 | Note On | 102–109 | |

---

## Deck 2 (MIDI ch 2) — secondary

Same control mappings as Deck 1 but on MIDI channel 2 (0-indexed 1).

---

## Effects section (MIDI ch 5)

LiveReact does not currently use effects state, but for future reference:

| Control | Type | CC# / Note# |
|---|---|---|
| Beat FX Level/Depth | CC | 16 |
| Beat FX Time | CC | 17 |
| Beat FX Channel Select | CC | 18 |
| Beat FX On/Off | Note On | 71 |

---

## What LiveReact actually subscribes to

Per architecture decisions in `03_ARCHITECTURE.md`, LiveReact reads:

| ShowState field | MIDI source |
|---|---|
| `fader_a` | Ch6 CC 23 (Channel 1 fader) |
| `fader_b` | Ch6 CC 24 (Channel 2 fader) |
| `crossfader` | Ch6 CC 31 |
| `eq_low_a` | Ch6 CC 15 |
| `eq_mid_a` | Ch6 CC 16 |
| `eq_high_a` | Ch6 CC 17 |
| `eq_low_b` | Ch6 CC 19 |
| `eq_mid_b` | Ch6 CC 20 |
| `eq_high_b` | Ch6 CC 21 |

Everything else can be ignored unless a future feature needs it.

---

## Implementation pattern

```python
import mido
from collections import defaultdict
import time

class MidiInputListener:
    # mapping: (midi_channel, cc_number) → (state_field, scale_fn)
    CC_MAP = {
        (5, 23): ('fader_a',     lambda v: v / 127.0),
        (5, 24): ('fader_b',     lambda v: v / 127.0),
        (5, 31): ('crossfader',  lambda v: v / 127.0),
        (5, 15): ('eq_low_a',    lambda v: v / 127.0),
        (5, 16): ('eq_mid_a',    lambda v: v / 127.0),
        (5, 17): ('eq_high_a',   lambda v: v / 127.0),
        (5, 19): ('eq_low_b',    lambda v: v / 127.0),
        (5, 20): ('eq_mid_b',    lambda v: v / 127.0),
        (5, 21): ('eq_high_b',   lambda v: v / 127.0),
    }

    def __init__(self, show_state, port_name='XDJ-XZ'):
        self.show_state = show_state
        self.port = mido.open_input(port_name)
        self._smoothers = defaultdict(lambda: 0.0)

    def run(self):
        for msg in self.port:
            if msg.type == 'control_change':
                key = (msg.channel, msg.control)
                if key in self.CC_MAP:
                    field, scale = self.CC_MAP[key]
                    value = scale(msg.value)
                    # Optional: light smoothing for faders
                    smoothed = 0.7 * self._smoothers[field] + 0.3 * value
                    self._smoothers[field] = smoothed
                    with self.show_state._lock:
                        setattr(self.show_state, field, smoothed)
                        self.show_state.midi_last_packet_at = time.monotonic()
```

---

## Caveats

- **CC numbers can vary** between XDJ firmware versions and between MIDI mode settings on the device. Always verify against the actual unit when you start. Update this doc if discrepancies are found.
- **The XDJ-XZ's MIDI mode must be enabled** in the device settings (Utility → MIDI). Without this, the unit won't send MIDI on USB.
- **`mido` on macOS** requires the `python-rtmidi` backend. Install with: `pip install mido python-rtmidi`.
- **MIDI port names change** between USB ports / reboots. Detect dynamically by name substring rather than hardcoding.
- **Pitch slider is 14-bit** — to read accurately, combine CC 0 (MSB) and CC 32 (LSB) values. LiveReact doesn't currently use it.
