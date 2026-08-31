# 03 — Architecture

The v2 design: dual-input → ShowState bus → three parallel engines → merge → DMX. This document is the technical core of the portfolio. Read it after `01_DOMAIN_PRIMER.md` and `02_HARDWARE_RIG.md`.

---

## 1. The diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                  INPUT                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌────────────────────┐                  ┌────────────────────┐            │
│   │   Pro DJ Link      │                  │     USB MIDI       │            │
│   │   (over Ethernet)  │                  │   (over USB-B)     │            │
│   │                    │                  │                    │            │
│   │   BPM · beat · bar │                  │  faders · crossfdr │            │
│   │   loop · on-air    │                  │  EQ knobs · cues   │            │
│   │   master deck      │                  │                    │            │
│   │                    │                  │                    │            │
│   │  "musical clock"   │                  │  "DJ's intent"     │            │
│   └─────────┬──────────┘                  └─────────┬──────────┘            │
│             │                                       │                       │
│             │       ProDJLinkListener   MidiInputListener                   │
│             │       (thread)            (thread)                            │
│             │                                       │                       │
└─────────────┼───────────────────────────────────────┼───────────────────────┘
              │                                       │
              ▼                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          ShowState  (shared data bus)                       │
│                                                                             │
│   - Thread-safe single object read by all consumers                         │
│   - Holds: bpm, beat, bar, beat_phase, loop_active, on_air,                 │
│            fader_a, fader_b, crossfader, eq_states, ...                     │
│   - No engine writes back to it (read-only from engines' POV)               │
│   - Only listeners write to it (with locks)                                 │
└─────────────────────────┬───────────────────────────────────────────────────┘
                          │
                          │  all engines READ from ShowState
                          │
       ┌──────────────────┼──────────────────┐
       │                  │                  │
       ▼                  ▼                  ▼
┌─────────────┐  ┌─────────────────┐  ┌─────────────────────┐
│  Reactive   │  │  Phrase Engine  │  │ Transition Engine   │
│   Layer     │  │                 │  │                     │
│             │  │ Fires every     │  │ Active only during  │
│ Every beat  │  │ 8 / 16 bars     │  │ mix (xfader move)   │
│             │  │                 │  │                     │
│ BPM-locked  │  │ Scene rotation  │  │ Deck handoff logic  │
│ pulses,     │  │ + crossfade     │  │ Loop hold pattern   │
│ movement    │  │                 │  │ 4-bar post-mix hold │
│             │  │                 │  │                     │
│ Always on   │  │ Picks next      │  │ Suspends Phrase     │
│             │  │ scene from      │  │ Engine while active │
│             │  │ catalog         │  │                     │
└──────┬──────┘  └────────┬────────┘  └──────────┬──────────┘
       │                  │                      │
       │                  │                      │
       └──────────────────┼──────────────────────┘
                          │
                          ▼
              ┌─────────────────────────┐
              │   Scene buffer +        │
              │   Output / Merge        │
              │   layer                 │
              │                         │
              │   Combines all engine   │
              │   contributions         │
              │   additively, then      │
              │   applies ManualParams  │
              │   (UI biases / caps)    │
              └────────────┬────────────┘
                           │
                           ▼
              ┌─────────────────────────┐
              │   DMX universe buffer   │
              │   (512 bytes)           │
              └────────────┬────────────┘
                           │
                           │  ~44 Hz writer thread
                           ▼
              ┌─────────────────────────┐
              │   Enttec USB Pro driver │
              │   (518-byte serial      │
              │    frame protocol)      │
              └────────────┬────────────┘
                           │
                           ▼
                  Daisy-chained DMX rig
                  (74 channels, 8 fixtures)
```

The same diagram exists as a one-page poster at `livereact_architecture.pdf` in the project root.

---

## 2. Threading model

LiveReact has the following long-lived threads:

| Thread | Purpose | Rate |
|---|---|---|
| **Main** (tkinter event loop) | UI rendering, user input | 30–60 Hz |
| **PDL Listener** | Receives Pro DJ Link UDP packets, parses, writes to ShowState | Event-driven (~beat rate) |
| **MIDI Listener** | Receives MIDI CC messages, writes to ShowState | Event-driven |
| **Show Engine** | Runs the three engines, builds the scene buffer | ~60 Hz |
| **DMX Writer** | Serializes the universe buffer, sends to Enttec | 44 Hz |
| **Local Metronome** | Interpolates between PDL beats to provide a smooth phase clock | ~120 Hz |

All threads communicate exclusively through:

- **ShowState** — for input data (read by engines, written by listeners)
- **Scene buffer** — for engine output (written by engines, read by merge layer)
- **DMX universe buffer** — for final output (written by merge, read by DMX writer)

**Engines never call each other directly.** Each engine reads ShowState, decides what to do, and writes its contribution to the scene buffer. The merge layer is the only thing that knows about all three engines simultaneously.

---

## 3. ShowState — the shared data bus

A single Python object that holds the latest state from all inputs. Read by every engine on every tick; written only by listener threads.

```python
@dataclass
class ShowState:
    # From Pro DJ Link
    bpm: float = 120.0
    beat: int = 1                # 1, 2, 3, 4 (within bar)
    bar: int = 1                 # 1..N (within phrase)
    beat_phase: float = 0.0      # 0.0–1.0 sub-beat position
    loop_active: bool = False
    loop_length_beats: int = 0
    on_air_deck: int = 1
    master_deck: int = 1
    track_position_seconds: float = 0.0
    pdl_last_packet_at: float = 0.0  # for staleness detection

    # From MIDI
    fader_a: float = 0.0          # 0.0–1.0 (deck A channel fader)
    fader_b: float = 0.0          # 0.0–1.0 (deck B channel fader)
    crossfader: float = 0.5       # 0.0=full A, 0.5=center, 1.0=full B
    eq_low_a: float = 0.5         # 0.0–1.0 (0.5 = neutral, 0.0 = killed)
    eq_mid_a: float = 0.5
    eq_high_a: float = 0.5
    eq_low_b: float = 0.5
    eq_mid_b: float = 0.5
    eq_high_b: float = 0.5
    midi_last_packet_at: float = 0.0

    # Derived (computed by listeners or a small derivation thread)
    in_transition: bool = False   # crossfader has moved meaningfully recently
    energy: float = 0.5           # 0.0–1.0 estimated from fader/EQ state
```

### Concurrency rules

- **One writer per field group.** PDL listener writes only PDL fields. MIDI listener writes only MIDI fields. Derivation runs on one thread.
- **Use a single lock** (`threading.RLock`) on the ShowState object. Acquire it for any read or write that touches multiple fields atomically.
- **Atomic snapshots for engines.** When an engine starts a tick, it calls `state.snapshot()` which returns a frozen copy. The engine works against the snapshot, never the live object. This prevents tearing where bpm and beat are read at different moments.
- **Reading a single field doesn't need the lock** (Python assignment is atomic for primitives).

```python
def snapshot(self) -> "ShowState":
    with self._lock:
        return replace(self)  # dataclasses.replace = shallow copy
```

### Staleness detection

- If `now() - pdl_last_packet_at > 1.0` seconds, log a warning and have the local metronome run free at the last known BPM.
- If MIDI is stale, just hold the last known fader/EQ values. Not as critical.

---

## 4. Input layer

### 4.1 ProDJLinkListener

A thread that wraps `python-prodj-link` (a well-maintained Python implementation of the Pioneer protocol). Responsibilities:

- Connect to the network interface that has the XDJ-XZ on it.
- Subscribe to beat packets and status packets.
- On each packet, parse it and update the appropriate ShowState fields.
- Track the last packet time for staleness.

**Beat jitter mitigation:** PDL packets arrive with timing jitter of 5–20 ms. We don't use them directly as a visual clock — we use them to **resync a local metronome** that runs at the current BPM and produces a smooth phase output. See section 4.3.

### 4.2 MidiInputListener

A thread that uses `mido` (or `python-rtmidi`) to read MIDI CC messages from the XDJ. The XDJ-XZ MIDI map is in `APPENDICES/C_XDJ_XZ_MIDI_MAP.md`. The listener:

- Opens the MIDI input port matching the XDJ name.
- For each CC message, looks up the meaning in the map and updates the relevant ShowState field.
- Smooths fader values with a short rolling average (~50 ms window) before writing.

### 4.3 Local metronome

A thread that maintains its own beat phase clock, synced to incoming PDL beats. Why: PDL packets arrive ~4 times a second at 120 BPM, but visual frames need smooth phase information at 60 Hz. The metronome interpolates between PDL packets.

Pseudocode:

```python
class LocalMetronome:
    def __init__(self, show_state):
        self.show_state = show_state
        self.last_beat_at = time.monotonic()
        self.last_beat_phase = 0.0

    def on_pdl_beat(self, beat_packet):
        # Resync to the canonical beat from PDL
        self.last_beat_at = time.monotonic()
        self.last_beat_phase = 0.0
        # Apply a small low-pass to bpm estimate to reject jitter
        ...

    def current_phase(self) -> float:
        bpm = self.show_state.bpm
        if bpm <= 0:
            return 0.0
        beat_period = 60.0 / bpm
        elapsed = time.monotonic() - self.last_beat_at
        phase = (self.last_beat_phase + elapsed / beat_period) % 1.0
        return phase
```

Engines should use `metronome.current_phase()` for sub-beat timing, not `show_state.beat_phase` directly. The PDL value is too jittery for smooth movement.

### 4.4 DemoDataGenerator (no-hardware mode)

For development without the rig. Generates synthetic PDL and MIDI data:

- A fixed 124 BPM clock advancing beat/bar normally
- Periodic synthetic transitions (every ~64 bars, simulate a crossfader move)
- Configurable energy curve to simulate buildups and drops

The application detects on startup whether hardware is connected. If not, it spins up DemoDataGenerator instead of the real listeners. Same ShowState contract; engines don't know the difference.

---

## 5. The three engines

Each engine is a class with a `tick(snapshot, scene_buffer)` method called by the Show Engine at ~60 Hz. Each one writes its contribution into the scene buffer's layers — never overwriting previous contributions.

### 5.1 Reactive Layer Engine

**Always on.** Produces beat-synced pulses and BPM-locked movement.

What it writes:
- Per-beat dimmer pulse on washes (envelope: spike to full on beat, decay over 200 ms)
- Pan/tilt motion on moving heads, BPM-locked (e.g., sweep that takes 4 beats per cycle)
- Color values driven by current frequency content (read from EQ states):
  - Low EQ engaged → red dominant
  - Mid EQ engaged → pink/magenta
  - High EQ engaged → cyan
  - All EQs engaged equally → white
- Strobe rate scaled with detected energy

This is the **always-on baseline**. Even if the Phrase Engine never fires and the Transition Engine is dormant, the rig still pulses with the beat.

### 5.2 Phrase Engine

**Fires on 8 or 16 bar boundaries.** Rotates active scenes from a catalog.

Logic:

```
on_tick(snapshot):
    if snapshot.in_transition:
        return  # Transition Engine has priority

    if snapshot.loop_active:
        return  # don't rotate during a loop

    if bar_boundary_just_crossed(snapshot, 16):
        if time_since_last_rotation() >= MIN_BARS_BETWEEN_ROTATIONS:
            next_scene = pick_next_scene(snapshot)
            start_crossfade(active_scene, next_scene, duration_bars=2)
```

The scene catalog is a list of `Scene` objects, each of which knows how to render itself given a snapshot and a "intensity" envelope. See section 6.

Picking the next scene can be:
- Round-robin (simplest)
- Weighted by current energy bucket (low/mid/high → different scene pools)
- A simple Markov chain (each scene has likely successors)

Start with round-robin; upgrade later.

### 5.3 Transition Engine

**Active only when a transition is detected.** Takes precedence over the Phrase Engine.

Detection:
- Crossfader movement of >0.1 over 4 seconds, OR
- Both channel faders meaningfully above 0 while one is moving, OR
- `on_air_deck` changes

When active:
- Suspends the Phrase Engine (no rotations)
- Holds the current scene's color palette but boosts brightness ~20%
- When transition completes (crossfader stops moving for 4 bars, or on_air changes are settled), crossfade to a new scene synced to the next downbeat
- **Mandatory 4-bar hold** on the new scene before Phrase Engine resumes

The Transition Engine is the engine that most needs hardware testing because real DJ behavior is varied. Build it last and iterate against real sets.

---

## 6. Scenes

A `Scene` is a class that describes one coherent visual look. Each scene knows how to render itself, given the rig and current state, into the scene buffer.

```python
class Scene:
    name: str

    def render(self, rig: Rig, snapshot: ShowState, intensity: float,
               scene_buffer: SceneBuffer):
        """
        Write this scene's contribution to the scene buffer.
        intensity: 0.0–1.0 — used by crossfades during scene rotation
        """
        ...
```

**Aim for ~8–12 scenes** in the v1 catalog. Categories:

- **Breakdown scenes** (low energy): slow color cycles, single moving head sweep, low brightness, no strobes, no laser
- **Build scenes** (rising): accelerating wash, moving heads doing wider sweeps, increasing strobe rate
- **Drop scenes** (peak): full intensity, lasers active, hard beat hits, full color saturation
- **Holding scenes** (steady mid-set): comfortable mid-energy looks for sustained sections

Each scene is **frequency-color-respecting**: a "drop" scene that biases toward red because bass is dominant is correct; a "drop" scene that uses random colors is incorrect.

Scenes should be expressible in ~50–100 lines of Python each. They should not contain hardware-specific DMX byte math — they call into fixture profile helpers (`mh.set("dimmer", 200)`, `par.set_rgbw(255, 0, 60)`).

---

## 7. Output / merge layer

The merge layer combines scene buffer contributions into the final DMX universe.

### Combining rule

For each channel:
- For most channels (color, dimmer): **max** of contributions, then multiplied by ManualParams brightness cap.
- For movement channels (pan/tilt): **last-write-wins**, since you can't "add" pan positions meaningfully.
- For strobe: max contribution, unless ManualParams strobe cap is set, then min(max-contrib, cap).

### ManualParams

User-controllable biases from the UI:

```python
@dataclass
class ManualParams:
    master_brightness: float = 1.0         # 0.0–1.0 hard cap on all dimmers
    strobe_cap: float = 1.0                # 0.0–1.0 cap on strobe rates
    laser_enable: bool = True              # if False, lasers stay at off mode
    blackout: bool = False                 # if True, all channels → 0
    color_bias_warm_cold: float = 0.5      # 0.5 = neutral, < 0.5 = warmer, > 0.5 = cooler
    freeze: bool = False                   # if True, hold current DMX state
```

These are **caps and biases, not overrides.** The automatic system keeps producing; manual just shapes the output.

Exception: `blackout` and `freeze` are hard switches.

### Sequence per frame

```
1. Engines tick → scene buffer populated
2. Merge layer combines scene contributions per-channel
3. ManualParams applied
4. Blackout/Freeze checks
5. Write final values to DMX universe buffer
```

The DMX writer thread reads the universe buffer at its own 44 Hz rate and sends it to the Enttec.

---

## 8. UI (tkinter control panel)

A live operator console for Josh during sets. Read-mostly, with a few action buttons.

### Display panels

- **Now playing**: current BPM, beat counter, bar counter, on-air deck
- **Energy meter**: a bar visualization of detected energy 0–100%
- **Frequency strip**: low / mid / high level meters (driven from EQ readings)
- **Active scene**: name + small thumbnail/icon
- **Transition indicator**: lights up when Transition Engine is active

### Controls (ManualParams)

- Master brightness slider
- Strobe cap slider
- Laser enable toggle
- Color bias warm/cool slider
- Blackout button (large, red)
- Freeze button
- Skip scene button (forces a Phrase Engine rotation now)

### Keyboard shortcuts

- `B` — toggle blackout
- `F` — toggle freeze
- `Space` — strobe burst (200ms full strobe then release)
- `→` — skip to next scene
- `T` — tap tempo (overrides PDL BPM, for emergency)

### Known tkinter caveats

- **Python 3.14 + tkinter Canvas**: drawing on a Canvas during widget creation can crash. Use `widget.after(50, draw_fn)` to defer the first draw until after the event loop starts.
- **Attribute name collisions**: tkinter widgets reserve names like `_w`, `_name`, `_root`, etc. Don't use those for your own attributes. (We hit this in v2 Phase 1 with `_w` for "width" — renamed to `_width`.)

---

## 9. Demo mode

The application launches in demo mode whenever:
- No Enttec is detected on any serial port, OR
- No XDJ-XZ MIDI device is detected, OR
- Pro DJ Link doesn't see any broadcasts within 5 seconds, OR
- Explicit `--demo` flag is passed

In demo mode:
- DMX writer writes to `/dev/null` or a log file instead of a serial port
- DemoDataGenerator drives ShowState with synthetic data
- The UI shows a `[DEMO MODE]` banner in the title bar

Demo mode is **the development default** — the dev should be able to clone the repo, run `python run.py --demo`, and see the UI render with simulated beats.

---

## 10. Project layout (suggested)

```
livereact/
├── run.py                       # entry point: parse args, wire up, start
├── version.py
├── requirements.txt
├── rigs/
│   └── full_show.json
│
├── core/
│   ├── show_state.py            # ShowState dataclass + lock
│   ├── show_engine.py           # main tick loop, instantiates engines
│   ├── reactive_layer.py        # Reactive Layer Engine
│   ├── phrase_engine.py         # Phrase Engine
│   ├── transition_engine.py     # Transition Engine
│   ├── merge.py                 # scene buffer → DMX universe
│   ├── manual_params.py         # ManualParams dataclass
│   ├── metronome.py             # local interpolated beat clock
│   ├── fixture.py               # base Fixture class
│   └── rig.py                   # rig loader
│
├── audio/                       # named "audio" for historical reasons; really "input"
│   ├── prodj_link.py            # ProDJLinkListener
│   ├── midi_input.py            # MidiInputListener
│   └── demo_data.py             # DemoDataGenerator
│
├── dmx/
│   └── enttec.py                # Enttec USB Pro driver
│
├── fixtures/
│   ├── registry.py
│   ├── rgbw_par.py
│   ├── shehds_180w.py
│   ├── shehds_laser_12ch.py
│   └── ok103_wash_bar_6ch.py
│
├── scenes/
│   ├── base.py                  # Scene base class
│   ├── catalog.py               # scene registry
│   ├── breakdown_scenes.py
│   ├── build_scenes.py
│   ├── drop_scenes.py
│   └── hold_scenes.py
│
└── ui/
    └── control_panel.py
```

The layer naming (`core`, `audio`, `dmx`, `fixtures`, `scenes`, `ui`) is what v2 Phase 1 used. Stick with it for continuity with the reference code, but feel free to refactor naming if something cleaner emerges.

---

## 11. What gets persisted

Nothing, in v1. LiveReact is stateless across runs. Rig file is loaded fresh; ManualParams reset to defaults. If you want preset profiles ("club mode," "bedroom mode"), that's a v2 feature.

---

Next: **`04_DESIGN_PRINCIPLES.md`** — the locked decisions and the v1 → v2 story in depth.
