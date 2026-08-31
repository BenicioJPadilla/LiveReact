# LiveReact — Developer Portfolio

A beat-reactive DMX lighting controller for live DJ sets. The system reads musical timing from a Pioneer XDJ-XZ in real time and drives a full fixture rig (moving heads, lasers, wash bars, pars) automatically, with minimal manual intervention during a set.

| | |
|---|---|
| **Stack** | Python 3.14, macOS, tkinter UI |
| **Inputs** | Pro DJ Link over Ethernet, USB MIDI |
| **Output** | Enttec DMX USB Pro → 74-channel DMX chain |
| **Deadline** | 2.5 weeks from project start (2 weeks of hardware access included) |
| **Product owner** | Josh — DJ, hardware operator, on-the-ground tester |
| **Builder** | You |

---

## Why this is a portfolio and not a codebase

Two drafts of this app exist already:

- **v1** detected beats and energy from USB audio via FFT. It worked, but timing was noisy and energy detection was unreliable in real DJ sets — too much variance in master-out audio for clean transition and phrase detection.
- **v2 Phase 1** replaced audio FFT with **Pro DJ Link** (exact BPM, beat phase, bar, and loop state straight from the controller) and added **USB MIDI** reads of the channel faders, crossfader, and EQs (the DJ's intent, directly). The input layer and shared data bus were validated. The engines that turn that data into lighting were never built.

**You are starting fresh — not extending v1, not extending v2 Phase 1.** A strong developer building it cleanly in one pass with full context will produce a tighter system than one extending two layers of someone else's code. The reference code is included so you can see *what was tried and what was learned*, not so you copy it.

The architecture, hardware layout, design principles, fixture channel maps, and acceptance criteria are all **locked**. Your job is to implement them well.

---

## What "done" looks like

A working application that:

1. Receives Pro DJ Link data from a Pioneer XDJ-XZ and reads MIDI from the same controller.
2. Drives the full rig over DMX-512 through the Enttec DMX USB Pro:
   - 2× SHEHDS 180W moving heads (15ch each)
   - 2× SHEHDS 3W lasers (12ch each)
   - 2× RGBW pars (4ch each)
   - 2× OK-103-288WL wash bars (6ch each)
   - **74 channels total, no address overlaps**
3. Runs a **semi-diverse** set of scenes that rotate automatically on musical phrase boundaries (8 / 16 bar).
4. Detects DJ transitions via MIDI crossfader and handles deck handoff cleanly.
5. Holds up unattended for a full ~90-minute DJ set with no visual artifacts and no manual intervention required.
6. Includes a **demo mode** (no hardware required) for development off the rig.

---

## How to read this portfolio

Read in order. Each document builds on the previous one.

| # | File | Covers | Time |
|---|------|--------|------|
| 00 | `README.md` | This file. The map. | 5 min |
| 01 | `DOMAIN_PRIMER.md` | DMX-512, Pro DJ Link, MIDI, scenes, what a DJ set looks like from a lighting POV. **Start here if you've never done lighting or DJ tech.** | 30 min |
| 02 | `HARDWARE_RIG.md` | Every device, the DMX chain wiring, address map, full per-fixture channel layouts. | 20 min |
| 03 | `ARCHITECTURE.md` | The v2 design: dual-input → ShowState bus → three parallel engines → DMX merge. Includes the canonical architecture diagram. | 30 min |
| 04 | `DESIGN_PRINCIPLES.md` | Locked design decisions, the v1→v2 story in depth, anti-patterns to never repeat. | 15 min |
| 05 | `BUILD_PLAN.md` | Phased roadmap from empty repo to show-ready, with acceptance checks per phase. | 15 min |
| 06 | `TESTING_AND_SHOW_DAY.md` | How to test on hardware, demo-mode safety net, the 2-week test plan, show-night checklist. | 10 min |

Two folders sit alongside:

- `REFERENCE/` — v1 codebase and v2 Phase 1 design notes. **Reference only.** Do not extend either. Use them to understand *why* certain choices were made and to crib data structures or fixture profiles if useful.
- `APPENDICES/` — DMX-512 wire format details, Pro DJ Link protocol notes, XDJ-XZ MIDI map, fixture manuals (SHEHDS 180W, SHEHDS 3W laser, OK-103-288WL bar), glossary of lighting terms.

---

## Hard constraints (do not violate)

1. **Frequency-driven color is non-negotiable.** Bass = red, mid = pink/magenta, high = cyan, all = white. Do not randomize color palettes per scene. Why this matters is in `DESIGN_PRINCIPLES.md`.
2. **Automation is the default; manual controls are biases, not overrides.** The lights keep running even when Josh isn't touching the panel. Manual UI inputs cap, bias, or color the automatic output — they don't replace it.
3. **Engines never talk to each other directly.** All inter-engine state flows through `ShowState`. No direct calls between Phrase Engine, Transition Engine, and Reactive Layer.
4. **Be paranoid about read-then-write data flow.** A v1 bug had a single function overwriting live audio data back to zero in the same call. The new architecture is designed around a shared bus specifically to avoid this class of issue — keep the discipline.
5. **Lasers boot OFF.** SHEHDS 3W CH1 = `0` (range 0–41 = laser off). Never boot a laser in any active mode. Only scenes activate lasers, and only with audience-safety angles verified.

---

## Environment

- MacBook (Josh's primary dev and show machine is a MacBook; build with that target in mind)
- Python 3.14 target (3.11+ should work)
- Homebrew + `portaudio` if you want the dev-time audio path for testing
- `pyserial` for Enttec USB Pro
- `python-prodj-link` for Pro DJ Link
- A USB MIDI library of your choice for the XDJ-XZ MIDI reads

The first runnable milestone is **demo mode with no hardware connected** — full UI, fake beat clock, simulated MIDI faders. See Phase 1 in `BUILD_PLAN.md`.

---

## Working with Josh

- **Domain questions** (what should a drop scene feel like? how aggressive is too aggressive on strobe? what does a "build" do?) → Josh.
- **Architecture questions** (why ShowState? why three parallel engines instead of one?) → read `ARCHITECTURE.md` and `DESIGN_PRINCIPLES.md` first, then Josh.
- **Hardware quirks** (the moving head isn't responding, the Enttec port keeps changing) → Josh — he has the rig in hand.
- **Anything blocking for >2 hours** → Josh. The deadline is tight.

---

## Quick orientation

If you only have 15 minutes today, read:
1. This README (you're here)
2. The architecture diagram on page 1 of `03_ARCHITECTURE.md`
3. Section "v1 → v2: what changed and why" in `04_DESIGN_PRINCIPLES.md`

That gives you the shape of the system. Everything else fills in detail.
