# 04 — Design Principles

These are the design decisions that are **locked**. They were debated, tested, and resolved through earlier work on v1 and v2 Phase 1. If you want to revisit any of them, talk to Josh first — these are not nice-to-haves, they're load-bearing.

---

## 1. Frequency-driven color is non-negotiable

**The rule:**

| Audio content | Lighting color |
|---|---|
| Bass / low-end dominant | Red |
| Mid-range dominant | Pink / magenta |
| High-end dominant | Cyan |
| Full-spectrum (all bands engaged) | White |

**Why this is locked:**

The human brain has a built-in cross-modal pairing between sound frequency and color temperature — low frequencies pair with warm/red, high frequencies pair with cool/cyan. This pairing is consistent across cultures and ages, and you can violate it, but doing so makes a show feel "off" even when viewers can't articulate why. Top-tier DJ visualists like the ones running Dom Dolla and John Summit's shows lean into this pairing constantly.

An earlier draft of v1 included a "random color palette" mode where scenes could pick arbitrary palettes. Josh tested it live, found it cheap-looking, and we removed it. **Do not add it back.**

**What this means in code:**
- Scenes don't pick colors as constants. They pick *roles* (bass, mid, high) and the renderer looks up the current EQ state to choose the actual color.
- Reactive Layer's "color per beat" function reads ShowState's EQ values and biases color choice accordingly.
- The only place where arbitrary color is fine: **Phrase Engine crossfade transitions** can briefly desaturate or wash through neutral before locking into the new scene's frequency-based palette.

---

## 2. Automation over manual control

**The principle:** LiveReact is **automatic by default**. Manual controls are biases and caps applied on top of the automatic output, not overrides that suspend it.

If Josh walks away from the laptop mid-set, the lights keep running, keep rotating scenes, keep reacting to the music. He never has to touch the panel for a show to function. Manual controls exist to **shape** the show in real time — make it brighter for a peak, kill strobes during a vocal section — but the underlying engine never stops.

**What this means in code:**

- `ManualParams` are **multipliers, caps, or biases**, not values that replace engine output.
  - Wrong: `if manual_brightness_slider_changed: dimmer = manual_brightness`
  - Right: `dimmer_final = dimmer_from_engine * manual_params.master_brightness`
- Even in "blackout," internally the engines keep producing scene output. The merge layer just zeroes the universe before write. The instant blackout releases, the rig is exactly where automation says it should be.
- There is **no "manual mode" toggle.** There is no "pause automation" button. Both would lead to a panic state where Josh is suddenly responsible for driving the show by hand.

**One exception:** The `Skip Scene` button is a hard override that forces an immediate Phrase Engine rotation. It's a tool for Josh to nudge automation, not to take over.

---

## 3. Additive layering, not replacement

**The principle:** All three engines contribute to the same scene buffer. Their outputs **combine**, they don't overwrite each other.

The Reactive Layer is always producing beat pulses. The Phrase Engine is always producing the current scene's static look. The Transition Engine, when active, is producing brightness boosts and crossfade alphas. The merge layer takes all of those, combines them per-channel (max for color/dimmer, last-write-wins for movement), and writes to DMX.

**Why:** This makes each engine's logic local. The Reactive Layer doesn't need to know "what scene is active" — it just adds beat pulses on top of whatever color is there. The Phrase Engine doesn't need to know about beats — it sets the slow-changing palette. Each engine is decoupled, testable, replaceable.

**What this means in code:**

```python
# In Reactive Layer
def tick(self, snapshot, scene_buffer):
    pulse = self._compute_beat_pulse(snapshot)
    for fixture in self.wash_fixtures:
        # ADD to whatever's already in the buffer for this channel
        scene_buffer.add(fixture.slot_id, "dimmer", pulse)

# In merge.py
def merge_channel(contributions):
    return min(255, max(contributions))  # cap at 255, take the max
```

Note: "additive" for color/dimmer means "max-of," not literal sum. Adding red 200 + red 200 = red 400 = clamp to 255, but max(200, 200) = 200 which is what you actually want visually.

---

## 4. Shared data bus pattern (ShowState)

**The principle:** Engines never call each other directly or share references to each other's internal state. Everything flows through **ShowState**, a single shared object that listeners write to and engines read from.

**Why:** This avoids the snowball of coupling that destroys most real-time codebases. With three engines and a UI, naïvely you have 4×3 = 12 possible directional edges between components. With ShowState, there are exactly **4 edges**: each engine reads ShowState. Done.

