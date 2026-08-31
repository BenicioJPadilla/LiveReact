# 12 — Rebuild Roadmap

A phased, **demo-first, macOS-first (portable)** plan from empty repo to show-ready. Adapted from the spec's `05_BUILD_PLAN.md`, re-ordered to maximize hardware-free progress and to reflect the stack/architecture decisions in this analysis. Per the platform decision ([07](07_CROSSPLATFORM_STRATEGY.md)), macOS is the target/test/sign platform; the code stays OS-agnostic (so Phases 0–6 can be built on Windows in the interim before the Mac arrives). Each phase has an **acceptance check** — the bar for "done, move on."

> **Sequencing principle:** finish *everything* that doesn't need hardware before the hardware phase, so an uncertain/limited hardware window is spent only on genuine hardware unknowns. Phases 0–6 need **no hardware**. ([11 §5](11_RECOMMENDED_APPROACH.md))

> **No calendar estimates.** The spec's "2.5 weeks" assumed full-time work + guaranteed hardware. You have neither confirmed. Plan by phase completion, not dates. ([10 C3](10_OPEN_QUESTIONS_AND_ASSUMPTIONS.md))

---

## Phase 0 — Foundation
**Goal:** repo, env, the spine of the system running on an injected clock with the writer never stopping.
1. Git repo; `pyproject.toml`/`requirements.txt` pinned to **Python 3.12**: `pyserial`, `mido`, `python-rtmidi`, `PySide6`, `pyartnet` (or `sacn`), `python-prodj-link` (vendored/pinned), `psutil`/`netifaces2`. Dev: `pytest`.
2. `Clock` interface (`RealClock`/`FakeClock`); `steady_loop` with drift correction + spin tail.
3. `DmxFrameBuffer` (double-buffered publish/consume); `OutputBackend` interface + `NullLogBackend`.
4. `DmxWriter` thread: reads published frame → (null) output at 40 Hz, catches all exceptions, keep-last-frame.
5. Supervisor: `threading.Event` stop, SIGINT + clean joins. Cross-platform launcher scripts (`run.command` + `run.bat`).

**Acceptance:** `run --demo` starts all threads on a `RealClock`, the null writer logs steady ~40 Hz frames, Ctrl-C shuts everything down cleanly; a `FakeClock` unit test drives the writer deterministically. Runs identically on Windows and macOS.

---

## Phase 1 — Demo musical clock + state bus
**Goal:** synthetic "music" producing smooth beat phase, no hardware.
1. `ShowState` with immutable `snapshot()` (one lock, frozen dataclass), provenance/confidence annotations per field.
2. `queue.Queue` message types (beat, bpm, midi-cc, transition).
3. `Metronome` (sole writer of clock fields): drains queue, advances/interpolates beat phase, resyncs to beat messages, infers bar count, free-runs on staleness.
4. `DemoDataSource` implementing `InputSource`: fixed BPM (default 124), advancing beat/bar, a slow energy curve, periodic synthetic transitions/loops; pushes the same messages a real listener would.

**Acceptance:** in demo mode, logs show a smooth interpolated beat phase at ~100 Hz, an advancing bar counter, and periodic synthetic transitions; snapshots are tear-free under a concurrency stress test.

---

## Phase 2 — Fixtures, rig, merge, virtual visualizer
**Goal:** *see* the universe on screen.
1. `Fixture` base + profiles (MH 15ch, laser 12ch, par 4ch, wash bar 6ch) from [04 §3](04_HARDWARE_AND_PROTOCOLS.md); named accessors, 16-bit pair handling.
2. `Rig` loader (JSON rig file); expose fixtures by role/side.
3. `merge` layer: per-channel max (color/dimmer), last-write-wins (movement), strobe cap, ManualParams caps/biases, blackout/freeze, **safety clamps (laser off unless explicitly enabled, strobe rate cap)**.
4. **PySide6 virtual rig visualizer** (`QGraphicsView`): draw 8 fixtures, color/brightness/position from the live universe at ~30 Hz. Plus a raw **DMX inspector** (per-channel values).

**Acceptance:** with a hand-set scene buffer, the visualizer and inspector show the correct universe; moving the (stub) master-brightness control scales all dimmers; blackout zeros output; laser channels can't be non-zero unless explicitly enabled.

---

## Phase 3 — Reactive Layer
**Goal:** the first "it's alive" moment — beat-locked, frequency-colored output on the virtual rig.
1. `ReactiveLayerEngine.tick(snapshot, scene_buffer)`: per-beat dimmer pulse on washes (rise on beat, ~200 ms decay), BPM-locked MH pan/tilt from `metronome.current_phase()`, **two-axis color** (energy→brightness/saturation, band→hue) from EQ state, energy-scaled strobe (capped).
2. Show engine wires snapshot → reactive → merge → publish, with per-engine try/except.

**Acceptance:** demo visualizer shows washes pulsing on each beat, MHs cycling smoothly, color reflecting synthetic EQ; an injected-clock test asserts a pulse fires once per beat and color follows band dominance.

---

