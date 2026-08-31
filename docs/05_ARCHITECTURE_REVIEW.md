# 05 — Architecture Review

A critical review of the v2 architecture in `03_ARCHITECTURE.md`. The shape is good. This document says what to **keep**, what to **fix**, and what to **add**, backed by the real-time architecture research.

---

## 1. The proposed architecture in brief

```
PDL listener ┐                         ┌ Reactive Layer ┐
             ├─► ShowState (shared bus)─┼ Phrase Engine  ├─► scene buffer ─► merge ─► DMX universe ─► Enttec writer ─► rig
MIDI listener┘   (lock + snapshot)     └ Transition Eng ┘   (additive)    (+ManualParams)   (512 bytes)   (~44 Hz)
                       ▲                                                                          
              DemoDataGenerator (stands in for the two listeners)
```
Threads: main/UI (tkinter), PDL listener, MIDI listener, show engine (~60 Hz), DMX writer (44 Hz), local metronome (~120 Hz).

## 2. Verdict: the shape is right

The core decomposition is sound and worth keeping:
- **Single shared state bus** instead of point-to-point engine coupling — reduces the dependency graph dramatically and makes each engine independently testable (construct a state, call `tick`, assert the scene buffer).
- **Three parallel engines writing additively** — each engine's logic stays local; the merge layer is the only thing that knows all three.
- **Manual params as caps/biases** applied at merge — keeps automation always-on.
- **Demo data source implementing the same contract** as real listeners — the key to hardware-free development.
- **Local interpolated metronome** for visual timing — the correct fix for PDL jitter.

These are good instincts. The refinements below are about **concurrency correctness and failure isolation**, which the spec gestures at but under-specifies.

## 3. What to KEEP as-is

| Element | Keep because |
|---|---|
| ShowState as the single bus | Right pattern; just harden how it's read/written (§4) |
| Reactive / Phrase / Transition split | Maps cleanly to the musical model; each is testable |
| Additive scene buffer + merge rules (max for color/dimmer, last-write-wins for movement, capped strobe) | Correct combine semantics for lighting |
| ManualParams as multipliers/caps + hard switches (blackout/freeze) | Matches the "automation is default" principle |
| Local metronome resyncing to PDL, interpolating between | Mandatory; the only way to get smooth beat-locked motion |
| Demo data source as a first-class input | The substrate for the whole demo-first plan |
| Role/side fixture addressing in scenes | Decouples scenes from DMX layout |

## 4. What to FIX (concurrency correctness)

The spec's ShowState is "a dataclass with an `RLock` and a `snapshot()`." That's *almost* right but has three sharp edges the research flagged:

### 4.1 Snapshots must be truly immutable copies
If `snapshot()` returns references to mutable internals (lists, dicts, numpy arrays), an engine computing on the snapshot can still observe later mutations → torn reads *outside* the lock. **Fix:** snapshot captures all fields under **one** lock acquisition and returns a `@dataclass(frozen=True)` of plain immutable scalars/tuples. Engines then need no lock at all after they hold the snapshot.

