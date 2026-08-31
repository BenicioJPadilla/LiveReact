# 05 — Build Plan

A phased roadmap from empty repo to a system that can run a live DJ set. **Total budget: 2.5 weeks.** The plan is risk-ordered: foundation first, dependencies before consumers, hardware-dependent work clustered into the 2-week hardware-access window.

Each phase has an explicit **acceptance check** — when this is true, the phase is done and you move on. Don't polish past the check; come back later if needed.

---

## Phase 0 — Setup (Day 1, morning)

**Goal:** Repo, Python env, dependencies installed, can run a `hello world` script.

Tasks:
1. Initialize a git repo at `livereact/`.
2. Create `requirements.txt` with: `numpy`, `scipy`, `pyserial`, `python-prodj-link`, `mido` (or `python-rtmidi`).
3. Create `run.py` that just prints "LiveReact v2 starting" and exits.
4. Set up `.gitignore` (`__pycache__/`, `.venv/`, `*.pyc`, `.DS_Store`).
5. Create empty package directories: `core/`, `audio/`, `dmx/`, `fixtures/`, `scenes/`, `ui/`, `rigs/`.

**Acceptance:** `python run.py` prints the message and exits cleanly on a fresh `venv` with `pip install -r requirements.txt`.

---

## Phase 1 — Demo-mode foundation (Days 1–2)

**Goal:** Skeleton system runs end-to-end with simulated data, no hardware needed. Empty scene buffer, empty DMX universe, zero output — but every thread is alive and every module is wired up.

Build, in order:

