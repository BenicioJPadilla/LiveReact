# 02 — Goal & Requirements

Distilled from `00_README.md`, `03_ARCHITECTURE.md`, `04_DESIGN_PRINCIPLES.md`, and `05_BUILD_PLAN.md`, then re-scoped for a macOS-first (portable), demo-first, no-Josh rebuild.

---

## 1. The goal in one paragraph

LiveReact is a **personal, automatic stage-lighting controller for live DJ sets**. While a DJ plays on a Pioneer XDJ-XZ, LiveReact listens to the musical clock (Pro DJ Link over Ethernet) and the DJ's hands (USB MIDI faders/EQ/crossfader), and **automatically** drives a small rig of moving heads, lasers, pars, and wash bars over DMX so the lighting feels musical, beat-locked, and intentional — **without anyone touching the controls** for a whole set. A human operator *can* shape the show (brightness, strobe cap, blackout) but never *has* to. It must also run a full **demo mode with no hardware** so it can be developed and demonstrated anywhere.

## 2. Primary user & context

- **Operator/owner:** a DJ running their own rig at small venues / bedroom / parties. Not a lighting professional sitting at a console all night.
- **Usage:** launch before the set, confirm it's live, mostly leave it alone; occasionally nudge brightness or hit blackout.
- **Failure cost:** medium. A glitch is embarrassing, not dangerous — *except* lasers and strobes, where safety is real (see [08](08_LIGHTING_DESIGN_AND_SAFETY.md)). The system must **degrade gracefully, never go fully dark unexpectedly, and never crash mid-set.**

## 3. Functional requirements

### FR-1 — Inputs
- **FR-1.1** Receive Pro DJ Link from an XDJ-XZ over Ethernet: BPM, beat-within-bar, on-air deck, master deck, loop state, play state.
- **FR-1.2** Read USB MIDI from the XDJ-XZ: channel faders A/B, crossfader, per-channel EQ (low/mid/high). Read-only — never send MIDI back.
- **FR-1.3** Derive a smooth beat-phase clock locally (interpolated between PDL beats), an inferred bar/phrase counter, an `in_transition` signal, and an `energy` estimate.
- **FR-1.4** Provide a **synthetic data source** (demo mode) that produces the same state contract with no hardware.

### FR-2 — Engines (the show logic)
- **FR-2.1 Reactive Layer (always on):** beat-synced dimmer pulses, BPM-locked movement, frequency-driven color.
- **FR-2.2 Phrase Engine:** rotate scenes on inferred 8/16-bar boundaries; suspend during transitions and loops; enforce a minimum hold after a change.
- **FR-2.3 Transition Engine:** detect DJ mixes from crossfader/fader movement and on-air changes; hold + slightly brighten during the mix; crossfade to a new scene on the next downbeat; mandatory ≥4-bar post-transition hold.
- **FR-2.4** Engines never call each other; they communicate only via shared state. Each writes additively to a scene buffer.

### FR-3 — Scenes
- **FR-3.1** A catalog of ~8–12 distinct, frequency-color-respecting scenes spanning breakdown / build / drop / hold energy levels.
- **FR-3.2** Lasers active **only** in explicit drop scenes; off everywhere else.
- **FR-3.3** Scenes address fixtures by **role and side** ("all wash, both sides"), not raw DMX index.

### FR-4 — Output
- **FR-4.1** Merge engine contributions per channel (max for color/dimmer, last-write-wins for movement, capped strobe), apply manual biases, then write a 512-byte universe.
- **FR-4.2** Transmit the universe to the rig at ~30–44 Hz via an Enttec DMX USB Pro.
- **FR-4.3 (new, recommended)** Support an alternative **Art-Net/sACN** output backend for hardware-free testing against software visualizers and for Ethernet-DMX nodes. *(See [07](07_CROSSPLATFORM_STRATEGY.md).)*

### FR-5 — Manual controls (biases, not overrides)
- Master brightness cap, strobe cap, laser enable, warm/cool color bias, blackout (hard), freeze (hard), skip-scene (forces a rotation).
- Keyboard shortcuts: blackout, freeze, strobe burst, skip scene, tap-tempo fallback.

### FR-6 — Operator UI
- Live readouts: BPM, beat/bar counters, on-air deck, energy meter, frequency strip, active scene, transition indicator, input-health/staleness indicators.
- A **DMX inspector / virtual rig visualizer** for development and verification without hardware.
- A **manual fixture-test panel** for hardware bring-up (drive individual channels).

