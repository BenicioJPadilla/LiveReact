# LiveReact — Build Plan & Status

The working checklist for the rebuild, derived from
[`docs/12_REBUILD_ROADMAP.md`](docs/12_REBUILD_ROADMAP.md). **Demo-first**: Phases
0–6 need no hardware; Phase 7 is the only hardware-gated phase. No calendar dates —
plan by phase completion. Each phase lists its **acceptance check** (the bar for
"done, move on").

Legend: `[x]` done · `[~]` in progress · `[ ]` not started

---

## Phase 0 — Foundation `[x]`
The spine: threads alive, frames flowing, writer never stops, all on an injected clock.

- [x] Git repo + `pyproject.toml` (Python 3.12 venv) + `.gitignore`
- [x] `Clock` interface, `RealClock` (hybrid sleep + spin tail), `FakeClock`
- [x] `LoopTimer` — drift-corrected fixed-rate scheduler with stall resync
- [x] `DmxFrameBuffer` — double-buffered publish/consume (keep-last-frame)
- [x] `OutputBackend` interface + `NullLogBackend`
- [x] `DmxWriter` thread — reads published frame, writes at 40 Hz, survives all faults
- [x] `App` supervisor — `threading.Event` stop, SIGINT/SIGTERM, clean joins
- [x] CLI entry point (`python -m livereact --demo`) + `run.bat` / `run.command`
- [x] pytest: clock/loop-timer, frame buffer, writer (deterministic via FakeClock)
- [x] **Acceptance:** `run --demo` starts threads on a RealClock, null writer logs
      steady ~40 Hz frames, Ctrl-C shuts down cleanly; FakeClock test drives the
      writer deterministically. ✅ *Verified: 40 fps steady, clean shutdown, 15 tests pass.*

## Phase 1 — Demo musical clock + state bus `[x]`
Synthetic "music" producing smooth beat phase; no hardware.

- [x] `ShowState` as a single-slot publisher of an immutable `ShowSnapshot`
      (atomic swap → tear-free); per-field provenance documented (measured /
      interpolated / inferred); track-position intentionally absent. (docs/04 §4.3)
- [x] `queue` message types: beat, status, midi-cc, transition (frozen, timestamped)
- [x] `Metronome` — sole writer; drains queue, interpolates beat phase, re-anchors
      to master beats, infers bar from downbeats, free-runs on staleness, derives
      smoothed energy; periodic ShowState log line
- [x] `DemoDataSource` (`InputSource`) — steady BPM, advancing beat/bar, slow energy
      curve via fader/EQ MIDI, periodic transitions (crossfader sweep + deck handoff) and loops
- [x] Wired into `App` (source → queue → metronome → ShowState) alongside the writer
- [x] **Acceptance:** demo logs show smooth ~100 Hz interpolated beat phase, an
      advancing bar counter, periodic transitions; snapshots tear-free under stress.
      ✅ *Verified: live log shows locked clock + advancing bars; 12 new tests incl. a
      4-reader tear-free stress test; transitions/handoff covered.*

## Phase 2 — Fixtures, rig, merge, virtual visualizer `[x]`
*See* the universe on screen.

- [x] `Fixture` base + profiles (MH 15ch, laser 12ch, par 4ch, wash bar 6ch) — docs/04 §3
- [x] `Rig` loader (JSON rig file, packaged `default_rig.json`); fixtures by role/side; overlap/overflow validation
- [x] `merge` layer: max (color/dimmer), last-write (movement), strobe cap, manual
      caps/biases, blackout, **safety clamps** (laser off unless enabled, strobe cap).
      *(freeze deferred to the show engine in Phase 3; warm/cool bias to Phase 5)*
- [x] PySide6 virtual rig visualizer (`QGraphicsView`, beam lines for MHs) + raw DMX inspector
- [x] Standalone demo: `python -m livereact.ui.visualizer` (animated hand-set scene)
- [x] **Acceptance:** hand-set scene buffer shows correct universe in viz/inspector;
      master-brightness scales dimmers; blackout zeros output; laser can't be nonzero
      unless explicitly enabled. ✅ *Verified: 40 tests pass + offscreen render confirmed
      (lasers on only in drop window, color/brightness/beams correct).*

## Phase 3 — Reactive Layer `[x]`
First "it's alive": beat-locked, frequency-colored output on the virtual rig.

- [x] Two-axis color model (`color.py` + `engines/color.py`): energy→brightness/sat,
      band-dominance→hue (bass red / mid magenta / high cyan; balanced→white)
- [x] `Engine` interface (`engines/base.py`): read snapshot, return a Contribution
- [x] `ReactiveLayerEngine.tick` — per-beat wash pulse (exp ~200 ms decay), BPM-locked
      mirrored MH pan/tilt, two-axis color, energy-gated conservatively-capped strobe
- [x] `ShowEngine` (60 Hz): snapshot → engines → merge → finalize → publish, with
      **per-engine try/except** (faulty engine keeps last contribution) and **freeze**
      = don't publish (writer holds last frame)
- [x] Wired into `App`; `--visualize` flag opens the live rig view
- [x] **Acceptance:** washes pulse each beat, MHs cycle smoothly, color reflects
      synthetic EQ; injected-clock test asserts one pulse per beat + color follows band.
      ✅ *Verified: 15 new tests; live demo shows 24 active channels; offscreen render
      confirms cyan (highs up), MH movement, lasers off.*

## Phase 4 — Scene catalog + Phrase Engine `[x]`
A rotating, crossfading show.

