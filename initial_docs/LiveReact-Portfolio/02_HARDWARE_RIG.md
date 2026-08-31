# 02 — Hardware Rig

Every device in the rig, every cable, every DMX channel. Treat this as the single source of truth for hardware. If you find a discrepancy between this doc and reality, **reality wins** — flag it to Josh and update the doc.

---

## Devices

| # | Device | Qty | Connection | Role |
|---|--------|-----|------------|------|
| 1 | Pioneer XDJ-XZ | 1 | USB + Ethernet to MacBook | Audio source, Pro DJ Link host, MIDI controller |
| 2 | Enttec DMX USB Pro | 1 | USB to MacBook | DMX-512 output adapter |
| 3 | SHEHDS 180W Beam Moving Head | 2 | DMX daisy chain | Spot beams |
| 4 | SHEHDS 3W Laser | 2 | DMX daisy chain | Laser effects |
| 5 | RGBW Par (generic 4ch) | 2 | DMX daisy chain | Color wash |
| 6 | OK-103-288WL Wash Bar | 2 | DMX daisy chain | Bar wash (RGBW) |
| 7 | MacBook (Josh's primary) | 1 | — | LiveReact host |

Total fixtures on the DMX chain: **8 (74 channels)**

---

## Connection topology

```
                          ┌─────────────────┐
                          │  Pioneer XDJ-XZ │
                          └────┬────────┬───┘
                               │        │
                       USB(MIDI)│        │Ethernet (Pro DJ Link)
                               │        │
                               ▼        ▼
                          ┌──────────────────┐
                          │     MacBook      │
                          │   (LiveReact)    │
                          └────────┬─────────┘
                                   │ USB
                                   ▼
                          ┌──────────────────┐
                          │ Enttec DMX USB   │
                          │      Pro         │
                          └────────┬─────────┘
                                   │ XLR-3 (DMX)
                                   ▼
        ┌──────────────────────────┴───────────────────────────┐
        │                                                       │
        │  DMX daisy chain (in order from Enttec):              │
        │                                                       │
        │  MH Left  ─▶  MH Right  ─▶  Laser Left  ─▶            │
        │  Laser Right  ─▶  Par Left  ─▶  Par Right  ─▶         │
        │  Wash Bar Left  ─▶  Wash Bar Right  ─▶  [120Ω term]   │
        │                                                       │
        └───────────────────────────────────────────────────────┘
```

**Always terminate the chain** with a 120Ω resistor in a male XLR-3 plug. Without termination, the chain becomes unreliable as it grows.

---

## DMX address map

**Universe 1.** No overlaps. Total 74 channels of 512 used.

| Fixture | Label | DMX Address | Channels | Range |
|---|---|---|---|---|
| SHEHDS 180W Moving Head | MH Left | **1** | 15 | 1–15 |
| SHEHDS 180W Moving Head | MH Right | **16** | 15 | 16–30 |
| SHEHDS 3W Laser | Laser Left | **31** | 12 | 31–42 |
| SHEHDS 3W Laser | Laser Right | **43** | 12 | 43–54 |
| RGBW Par | Par Left | **55** | 4 | 55–58 |
| RGBW Par | Par Right | **59** | 4 | 59–62 |
| OK-103-288WL Wash Bar | Wash Bar Left | **63** | 6 | 63–68 |
| OK-103-288WL Wash Bar | Wash Bar Right | **69** | 6 | 69–74 |

**Setting addresses on hardware:** Each fixture has a small display on the back. Navigate to `DMX → Addr → [number]` and confirm. Also set the channel **mode** for the moving heads (15CH) and the wash bars (6CH).

---

## Fixture profiles

### 3.1 — SHEHDS 180W Moving Head (15ch mode)

**Use 15CH mode.** Set on hardware via `DMX → Channel → 15CH`.

| CH | Name | Range | Notes |
|---|---|---|---|
| 1 | Pan | 0–255 | Coarse pan (450° rotation) |
| 2 | Pan fine | 0–255 | Low byte; together with CH1 = 16-bit position |
| 3 | Tilt | 0–255 | Coarse tilt (210° range) |
| 4 | Tilt fine | 0–255 | Low byte |
| 5 | Speed | 0–255 | Pan/tilt move speed (low = slow) |
| 6 | Dimmer | 0–255 | Master brightness |
| 7 | Strobe | 0–255 | 0 = off, 1–255 = slow→fast (up to 25 Hz) |
| 8 | Color wheel | 0–255 | See color table below |
| 9 | Gobo wheel | 0–255 | See gobo table below |
| 10 | Prism | 0–255 | 0–7 off, 8–127 open, 128–190 rotation |
| 11 | Focus | 0–255 | Beam focus |
| 12 | Frost | 0–255 | 0–7 off, 8–127 rainbow effect, 192–255 frost |
| 13 | Macro | 0–255 | **Keep at 0** — we drive via DMX, not built-in macros |
| 14 | Macro speed | 0–255 | Ignored when Macro = 0 |
| 15 | Reset | 0–255 | 0–240 off, 241–255 trigger reset (5 sec) |

**Color wheel (CH8) values:**

| Value | Color |
|---|---|
| 0–10 | White (open) |
| 11–21 | Color 1 |
| 22–32 | Color 2 |
| 33–43 | Color 3 |
| 44–54 | Color 4 |
| 55–65 | Color 5 |
| 66–76 | Color 6 |
| 77–87 | Color 7 |
| 88–98 | Color 8 |
| 99–109 | Color 9 |
| 110–120 | Color 10 |
| 121–127 | Color 11 |
| 128–191 | Clockwise rotation (speed varies with value) |
| 192–255 | Anti-clockwise rotation |

**Gobo wheel (CH9) values:**

| Value | Gobo |
|---|---|
| 0–15 | White (open) |
| 16–23 | Gobo 1 |
| 24–31 | Gobo 2 |
| ... | (each gobo = 8-value range) |
| 120–127 | Gobo 14 |
| 128–191 | Clockwise rotation |
| 192–255 | Anti-clockwise rotation |

**Boot defaults (recommended):** Pan = 128 (center), Tilt = 80 (angled down), Speed = 128, Dimmer = 0 (off until scene activates).

---

### 3.2 — SHEHDS 3W Laser (12ch mode)

The laser has 12ch and 25ch modes. **Use 12ch for LiveReact** unless you specifically need dual-pattern control. Set on hardware via the menu.

| CH | Name | Range | Notes |
|---|---|---|---|
| 1 | Mode | 0–255 | **0–41 = LASER OFF (default state)**, 42–83 manual, 84–125 auto anim, 126–167 auto beam, 168–209 sound beam, 210–251 sound anim, 252–255 manual |
| 2 | Pattern A coarse | 0–255 | Every 32 values = new pattern group |
| 3 | Pattern A fine | 0–255 | Every 16 values = new pattern |
| 4 | Rotation | 0–255 | 1–127 angle, 128–191 inverse, 192–255 forward |
| 5 | H-Flip | 0–255 | 0–127 position, 128–255 rotation speed |
| 6 | V-Flip | 0–255 | Same as H-Flip |
| 7 | H-Move | 0–255 | 0–127 position, 128–255 speed |
| 8 | V-Move | 0–255 | 0–127 position, 128–255 speed |
| 9 | Pattern scale | 0–255 | 0–63 scale, 64–127 narrow, 128–191 enlarge, 192–255 speed |
| 10 | Pattern painting | 0–255 | Speed control |
| 11 | Scan | 0–255 | 0–127 scan speed, 128–255 pattern lattice |
| 12 | Color | 0–255 | 0–63 select, 64–127 auto change, 128–191 rainbow, 192–255 painting |

**SAFETY-CRITICAL DEFAULTS:**
- CH1 must boot at **0** (laser off). Never boot in any active mode.
- The DJ controls when the laser comes on via scenes — never via UI panic buttons that could activate it accidentally.
- Audience-safe pointing angle (above head level) is verified at install time, not at runtime. The software trusts that mounting is correct.
- Never set CH1 to sound-active modes (168–251). LiveReact controls all timing — we do not want the laser doing its own thing.

---

### 3.3 — RGBW Par (4ch)

Generic RGBW par/can with 4-channel mode. Simple.

| CH | Name | Range | Notes |
|---|---|---|---|
| 1 | Red | 0–255 | |
| 2 | Green | 0–255 | |
| 3 | Blue | 0–255 | |
| 4 | White | 0–255 | Separate white LED, not a mix of RGB |

**No master dimmer, no strobe channel.** To "strobe" an RGBW par, alternate RGB values between full and 0 in software at the desired rate. To dim, scale the RGB values directly.

---

### 3.4 — OK-103-288WL Wash Bar (6ch mode)

The wash bar supports 5 DMX modes. **Use 6CH mode** (simplest, treats the whole bar as one RGBW unit). Set on hardware: `DMX → Addr → [number] → 6CH`.

| CH | Name | Range | Notes |
|---|---|---|---|
| 1 | Master Dimmer | 0–255 | Overall brightness |
| 2 | Strobe | 0–255 | 0–9 off, 10–255 slow→fast |
| 3 | All Red | 0–255 | Applied to all 288 LEDs |
| 4 | All Green | 0–255 | |
| 5 | All Blue | 0–255 | |
| 6 | All White | 0–255 | |

The 12CH and 32CH/64CH modes (pattern effects and per-zone control) are not used by LiveReact. If a future scene needs zone control, switch to 12CH mode and add the second profile.

---

## XDJ-XZ connectivity

| Connection | Purpose | Notes |
|---|---|---|
| **USB** (USB-B on XDJ → USB-A on Mac) | MIDI controller messages | XDJ shows up as `XDJ-XZ` MIDI device |
| **Ethernet** (RJ45 on XDJ → USB-C-to-Ethernet adapter on Mac) | Pro DJ Link broadcast | Auto-IP (`169.254.x.x`) usually works without manual config |
| **USB audio** (same USB-B as MIDI) | Master out audio stream | **Not used** in v2. Available for diagnostics if needed. |

### macOS specifics

- The XDJ-XZ may take 2–3 seconds after boot to start broadcasting Pro DJ Link.
- macOS energy saver should be set to **never sleep** on AC power during a show.
- Disable automatic OS updates. Disable notifications. Use Focus mode.
- The Enttec serial port is `/dev/tty.usbserial-XXXX` or `/dev/cu.usbserial-XXXX` — the device number suffix can change between USB ports. Detect dynamically rather than hard-coding.

---

## Rig file format (proposed)

The application loads a **rig file** that defines which fixtures are present, where they are addressed, and their roles. Recommended format (JSON):

```json
{
  "name": "Full Show",
  "universe_size": 512,
  "slots": [
    { "slot_id": 0, "fixture_type": "SHEHDSMovingHead180W", "dmx_address": 1,  "label": "MH Left",       "role": "spot",  "side": "left"  },
    { "slot_id": 1, "fixture_type": "SHEHDSMovingHead180W", "dmx_address": 16, "label": "MH Right",      "role": "spot",  "side": "right" },
    { "slot_id": 2, "fixture_type": "SHEHDSLaser12ch",      "dmx_address": 31, "label": "Laser Left",    "role": "laser", "side": "left"  },
    { "slot_id": 3, "fixture_type": "SHEHDSLaser12ch",      "dmx_address": 43, "label": "Laser Right",   "role": "laser", "side": "right" },
    { "slot_id": 4, "fixture_type": "RGBWPar",              "dmx_address": 55, "label": "Par Left",      "role": "wash",  "side": "left"  },
    { "slot_id": 5, "fixture_type": "RGBWPar",              "dmx_address": 59, "label": "Par Right",     "role": "wash",  "side": "right" },
    { "slot_id": 6, "fixture_type": "OK103WashBar6ch",      "dmx_address": 63, "label": "Wash Bar Left", "role": "wash",  "side": "left"  },
    { "slot_id": 7, "fixture_type": "OK103WashBar6ch",      "dmx_address": 69, "label": "Wash Bar Right","role": "wash",  "side": "right" }
  ]
}
```

The application loads this at startup, instantiates the corresponding fixture profile classes, and exposes them by slot_id, role, or label. Scenes address fixtures by **role and side** ("all wash, both sides"), not by raw DMX index.

---

## Power and physical setup

Not your concern for software, but useful context:
- Each moving head: ~180W mains power
- Each laser: ~3W (low draw)
- Each par / bar: ~30–50W LED
- All fixtures use IEC C13 power cords; daisy-chain power is **not** recommended — give each fixture its own plug if possible.
- Mounting: trusses, T-bar stands, or floor-stand for the moving heads.
- The 180W moving heads get hot — leave them ~20 min to cool after powering off.

Josh handles all this. If you're on site for testing, he'll have the rig set up before you arrive.

---

## Hardware bring-up checklist

Before running LiveReact on the rig, verify:

1. [ ] Every fixture is powered, has its DMX address set, and has its channel mode set correctly.
2. [ ] DMX cables daisy-chained in the order in the address map.
3. [ ] 120Ω terminator plugged into the last fixture.
4. [ ] Enttec USB Pro plugged in, blue light steady (not flashing).
5. [ ] XDJ-XZ powered, USB cable to Mac, Ethernet cable to Mac.
6. [ ] In Pioneer's Pro DJ Link settings on the XDJ, "Link" mode is enabled.
7. [ ] macOS sees the XDJ as a MIDI device (Audio MIDI Setup → MIDI Studio).
8. [ ] `ifconfig` shows a `169.254.x.x` link-local IP on the Ethernet interface (or a configured static IP shared with the XDJ).

Next: **`03_ARCHITECTURE.md`** — how the software is organized.