It also makes the application **trivial to test**. Want to test the Phrase Engine? Construct a ShowState with the values you want, hand it to the engine, observe what it produces. No mocking of other engines, no need to wire up MIDI or PDL.

**Anti-pattern (do not do):**

```python
# WRONG
class PhraseEngine:
    def __init__(self, reactive_layer, transition_engine):
        self.reactive_layer = reactive_layer
        self.transition_engine = transition_engine

    def tick(self):
        if self.transition_engine.is_active():  # NO
            return
        ...
```

**Correct:**

```python
# RIGHT
class PhraseEngine:
    def tick(self, snapshot, scene_buffer):
        if snapshot.in_transition:  # comes from ShowState
            return
        ...
```

`in_transition` is a derived field that lives in ShowState. The Transition Engine sets it (writing into a "engine state" sub-section of ShowState, ideally), and the Phrase Engine reads it. They never know about each other as objects.

---

## 5. Pro DJ Link over audio FFT — the v1 → v2 story

This is the architectural pivot at the heart of v2. Worth understanding in detail.

### What v1 did

v1 sampled the master audio output of the XDJ-XZ via USB audio at 48 kHz, ran an FFT on rolling windows, and derived:
- Beat detection from RMS energy peaks in the low band (~40–120 Hz)
- BPM from the spacing of those peaks
- "Energy mode" (BREAK / BUILD / DROP / PEAK / OUTRO) from RMS levels and spectral centroid

It worked, in the sense that it produced beat-locked light pulses. But it had three fundamental problems:

1. **Beat detection drifted.** When a DJ applied filter effects (low-pass sweeps are common in builds), the bass disappeared and beat detection lost lock. The lights would freeze or flutter for several seconds until the bass came back.

2. **Energy detection was unreliable.** Mastered tracks are heavily compressed — the dynamic range between a "build" and a "drop" in RMS is much smaller than you'd think. v1's energy classifier was constantly second-guessing itself.

3. **Transition detection was guesswork.** From audio alone, you can't reliably tell when a DJ is mixing. The audio just changes character, gradually. We tried multiple heuristics (spectral entropy, key change, sudden BPM shift) and none of them were robust.

### What v2 does

v2 abandons audio analysis entirely (for the beat/energy/transition signals) and replaces it with **two structured inputs**:

- **Pro DJ Link over Ethernet** — the XDJ-XZ reports exact BPM, beat phase, bar, and loop state directly. No estimation. The clock is the clock.
- **USB MIDI** — channel faders, crossfader, EQs reveal the DJ's intent before it shows up in audio. The crossfader moves before the audio reflects the transition; the EQ kill happens *at* the audio change, not after.

The result is a **dramatically more reliable system** with much less code. Beat lock is rock-solid. Transitions are detected from the actual transition action (crossfader move), not inferred from its acoustic consequence. Loops are reported directly.

### What's still useful from v1

- The fixture profile structure (channel maps, helper methods like `set_rgbw`)
- The base `Scene` class shape
- The Enttec USB Pro driver — the protocol hasn't changed
- The tkinter control panel layout

### What got dropped from v1

- The audio FFT pipeline (`audio/engine.py` in v1)
- The energy classifier (`core/energy_detector.py` in v1) — replaced by `core/phrase_engine.py` in v2
- All beat-from-audio code
- The "BREAK/BUILD/DROP/PEAK/OUTRO" energy state machine — replaced by per-engine logic against ShowState fields

### Don't reintroduce audio FFT just because

Audio is *still* available as a USB audio device on the XDJ — and it might be tempting to add it back for some visual driver (e.g., a "spectrum visualization" mode). Resist. v2's whole gain comes from having **fewer, more reliable inputs**. Adding audio back as a side input creates new failure modes (audio drift, audio loss, conflict between audio-derived and PDL-derived clocks) for marginal benefit. If a future feature needs audio, design it so it can fail without affecting the rest of the system.

---

## 6. Anti-patterns from past bugs

These bugs were real, they were painful, they took hours to track down. Don't repeat them.

### 6.1 Read-then-overwrite in the same function

In v1, this pattern existed in the audio engine:

```python
def update_from_audio(self, audio_block):
    # compute new energy levels
    self.bass = self._compute_bass(audio_block)
    self.mid = self._compute_mid(audio_block)
    self.high = self._compute_high(audio_block)

    # OOPS — at the end of every call, this resets everything to zero
    # before returning. Was leftover from earlier code path.
    self.bass = 0  # 🔥
    self.mid = 0   # 🔥
    self.high = 0  # 🔥
```