- [x] `Scene` base + energy buckets + 8 starter scenes (docs/08 §3) across
      breakdown/build/drop/hold (`scenes/base.py`, `scenes/library.py`)
- [x] `SceneCatalog` (round-robin within energy bucket, energy→bucket thresholds);
      **only drop scenes touch laser channels**
- [x] `PhraseEngine.tick` — bar-boundary rotation every 16 bars (fires once, not per
      tick), ~2-bar weighted crossfade (movement/laser switch at midpoint), ≥4-bar
      hold, suspend on transition/loop; `skip()`/`force_scene()` hooks
- [x] Active scene name shown in the visualizer title (dropdown deferred to Phase 5 console)
- [x] Demo arms lasers (operator-arm simulation) so drop scenes fire them on screen
- [x] **Acceptance:** scenes rotate every 16 inferred bars with smooth crossfades;
      each scene distinct; lasers only in drops; transition/loop suspends rotation;
      boundary fires once (unit test). ✅ *Verified: 13 new tests; live log shows
      rotation; forced drop fires lasers through the full pipeline (CH1=60, 34 active).*

## Phase 5 — Operator console + manual control + safety `[x]`
The full UI and the "automation is default, manual is bias" model.
✅ *Done & verified: 14 new tests; offscreen console render confirmed; controls drive
ManualParams; tap-tempo injects beats; config.json round-trips. 60-min soak → Phase 8.*

- [x] PySide6 console: BPM/beat/bar, on-air deck, energy meter, frequency strip,
      active scene, transition + input-staleness indicators
- [x] ManualParams: master brightness, strobe cap, laser enable, warm/cool bias,
      blackout, freeze, skip-scene + keyboard shortcuts (B/F/Space/→/T tap-tempo)
- [x] Confirm safety clamps in merge on every path; instant blackout
- [x] Optional `config.json` persistence (brightness, rig, scene tuning)
- [x] **Acceptance:** full console runs the demo 60 min unattended, no leak/artifact;
      manual controls cap/bias without stopping automation; blackout/freeze/skip work.

## Phase 6 — Transition Engine `[x]`
Clean DJ-mix handling, built against synthetic transitions first.

- [x] `TransitionEngine.tick` — crossfader/fader/on-air detection → `in_transition`,
      hold + ~20% brightness, crossfade on next downbeat, mandatory ≥4-bar hold
- [x] Demo source drives varied synthetic transitions
- [x] **Acceptance:** synthetic crossfader move flips indicator within ~200 ms; no
      rotation during transition; settles cleanly; ≥4-bar hold; deterministic FakeClock tests.
      ✅ *Verified: 99 tests; live demo detects transition=Y from the crossfader and settles into a new scene right after.*

## Phase 7 — Hardware integration `[~]` *(built "ready but UNTESTED"; acceptance awaits the rig)*
Real adapters written behind the existing interfaces; hardware mode degrades
gracefully when no devices are present. See [`HARDWARE.md`](HARDWARE.md) for bring-up.

- [x] Hardware deps install on **Python 3.12** (`pyserial`, `mido`, `python-rtmidi`)
- [x] `EnttecSerialBackend` (`output/enttec.py`) — FTDI VID/PID detect, macOS `cu.*`,
      518-byte frames, self-healing via the writer. *(frame + port select unit-tested)*
- [x] Manual fixture-test panel (`ui/fixture_test.py`) — per-channel sliders + flash,
      `--fixture-test`
- [x] `ProDjLinkListener` (`inputs/prodj.py`, explicit interface override, "no DJ-Link
      seen" diagnostic) + `MidiListener` (`inputs/midi.py`, read-only). *(lazy-imported)*
- [x] MIDI-learn via `--midi-monitor`; CC map persists to `midi_map.json` (`inputs/midi_map.py`)
- [x] Network helper + `--net-check` (static `169.254.x.y/16` guidance, firewall ports)
- [x] `--hardware` wires real backend + inputs with graceful fallback (verified: no
      devices → null backend, inputs skipped, clean run/shutdown)
- [ ] **Acceptance (NEEDS HARDWARE):** each fixture responds to manual writes; lights
      pulse on real XDJ beats; crossfader updates UI live; full scene rotation on the
      macOS show machine. ⏳ *Awaiting the rig; everything testable without it is unit-tested.*

## Phase 8 — Tuning, endurance, packaging `[ ]`
Make it good and shippable.

- [ ] Tune against real sets (beat-lock, color, crossfade, strobe, scene distinctiveness)
- [ ] 90-min endurance soak; exercise every failure mode (PDL drop, MIDI unplug, serial fail, loop, hard cut)
- [ ] Package: PyInstaller `--onedir` → signed + notarized macOS `.app`; test on clean Mac
- [ ] **Acceptance:** 90-min unattended set, graceful degradation on every failure,
      writer never stops, signed `.app` runs on a clean Mac.

---

## Definition of done (whole rebuild)
All of [`docs/02 §6`](docs/02_GOAL_AND_REQUIREMENTS.md): PDL+MIDI input, 74-channel
DMX output (Enttec or Art-Net), ≥8 rotating scenes, transition handling, 90-min
unattended endurance, full demo mode, macOS (portable codebase), graceful
degradation with a writer that never stops, verified laser/strobe safety.

> **If hardware never materializes**, Phases 0–6 still yield a complete,
> demonstrable, visualizer-driven application — the whole point of "demo mode is
> the substrate."