1. **`core/show_state.py`** — `ShowState` dataclass with all fields from `03_ARCHITECTURE.md` section 3. Include lock and `snapshot()` method.
2. **`core/manual_params.py`** — `ManualParams` dataclass with defaults from architecture doc.
3. **`audio/demo_data.py`** — `DemoDataGenerator` thread that writes a fixed BPM clock and synthetic beat/bar progression into ShowState.
4. **`core/metronome.py`** — `LocalMetronome` that resyncs to demo beats and exposes `current_phase()`.
5. **`dmx/enttec.py`** — `EnttecDriver` class with a `NullDriver` fallback. The null driver just logs writes instead of opening a serial port.
6. **`fixtures/registry.py`** + base **`core/fixture.py`** — Fixture base class with `get(channel_name)`, `set(channel_name, value)`, and DMX index resolution.
7. **`fixtures/rgbw_par.py`**, **`fixtures/shehds_180w.py`**, **`fixtures/shehds_laser_12ch.py`**, **`fixtures/ok103_wash_bar_6ch.py`** — Profile classes (channel data is in `02_HARDWARE_RIG.md`).
8. **`core/rig.py`** — `Rig` loader that reads `rigs/full_show.json` and instantiates fixtures.
9. **`core/show_engine.py`** — Main tick loop at 60 Hz. Reads ShowState, runs (empty for now) engines, writes a (still-zero) universe to the DMX driver.
10. **`run.py`** — Wires up all of the above. Parses `--demo` flag, detects hardware (or doesn't), starts threads.

**Acceptance:**
- `python run.py --demo` runs without errors.
- Logs show the demo BPM clock advancing.
- The (null) DMX writer logs frames being sent at ~44 Hz.
- Ctrl-C cleanly shuts down all threads.

---

## Phase 2 — UI shell (Day 2)

**Goal:** A visible tkinter window showing the demo data live.

Tasks:
1. **`ui/control_panel.py`** — Window with placeholder panels: BPM display, beat counter, energy meter (driven by a synthetic energy curve in the demo), active-scene name, ManualParams sliders, blackout/freeze buttons.
2. Wire the UI to read ShowState at 30 Hz and update display.
3. Hook ManualParams sliders to update the live ManualParams object (which the merge layer will read later).
4. Implement keyboard shortcuts (B, F, Space, →, T).

**Acceptance:**
- Window opens, shows the BPM ticking up and beat counter advancing in real time.
- Moving the master brightness slider updates the in-memory ManualParams value (visible via a log line).
- `B` key toggles a "BLACKOUT" indicator on the UI.
- Closing the window cleanly shuts down the app.

Phase 1 + 2 together = **"runnable demo mode"**, the goal Josh wants achievable in the first 2–3 days.

---

## Phase 3 — Reactive Layer Engine (Days 3–4)

**Goal:** Beat-locked light output happening in demo mode, visible in a fixture state inspector (and on real hardware in Phase 6).

Tasks:
1. **`core/reactive_layer.py`** — Implement `ReactiveLayerEngine.tick(snapshot, scene_buffer)`.
2. Per-beat dimmer pulse on washes (envelope: rise on beat, decay over 200 ms).
3. Pan/tilt motion on moving heads driven by `metronome.current_phase()` (e.g., sine sweep with 4-beat cycle).
4. Color values from current EQ state (read from ShowState; demo mode can drive EQ values with a slow oscillator).
5. **`core/merge.py`** — Build the scene buffer → DMX universe merge function with the per-channel rules from `03_ARCHITECTURE.md` section 7.
6. **UI addition:** A "DMX Inspector" panel showing the current value of each channel of each fixture, updated at 10 Hz. Critical for development without hardware.

**Acceptance:**
- In demo mode, the DMX inspector shows the wash fixtures' dimmer channels pulsing on each beat.
- The moving heads' pan/tilt channels are smoothly cycling.
- Color channels reflect the synthetic EQ state.
- Master brightness slider in the UI scales all dimmer output.

---

## Phase 4 — Scene catalog (Days 4–5)

**Goal:** 6–10 scenes implemented, each rendering correctly when "selected."

Tasks:
1. **`scenes/base.py`** — `Scene` base class with `render(rig, snapshot, intensity, scene_buffer)`.
2. **`scenes/breakdown_scenes.py`** — at least 2 low-energy scenes (slow color cycle, single MH sweep).
3. **`scenes/build_scenes.py`** — at least 2 rising-energy scenes (accelerating wash, MH wider sweeps).
4. **`scenes/drop_scenes.py`** — at least 2 peak scenes (full intensity, lasers active, hard beat hits).
5. **`scenes/hold_scenes.py`** — at least 2 mid-energy "comfortable" scenes for sustained sections.
6. **`scenes/catalog.py`** — `SceneCatalog` class that lists all scenes and can pick the next one (round-robin to start).
7. **UI addition:** Force a specific scene from a dropdown ("Scene override") for testing.

**Acceptance:**
- Each scene can be force-selected from the UI dropdown.
- Each scene renders something visibly distinct in the DMX inspector.
- Lasers activate **only** in drop scenes; in all others, laser CH1 stays at 0.
- All scenes respect the frequency-color rule (per `04_DESIGN_PRINCIPLES.md` section 1).

---

## Phase 5 — Phrase Engine (Days 5–6)

**Goal:** Scene rotation on 8/16-bar boundaries, with crossfade between scenes.

Tasks:
1. **`core/phrase_engine.py`** — `PhraseEngine.tick(snapshot, scene_buffer)`.
2. Detect bar-boundary crossings (track previous bar in engine state; trigger when `snapshot.bar % 16 == 1` and `prev_bar % 16 != 1`).
3. Respect `snapshot.in_transition` (return early) and `snapshot.loop_active` (return early).
4. Pick next scene from catalog (round-robin v1; weighted by energy later).
5. Crossfade between active and next scene over ~2 bars: blend `intensity` parameter from 1.0→0.0 on outgoing scene and 0.0→1.0 on incoming.
6. Enforce a minimum 4-bar hold on the new scene before allowing another rotation.

**Acceptance:**
- In demo mode (which advances bars continuously), scenes rotate every 16 bars.
- The crossfade is visually smooth in the DMX inspector (no jumps).
- Forcing a transition flag in ShowState (via a dev-only UI button) immediately suspends Phrase Engine output.
- Forcing `loop_active = true` also suspends rotations.

---

## Phase 6 — Hardware integration (Days 6–9, **requires rig access**)

**Goal:** Real Enttec, real fixtures, real PDL, real MIDI. The system runs end-to-end with hardware.

This is the start of the 2-week hardware window. Schedule a session with Josh to set up the rig.

Tasks:
1. **Enttec USB Pro driver** — replace `NullDriver` writes with real serial writes. Test with a single fixture first.
   - Open serial port at correct baud
   - Frame the 512-byte universe with the Enttec header/footer (518 bytes total)
   - Send at 30–44 Hz in the writer thread
2. **Verify each fixture individually** — Use a "manual test" UI panel: select a fixture, manually set channel values, confirm correct response. Walk through each of the 8 fixtures.
3. **Replace `DemoDataGenerator` with real listeners** in non-demo mode:
   - **`audio/prodj_link.py`** — Use `python-prodj-link`. Connect, subscribe to beat and status packets, update ShowState.
   - **`audio/midi_input.py`** — Open XDJ-XZ MIDI port via `mido`. Map CC numbers per `APPENDICES/C_XDJ_XZ_MIDI_MAP.md`. Update ShowState.
4. **End-to-end test:** Play music on the XDJ, observe lights reacting correctly.

**Acceptance:**
- Each fixture responds correctly to manual channel writes from the test panel.
- Lights pulse on real beats from the XDJ — not from a demo clock.
- Moving the crossfader on the XDJ updates the UI's crossfader display in real time.
- A full scene rotation cycle works on hardware.

This phase has the most unknowns. Budget extra time. Hardware quirks (the laser doesn't respond, the Enttec drops every 5th frame, the PDL connection requires a static IP) will eat hours.

---

## Phase 7 — Transition Engine (Days 9–11)

**Goal:** Detect DJ transitions from MIDI fader/crossfader movement and orchestrate a clean light handoff.

Tasks:
1. **`core/transition_engine.py`** — `TransitionEngine.tick(snapshot, scene_buffer)`.
2. **Detection logic:** Maintain a rolling 4-second window of crossfader values. If the value range across the window exceeds 0.1, set `snapshot.in_transition = true`. Also check `on_air_deck` changes.
3. **While transitioning:**
   - Suspend Phrase Engine (already handled by reading `in_transition`).
   - Hold current scene, boost master brightness by ~20%.
   - Continue Reactive Layer normally.
4. **Transition exit:** When crossfader stops moving for 4 bars AND `on_air_deck` settles:
   - Pick a new scene from the catalog.
   - Crossfade to it, synced to the next downbeat (`snapshot.beat == 1 and snapshot.bar % 4 == 1` works as a downbeat heuristic).
   - **Lock for 4 bars** — Phrase Engine cannot rotate until this hold expires.
5. **Iterate against real DJ behavior.** Josh DJs to test; observe; tune. This is the engine that most needs real-set tuning.

**Acceptance:**
- When Josh moves the crossfader on the XDJ, the UI shows "TRANSITION ACTIVE" within ~200 ms.
- During a transition, the active scene doesn't rotate even if 16 bars pass.
- After the transition completes, lights settle into a new scene cleanly.
- No flicker, no blackout, no stutter during the transition.

---

## Phase 8 — Polish and live-test (Days 11–14)

**Goal:** Run real DJ sets, tune scenes, fix edge cases, write a basic README.

Tasks:
1. **Run sets.** Josh DJs full sets (30–90 min) while you observe. Take notes on what doesn't look right.
2. **Tune scene parameters.** Move speeds, color saturation, strobe rates, beat-pulse decay, crossfade duration.
3. **Add 2–4 more scenes** if the catalog feels thin.
4. **Edge case fixes:**
   - PDL connection drops mid-set: does the metronome free-run cleanly?
   - MIDI cable unplugged: graceful degradation?
   - DJ does a long loop (16 bars): does Phrase Engine hold correctly?
   - DJ does a hard cut (no crossfader, both decks just go from 0 to full): is this detected?
5. **Write a minimal `README.md`** in the repo: install, run, dev mode, hardware bring-up.

**Acceptance:**
- Josh runs a full 60-minute set with the lights handling everything automatically.
- No interventions required beyond the occasional manual brightness adjustment.
- The set ends and the system is still running cleanly (no memory leaks, no orphan threads).

---

## Phase 9 — Show-night buffer (Days 14–17)

The remaining time before the deadline is buffer. Use it for:
- Whatever phase ran over
- Bug fixes from the run-set notes
- A second pass on scene tuning
- A dry-run with Josh on the actual show-night rig (if different from the test rig)

**Acceptance for handoff complete:**
- The hard constraints in `00_README.md` are all true.
- Josh can run a full set with no intervention except brightness/blackout.
- Code is documented to the point that *you* could come back to it in 6 months and remember how it works.

---

## Risk register (read this before starting)

The most likely things to eat time:

| Risk | Mitigation |
|---|---|
| Pro DJ Link won't connect (network config issues) | Have a backup plan: synthetic clock with tap tempo. Get this working on real hardware in Phase 6, day 1. |
| Enttec drops frames or has timing weirdness | Test with the simplest possible fixture first (one RGBW par at DMX 1). If that's stable, add complexity. |
| Beat detection feels "off" | The local metronome is the key — invest time tuning the interpolation in Phase 3 even before going to hardware. |
| Scenes look generic / not "DJ-set-quality" | Iterate with Josh actually playing music. Don't tune scenes in isolation. |
| The 2-week hardware window slips | Negotiate hardware access early. Phase 6 onwards is hardware-gated. |
| Transition Engine misfires on Josh's actual DJ style | Save this for last. It needs the most real-set iteration. |

---

## Phase ordering rationale

You may notice this plan front-loads demo-mode work before any hardware. That's deliberate:

- Demo mode is the **development substrate**. If you can build, run, and iterate on the system without hardware, you can work in parallel with Josh's schedule and you can debug without the rig setup overhead.
- Hardware integration in Phase 6 is **mostly drivers, not logic** — the engines and scenes are already written. Hardware phase is mostly "swap the input source and verify."
- The Transition Engine is last because it needs the most real-DJ-set iteration to feel right. Building it before you have a working light show to transition between is putting the cart in front of the horse.

---

## What "done" means revisited

From `00_README.md`:

1. ✅ Receives PDL + MIDI from the XDJ-XZ
2. ✅ Drives 74 channels of DMX through the Enttec
3. ✅ Semi-diverse scene catalog
4. ✅ Phrase Engine rotates on 8/16 bar boundaries
5. ✅ Transition Engine handles crossfades
6. ✅ Runs a 90-minute set unattended
7. ✅ Demo mode works for development

You hit all 7 by Phase 8. Phase 9 is buffer.

Next: **`06_TESTING_AND_SHOW_DAY.md`** — practical test plans and show-night checklists.