This took ~3 hours to find because the UI meters all read zero, but isolated print statements showed the computation working fine. The bug was a leftover line at the end of the function.

**Lesson:** Be paranoid about read-then-write data flow. If you're updating shared state from a function, the function should *only* update — never compute-then-update-then-reset.

The v2 architecture is designed to reduce surface area for this class of bug. Listeners only write to their own ShowState fields. Engines only write to the scene buffer. Merge only reads scene buffer and writes universe. There's no place where the same code path computes and resets the same value.

### 6.2 Initial values that look like "off" but cause bugs

v1's peak normalization started at a tiny epsilon value. The UI meters were normalized by dividing by the running peak — but until a loud sound came in, the peak was epsilon, so divide-by-tiny made everything saturate to 100%. Looked like the UI was working until you noticed it never *changed* during quiet sections.

**Lesson:** Initial values matter. Default normalization to a sane scale, not to zero or epsilon. For peak detection, initialize to your expected nominal level (e.g., 0.3 for RMS).

### 6.3 tkinter Canvas drawing before mainloop

In v2 Phase 1, a `BarMeter` widget tried to draw on its Canvas in `__init__`, before the tkinter event loop was running. On Python 3.14, this crashed (the underlying Tcl interpreter wasn't ready). On older Pythons it sort-of worked.

**Fix:** Defer initial drawing with `widget.after(50, self._draw_initial)`. Anything that draws on a Canvas should be scheduled, not called inline during widget construction.

### 6.4 Reserved attribute name collisions in tkinter widget subclasses

```python
class BarMeter(tk.Canvas):
    def __init__(self, parent, width, height):
        super().__init__(parent, width=width, height=height)
        self._w = width   # 🔥 _w is reserved by tkinter
        self._h = height
```

`_w` is the internal Tk widget name attribute. Overwriting it breaks everything weirdly (the widget might not get destroyed correctly, or events stop firing). Use `_width`, `_height`, or anything else.

**Lesson:** When subclassing tkinter widgets, double-underscore-prefix any state attributes (`__width`) or use a non-underscore name. Or just don't subclass — composition over inheritance.

### 6.5 PDL multi-field tearing

If the PDL listener writes `bpm` and then `beat` to ShowState without holding a lock, an engine snapshot can catch the new bpm with the old beat (or vice versa). For BPM changes this matters because beat phase depends on BPM.

**Fix:** Always write related fields under a single `with self._lock:` block. The `snapshot()` method also takes the lock. This makes multi-field reads atomic.

### 6.6 Beat jitter as a visual clock

PDL beat packets arrive every 4 beats at a base rate — and each packet has some delivery jitter. If you use raw PDL beat events as the source for visual animation, your lights stutter on every beat.

**Fix:** Use the local metronome (section 4.3 of architecture doc) for visual timing. Resync to PDL, but interpolate between.

---

## 7. Code-style conventions

These aren't strict rules, but consistent codebases are easier to maintain.

- **Type hints everywhere.** Python 3.11+ supports `from __future__ import annotations` and clean `list[int]` / `dict[str, float]` style. Use it.
- **Dataclasses for shared state.** `@dataclass(frozen=True)` for immutable snapshots, plain `@dataclass` for mutable bus state.
- **One class per file** for major components (each engine in its own file). Multiple small dataclasses can share a file.
- **Module names lowercase, snake_case.** Class names PascalCase.
- **No global mutable state.** The application has a single `App` object created in `run.py` that owns everything. Pass references explicitly.
- **Logging, not print.** Use `logging` with a configured root logger. Show output controls are in the UI.
- **No external dependencies beyond:** `numpy`, `scipy` (if needed for any DSP), `pyserial`, `python-prodj-link`, `mido` (or `python-rtmidi`), `tkinter` (stdlib). Keep the wheel small.

---

## 8. Things explicitly out of scope

Save these for v2.x or never:

- **Multi-universe DMX.** One universe is enough for this rig.
- **Art-Net or sACN networking.** Direct serial to one Enttec is simpler and more reliable.
- **Web UI / browser frontend.** tkinter is fine for a personal tool.
- **Cloud sync, account systems, presets.** Stateless across runs is fine.
- **Live audio analysis.** See section 5.
- **Plugin / scene-scripting system.** Hardcoded scenes in Python are easier to debug.
- **Mobile or remote control.** This is a venue-laptop tool.
- **Cue list / pre-programmed shows.** LiveReact is reactive, not timeline-based.

---

Next: **`05_BUILD_PLAN.md`** — phased roadmap from empty repo to show-ready.