### FR-7 — Modes & lifecycle
- Auto-detect hardware on startup; fall back to demo mode if absent. Explicit `--demo` / `--hardware` flags.
- Clean startup and shutdown of all threads (Ctrl-C and window-close), releasing serial/MIDI/UDP cleanly.

## 4. Non-functional requirements

| ID | Requirement | Target | Source/Notes |
|---|---|---|---|
| NFR-1 | **macOS-first, portable** | Targets & tests macOS; code stays OS-agnostic so a Windows build is a low-cost future option | Your decision (2026-06); refines spec's macOS-only |
| NFR-2 | **DMX refresh stability** | Steady ~40 Hz, low jitter, on both OSes | Needs 3.11+ high-res timer + drift-corrected loop ([07](07_CROSSPLATFORM_STRATEGY.md)) |
| NFR-3 | **Beat-lock accuracy** | Pulses visually on the beat; no stutter | Local interpolated metronome, never raw PDL packets |
| NFR-4 | **Unattended endurance** | ~90 min with no intervention, no leak, no orphan threads, no visual artifacts | `00_README.md` |
| NFR-5 | **Graceful degradation** | PDL loss → free-run metronome; MIDI loss → hold values; serial fail → retry; engine error → keep last frame; **DMX writer never stops** | `06_TESTING_AND_SHOW_DAY.md` §8 |
| NFR-6 | **Safety** | Lasers boot off & only in drop scenes; strobe capped & rationed; instant blackout | Regulation-confirmed ([08](08_LIGHTING_DESIGN_AND_SAFETY.md)) |
| NFR-7 | **Demo-first dev** | Full app runs and is iterable with zero hardware | Central to hardware-uncertain rebuild |
| NFR-8 | **Testability** | Real-time logic unit-testable deterministically (injected clock), fast suite (<10 s) | [05](05_ARCHITECTURE_REVIEW.md) |
| NFR-9 | **One-click launch** | Double-click start on macOS (`.app` / `.command`); portable run script otherwise | macOS-first launcher/packaging ([07](07_CROSSPLATFORM_STRATEGY.md)) |
| NFR-10 | **Maintainability** | Type hints, one-class-per-file majors, logging not print, no global mutable state | `04_DESIGN_PRINCIPLES.md` §7 |

## 5. Hard constraints (from the spec — keep, with one correction)

1. **Frequency-driven color** — bass→red, mid→pink/magenta, high→cyan, all→white. *Keep as house style. Correct the rationale (see [08](08_LIGHTING_DESIGN_AND_SAFETY.md)). The grounded part — energy→brightness/saturation — is mandatory; the hue mapping is a consistent convention.*
2. **Automation is default; manual is bias/cap, not override.** No "manual mode," no "pause automation."
3. **Engines never talk to each other directly.** All inter-engine state flows through shared state.
4. **Be paranoid about read-then-write data flow.** Structural avoidance via single-writer-per-field + immutable snapshots ([05](05_ARCHITECTURE_REVIEW.md)).
5. **Lasers boot OFF.** Never boot or auto-enable a laser in any active mode; only drop scenes activate them, only at install-verified safe angles.

## 6. Acceptance criteria ("done")

The spec's definition of done, restated and adjusted for macOS-first (portable):

1. ✅ Receives PDL + MIDI from the XDJ-XZ (when hardware present).
2. ✅ Drives 74 channels of DMX through the Enttec (or Art-Net backend) with no address overlaps.
3. ✅ Runs a semi-diverse scene catalog (≥8 scenes) rotating automatically on 8/16-bar boundaries.
4. ✅ Detects DJ transitions via MIDI/PDL and handles deck handoff cleanly.
5. ✅ Holds up unattended for a ~90-minute set with no artifacts and no manual intervention.
6. ✅ Demo mode runs the full app with no hardware.
7. ✅ **Runs on macOS** (primary target); code kept portable so a Windows build is low-cost later.
8. ✅ Degrades gracefully on every documented failure mode; DMX writer never stops.
9. ✅ Laser/strobe safety behavior verified.

## 7. Explicit non-goals (from spec — endorsed)

Multi-universe DMX, Art-Net/sACN as the *primary* path (it's now an optional secondary backend), web UI *as the only UI*, cloud/accounts, live audio FFT analysis, plugin/scripting scene system, mobile/remote control, timeline/cue-list shows. Stateless-across-runs is acceptable, though a tiny optional preset/config file is worth reconsidering ([10](10_OPEN_QUESTIONS_AND_ASSUMPTIONS.md)).
