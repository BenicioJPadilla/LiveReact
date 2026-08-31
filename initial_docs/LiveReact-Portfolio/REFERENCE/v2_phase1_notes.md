# v2 Phase 1 — what was built and validated

Phase 1 of v2 built and validated the **input + data-bus foundation**: the things that produce ShowState. The engines that consume ShowState were scaffolded but never finished. This document captures what Phase 1 proved, so you don't have to re-prove it.

## What Phase 1 built

| Component | Status | Notes |
|---|---|---|
| `core/show_state.py` | ✅ Built and tested | Dataclass with PDL + MIDI fields, lock, snapshot method |
| `audio/prodj_link.py` | ✅ Built and tested | Wraps `python-prodj-link`, writes PDL fields into ShowState |
| `audio/midi_input.py` | ✅ Built and tested | Reads XDJ MIDI via `mido`, maps CCs to ShowState fields |
| `audio/demo_data.py` | ✅ Built and tested | Synthetic clock + transitions for demo mode |
| Validation script | ✅ Built and ran | Prints live ShowState while a real or demo source feeds it |
| Project scaffold | ✅ Built | Fixture profiles, rig loader, Enttec driver, scene stubs, reactive layer engine, show engine, control panel UI |
| `core/phrase_engine.py` | ❌ Not started | Stub only |
| `core/transition_engine.py` | ❌ Not started | Stub only |
| Real scenes | ❌ Not started | Only placeholder stubs |

## What was validated

1. **`python-prodj-link` works with the XDJ-XZ** — confirmed BPM, beat, bar, loop, and on-air signals all arrive correctly over Ethernet.
2. **MIDI from the XDJ-XZ is readable via `mido`** — every channel fader, crossfader, EQ knob, and major button produces a clean CC stream.
3. **ShowState as a shared bus pattern works** — engines reading snapshots see consistent state, no tearing under load.
4. **Demo mode is a viable first-class development substrate** — you can develop without hardware and the engines never know the difference.
5. **The Python 3.14 + tkinter combination has quirks but is workable** — see anti-pattern 6.3 and 6.4 in `04_DESIGN_PRINCIPLES.md` for the specific bugs hit and their fixes.

## Bugs found and fixed during Phase 1

These two bugs are worth knowing about because they're easy to re-introduce:

**Bug 1: tkinter `BarMeter` crash on Python 3.14**

The `BarMeter` widget tried to draw on its Canvas inside `__init__`, before the tkinter event loop was running. Fix: defer with `widget.after(50, draw_fn)`.

**Bug 2: tkinter reserved attribute name conflict**

The widget code used `self._w` and `self._h` for "width" and "height" — `_w` is reserved by tkinter for the internal Tk widget path. Renamed to `_width` / `_height`.

## Open architectural items (carried forward to v2 full)

1. **PDL multi-field writes need atomic locks on ShowState** — when bpm, beat, and bar arrive in the same packet, they need to be written under a single lock acquisition so engines never see torn state. Documented in `03_ARCHITECTURE.md` section 3.
2. **Beat jitter mitigation via local metronome** — Phase 1 confirmed PDL packets have 5–20 ms jitter; using them as a visual clock causes stutter. The `LocalMetronome` design in the architecture doc addresses this.
3. **Phrase Engine follows one deck; Transition Engine manages handoff** — the question of "which deck's beat clock do we use during a transition" was debated. Resolution: Phrase Engine follows the `master_deck` field from PDL. Transition Engine takes over selection during mixes and re-anchors after handoff.
4. **4-bar minimum hold after transitions** — Phrase Engine must wait at least 4 bars after a transition completes before rotating again. Prevents visual whiplash.
5. **Loop detection triggers a hold-and-release pattern** — when `loop_active` is true, the Phrase Engine holds; when it goes false, optionally fires a "release" mini-event (a brief brightness pulse) before resuming normal rotation.

## Why Phase 1 code isn't in this folder

Josh's preference is for the new dev to build cleanly from the design docs rather than extending Phase 1's scaffold. The Phase 1 source exists — Josh has it — but providing it as a starting point creates a temptation to extend rather than rebuild, and rebuilding cleanly from a strong spec is more valuable than extending half-finished code.

If you want to see Phase 1 source for any specific component (the ShowState lock implementation, the PDL field mapping, the MIDI smoothing approach), ask Josh for the file.

## Recommendation

Start clean. The validated patterns are:
- ShowState as a single shared dataclass with a lock and snapshot method
- Listener threads writing only their own field groups
- Demo data generator producing the same ShowState contract as real listeners
- Local metronome interpolating between PDL beats

Implement those four, then build forward into the engines.
