# v1 — context notes

What this snapshot shows, and what to take from it.

## What v1 was

v1 was the first working version of LiveReact. Used USB audio FFT (sampling the XDJ-XZ's master out) to drive a beat/energy detection state machine (`BREAK / BUILD / DROP / PEAK / OUTRO`), which selected scenes and parameters in real time. It worked, ran on real shows, and proved the concept.

The files in this folder are a partial snapshot from around April 2026:

| File | What it is |
|---|---|
| `run.py` | Entry point. Auto-detects audio device and DMX port, falls back to demo mode. |
| `README.md` | The v1 setup guide and feature description. Mentions the `BREAK/BUILD/DROP/PEAK/OUTRO` energy mode system that's been replaced in v2. |
| `version.py` | Version constant (v0.1.0-BETA). |
| `LiveReact.command` | macOS double-click launcher script. Auto-detects XDJ audio and Enttec port, falls back to demo. Worth replicating in v2 — Josh likes one-click launching. |
| `LiveReact_Setup.command` | First-time-setup script. Installs Homebrew + portaudio + Python dependencies. Likely simplifiable for v2 since portaudio isn't needed. |

## What's worth keeping (in design, not code)

- **The auto-detection pattern in `LiveReact.command`** — searching common Python paths, finding the Enttec port via `/dev/tty.usbserial-*` glob, falling back gracefully when devices aren't found. Reproduce this in v2's launcher.
- **The fixture profile abstraction** — v1's `core/fixture.py` defined a `Fixture` base with `ChannelDef` entries and named `get()/set()` accessors. The v2 design uses the same pattern.
- **The rig file format** — JSON describing slots, fixture types, addresses, labels, and roles. Cleanly extensible.
- **The tkinter control panel layout** — meters, scene buttons, action buttons. Visual layout is solid.

## What's been replaced

- **Audio FFT pipeline** (`audio/engine.py`) — replaced by Pro DJ Link listener + MIDI listener. See `01_DOMAIN_PRIMER.md` section 3 and `04_DESIGN_PRINCIPLES.md` section 5 for why.
- **Energy detector** (`core/energy_detector.py`, the BREAK/BUILD/DROP/PEAK state machine) — replaced by per-engine logic. The Phrase Engine handles rotation. The Transition Engine handles mixes. The Reactive Layer handles beat sync. There is no longer a global "energy mode" the whole system reads.
- **Demo mode mechanics** — v1's demo mode was bolted on. v2 makes demo mode a first-class input source (`DemoDataGenerator`) that produces the same ShowState contract as the real listeners.

## What you won't find in this snapshot

The full v1 code includes:
- `core/fixture.py` — fixture base class
- `core/rig.py` — rig loader
- `core/show_state.py` — earlier version of ShowState (audio-focused)
- `core/energy_detector.py` — the audio energy classifier (replaced)
- `core/show_engine.py` — main loop
- `audio/engine.py` — FFT pipeline (dropped)
- `audio/prodj_link.py` — early PDL integration
- `dmx/enttec.py` — Enttec driver
- `fixtures/*.py` — fixture profiles for RGBW par, moving head, laser, wash bar
- `scenes/scenes.py` — scene catalog
- `ui/control_panel.py` — tkinter UI

The snapshot here doesn't include those modules, but their **structure** (file layout, class shapes) is preserved in the suggested v2 layout in `03_ARCHITECTURE.md` section 10. If you want to see, say, the Enttec driver implementation, talk to Josh — he can share the full v1 zip.

## The one important thing v1 got right

The DMX output side. The Enttec USB Pro driver, fixture profiles, scene rendering pattern, and the merge from scene buffer → universe buffer are all conceptually sound and were never the bottleneck. Most of v2's redesign is on the **input** side; the **output** side carries over largely unchanged.
