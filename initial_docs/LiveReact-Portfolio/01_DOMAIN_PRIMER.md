# 01 — Domain Primer

This document covers the four domains LiveReact lives at the intersection of: **DMX-512** (lighting wire protocol), **Pro DJ Link** (Pioneer's musical-clock network), **MIDI** (DJ controller event stream), and **lighting design** (the actual show). Read this end-to-end before touching the architecture document. None of it is hard once you've seen it, but it's all unfamiliar if you've never done a show before.

---

## 1. DMX-512: the lighting wire protocol

DMX-512 (formally ANSI E1.11) is the protocol that lighting fixtures have spoken since 1986. Once you internalize it, everything else clicks.

### Wire format

- A DMX **universe** is a single chain of up to **512 channels**.
- Each channel is **one byte** (value 0–255).
- The host sends the entire universe ~44 times per second (44 Hz) as one packet over an RS-485 serial line at 250 kbps.
- The packet has a fixed structure: a **break** signal (lines held low), a start byte (0x00 = standard dimmer data), then up to 512 channel bytes back-to-back.
- Every fixture on the chain sees every byte. Each fixture is configured with a **start address** (1–512) and **reads its own slice** of channels starting from there.

### Daisy-chain topology

```
Host (Enttec DMX USB Pro)
  │
  ╞═══ XLR-3 ═══▶ Fixture 1 (DMX 1, 15ch)
                       │
                       ╞═══ XLR-3 ═══▶ Fixture 2 (DMX 16, 15ch)
                                            │
                                            ╞═══ ... ═══▶ Last fixture
                                                               │
                                                               ▼
                                                       120Ω terminator
```

Each fixture has DMX-IN and DMX-OUT. You daisy-chain them with XLR cables. The last fixture in the chain needs a **120Ω terminator** (a resistor soldered into a male XLR plug) to prevent signal reflection. Without termination, the chain becomes flaky as it gets longer.

### Key consequences for the code

- DMX is **stateless and unidirectional**. The host blasts the full universe state 44 times a second. No "set this channel" command; there's just "here is the entire universe." If you want a fixture's red channel to be 200, you write 200 into your in-memory universe buffer at that channel's index, and the writer thread keeps sending the whole buffer.
- **Resolution is one byte.** No fractional brightness. For smooth fades you ramp the value over multiple frames.
- **Some fixtures have "fine" channels** (e.g., the SHEHDS moving head has `Pan` and `Pan fine` — together they form a 16-bit position value). The coarse channel is the high byte, fine is the low byte.
- **Channel meaning is fixture-specific.** Channel 1 of a moving head is "pan." Channel 1 of an RGBW par is "red." You can't generalize. Each fixture has a **profile** that maps channel offsets to semantic names.
- **No checksum, no acknowledgement.** A fixture either gets the packet or it doesn't. If your cable is bad or your refresh is too slow, lights flicker or freeze.
- **44 Hz refresh = ~22 ms per frame.** Lighting reacts plenty fast at this rate. Don't try to write the universe faster than that.

### The Enttec DMX USB Pro specifically

Our DMX adapter is an **Enttec DMX USB Pro**. It's a USB-to-DMX converter that:

- Shows up as a serial port on macOS (`/dev/tty.usbserial-XXXX` or `/dev/cu.usbserial-XXXX`).
- Speaks a documented packet protocol over serial: you send it a 518-byte frame (5-byte header + 512 DMX bytes + end byte) and it handles the DMX-side timing.
- Wants frames at roughly 30–44 Hz. Sending faster doesn't help and may stress the device.

The driver code is short — open the serial port, write framed packets in a tight loop. See `pyserial` and the Enttec USB Pro Widget API spec.

---

## 2. Fixtures, channels, and profiles

A **fixture** is any physical lighting unit on the DMX chain: a moving head, a laser, a par can, a wash bar. Each one occupies a contiguous block of DMX channels starting at its **DMX address**.

### Example: a 4-channel RGBW par

```
DMX address: 1
Channels:
  CH 1 (DMX 1): Red       0-255
  CH 2 (DMX 2): Green     0-255
  CH 3 (DMX 3): Blue      0-255
  CH 4 (DMX 4): White     0-255
```

A second RGBW par on the same chain might be at DMX address 5 (occupying channels 5–8), and so on. **You configure the DMX address on the fixture itself**, usually via a small display on the back. The fixture also lets you pick its channel **mode** — for example, the SHEHDS 180W moving head can run in different channel modes (8ch, 15ch, 16ch...) depending on how much control you want. We always use 15ch for the moving head.

### Fixture **profiles** in software

A profile is a data structure that describes a fixture type:

```python
class SHEHDS180WMovingHead:
    NAME = "SHEHDS 180W Moving Head (15ch)"
    CHANNEL_COUNT = 15
    CHANNELS = [
        ChannelDef(number=1,  name="pan",        default=128),
        ChannelDef(number=2,  name="pan_fine",   default=0),
        ChannelDef(number=3,  name="tilt",       default=80),
        ChannelDef(number=4,  name="tilt_fine",  default=0),
        ChannelDef(number=5,  name="speed",      default=128),
        ChannelDef(number=6,  name="dimmer",     default=0),
        ChannelDef(number=7,  name="strobe",     default=0),
        ChannelDef(number=8,  name="color",      default=0),
        ChannelDef(number=9,  name="gobo",       default=0),
        # ... etc through ch15
    ]
```

The scene code says `mh.set("dimmer", 200)` — the profile knows that maps to byte 6 of this fixture's slice of the universe. The scene never touches DMX byte indices directly.

**Full per-fixture channel maps are in `02_HARDWARE_RIG.md`.**

---

## 3. Pro DJ Link: musical timing from the controller

Pro DJ Link is **Pioneer's proprietary networking protocol** that Pioneer DJ gear (CDJs, XDJs, DJM mixers) use to share state — beat phase, BPM, track position, master deck, loop state — over an Ethernet connection. Every Pioneer unit on the network broadcasts and listens to UDP packets on specific ports.

### Why this matters more than audio analysis

The v1 version of LiveReact used **USB audio FFT** — sampling the master out, running FFT, detecting beats from RMS peaks. This works, but it's noisy in real DJ sets: limiters compress the dynamic range, basslines bleed into mids, sub-bass washes the low band, and beat detection drifts when DJs do filter sweeps or apply effects.

Pro DJ Link cuts past all of that. The XDJ-XZ **knows** the exact BPM (it's reading it from the loaded track's analysis), it **knows** the beat phase (it computed it during track analysis in Rekordbox), it **knows** when a loop is active and when one is released, and it **knows** which deck is currently outputting audio ("on air").

You're not estimating timing — you're reading it from the source.

### What Pro DJ Link gives us

The library we use (`python-prodj-link`) exposes these per-deck:

| Field | Meaning |
|---|---|
| `bpm` | Current BPM with sub-decimal precision (e.g., 124.03) |
| `beat` | Which beat of the bar we're on (1, 2, 3, 4) |
| `bar` | Which bar of the phrase we're on (loops 1..N) |
| `beat_phase` | Sub-beat fractional position (0.0–1.0), updated continuously |
| `track_id` / `track_position` | What's playing and where in the track |
| `loop_active` | True if the DJ has engaged a loop |
| `on_air` | True if this deck's audio is currently going to the master output |
| `master` | True if this deck is the sync master |

### Connection setup

- The XDJ-XZ has an Ethernet port. Connect it directly to the MacBook's Ethernet (USB-C-to-Ethernet adapter on a modern Mac).
- Both machines need to be on the same subnet — usually a link-local IPv4 (`169.254.x.x`) auto-negotiates when nothing else is plugged in, or you can configure a static IP on both sides.
- Pro DJ Link traffic is UDP broadcast. The library listens for it, parses the packets, and exposes the structured state.
- **`python-prodj-link` has been confirmed working with the XDJ-XZ.** Use that library, not a fork.

### Failure modes to handle

- The XDJ takes ~2–3 seconds after boot to start broadcasting.
- If the Ethernet cable is unplugged mid-set, packets stop arriving. The code must detect staleness and fall back to a local metronome that continues at the last known BPM.
- Beat jitter: the actual packet arrival jitter can be 5–20 ms. For tight visual sync you'll want a local metronome that's synced to incoming beat packets but interpolates between them.

---

## 4. MIDI: reading the DJ's hands

MIDI is the protocol DJ controllers use to send their physical control state to a computer. The XDJ-XZ shows up as a USB MIDI device on macOS, and every knob, fader, button, and EQ produces a MIDI message you can read.

### What we actually care about

LiveReact does *not* use MIDI to control the lights. It uses MIDI to **observe the DJ's intent**:

| MIDI control | Why we read it |
|---|---|
| **Channel fader A** (deck 1 level) | When this rises, deck 1 is becoming audible — a mix is starting |
| **Channel fader B** (deck 2 level) | Same for deck 2 |
| **Crossfader** | Lateral position between the decks; the canonical "we're transitioning" signal |
| **EQ knobs** per channel (low / mid / high) | Tells us when the DJ has killed bass or filtered out highs — useful for energy detection |
| **Cue / play buttons** | Detect a new track being cued or started |

These are read-only inputs. We never send MIDI back to the XDJ.

### Why MIDI in addition to Pro DJ Link

Pro DJ Link tells us **what the music is doing**. MIDI tells us **what the DJ is doing with the music**. The combination is much more powerful than either alone:

- PDL says "deck 2 BPM 128, beat 3 of bar 16, on-air, loop active"
- MIDI says "crossfader is moving from full-left to full-right over the past 8 seconds"
- Together: "the DJ is mid-transition from deck 1 to deck 2 — engage the Transition Engine."

### Implementation notes

- Use `mido` or `python-rtmidi` — both work on macOS.
- The XDJ-XZ MIDI map is in `APPENDICES/C_XDJ_XZ_MIDI_MAP.md`.
- MIDI control change (CC) values are 0–127. Faders send a stream of CC messages as they move.
- Smooth incoming fader values with a short rolling average (e.g., 50 ms) before using them as signals.

---

## 5. Lighting design vocabulary

These are the words and concepts that show up throughout the rest of the docs.

| Term | Meaning |
|---|---|
| **Scene** | A coherent visual *state* — a specific configuration of color, intensity, movement, and effect across the rig. "Drop scene," "build scene," "breakdown scene." |
| **Look** | Casual synonym for scene, sometimes used for a static still moment. |
| **Wash** | Soft, broad colored light — typically from RGBW pars or wash bars. The "ambient" layer. |
| **Beam** | A tight columnar shaft of light — from moving heads or beam fixtures. Cuts through fog. |
| **Spot** | A focused circular projection — same hardware as a beam usually, just with different optics. |
| **Strobe** | Rapid flashing, typically 1–25 Hz. Hardware fixtures have a built-in strobe channel; for fixtures without one (RGBW pars), you simulate it in software by flashing RGB values. |
| **Gobo** | A patterned disk in front of the lamp that projects a shape (dots, lines, breakup patterns). Moving heads have a "gobo wheel" with multiple options. |
| **Color wheel** | A wheel of colored gels in the fixture; you pick a color by setting the color channel to a specific value. |
| **Pan / Tilt** | Movement axes on a moving head. Pan = rotation around the vertical axis. Tilt = pitch up/down. |
| **Dimmer** | Master brightness channel for a fixture. Goes to 0 = blackout, 255 = full. |
| **Blackout** | Everything to 0. Emergency or transition state. |
| **Chase** | A pattern where fixtures light up in sequence ("running lights"). |
| **DMX address** | The starting channel number a fixture reads from. |
| **Universe** | One DMX-512 chain (up to 512 channels). We use exactly one universe. |
| **Fixture profile** | Software description of what each channel of a fixture does. |
| **Frequency-driven color** | Our locked rule: bass freqs → red, mid → pink/magenta, high → cyan, all → white. |
| **Additive layering** | Multiple lighting passes combine by adding/maxing their outputs; nothing overwrites. |

---

## 6. The anatomy of a DJ set

A live electronic DJ set has structure. Every house, techno, EDM, or melodic-techno set goes through repeating phases — and the lights should mirror them. The four phases that matter most:

### Intro / breakdown (LOW energy)
- Sparse, often just kick and a melody
- Lights: low ambient wash, slow color cycling, maybe a single moving head doing slow sweeps
- Color: cooler — blues, magentas, dim cyan

### Build (RISING energy)
- Tension layer comes in — risers, claps, snares accelerating
- Lights: brightening wash, accelerating movement, increasing strobe rate
- Color: warming — pinks, reds, oranges

### Drop (PEAK energy)
- The track's main event — bass drops, full mix, crowd peak
- Lights: full intensity, hard hits on every beat, strobes engaged, lasers active, moving heads at peak movement
- Color: full-spectrum, often white-heavy on hits

### Outro / mix-out (DESCENDING energy)
- DJ is fading this track and bringing in the next
- Lights: hold steady or fade slightly, prepare to transition palette as the new track takes over
- This is when the **Transition Engine** does its work

### Phrase structure

Within any phase, music is organized in **phrases of 8 or 16 bars** (32 or 64 beats). A bar is 4 beats. A drop typically hits on bar 1 of a 16-bar phrase. A build ramps over 16 or 32 bars.

**Our Phrase Engine fires scene rotations on 8 or 16 bar boundaries** — meaning every 32 or 64 beats, we may change the active scene. This keeps the visuals fresh without changing them so often that they feel chaotic.

### Loops and the "hold" pattern

DJs often **engage a loop** during a set (loop 4 beats, 8 beats, 16 beats). When a loop is active:
- Pro DJ Link reports `loop_active = true`
- The musical content is now repeating
- Lights should "hold" — not rotate scenes, not introduce new looks — and **release** when the loop ends

### Transitions between tracks

A DJ transition is when one track is mixed out as another comes in. Indicators:
- MIDI crossfader is moving
- Or both channel faders are up while one is being faded
- Or the "on-air" deck changes in Pro DJ Link
- BPMs may briefly differ between the two decks

During a transition, the **Transition Engine** takes priority over the Phrase Engine: hold the current scene, increase brightness slightly, then crossfade to a new scene synchronized with the new track's first downbeat after the mix completes. **Always hold the new scene for at least 4 bars after a transition** before allowing the Phrase Engine to rotate again.

---

## 7. What "good DJ lighting" looks like

LiveReact is being built to drive a personal rig for Josh's DJ sets. The aesthetic reference points are:

- **Dom Dolla** — clean, restrained, color-driven. Lighting that breathes with the track instead of attacking it. Heavy on washes, sparing on strobes.
- **John Summit** — punchier, more contrast, hard hits on drops. Strobes engage at drops but never feel cheap.
- **Zedd** — high-production, choreographed feel. Even when automated, it should feel intentional.

The thread is: **musical, not chaotic**. Lights should reinforce what the music is doing, not fight it. A frenetic, color-randomizing light show is worse than a simpler one that locks tightly to the beat.

This is why frequency-driven color is non-negotiable. The human brain pairs low-frequency sound with warm/red, high-frequency with cool/cyan. Violating that pairing makes the show feel "off" even if the viewer can't articulate why. See `04_DESIGN_PRINCIPLES.md` for more on this.

---

## 8. How LiveReact bridges all of this

Read this paragraph last; it ties everything together.

LiveReact receives two real-time inputs (Pro DJ Link over Ethernet and USB MIDI), maintains a single in-memory **ShowState** that all consumers read from, and runs three engines in parallel that write to a shared **scene buffer**: a **Reactive Layer** that pulses on every beat, a **Phrase Engine** that rotates scenes on 8/16-bar boundaries, and a **Transition Engine** that takes over during mixes. Their combined output is **merged** with manual UI biases ("ManualParams") and then written to a 512-byte **DMX universe buffer**, which an Enttec USB Pro driver thread blasts out at ~44 Hz to the daisy-chained rig.

That's the whole system in one sentence. The rest of this portfolio fills in how each piece works.

---

## Reading checklist

You should now know:

- [ ] What a DMX-512 packet is and why it's stateless
- [ ] What a fixture profile is
- [ ] What Pro DJ Link gives us and why it's better than audio analysis
- [ ] What we use MIDI for (DJ intent signal — read only)
- [ ] What a "scene" and a "phrase" mean in this codebase
- [ ] The four phases of a DJ set and what should happen to lighting in each
- [ ] Why frequency-driven color is locked

Next: **`02_HARDWARE_RIG.md`** — every fixture, every channel, every address.
