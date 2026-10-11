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

**Which rig, which show?** `--rig rigs/<file>.json` picks the fixtures AND the
laser profile: `rigs/testing_setup.json` (the garage truss rig, `laser_profile:
trigger` — the lasers are punctuation: dark by default, 2-bar moments on the
drop hit / each 8-bar block of a sustained peak / a big low-end hit, spaced 8
bars apart and capped at 10 % of any 2 minutes, plus **J** = one moment now and
**K** = hold; `engines/laser_trigger.py`), `rigs/josh_rig.json` (the old home
layout, `laser_profile: accent` — one sweep per 8-bar block in a peak) or
`rigs/bar_rig.json` (the bar residency, `laser_profile: feature` — two lasers as
the main light, lit for the whole set; `engines/laser_feature.py`, TESTING.md
Test 6). After a drop the moving heads run `scenes/movement.py`'s tempo-locked
shapes around the calibrated crowd aim (Venue tab, TESTING.md Test 5).

Watch it live (the full pipeline driving the rig view):

```bash
.venv\Scripts\python -m livereact --demo --visualize     # Windows
.venv/bin/python -m livereact --demo --visualize         # macOS / Linux

# 2026-10-08: Python 3.14.3's garbage collector segfaulted three times inside the
# show-engine thread (crash reports Python-2026-10-05-232007, -10-08-152952,
# -10-08-160540: SIGSEGV in mark_stacks < _PyGC_Collect). A Python 3.13 venv lives
# at .venv313 (`uv python install 3.13 && uv venv .venv313 --python 3.13 &&
# uv pip install --python .venv313/bin/python -e ".[ui,hardware,dev]" netifaces`).
# For a live night use the relaunch loop, which prefers .venv313 and restarts
# after a crash (closing the window, or `touch logs/STOP`, ends it):
nohup tools/run_show.sh --hardware --visualize --record --rig rigs/sophias_thai.json > logs/watchdog.log 2>&1 & disown
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

## Lighting spec & look library

The actual *content* of the show — what look plays for a given energy state,
what colors/movement it uses, when it degrades — is driven by
[`spec/LIGHTING_BIBLE.md`](spec/LIGHTING_BIBLE.md), a normative lighting-design
spec, with [`spec/conformance.md`](spec/conformance.md) tracking implementation
status rule-by-rule. This is a separate, later integration effort layered on
top of the phases above (tracked as its own "Bible-integration" phase series in
[`docs/bible_integration/`](docs/bible_integration/) and the working plan, not
renumbered into Phases 0–8) — see `docs/bible_integration/RULES_MATRIX.md` for
the current status and `docs/bible_integration/LOOK_CATALOG.md` for the full
30-look catalog this project targets. As of this writing, 29 scenes span every
energy bucket (BREAK/BUILD/DROP/PEAK/OUTRO) in
[`src/livereact/scenes/library.py`](src/livereact/scenes/library.py); a small
number of Bible-named looks are deliberately deferred (documented in-code and
in the rules matrix, not silently skipped) pending either new detection
infrastructure (`build_snare_accent`) or hardware this rig doesn't have (a
gobo wheel, a second moving head, haze/fog).

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
