# Hardware Bring-Up Guide

> **Status: the hardware layer is BUILT but UNTESTED on real gear.** Every adapter
> below is written from the spec and unit-tested for the parts that don't need a
> device, but the serial/MIDI/Pro DJ Link paths must be verified the first time the
> rig is connected. Treat every channel number, MIDI CC, and DMX address as a
> *hypothesis to confirm* (docs/04). Work through this checklist in order.

## 0. Prerequisites

- Python **3.12** venv with hardware deps: `pip install -e ".[hardware]"`
- For Pro DJ Link, also install the git-only library (pin a SHA):
  ```
  pip install "git+https://github.com/flesniak/python-prodj-link@<sha>"
  ```
  Until it's installed, hardware mode runs fine but simply has no PDL input (the
  metronome free-runs; use `--midi-monitor` / tap-tempo).

## 1. The rig (docs/04 §1-3)

8 fixtures, 74 DMX channels, one universe. Chain order and addresses:

| Fixture | Addr | Mode |
|---|---|---|
| MH Left / Right | 1 / 16 | 15CH |
| Laser Left / Right | 31 / 43 | 12CH |
| Par Left / Right | 55 / 59 | 4CH |
| Wash Bar Left / Right | 63 / 69 | 6CH |

Set each fixture's DMX address + channel mode on the fixture itself, daisy-chain in
order, and put a **120 Ω terminator** on the last fixture.

## 2. DMX output (Enttec)

1. Plug in the Enttec DMX USB Pro. Confirm it's detected:
   - it shows up as an FTDI device; the app auto-selects it by VID `0x0403`.
   - on macOS the `cu.*` node is used automatically (never `tty.*`).
   - the launch dialog (`--choose`) shows it in the Gear card with its model and
     serial number, and lists what it matched on.
   - **Fixtures can't be detected.** DMX is one-way. The Enttec Pro's widget
     API does have RDM requests, but LiveReact only sends "Output Only Send
     DMX" (label 6) and never reads the port, so there is no RDM discovery, and
     the rig's fixtures may not answer RDM anyway. Confirm each fixture with
     its **Flash** button (step 2, or **Flash each light** in the dialog).
2. **Test one fixture at a time** with the manual panel:
   ```
   python -m livereact --hardware --fixture-test
   ```
   Use each fixture's **Flash** button and the per-channel sliders. Verify every
   channel does what `docs/04 §3` claims (pan, tilt, dimmer, color, strobe, …).
   Fix any mismatches in `src/livereact/fixtures/profiles.py` / `default_rig.json`.
3. **Laser safety**: confirm CH1 boots at 0 (off), and that the laser only lights
   when you explicitly raise it. Aim is verified by a human at install — keep all
   beams above head height (~3 m). Never use the fixture's sound-active modes.

## 3. Pro DJ Link (network)

1. Wire the XDJ-XZ to the host by Ethernet; enable **Link** on the XZ.
2. Set the host wired NIC to a **static link-local** address:
   `169.254.50.50` / `255.255.0.0`. Check readiness:
   ```
   python -m livereact --net-check
   ```
3. Allow the DJ-Link UDP ports (**50000-50002**) through the firewall.
4. Run hardware mode and watch for beats; if you see "No DJ-Link device seen",
   re-check the steps above (static IP + firewall are the usual culprits).
   ```
   python -m livereact --hardware --visualize
   ```
   The virtual CDJ claims player number 5 so it won't collide with the XZ.

## 4. MIDI (the XDJ mixer)

1. On the XDJ-XZ enable **Utility → MIDI**, connect USB.
2. Remap empirically — the default CC map is only a hypothesis:
   ```
   python -m livereact --midi-monitor
   ```
   Move each control (faders, crossfader, EQ) and note its `channel`/`cc`. Put the
   results in `midi_map.json` (keys `"channel:cc"`, e.g. `{"5:31": "crossfader"}`),
   or update `DEFAULT_CC_MAP` in `src/livereact/inputs/midi_map.py`.
3. Some controls may be HID rather than MIDI and may not appear at all — map what
   you can; the show degrades gracefully on missing controls.

## 5. End-to-end

```
python -m livereact --hardware --visualize
```
Play a track on the XDJ-XZ: the rig should pulse on the real beats, scenes should
rotate, drops should fire the lasers (once armed in the console), and a crossfade
between tracks should be detected as a transition. Tune to taste in Phase 8.

## What's verified vs. not

- **Unit-tested (no hardware):** Enttec frame framing + port selection, MIDI CC
  map + port matching, network diagnostics, graceful fallback when no devices.
- **Needs the rig:** actual serial output to the Enttec, real MIDI values from the
  XDJ, the `python-prodj-link` API/field mapping, and all channel-map specifics.
