# 11 — Recommended Approach

The brainstorm: how I'd actually rebuild LiveReact given everything in the prior documents — macOS-first (portable), demo-first, no Josh, no code, spec challenged. This is the synthesis; the phase-by-phase plan is in [12](12_REBUILD_ROADMAP.md).

---

## 1. Strategy in one line

**Build a clean Python 3.12 core that is fully exercisable in demo mode with an on-screen virtual rig, behind well-defined input/output interfaces, so that "going to hardware" is just swapping adapters — not rewriting logic.**

Everything below serves that sentence.

## 2. Guiding principles for the rebuild

1. **Demo-first is not a feature, it's the development substrate.** The synthetic data source and virtual rig visualizer are built *first* and used for 80% of development. If you can't see the show on screen, you can't build it without hardware — and your hardware access is uncertain.
2. **Interfaces at every hardware boundary.** Input (`InputSource`), output (`OutputBackend`), and time (`Clock`) are abstractions. Real and fake implementations are interchangeable. This is what makes the system testable, cross-platform, and hardware-optional simultaneously.
3. **Structural correctness over discipline.** The spec's worst bugs were "remember not to do that." Replace them with patterns where the bug is *impossible*: immutable snapshots, single-writer-per-field, queue inputs, double-buffered output. (See [05](05_ARCHITECTURE_REVIEW.md).)
4. **The DMX writer is sacred.** It never blocks on logic, never sees a half-frame, never crashes, never stops. Everything else can fail and the lights keep running on the last good frame.
5. **Honesty about data.** Build to what PDL/MIDI actually give you (bar inferred, phrase absent, position unavailable), and surface unverified assumptions (MIDI map, channel maps) in the UI until hardware confirms them.
6. **Safety is non-negotiable and cheap to honor.** Lasers off by default and only in drop scenes; strobe capped and rationed. These are simple rules with serious consequences — bake them into the merge layer, not individual scenes.

## 3. The shape of the system

```
inputs/                          core/                              output/
  InputSource (interface)          ShowState (immutable snapshots)    OutputBackend (interface)
   ├─ LiveInput                    Metronome (owns clock fields)       ├─ EnttecSerial
   │   ├─ ProDjLinkListener ─┐     ShowEngine (60Hz):                  ├─ ArtNet / sACN
   │   └─ MidiListener ──────┤        snapshot → engines → merge       └─ NullLog (demo)
   └─ DemoDataSource ────────┘        → publish frame ──────────────►  DmxFrameBuffer (double-buffered)
        (all push messages          engines/                                    │
         to a queue.Queue)            ReactiveLayer / Phrase / Transition        ▼
                                     scenes/ (role+side, freq-color)      DmxWriter thread (40Hz, never stops)
   clock/                            merge/ (max,last-write,caps, safety)
     Clock (interface): RealClock | FakeClock     ui/ (PySide6 console + virtual rig + fixture-test + MIDI-learn)
```

## 4. Key decisions (and why) — quick reference

| Decision | Choice | Rationale | Detail |
|---|---|---|---|
| Language | Python 3.12 | Ecosystem lock-in; retires MIDI-wheel + Windows-timer risks | [06 §1–2](06_TECH_STACK_EVALUATION.md) |
| Concurrency | Threads + queues, injected clock | Right for soft-real-time I/O; testable | [05 §6](05_ARCHITECTURE_REVIEW.md) |
| UI | PySide6 (Dear PyGui backup) | Best cross-platform console + visualizer; already in tree | [06 §3](06_TECH_STACK_EVALUATION.md) |
| State | Immutable snapshot + single-writer + queues | Makes the spec's bug classes impossible | [05 §4](05_ARCHITECTURE_REVIEW.md) |
| Output | Interface w/ Enttec + Art-Net + Null | Hardware-optional, OS-agnostic, visualizer-testable | [05 §5.5](05_ARCHITECTURE_REVIEW.md), [07 §6](07_CROSSPLATFORM_STRATEGY.md) |
| PDL | python-prodj-link, hardened, behind interface | Only viable in-process option; replaceable | [06 §4](06_TECH_STACK_EVALUATION.md) |
| MIDI | mido+python-rtmidi, empirically remapped | Standard; XDJ map must be verified | [04 §6](04_HARDWARE_AND_PROTOCOLS.md) |
| Color | Two-axis: energy→bright/sat, band→hue | Keeps the rule, fixes the rationale | [08 §1](08_LIGHTING_DESIGN_AND_SAFETY.md) |
| Persistence | Tiny optional config.json | Saves iteration pain w/o violating non-goals | [10 C1](10_OPEN_QUESTIONS_AND_ASSUMPTIONS.md) |

