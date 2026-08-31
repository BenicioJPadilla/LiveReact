# 03 — Domain Brief (self-contained)

Because you have no access to Josh, this is a standalone primer on the four domains LiveReact straddles — **DMX-512**, **Pro DJ Link**, **MIDI**, and **lighting design** — distilled from the spec and corrected/expanded with external research. It is deliberately enough to build from without consulting anyone. Wire-level detail and the rig itself live in [04](04_HARDWARE_AND_PROTOCOLS.md); aesthetics and safety live in [08](08_LIGHTING_DESIGN_AND_SAFETY.md).

---

## 1. DMX-512 — the lighting wire protocol

The protocol every stage/club fixture has spoken since 1986 (ANSI E1.11). Mental model:

- A **universe** is one chain of up to **512 channels**; each channel is **one byte (0–255)**.
- The host **blasts the entire universe ~44 times/second** over an RS-485 serial line (250 kbps). There is no "set channel X" command — only "here is the whole universe, again." To change a fixture, you write into your in-memory 512-byte buffer and let the writer thread keep sending it.
- DMX is **stateless, unidirectional, unacknowledged.** No checksum, no confirmation. Bad cable or too-slow refresh → flicker/freeze.
- Each fixture has a **start address** (1–512) and reads its own contiguous slice. **Channel meaning is fixture-specific** — channel 1 is "pan" on a moving head, "red" on a par. Software needs a **fixture profile** per fixture type to map channel offsets to semantic names.
- Some channels are **16-bit pairs** (coarse + fine, e.g. Pan / Pan-fine): combined value = coarse×256 + fine.
- **Daisy-chain topology**, last fixture terminated with a **120 Ω** resistor. Up to 32 fixtures electrically.

**For the code:** model a `Fixture` base with named channel accessors (`mh.set("dimmer", 200)`), one universe buffer, and a writer thread. Scenes never touch byte indices.

The host adapter here is the **Enttec DMX USB Pro** — appears as a serial port, takes a simple framed packet, and handles DMX-side timing itself. Wire detail in [04 §3](04_HARDWARE_AND_PROTOCOLS.md).

---

## 2. Pro DJ Link — musical timing from the controller

Pioneer/AlphaTheta's **proprietary, officially-undocumented** Ethernet protocol. Gear broadcasts musical state over UDP; the whole third-party ecosystem is reverse-engineered.

**Why it's better than audio analysis (the v1→v2 pivot):** v1 sampled master-out audio and ran FFT to *estimate* beats and energy. That's noisy in real sets — limiters compress dynamic range (build vs. drop barely differ in RMS), filter sweeps remove the bass that beat detection depends on, and transitions can't be reliably inferred from audio. PDL replaces estimation with **structured data read from the source.** This is the right call and external research backs it.

**What you actually get (corrected — see [04 §4](04_HARDWARE_AND_PROTOCOLS.md) for the full reality check):**

| Field | Available directly? | Notes |
|---|---|---|
| BPM (with pitch) | ✅ | Effective BPM = track BPM × pitch; smooth it (pitch fader dithers it) |
| Beat-within-bar (1–4) | ✅ | The cyclic downbeat counter |
| On-air (which deck is audible) | ✅ | From the mixer; drives "which deck to follow" |
| Master / sync / play state | ✅ | |
| Loop active | ✅ | Hold visuals during loops |
| **Bar number** | ⚠️ **Inferred** | Count 4→1 wraps locally; no absolute bar field |
| **Musical phrase** | ❌ **Not transmitted** | The "Phrase Engine" rotates on *inferred bar counts*, not detected phrases |
| **Continuous beat phase** | ❌ **Interpolated** | Packets carry beat events / countdowns, not a smooth 0–1 phase |
| **Absolute track position** | ❌ **Not on XDJ-XZ** | (CDJ-3000 feature) — don't design features needing it |

**Networking:** ordinary UDP broadcast on ports **50000/50001/50002** (keep-alive / beat / status). **No pcap/Npcap, no admin** — but Windows has real gotchas (firewall, slow link-local). See [07](07_CROSSPLATFORM_STRATEGY.md).

**Failure modes to handle:** packets jitter 5–20 ms (never use them as a direct visual clock — interpolate with a local metronome and resync); cable unplug → packets stop (detect staleness >1 s, free-run at last BPM); pitch-fader BPM wobble (low-pass it); half/double-time BPM tagging.

---

## 3. MIDI — reading the DJ's hands

The XDJ-XZ also presents as a **USB MIDI device**. LiveReact does **not** control lights with MIDI; it **observes the DJ's intent**:

| Control | Why read it |
|---|---|
| Channel faders A/B | A rising fader = that deck becoming audible (a mix is starting) |
| Crossfader | The canonical "we're transitioning" signal — and it moves *before* the audio reflects it |
| EQ low/mid/high per channel | DJ killing bass / filtering highs → energy + frequency-color signal |
| Cue/play buttons | New track cued/started |