### 4.2 Single-writer-per-field discipline (the real fix for the v1 bug class)
The spec's signature anti-pattern (a function that computes-then-resets the same field) and "multi-field tearing" both come from *shared mutable fields with multiple writers*. **Fix:** assign each field an owner thread. The **metronome owns** `bpm`/`beat_phase`/`bar`; the **UI owns** ManualParams/scene-skip; **listeners feed the metronome via messages**, they don't write clock fields directly. With one writer per field, read-modify-write races on that field disappear — and the code becomes free-threading-safe (don't rely on GIL atomicity).

### 4.3 Message-passing for inputs (queues), not direct pokes
Don't let the UDP/MIDI callback threads mutate ShowState. Have them push **immutable messages** onto a `queue.Queue`; the metronome/engine drains the queue at the top of each tick. `queue.Queue` is thread-safe, gives clean producer/consumer boundaries, and makes input handling unit-testable by just `put`-ing synthetic messages. This eliminates an entire class of locking bugs at the input boundary.

> Net ShowState pattern: **immutable one-lock snapshot for reads + single-writer-per-field + queue inputs.** The `RLock` then only guards the few genuinely multi-writer fields, and the spec's painful bugs become *structurally impossible* rather than "remember not to do that."

## 5. What to ADD (failure isolation & testability)

### 5.1 Double-buffer the DMX universe (most important addition)
The DMX writer is the "never stops" thread. It must never see a half-written frame and never block on engine logic. **Add a publish/consume buffer:** the engine renders into a back buffer and, only when complete, atomically publishes it (single-reference swap, or a sub-microsecond memcpy under a tiny lock). The writer always reads the last *complete* published frame.
- **Consequence (keep-last-frame):** if the engine stalls or throws, no new frame is published, so the writer keeps emitting the last good frame — lights hold steady instead of flickering or going black.
- **Writer survives everything:** wrap the writer's per-iteration body so no exception escapes; on serial failure, close + reopen with backoff while still ticking. *(Spec says "DMX writer never stops" — this is the mechanism that makes it true.)*

### 5.2 Injected clock for deterministic tests
Don't call `time`/`time.sleep` directly in loop logic. Inject a `Clock` (`monotonic()` + `sleep()`); production uses a real clock, tests use a `FakeClock` you can fast-forward. A 90-minute show simulation then runs in milliseconds, and you can assert beat-lock, scene rotation, and drift correction deterministically with no hardware and no real time passing. This single move makes the whole real-time core unit-testable.

### 5.3 Per-engine exception isolation
Each engine's `tick` is wrapped in try/except: on error, log and skip that engine for that tick (keep its previous contribution), and continue. A Phrase Engine bug must never stop the Reactive Layer — the rig keeps pulsing. The spec states this policy; make it a structural wrapper in the show engine, not per-engine boilerplate.

### 5.4 A staleness/health layer
Timestamp every PDL/MIDI message. Expose per-source freshness in ShowState and the UI ("PDL: stale"). On PDL staleness >1 s, the metronome free-runs at last BPM with a low-confidence flag; on MIDI staleness, hold last values. This is the backbone of NFR-5 (graceful degradation).

### 5.5 Output backend abstraction
Put DMX output behind an interface with **Enttec-serial** and **Art-Net/sACN** backends (and a **null/log** backend for demo). This enables hardware-free testing against software visualizers (QLC+, Resolume) and sidesteps every serial/driver issue when you don't have the Enttec. (See [07](07_CROSSPLATFORM_STRATEGY.md).)

## 6. Concurrency model decision

The spec's **multi-threaded** model is correct for this workload, and the research confirms it: the work per tick is light, and the heavy operations (serial write, UDP recv, MIDI read, sleep) all **release the GIL** while blocked, so threads genuinely overlap. Do **not** restructure around asyncio — it doesn't improve the cadence-critical serial writer and complicates it. Do **not** adopt free-threaded (no-GIL) Python for v1 — it's officially supported in 3.14 but your GUI/MIDI native extensions aren't validated for it in 2026, and you're not CPU-bound so it buys little. Keep the threaded design; just write it free-threading-clean (no reliance on GIL atomicity) so you *could* flip it on later.

**Optional refinement:** run an asyncio loop *inside one input thread* purely for the event-driven UDP + MIDI sources, feeding the same queue. Reasonable if input handling grows, but start with plain threads + queues.

## 7. Refined thread map

| Thread | Owns / does | Rate | Notes |
|---|---|---|---|
| Main / UI | Renders console + visualizer; owns ManualParams + scene-skip | 30–60 Hz | Never touch UI off this thread (Qt rule) |
| PDL listener | Receives UDP, parses, pushes messages to queue | event-driven | Socket timeout so it can honor stop flag |
| MIDI listener | Callback → pushes messages to queue | event-driven | Handle "port busy" on Windows |
| Metronome | Drains queue; owns bpm/phase/bar; writes ShowState | ~100 Hz | The single writer of clock fields |
| Show engine | Snapshot → run 3 engines → merge → publish frame | ~60 Hz | Per-engine try/except; publishes to double buffer |
| DMX writer | Reads published frame → frames → serial/Art-Net | ~40 Hz | Never stops; drift-corrected loop; self-healing |

Supervisor (main): one `threading.Event` stop flag; SIGINT/window-close → stop; **join** (non-daemon) all hardware-touching threads so ports close cleanly; bounded joins on shutdown.

## 8. Minor notes

- **`audio/` package name** (kept "for historical reasons") is now actively misleading — there is no audio. Name it `inputs/`.
- **Persistence:** the spec is stateless across runs. During iteration you'll re-tune scenes constantly; losing that on every restart hurts. A tiny optional `config.json` (last brightness, discovered MIDI map, selected rig, per-scene tuning) is worth adding without violating the "no cloud/accounts" non-goal. (See [10](10_OPEN_QUESTIONS_AND_ASSUMPTIONS.md).)
- **"Phrase Engine" naming** — rename or document clearly that it rotates on *inferred bar counts*, since true phrase data isn't available ([04 §4](04_HARDWARE_AND_PROTOCOLS.md)).
