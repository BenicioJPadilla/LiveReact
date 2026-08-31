# LiveReact

Beat-reactive DMX lighting for DJ sets. Driven by your XDJ-XZ via USB.

## Hardware

| Device | Connection |
|--------|-----------|
| Pioneer XDJ-XZ | USB to MacBook |
| Enttec DMX USB Pro | USB to MacBook |
| SHEHDS 180W Moving Heads (x2) | DMX chain from Enttec |
| 3W SHEHDS Lasers (x2) | DMX chain |
| RGBW Pars / Bars | DMX chain |

## Setup

### 1. Install dependencies

```bash
brew install portaudio          # macOS only
pip install -r requirements.txt
```

### 2. Find your audio device name

```bash
python run.py --list-audio
```

Look for the XDJ-XZ in the list. It will show up as something like
`"XDJ-XZ"` or `"Pioneer DJ XDJ-XZ"`. Note the exact name.

### 3. Find your Enttec serial port

```bash
python run.py --list-dmx
```

On macOS it will look like `/dev/tty.usbserial-A50285BI`.

### 4. Run

```bash
# Auto-detect everything
python run.py

# Specify devices explicitly
python run.py --audio "XDJ-XZ" --dmx /dev/tty.usbserial-XXXX

# Use full show rig (moving heads + lasers + pars)
python run.py --rig rigs/full_show.json --audio "XDJ-XZ"
```

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| `B` | Blackout toggle |
| `F` | Freeze (hold current DMX state) |
| `T` | Tap tempo |
| `Space` | Strobe burst |

## Rig files

Rig files live in `rigs/`. Each is a JSON file describing your fixture layout.

**Current rigs:**
- `two_rgbw.json` — 2x RGBW pars at DMX 1 and 5
- `full_show.json` — 2x moving heads + 2x RGBW pars

**To create a new rig**, copy an existing file and edit it:

```json
{
  "name": "My Rig",
  "slots": [
    {
      "slot_id": 0,
      "fixture_type": "RGBWPar",
      "dmx_address": 1,
      "label": "Par Left",
      "role": "wash"
    }
  ]
}
```

**Available fixture types:**
- `RGBWPar` — 4ch RGBW par / bar
- `SHEHDSMovingHead180W` — 15ch moving head

**Roles:**
- `wash` — ambient colour fill (pars, bars)
- `spot` — moving head beam
- `laser` — laser fixture
- `strobe` — dedicated strobe unit

## DMX chain wiring

```
MacBook USB → Enttec DMX USB Pro
                    │
                    ├─ Moving Head L  (DMX addr 1,  15ch)
                    ├─ Moving Head R  (DMX addr 16, 15ch)
                    ├─ Par Left       (DMX addr 31, 4ch)
                    └─ Par Right      (DMX addr 35, 4ch)
                                          ↑
                               terminate with 120Ω resistor
```

## Energy modes

The engine automatically detects musical energy and transitions between:

| Mode | Description |
|------|-------------|
| BREAK | Low energy, breakdown — slow breathing wash |
| BUILD | Rising energy — escalating intensity, chasing patterns |
| DROP | Drop hit — full brightness, bass-reactive strobes |
| PEAK | Sustained peak — beat-synced colours, gobo patterns |
| OUTRO | Winding down — slow fade to dark |

## Project structure

```
livereact/
├── run.py                  ← start here
├── requirements.txt
├── rigs/                   ← show configurations
├── core/
│   ├── fixture.py          base fixture class
│   ├── rig.py              rig loader
│   ├── show_state.py       shared show state
│   ├── energy_detector.py  break/build/drop/peak detection
│   └── show_engine.py      main loop
├── audio/
│   ├── engine.py           FFT, beat tracking, onset detection
│   └── prodj_link.py       Pro DJ Link BPM sync
├── dmx/
│   └── enttec.py           Enttec USB Pro driver
├── fixtures/
│   ├── registry.py         fixture type registry
│   ├── rgbw_par.py         4ch RGBW par profile
│   └── shehds_moving_head_180w.py  15ch moving head profile
├── scenes/
│   ├── base.py             scene base class
│   └── scenes.py           all lighting scenes
└── ui/
    └── control_panel.py    live control panel
```
