# LiveReact

A beat-reactive DMX stage-lighting controller for live DJ sets. It reads musical
timing from a Pioneer XDJ-XZ (Pro DJ Link over Ethernet + USB MIDI) and
automatically drives an 8-fixture / 74-channel DMX rig through an Enttec DMX USB
Pro at ~40 Hz. **Automation is the default**; a human only nudges
brightness / strobe-cap / blackout.

This is a clean-room rebuild from the design analysis in [`docs/`](docs/). Start
with [`docs/00_EXECUTIVE_SUMMARY.md`](docs/00_EXECUTIVE_SUMMARY.md), then read the
[rebuild roadmap](docs/12_REBUILD_ROADMAP.md). Build status and the working plan
live in [`PLAN.md`](PLAN.md); deferred hardware/usage decisions live in
[`ASSUMPTIONS.md`](ASSUMPTIONS.md).

## Status

**Phases 0–6 complete; Phase 7 hardware layer built ("ready but untested").** The
full show runs hardware-free (synthetic clock → ShowState → Reactive + Phrase +
Transition engines → merge/safety → DMX writer, in an operator console). The
hardware adapters — Enttec serial output, Pro DJ Link + read-only MIDI input, the
fixture-test panel, MIDI-learn, and network diagnostics — are written behind the
existing interfaces and unit-tested for everything that doesn't need a device;
`--hardware` degrades gracefully when none are present. The real serial/MIDI/PDL
paths await the physical rig — see [`HARDWARE.md`](HARDWARE.md). **Phase 8 (tuning,
endurance, packaging)** is the last step. See [`PLAN.md`](PLAN.md).

```bash
python -m livereact --hardware --visualize   # real devices (auto-detect, graceful fallback)
python -m livereact --fixture-test           # drive raw DMX channels for bring-up
python -m livereact --midi-monitor           # discover the XDJ's MIDI CCs
python -m livereact --net-check              # Pro DJ Link network readiness
python -m livereact --doctor                 # environment + detected-devices report
```

**Testing on hardware?** Follow [`TESTING.md`](TESTING.md) — the exact test
procedure plus a recording system (`--record`, `--doctor`) that captures logs,
state, and your notes into a session folder you can hand back for analysis.

Watch it live (the full pipeline driving the rig view):

```bash
.venv\Scripts\python -m livereact --demo --visualize     # Windows
.venv/bin/python -m livereact --demo --visualize         # macOS / Linux
```

## Quick start

This repo targets **Python 3.12** (the analysis pins it for prebuilt
`python-rtmidi` wheels at the hardware-MIDI phase), which is what the dev venv uses.

```bash
# Windows (PowerShell)
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m livereact --demo --duration 3   # short demo run
.venv\Scripts\python -m pytest                          # run the test suite

# macOS / Linux
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m livereact --demo --duration 3
.venv/bin/python -m pytest
```

Or use the dev launchers: `run.bat` (Windows) / `./run.command` (macOS).

## Layout

```
src/livereact/
  clock.py            Clock / RealClock / FakeClock + drift-corrected LoopTimer   [Phase 0]
  app.py              Supervisor: wires components, owns lifecycle + shutdown      [Phase 0]
  __main__.py         CLI entry point (python -m livereact)                        [Phase 0]
  core/               frame_buffer (Phase 0); ShowState, Metronome (Phase 1); show engine (Phase 3)
  output/             backend interface + null/log + writer (Phase 0); Enttec/Art-Net (Phase 7)
  inputs/             InputSource interface; DemoDataSource (Phase 1); PDL/MIDI (Phase 7)
  engines/            ReactiveLayer / Phrase / Transition (Phases 3-6)
  scenes/             scene catalog (Phase 4)
  merge/              per-channel merge + manual caps + safety clamps (Phase 2)
  fixtures/           fixture profiles + rig loader (Phase 2)
  ui/                 PySide6 console + virtual rig visualizer (Phases 2, 5, 7)
tests/                pytest suite (deterministic via FakeClock)
```

## Design notes baked into the foundation

- **Injected clock everywhere** — real-time logic is unit-testable; a 90-min show
  simulates in milliseconds. (docs/05 §5.2)
- **Double-buffered DMX** — the writer always emits the last *complete* frame, so
  an engine stall holds the lights steady instead of flickering. (docs/05 §5.1)
- **The writer never stops** — every backend fault is contained; it reopens with
  backoff and keeps ticking. (NFR-5)
- **Output behind an interface** — null/log now; Enttec serial + Art-Net later,
  swapped without touching engine code. (docs/05 §5.5)
```
