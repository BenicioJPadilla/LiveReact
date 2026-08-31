# E — Glossary

Terms used throughout the portfolio, alphabetical. Covers lighting, DJ, and DMX vocabulary. Cross-references in **bold** point to other entries.

---

**Address (DMX address).** The starting channel number a **fixture** reads from on the **universe**. Set on the fixture's local display. A 4-channel fixture at address 5 reads channels 5–8.

**Additive layering.** LiveReact's design pattern where multiple engines contribute to the same **scene buffer** without overwriting each other; the **merge layer** combines contributions per-channel (max for color/dimmer, last-write-wins for movement).

**Auto-IP / link-local.** A fallback IP assignment in the `169.254.0.0/16` range that two devices fall into when no DHCP server is available. Lets **Pro DJ Link** work over a direct Ethernet cable with no router.

**Bar.** Four beats. The unit musical phrases are measured in. A 16-bar phrase = 64 beats.

**Beam.** A tight columnar shaft of light. Moving heads produce beams. Cuts visibly through fog.

**Beat.** One quarter-note pulse in the music. At 120 BPM, beats are 500 ms apart.

**Beat phase.** Sub-beat fractional position (0.0–1.0). LiveReact's **local metronome** computes this for smooth visual animation between **PDL** beat packets.

**Blackout.** All channels to 0. The "panic" state. Engines keep running underneath; only the final write is zeroed.

**BPM.** Beats per minute. Tempo. House music is typically 124–130; techno 130–140.

**Breakdown.** A low-energy section of a track where the main groove drops out. Lighting should match: lower brightness, slow color cycling.

**Build.** A rising-energy section preceding a **drop**. Risers, snares, claps accelerate. Lighting should ramp.

**CC (Control Change).** A type of MIDI message used for continuous controllers (faders, knobs, EQs). Each CC has a number (0–127) and a value (0–127). See `APPENDICES/C_XDJ_XZ_MIDI_MAP.md`.

**Channel (DMX).** One byte (0–255) in the DMX **universe**. Channels are addressed 1–512.

**Channel (MIDI).** A 0-15 numeric subdivision of MIDI traffic, allowing multiple "instruments" on one MIDI port.

**Channel fader.** The vertical slider on a DJ mixer that controls one deck's audio level. Different from **crossfader**.

**Chase.** A pattern where fixtures light up in sequence (e.g., left-to-right). A common look.

**Color wheel.** A wheel of colored gels inside a fixture; you select a color by setting the color-wheel channel to a specific value range.

**Crossfader.** The horizontal slider on a DJ mixer that blends between two decks. Center = both, full-left = deck A only, full-right = deck B only.

**Deck.** One of the multiple "players" in a DJ setup. The XDJ-XZ has 4 internal decks.

**Demo mode.** LiveReact's no-hardware mode. Synthetic **ShowState** values are produced by `DemoDataGenerator` instead of real **PDL** and **MIDI** listeners. Used for development without the rig.

**Dimmer.** A channel that controls master brightness of a fixture. 0 = off, 255 = full.

**DMX address.** See **Address**.

**DMX-512.** The lighting wire protocol used by almost all stage and club gear. See `APPENDICES/A_DMX_512_PROTOCOL.md`.

**DMX universe.** A single DMX-512 chain of up to 512 channels. LiveReact uses one universe.

**Downbeat.** Beat 1 of a bar. Musical impacts (drops, accents) usually land here.

**Drop.** The peak-energy moment of a track. Bass kicks in full, full mix engaged. Lighting goes to peak: lasers, strobes, full color saturation.

**Energy.** A subjective signal estimating how intense the current music is (0.0–1.0). Derived from EQ states, **fader** positions, and music context. Used by scenes to scale intensity.

**Enttec DMX USB Pro.** The USB-to-DMX adapter LiveReact uses. Appears as a serial port; speaks a documented frame protocol. See `APPENDICES/A_DMX_512_PROTOCOL.md`.