## Phase 4 — Scene catalog + Phrase Engine
**Goal:** a rotating, crossfading show.
1. `Scene` base (`render(rig, snapshot, intensity, scene_buffer)`); implement ~8 of the 12 starter scenes ([08 §3](08_LIGHTING_DESIGN_AND_SAFETY.md)) across breakdown/build/drop/hold.
2. `SceneCatalog` (round-robin within energy bucket); **lasers only in drop scenes**.
3. `PhraseEngine.tick`: detect inferred bar boundaries (8/16), crossfade over ~2 bars, min 4-bar hold, suspend on `in_transition`/`loop_active`.
4. UI: scene-override dropdown; force-scene for testing.

**Acceptance:** scenes rotate every 16 inferred bars with smooth crossfades on the visualizer; each scene is visibly distinct; lasers active only in drop scenes; forcing transition/loop flags suspends rotation; all scenes respect the color rule. Unit tests: boundary fires once, not repeatedly.

---

## Phase 5 — Operator console + manual control + safety
**Goal:** the full UI and the "automation is default, manual is bias" model.
1. PySide6 console: BPM/beat/bar, on-air deck, energy meter, frequency strip, active scene, transition + input-staleness indicators.
2. ManualParams: master brightness, strobe cap, laser enable, warm/cool bias, blackout, freeze, skip-scene; keyboard shortcuts (B/F/Space/→/T tap-tempo).
3. Confirm safety clamps in merge: strobe cap on every path; laser fail-safe; instant blackout.
4. Optional `config.json` persistence (brightness, selected rig, scene tuning).

**Acceptance:** full console runs the demo show for 60 min unattended on the visualizer with no leak/artifact; manual controls cap/bias output without stopping automation; blackout/freeze/skip work; tap-tempo overrides BPM when triggered.

---

## Phase 6 — Transition Engine
**Goal:** clean DJ-mix handling, built against synthetic transitions first.
1. `TransitionEngine.tick`: rolling crossfader window detection (+ fader + PDL on-air), set `in_transition`, hold scene + ~20% brightness, crossfade to a new scene on the next downbeat, mandatory ≥4-bar hold.
2. Demo source drives varied synthetic transitions to exercise it.

**Acceptance:** synthetic crossfader move flips the transition indicator within ~200 ms; no rotation during a transition even past 16 bars; settles into a new scene cleanly with no flicker/blackout; ≥4-bar hold enforced. Deterministic tests via FakeClock + injected crossfader messages.

---

## Phase 7 — Hardware integration *(requires rig; the only hardware-gated phase)*
**Goal:** swap demo adapters for real ones — no engine/scene changes.
1. `EnttecSerialBackend`: detect by FTDI VID/PID, macOS `cu.*` node, 518-byte frames at 40 Hz, self-healing reopen.
2. **Manual fixture-test panel**: drive individual channels; verify each of the 8 fixtures one at a time.
3. `ProDjLinkListener` (hardened: explicit interface override, netifaces swap) + `MidiListener`; **MIDI-learn tool** to remap the XDJ empirically and persist it.
4. Cross-platform networking setup: static `169.254.x.y/16`, firewall rule, "no DJ-Link seen" diagnostic.
5. End-to-end: real XDJ playing → lights react.

**Acceptance:** each fixture responds correctly to manual writes; lights pulse on real XDJ beats (not the demo clock); crossfader updates the UI in real time; a full scene-rotation cycle works on hardware — on the **macOS** show machine (code kept portable for a future Windows build). ([07](07_CROSSPLATFORM_STRATEGY.md))

---

## Phase 8 — Tuning, endurance, packaging
**Goal:** make it good and shippable.
1. **Tune against real sets** (when hardware available): beat-lock, color fit, crossfade duration, strobe intensity, scene distinctiveness, transition feel; add 2–4 scenes if thin.
2. **Endurance:** 90-min soak — no leak, no orphan threads, no artifacts; exercise every failure mode (PDL drop, MIDI unplug, serial fail, long loop, hard cut).
3. **Package:** PyInstaller `--onedir` → signed + notarized macOS `.app`; test the bundle on a clean Mac. (Windows `.exe`/signing deferred unless revived.) Minimal README (install, run, demo, hardware bring-up, network setup).

**Acceptance:** a 90-min unattended set with only occasional brightness nudges; graceful degradation verified on every documented failure; the DMX writer never stops; a signed, notarized double-click `.app` runs on a clean Mac.

---

## Hardware-gating summary

| Phase | Needs hardware? |
|---|---|
| 0 Foundation | ❌ |
| 1 Demo clock + state | ❌ |
| 2 Fixtures + visualizer | ❌ |
| 3 Reactive Layer | ❌ |
| 4 Scenes + Phrase Engine | ❌ |
| 5 Console + manual + safety | ❌ |
| 6 Transition Engine | ❌ |
| 7 Hardware integration | ✅ (the only one) |
| 8 Tuning + endurance | ⚠️ tuning needs it; endurance/packaging partly without |

If hardware never materializes, Phases 0–6 still yield a complete, demonstrable, visualizer-driven application — which is a strong portfolio artifact in its own right and the entire point of "demo mode is the substrate."

---

## Definition of done (rebuild)
All acceptance criteria in [02 §6](02_GOAL_AND_REQUIREMENTS.md) met: PDL+MIDI input, 74-channel DMX output (Enttec or Art-Net), ≥8 rotating scenes, transition handling, 90-min unattended endurance, full demo mode, **macOS (portable codebase)**, graceful degradation with a writer that never stops, and verified laser/strobe safety.