**Why MIDI *and* PDL:** PDL says *what the music is doing*; MIDI says *what the DJ is doing to it*. Together: "deck 2 on-air, bar 16, and the crossfader has swept left→right over 8 s → engage the Transition Engine."

**Practical notes:** MIDI CC values are 0–127; the XDJ uses **different MIDI channels** for each deck and the mixer; smooth fader streams with a one-pole filter at frame rate. **Caveat:** the XDJ-XZ's exact MIDI map is poorly documented publicly, firmware/mode-dependent, and some controls may use HID rather than class-compliant MIDI — **remap empirically on hardware** ([10](10_OPEN_QUESTIONS_AND_ASSUMPTIONS.md)). On Windows, only one app can typically hold a MIDI input (historically) — handle the "port busy" case ([07](07_CROSSPLATFORM_STRATEGY.md)).

---

## 4. Lighting vocabulary (the words used everywhere)

| Term | Meaning |
|---|---|
| **Scene / Look** | A coherent visual state: a configuration of color, intensity, movement, effect across the rig |
| **Wash** | Soft broad colored light (pars, bars) — the ambient layer |
| **Beam / Spot** | Tight columnar / focused light from moving heads; cuts through fog |
| **Strobe** | Rapid flashing (1–25 Hz hardware); simulate in software on fixtures lacking a strobe channel |
| **Gobo** | Patterned disk projecting a shape; moving heads have a gobo wheel |
| **Color wheel** | Wheel of gels; pick a color by a channel value range |
| **Pan / Tilt** | Moving-head rotation (horizontal) / pitch (vertical) |
| **Dimmer** | Master brightness of a fixture (0=off, 255=full) |
| **Blackout / Freeze** | All channels to 0 / hold current state |
| **Chase** | Fixtures lighting in sequence |
| **Phrase** | A musical unit of 8/16 bars; scene rotations fire on these boundaries |
| **Additive layering** | Multiple passes combine by max/last-write; nothing overwrites |
| **Frequency-driven color** | The house rule: bass→red, mid→pink, high→cyan, all→white |

---

## 5. The anatomy of a DJ set (what lighting should mirror)

Electronic sets have repeating energy phases; the lights should track them:

- **Intro / breakdown (LOW):** sparse, filtered. Lights: low ambient wash, slow cool color cycling, maybe one slow moving-head sweep. *Use darkness deliberately.*
- **Build (RISING):** risers, snare rolls accelerating, filter opening. Lights: brightening wash, accelerating movement, strobe rate ramping (capped), warming toward white. *Movement and brightness climb monotonically.*
- **Drop (PEAK):** full mix, bass in, crowd peak. Lights: full intensity, white-heavy hits on the beat, lasers/beams engaged, strobe (within cap). **The drop lands on bar 1 of a phrase — the single most important sync moment.**
- **Outro / mix-out (DESCENDING):** track fading, next coming in. Lights: hold/fade, begin migrating palette toward the incoming track. This is where the Transition Engine works.

**Phrase structure:** music groups into **8/16/32-bar phrases**. Rotate scenes on those boundaries — more often reads as chaotic, less often as static.

**Loops:** when the DJ engages a loop (`loop_active`), the music repeats — **hold** the look (no rotation, no new colors), **release** on loop exit at the next phrase boundary.

**Transitions:** during a mix, the Transition Engine takes priority — hold the current scene, nudge brightness up, then crossfade to a new scene on the new track's first downbeat, and **hold ≥4 bars** before the Phrase Engine may rotate again.

---

## 6. What "good DJ lighting" means here

Reference aesthetics (and what to emulate — full detail in [08](08_LIGHTING_DESIGN_AND_SAFETY.md)):

- **Dom Dolla** — clean, restrained, color/wash-driven; uses negative space (darkness) as a tool; sparing on strobes.
- **John Summit** — punchy, high-contrast, decisive beat-locked hits; strobes reserved for drops so they keep impact.
- **Zedd** — choreographed, precision-timed; "looks timecoded even though it's run live."

The unifying principle: **musical, not chaotic.** Reinforce what the music is doing; don't fight it. Consistency (a fixed, sensible color/movement convention applied every time) is what makes automation read as *authored* rather than random — which is the real reason to keep the frequency→color rule locked.

---

## 7. How it all bridges (one sentence)

LiveReact takes two real-time inputs (PDL timing + MIDI intent), maintains one shared **ShowState**, runs three parallel engines (Reactive / Phrase / Transition) that write additively to a scene buffer, **merges** that with manual biases into a 512-byte DMX universe, and a writer thread blasts it at ~44 Hz to the daisy-chained rig — with a demo data source able to stand in for the hardware end-to-end.

Next: [04 — Hardware & Protocols](04_HARDWARE_AND_PROTOCOLS.md) for the rig, channel maps, and wire-level detail.