**EQ.** Equalization knobs on a DJ mixer, typically Low/Mid/High per channel. DJs often "kill" the bass on an incoming track during a mix, then bring it back at the right moment.

**Fader.** Any slider. See **Channel fader** and **Crossfader**.

**Fixture.** Any physical lighting unit on the DMX chain — moving head, laser, par, wash bar.

**Fixture profile.** Software description of a fixture type: how many channels it occupies and what each channel means.

**Frequency-driven color.** LiveReact's locked rule: bass → red, mid → pink, high → cyan, all → white. See `04_DESIGN_PRINCIPLES.md` section 1.

**Frost.** A diffusion effect — softens a beam into a wash. Some moving heads have a frost channel.

**Gobo.** A patterned disk in front of a fixture's lamp that projects a shape (dots, lines, breakup patterns). Moving heads have a gobo wheel with multiple choices.

**Hold.** Pause scene rotation. Triggered during loops, during transitions, and for the 4-bar minimum after transitions complete.

**Intensity.** A 0.0–1.0 parameter passed to a **scene**'s render method, used by the **Phrase Engine** for crossfades.

**Laser.** A fixture that produces coherent-light patterns. LiveReact's lasers are RGB 3W units, used sparingly (typically only in **drop scenes**).

**Local metronome.** A LiveReact thread that maintains a smooth beat phase clock, resyncing to **PDL** beats but interpolating between them at 60+ Hz. Mitigates PDL packet jitter.

**Look.** Casual synonym for **scene**.

**Loop.** When a DJ engages the loop function on a deck, looping a 4/8/16/32-beat segment. **PDL** reports `loop_active` so LiveReact can hold visuals during loops.

**ManualParams.** LiveReact dataclass holding user-controllable biases from the UI (master brightness, strobe cap, laser enable, blackout, freeze). Applied as caps and biases by the **merge layer**, not as overrides.

**Master deck.** The deck currently considered the BPM/sync master in **PDL**. Other decks sync to it. Changes during DJ sets as transitions complete.

**MBS (Mark Between Slots).** Optional gap between bytes in a **DMX** packet. Handled by the **Enttec**, not application concern.

**Merge layer.** LiveReact module that combines scene buffer contributions into the final DMX universe, applies **ManualParams**, and produces the buffer the DMX writer thread reads.

**MIDI.** Musical Instrument Digital Interface. Standard protocol used by DJ controllers to send physical control state (fader positions, button presses) over USB.

**Mix / mix-out.** When a DJ transitions from one track to another. Detected by **MIDI** crossfader movement or `on_air_deck` change in **PDL**.

**Moving head.** A fixture that can pan and tilt — physically aim a beam in different directions while running.

**On-air.** The state of a deck whose audio is currently going to the master output. **PDL** reports this per deck.

**Pan.** Horizontal rotation of a **moving head**. The XDJ moving heads rotate 450°.

**Par / Par can.** A simple LED light fixture, typically RGBW with no mechanical movement. Provides a static wash from a fixed direction.

**Patch.** The configuration mapping DMX addresses to fixtures. In LiveReact, this is the **rig file**.

**PDL.** Pro DJ Link. See **Pro DJ Link**.

**Phrase.** A musical unit of 8 or 16 bars. **Phrase Engine** fires rotations on phrase boundaries.

**Phrase Engine.** LiveReact engine that rotates active **scenes** on phrase boundaries.

**Pro DJ Link.** Pioneer DJ's proprietary networking protocol for sharing musical state (BPM, beat, bar, loop, on-air) over Ethernet between Pioneer gear and listeners. See `APPENDICES/B_PRODJLINK_PROTOCOL.md`.

**Prism.** A glass prism that splits a single beam into multiple beams. Some moving heads have a prism channel.

**Reactive Layer.** LiveReact engine that produces always-on beat pulses and BPM-locked movement.

**Refresh rate.** How often the DMX universe is transmitted. LiveReact targets 30–44 Hz.