## 5. What I would build first (and why that order)

The spec's phase order is good but macOS/hardware-flavored. My re-ordering optimizes for **maximum progress with zero hardware**, then a tight hardware swap:

1. **The skeleton + clock + double-buffer + null output** — threads alive, frames flowing to a log, clean shutdown, all on an injected clock with unit tests. *Proves the spine.*
2. **DemoDataSource + Metronome + ShowState** — a synthetic musical clock driving smooth interpolated beat phase. *Now you have "music" without hardware.*
3. **Fixtures + rig loader + merge + virtual rig visualizer (PySide6)** — see the universe on screen. *Now you can see output without hardware.*
4. **Reactive Layer** — beat pulses + frequency color visible on the virtual rig. *First "it's alive" moment.*
5. **Scene catalog + Phrase Engine** — rotating, crossfading looks. *Now it's a show.*
6. **Operator console + manual params + safety in merge** — the full UI, caps, blackout/freeze, laser/strobe rules.
7. **Transition Engine** — built against the demo's synthetic transitions first.
8. **Hardware adapters** — EnttecSerial output + real ProDjLink/Midi input, swapped in behind the existing interfaces; manual fixture-test + MIDI-learn tools; cross-platform networking setup.
9. **Tuning + endurance + packaging** — real-set iteration (when hardware available), 90-min soak, signed installers.

Steps 1–7 need **no hardware at all** and are where most of the value and risk live. Step 8 is "mostly adapters, not logic," exactly as the spec intends.

## 6. Two strategic options to decide early

- **PDL: in-process vs. sidecar.** Default to in-process `python-prodj-link` (coherent codebase). Keep the input interface clean so that *if* Windows PDL reliability becomes a recurring fight, you can drop in a Java **beat-link** sidecar without touching the engines. Decide based on real behavior, not upfront.
- **UI: PySide6 vs. web.** Default PySide6. If you find yourself wanting a genuinely beautiful visualizer or remote/tablet control, the local-web-UI route (FastAPI + browser) is the pivot — but it's a bigger commitment. Don't start there.

## 7. What success looks like at each "altitude"

- **Tracer-bullet success:** `run --demo` opens a window, a synthetic 124 BPM clock ticks, and the virtual rig pulses on the beat with frequency-driven color. Achievable early, entirely without hardware.
- **Demo-complete success:** the full console + 8-scene catalog + all three engines + manual controls run a believable, non-chaotic show on the virtual rig for an hour, deterministically testable.
- **Hardware success:** the same software, unchanged above the adapter layer, drives the real rig from a real XDJ-XZ on both a Windows and a macOS machine.
- **Show-ready success:** a 90-minute set runs unattended, degrades gracefully on every failure mode, and the lights never stop.

## 8. Anti-goals for the rebuild (don't get distracted)
No audio FFT, no multi-universe, no web UI as the primary path, no plugin system, no presets/cloud, no timeline cues. Resist re-adding audio "just for a spectrum visualizer" — the whole point of v2 is fewer, more reliable inputs. Keep the dependency set small. (Spec non-goals, endorsed — [02 §7](02_GOAL_AND_REQUIREMENTS.md).)

Next: [12 — Rebuild Roadmap](12_REBUILD_ROADMAP.md) for the phase-by-phase plan with acceptance checks.