**Rekordbox.** Pioneer's DJ software. Pre-analyzes tracks (BPM, beats, structure) before DJ sets. **PDL** transmits Rekordbox-derived data live.

**Rig.** The entire physical lighting setup. LiveReact's **rig file** describes it.

**Rig file.** JSON file (e.g., `rigs/full_show.json`) describing which fixtures are present, their addresses, and their roles.

**RGBW.** Red, Green, Blue, White — four-color LED with a dedicated white emitter (better than mixing RGB for pure whites).

**RMS.** Root Mean Square — a measure of audio loudness. Used in **v1** for beat detection (abandoned in v2).

**Scene.** A coherent visual look — a specific configuration of color, intensity, movement, and effect across the rig.

**Scene buffer.** The intermediate buffer engines write into before the **merge layer** combines them.

**Show engine.** LiveReact's main tick loop. Runs at ~60 Hz, calls each engine's `tick()`, runs the merge layer, writes the universe.

**ShowState.** LiveReact's shared data bus. A single dataclass holding all current input state. Listeners write to it; engines read from it.

**Sneak (sneak in / sneak out).** Slowly bring a light up or down so the change isn't perceptible. Used in **breakdown** scenes.

**Snapshot.** An atomic frozen copy of ShowState, taken at the start of an engine's tick. Prevents reading torn state.

**Spot.** A focused circular projection from a moving head or spotlight. Same hardware as a **beam** typically; optics differ.

**Start address.** See **Address**.

**Start code.** First byte of a DMX packet. `0x00` = standard dimmer data (LiveReact only uses this). Other codes (`0xCC` for RDM, etc.) exist but aren't used.

**Strobe.** Rapid flashing. Fixture strobe channels handle rates from 1–25 Hz. For fixtures without a strobe channel (RGBW pars), strobing is simulated in software.

**Tap tempo.** A way to manually set BPM by tapping a key in time with the music. Used as an emergency fallback when **PDL** is unavailable.

**Termination (DMX).** A 120Ω resistor at the end of the DMX chain to prevent signal reflection. Required for reliable operation.

**Tilt.** Vertical rotation of a moving head. Typically ~210° range.

**Transition.** A DJ mixing from one track to another. Detected by **MIDI** crossfader movement and **PDL** `on_air_deck` changes. Handled by **Transition Engine**.

**Transition Engine.** LiveReact engine that takes priority during DJ transitions, suspends **Phrase Engine**, holds the current scene, and crossfades to a new scene at completion.

**Trim (DJ).** Per-channel gain adjustment on a DJ mixer, before the **channel fader**.

**Universe (DMX).** One DMX-512 chain of up to 512 channels. LiveReact uses one universe.

**v1.** The first working version of LiveReact, built around USB audio FFT. Worked but had reliability issues. See `REFERENCE/v1_codebase/NOTES.md`.

**v2.** The current architecture. Replaces audio FFT with **Pro DJ Link** + **MIDI**. See `03_ARCHITECTURE.md`.

**v2 Phase 1.** The completed first phase of v2 — input layer + ShowState foundation. Engines were never finished. See `REFERENCE/v2_phase1_notes.md`.

**Wash.** Soft, broad colored light from a par or wash bar. The "ambient" layer of a lighting design.

**Wash bar.** A horizontal bar of multiple RGBW LEDs, providing wide-area wash light. LiveReact's are 288-LED units.

**Widget API.** The Enttec DMX USB Pro's host-side protocol. Frames are `[0x7E][label][LSB][MSB][payload][0xE7]`. See `APPENDICES/A_DMX_512_PROTOCOL.md`.

**XDJ-XZ.** Pioneer's all-in-one DJ system — 4-deck controller + mixer + screen, supports USB MIDI and Pro DJ Link over Ethernet. The source of all musical input to LiveReact.

**XLR.** The connector type used for DMX cables (3-pin or 5-pin). LiveReact uses 3-pin.
