# 14 — Audio-Reactive Scene Logic (planning, 2026-08-31)

Design for the next build phase, driven directly by Josh's brief: real audio-reactive
color/intensity, selective (not constant) laser triggering, silence → blackout, and
moving heads that read as "aimed at the stage" instead of roaming randomly. Genre
focus: EDM/house.

This is a planning doc, not a build log — sections marked **OPEN** need a decision
before implementation starts. **Stress-tested twice** (2026-08-31) against a
synthetic house track with known ground truth (sidechained kick/bass, hi-hats, a
real breakdown, a true-silence section) — see the ⚠️ callouts below.

- **Round 1** (`tools/simulations/audio_pipeline_sim.py` / `audio_sim_report.png`):
  found 3 real bugs testing each piece in isolation.
- **Round 2** (`audio_pipeline_sim_v2.py` / `audio_sim_v2_report.png`): applied all
  3 fixes *together* and re-ran — found a **4th, second-order bug that only showed
  up once the fixes were combined**: the mean-per-bin band fraction (the fix for
  bug #4 below) turned out to be a bad signal for onset detection specifically,
  because it saturates near 1.0 whenever *any* continuous bass is present, kick or
  no kick. Root cause: color needs a **normalized fraction**, onset detection needs
  **absolute energy** — conflating them was the actual mistake, not the
  normalization itself. Fixed by computing and exposing both signals separately.
  **All 4 fixes now verified together, not just individually:** band split
  balanced during silence, onset detector 80.3% recall / 98.0% precision, silence
  detector 0% false-positive on a realistically quiet breakdown / 93.6% correct
  on true silence. Rerun either script directly against real captured audio once
  the real capture pipeline exists.

---

## 0. The gap this closes

Everything in the current engine (`energy`, band-dominance color) is inferred from
**MIDI mixer-knob position** (`metronome._derive_energy`: `0.6·fader + 0.4·eq_open`),
not the actual sound. That's a fine proxy for an actively-mixing DJ, but it isn't
"intensity and frequency" in the sense Josh means, and it has no concept of silence.

**Real fix: read the actual audio.** Good news found while planning this — the
XDJ-XZ's USB-B cable (the same one already carrying MIDI) is *documented* to expose
a **USB audio interface** (`docs/04 §4.2`, unused until now).

> ⚠️ **STRESS-TEST FINDING (unverified assumption):** that "no new port needed"
> claim comes straight from a design-doc note written before any hardware testing
> — never actually confirmed. This is the exact category of mistake that bit us
> repeatedly tonight (wrong Par channels, wrong MIDI CC map, wrong default rig —
> all were untested written-spec guesses). **Before this architecture depends on
> it: verify the XDJ-XZ's USB audio interface genuinely enumerates in CoreAudio,
> at a usable sample rate/channel count, with the same cable already carrying
> MIDI.** If it doesn't, we're back to being port-constrained and need a real plan
> B (a small USB hub, most likely).

---

## 1. Audio capture + analysis subsystem (new)

```
XDJ-XZ USB audio (master/booth out — VERIFY which; see below)
  -> sounddevice capture callback: copies raw block into a ring buffer, NOTHING ELSE
  -> separate analysis thread: drains the ring buffer
       -> mono-sum L+R
       -> Hann-windowed FFT (numpy.rfft), small block (512-1024 samples)
       -> band split: low/mid/high (same 3 bands as the existing EQ concept)
       -> RMS loudness, VU-meter-style smoothing (fast attack / slow release)
       -> rolling "is a deck actually playing" check (see §2 — NOT raw silence alone)
  -> AudioLevelMessage(timestamp, rms, band_low, band_mid, band_high) -> input_queue
```

> ⚠️ **STRESS-TEST FINDING (real-time safety):** the diagram above deliberately
> separates capture from analysis. `sounddevice`'s callback runs on a real-time
> audio thread managed by PortAudio — doing FFT/numpy work *inside* that callback
> risks dropped audio blocks or stream errors if Python/GIL timing hiccups. The
> callback must do the absolute minimum (copy bytes into a thread-safe ring
> buffer); a separate thread does the actual analysis. Same producer/consumer
> discipline this project already uses for every other input source.

- **New dependencies: `sounddevice` *and* `numpy`.** Corrected count — the
  original draft only named `sounddevice`, but FFT needs `numpy`, and this
  project currently has **zero** base dependencies (`dependencies = []` in
  `pyproject.toml`). Both go under a hardware-mode-only optional group, same
  pattern as `mido`/`pyserial`/`python-prodj-link`.
- New `ShowSnapshot` fields, kept **separate from** the existing MIDI-derived
  `eq_low_a`/etc. (provenance matters — docs/04 §4.3's rule): `audio_energy`,
  `audio_band_low/mid/high` (normalized fractions, for color), `audio_band_low_abs`
  (absolute low-band energy, for the laser onset trigger — see the second-order
  bug below for why this needs to be a separate field, not derived from the
  normalized fraction), `audio_fresh`, `audio_playing`.
- **`band_levels()`/`two_axis_color()` need an actual rewrite, not just new
  fields bolted on.** Checked the real code: `band_levels()` currently picks EQ
  from "whichever deck's fader is louder" — a two-deck MIDI concept. Real audio
  is a single already-mixed signal, so these functions need explicit
  source-selection logic (real audio when `audio_fresh`, MIDI-deck-comparison
  fallback otherwise), not two parallel field sets sitting unreconciled.
- **Concrete starting numbers** (was left fully open before — no reason to,
  these are reasonable defaults to start from and adjust by ear):
  - FFT block: 512-1024 samples (~12-23ms @44.1kHz) — small on purpose, since a
    3-band split doesn't need fine frequency resolution, but visual reactivity
    does need low latency.
  - RMS smoothing: fast attack (~10-20ms), slower release (~200-300ms) — VU-meter
    shape, avoids frame-to-frame brightness flicker without feeling laggy.
  - Mono-sum L+R before analysis (simpler, avoids stereo-phase artifacts; no
    stated need for stereo-aware effects).
- **Loudness caveat for this genre specifically:** raw RMS isn't perceptual
  loudness. House/EDM sub-bass will dominate raw RMS without corresponding to
  how "energetic" a track actually feels, and could skew color to "bass red"
  almost constantly (`docs/08`'s hue convention: bass→red). Worth a
  perceptual/weighted loudness pass once real data is flowing, not on day one.
- **⚠️ SIMULATION FOUND A REAL BUG (band-splitting bin-count bias):** ran the
  proposed pipeline against a synthetic house track (128 BPM, sidechained kick/
  bass, hi-hats, a breakdown, and a true-silence section — known ground truth
  throughout). Summing raw FFT magnitude per band, as originally specified, is
  **biased toward whichever band has more FFT bins** — at the proposed 1024-
  sample block size, the high band (2-16kHz) has **65× more bins** than the low
  band (20-250Hz). Confirmed directly: pure noise-floor "silence" (no real
  spectral content at all) read as **64% high-band-dominant** under the
  sum-based method — which would show as cyan, not dark, purely from bin-count
  math, not real sound. **Fix, verified:** average magnitude *per bin* within
  each band instead of summing (normalizes for the bin-count disparity while
  keeping the musically-sensible unequal-Hz band boundaries). Confirmed this
  brings the same noise-floor block down to a roughly balanced 47/26/28
  low/mid/high split — no more phantom high-band bias.
- **⚠️ SECOND-ORDER BUG (found only by testing the fixes together, round 2):**
  applying the band-normalization fix broke the low-band-weighted onset
  detector — recall collapsed from 86.9% to 1.6%. Cause: the normalized
  `band_low` fraction saturates near 0.9-1.0 almost constantly during a
  groove, because the sidechained bassline is still present (just quieter)
  even *between* kicks, and with only 5 bins in the low band its mean-per-bin
  barely dips when ducked. Measured contrast kick-vs-quiet-gap: only 1.06×
  for the normalized fraction, vs. **2.35× for absolute (non-normalized)
  low-band energy**. **Fix:** compute and expose *two separate* low-band
  signals — a normalized fraction for color (what bug #4's fix produces) and
  raw/absolute low-band magnitude for onset detection (what the trigger
  actually needs). They are genuinely different signals for different jobs;
  conflating them was the mistake, not the normalization itself. Re-verified
  with both fixes together: onset detector back to 80.3% recall / 98.0%
  precision, band split still balanced during silence — both hold
  simultaneously now, not just individually (`audio_pipeline_sim_v2.py`).
- **Verify, don't assume, once hardware-testable:** which XDJ-XZ output the USB
  audio interface actually carries (master vs. booth — may be a device setting,
  not fixed), and validate the band-splitting against a **known test tone**
  (a generated sine wave) before trusting it against a real set — same
  verify-before-building-on-it approach as every hardware finding tonight.
- **Failure/degradation story:** missing `sounddevice`/`numpy`, or no matching
  input device found, should raise a clear error (same `ProDjLinkError`-style
  pattern already established) and the app continues in degraded mode — no
  audio reactivity, MIDI-proxy fallback still works, app doesn't crash.
- **Good sign, not a gap:** real `energy` slots directly into the *existing*
  `wash_level = energy × (floor + (1-floor) × pulse)` formula already in
  `ReactiveLayerEngine` — the slow audio-loudness baseline and the existing
  fast beat-locked pulse combine naturally. No new merge logic needed there.

### Monitoring / debugging — mostly already built
The console's `pb_low`/`pb_mid`/`pb_high` meters (`ui/console.py`) already exist
and are wired to `band_levels()` — once that function sources from real audio,
these meters show real audio levels with **zero new UI work**. Add one thing to
match the pattern from tonight: a red/green **"Audio"** status dot next to the
existing DJ BOARD (Link)/DJ BOARD (MIDI)/LIGHTS (DMX) dots, so the pipeline's
aliveness is a glance, not a guess. Also add a `--audio-device` CLI override
(matching `--pdl-interface`), so a specific input can be forced if
auto-detection guesses wrong or the XDJ interface turns out unavailable.

## 2. Silence → blackout

> ⚠️ **STRESS-TEST FINDING (would misfire on the exact genre this is for):**
> the original plan used raw RMS silence as the "no music" trigger. That's
> wrong for house/EDM specifically — a dramatic quiet breakdown before a drop
> is a genre hallmark, and it can be near-silent in raw RMS terms while the
> track is very much still playing. Blacking out during an intentional
> breakdown is the opposite of what's wanted.
>
> **Fix: make "is a deck actually playing" the primary signal, not audio
> silence.** We already have this — `pdl_fresh`/beat data stops the instant a
> deck is paused or stopped, but keeps flowing through a quiet breakdown
> because the deck is still playing. Use real audio silence only as a
> secondary confirmation (e.g. both "no beat data" *and* "genuinely silent"
> before blacking out), not as the trigger on its own.
>
> **⚠️ SIMULATED AND CONFIRMED (not just theoretical):** ran a naive RMS-only
> silence detector (threshold + 2s hold, the original plan) against a
> synthetic breakdown at a realistic quiet level. Result: **72.7% of the
> breakdown got incorrectly flagged as "silent."** At a louder breakdown level
> it correctly stayed silent-free — meaning the failure is real but threshold-
> dependent, which is exactly the trap: it'll work in casual testing and then
> misfire live on a quieter track. This is concrete, not hypothetical,
> evidence for the PDL-primary fix above.

Once `audio_playing` (deck-driven) confirms no music: treat it as an
**automatic blackout**, reusing the existing manual-blackout mechanism in
`merge/finalize` rather than inventing a second code path — same effect (all
channels zeroed, laser safety already forces off), just triggered
automatically instead of by the operator's button. Resuming → show resumes
normally (no special fade-in needed unless it feels too abrupt once tested).

## 3. Selective laser triggering (not "on for the whole drop")

Current: `uses_lasers` scenes hold the laser on continuously for the whole scene
(gated by DROP bucket + manual arm). Josh's ask: lasers should punctuate specific
moments, not run constantly — otherwise "overstimulating and boring."

Plan: add a lightweight **onset/transient detector** on top of the audio pipeline —
a sudden spike in high-band (or overall) energy above its recent rolling average
fires a brief laser flash (e.g. one beat, maybe two), then the laser drops back off
until the next real onset. Layers on top of the existing gating (still needs
DROP-bucket + armed) rather than replacing it — this changes lasers from
"held on for a scene" to "flashed on real hits within a scene."

- **RESOLVED BY SIMULATION (was open):** tested both candidates against 61
  known kick times in the synthetic track. **Overall/whole-signal RMS onset
  detection barely works: 3.3% recall (caught 2 of 61 kicks).** Cause: a
  sidechained house bassline keeps the rolling-average energy elevated
  continuously, so an individual kick's contribution to *overall* loudness
  isn't a big enough relative jump to trigger — it only fired on the much
  bigger transient of the whole groove re-entering after silence.
  **Low-band-energy onset detection is far better: 80.3-86.9% recall,
  94.6-98.0% precision** (range across two verification rounds — see the
  second-order bug below). Use that, not overall RMS — for house/EDM
  specifically, this is the trigger signal, not a genre-dependent toss-up.
  Important detail confirmed the hard way: it must be **absolute** low-band
  energy (`audio_band_low_abs`), *not* the normalized `audio_band_low`
  fraction used for color — the normalized version saturates near constant
  during a groove (a continuous sidechained bassline keeps it high even
  between kicks) and loses almost all its discriminative power (1.06×
  contrast vs. 2.35× for the absolute version, measured). (High-band-only
  for cymbal/riser-style hits is still worth adding as a *second*,
  independent trigger later — not tested here, no synthetic riser in this
  track — but low-band is the one that actually matters for the kick-driven
  "certain noises" Josh described.)
- **OPEN:** flash duration/decay shape — hard cut vs. a quick exponential decay
  like the existing beat-pulse.

### Idea captured, next step after this one (Josh, 2026-09-01): wub-driven laser speed

Distinct from onset detection above, not a variant of it. A "wub" bassline
(dubstep/bass-house wobble) isn't a transient spike — it's *sustained*
low-band energy that rhythmically oscillates in amplitude (an LFO-style
wobble). The spike-vs-rolling-average approach that works for kicks doesn't
detect this at all; it needs a different technique:

```
audio_band_low_abs (already real, from step 1)
  -> track its envelope over a longer window (~1 bar)
  -> estimate the envelope's OWN modulation rate — autocorrelation or a
     small FFT of the envelope itself, not the raw signal
  -> a detected wobble rate -> drives the laser's pattern/movement SPEED
     channel (CH9 "scale" or a rate-mapped pattern value — verify which
     channel actually controls perceived movement speed vs. shape, laser's
     own channel semantics are still only partially mapped, see docs/14 §1)
```

Josh's own framing is the right caution here: this needs real training/
tuning against a variety of real "sounds" and explicit criteria for what
counts as a wub vs. just bass — a genuinely bigger scope than a threshold
check. Natural next step after the onset-flash trigger above is built and
verified (same `core/laser_trigger.py` foundation, extended rather than
replaced), not a replacement for it — the onset flash still solves "lasers
running constantly," which was the original, more urgent ask.

### 3b. The bar's FEATURE profile — lasers as the main light (2026-10-01)

Everything above is the HOME answer: lasers are punctuation (the Bible's
§8.5), and `engines/laser.py` fires one sweep per 8-bar block in PEAK. The
bar residency inverts it: two lasers at 9 ft over a small dancefloor, haze,
and Josh's brief — "lasers on (almost) the whole time; a relatively chill
pattern while the music is in transition / build-up, possibly a solid line
or a curvy line moving / slowly changing colours, and after intense beat
drops the fast fanning pattern." Same audio/MIDI/PDL analysis.

Built as a second engine, not a mode switch inside the first (the accent
engine is verified live and stays byte-for-byte): `rigs/bar_rig.json` says
`"laser_profile": "feature"`, `app.py` builds `engines/laser_feature.py`'s
`LaserFeatureEngine`, and everything downstream duck-types. One mood per
tick from the debounced bucket — OFF (no audio) / CALM (break, outro,
unarmed build: the line at the slowest confirmed sweep, colour stepping
every 8 bars, the right laser one step ahead) / TENSION (build while
rising or armed: sweep climbs with the rise index) / GROOVE (a drop whose
hit is under 0.95: medium sweep) / FAN (hit ≥ 0.95, or the K cue: the full
wub-driven fan, held for the whole drop). Decisions Josh made 2026-10-01:
intense drops only, hold the whole drop; unison, one palette step apart in
calm. Deliberate deviations recorded in `spec/conformance.md`: §8.5's duty
rule (LASER-14) and PDL loss not cutting the laser (LASER-12). The
beam-height rule itself was removed on 2026-10-03 at Josh's request.

Still unverified bytes: the solid line, the curvy line, a still line, and
hardware colour drift — `Laser.PROBE_CANDIDATES` + `tools/laser_probe.py`,
TESTING.md Test 6. Offline evidence so far: `tools/simulations/
replay_laser.py` over every capture — calm 55% / fan 11% of recorded time,
zero fan rows outside DROP/PEAK; the one 82-minute set runs fan 38% because
nearly every recorded hit reads 1.00 (energy_norm re-normalises per track),
so "intense drops only" barely discriminates on long sets. Two knobs if
that reads as too much live, both one-line changes: raise `FAN_MIN_HIT`, or
add a fan length cap that settles to GROOVE after N bars.

## 4. Moving heads aimed at the stage, not roaming

Current: pan/tilt sweeps use an arbitrary center (`0.5`) with wide amplitude
(`sin(position·k)`), which can swing through most of the fixture's full pan
range (up to 450° on the real MH) — no concept of "this is the direction the
stage/crowd actually is."

Two options, not mutually exclusive:

- **A — Home-position calibration (buildable now).** Per fixture, calibrate a
  "facing the stage" pan/tilt value (jog it into place once, save it — same
  interactive spirit as the layout feature we just built). All scene movement
  then oscillates around that calibrated home within a bounded, tasteful range
  instead of an arbitrary fixed center — e.g. ±15–20% instead of the current
  wide sweep. Small, contained change to `Scene`/`ReactiveLayerEngine` position
  math; no new hardware input needed.
- **B — True spatial aim (bigger lift, stretch goal).** Extend the rig-layout
  canvas we just built with a "stage/target" marker and real-world height/
  distance per fixture, then compute the actual pan/tilt angle via trigonometry
  to point precisely at that target. Needs real measurements from Josh (mount
  height, distance to target) and 3D math the current 2D schematic canvas
  doesn't capture yet.

  **Idea captured 2026-09-01, not yet built:** Josh's suggestion for making
  the layout canvas venue-aware, rather than an unscaled abstract schematic —
  let the operator set a base venue shape/size (e.g. a 100ft×100ft square, or
  a 50ft-diameter circle) on the main UI, so fixture positions on the canvas
  carry real-world scale instead of just relative arrangement. This is
  actually the missing piece for option B above (true trigonometric aim needs
  real distances, which a scaled floor plan would provide) — and generalizes
  the layout tool to different venue shapes/sizes, which fits Josh's stated
  "many people's rigs" platform goal too. Bigger than step 3's actual scope
  (fixing "pointing randomly"), so deliberately deferred rather than built
  alongside it — worth returning to once B (or venue planning generally)
  becomes the active goal.

**Recommendation:** build A first — it directly fixes "pointing in random
directions" with a same-session-sized change, and doesn't block B later if
precise aiming turns out to matter.

**Status 2026-09-18: B is built** (Josh's venue floor-plan request). The rig
JSON now carries an optional `venue` block (width/length/height in meters,
named `targets`) and per-fixture `position`/`facing_deg`/`calibration`/`beam`
— schema in `src/livereact/fixtures/rig.py`'s docstring, coordinate
convention and the trig in `src/livereact/fixtures/geometry.py`. The console's
**Venue tab** (`ui/venue_tab.py`, drawing in `ui/floorplan.py`) is the scaled
floor plan: the operator types feet, drags fixtures and targets, then
calibrates a moving head by jogging the real unit onto the `dj_booth` target
and clicking SET AIM (one-point capture solves the pan/tilt offsets). Scenes
reach named targets through `scenes/base.py`'s `aim_spots` — the two
hardcoded guesses (`BreakSingleSpotSpecial`'s `dj_booth`, `OutroSingleBeam`'s
`ceiling_bounce`) now compute the real aim when the rig has geometry and fall
back to the old guess otherwise. Option A's `home_pan`/`home_tilt` still
exists (the ±10 % bounded motion for every other scene) and the Venue tab can
set it from a target ("Set home = target"). Pan/tilt went 16-bit for this
(`MovingHead.USE_FINE_CHANNELS`). Unverified on hardware as of this writing:
the fine channels, the one-point capture landing on a second target, and
the laser's CH7 0-127 static half (`Laser.set_static_line`, probe from the
Venue tab).

---

## 5. Suggested build order

1. ✅ **DONE (2026-08-31), built and confirmed live on real hardware.** Audio
   capture + FFT + band/RMS pipeline, wired into `ShowState`
   (`inputs/audio.py`, `AudioLevelMessage`, `Metronome`/`band_levels()`
   preferring real audio over the MIDI proxy when fresh). USB-audio-over-
   MIDI-cable assumption verified true (device `XDJ-XZ`, 8 in/12 out, 44.1kHz
   — channels 5&6 carry the live master/booth mix, 1-4 silent). `ENERGY_GAIN`
   calibrated against real captured playback (raw RMS ~0.009-0.047, p90
   ~0.03), not guessed. **Confirmed by Josh live**: the console's energy/
   low/mid/high meters visibly track the real playing track, and scene
   selection now responds to real audio energy instead of the flat
   MIDI-proxy value. 132 tests passing (9 new: `test_audio.py` +
   audio-preference tests in `test_metronome.py`/`test_color.py`, including a
   regression test pinning down the bin-count band bias so it can't return).
2. ✅ **DONE, confirmed live on real hardware.** Silence → auto-blackout
   (`core/silence.py`, `SilenceDetector`), gated on "deck actually playing"
   (`pdl_fresh`) as primary signal, real audio as secondary confirmation only
   when audio is available, 3s hold to survive brief PDL hiccups — matches
   the stress-tested design exactly. `finalize()` gained an independent
   `auto_blackout` param (kept separate from `manual.blackout` so the
   operator's switch and the automatic one never fight over shared state).
   New console indicator distinguishes auto- from manual blackout. **Verified
   live**: paused the real track → `pdl=STALE`, `audio=fresh` confirmed
   `energy=0.00`, output genuinely zeroed (0/512 channels active, sustained)
   after the hold; resumed → relit instantly, no lag, no lingering blackout.
   7 new tests (`test_silence.py` + 2 ShowEngine integration tests + 1 merge
   test) — 139 passing total.
3. ✅ **DONE, confirmed live on real hardware.** MH home-position calibration
   + bounded movement — built as a finalize-stage transform
   (`Fixture.apply_home_position`, no-op default on the base class,
   overridden on `MovingHead`), not a rewrite of every scene's position math:
   it remaps whatever raw pan/tilt a scene set (all assume the old
   0.5-centered convention) around a calibrated `home_pan`/`home_tilt`,
   scaled into a ±10% bound (`bound=0.20`). Calibration UX reuses the
   existing `--fixture-test` panel (already proven for live jogging) rather
   than building a new live-jog UI — jog pan/tilt/dimmer live, hit "Save as
   Home Position," which persists `home_pan`/`home_tilt` into the rig JSON
   alongside the layout `x`/`y` from step-adjacent work. Uncalibrated
   fixtures (`home_pan is None`) keep the old raw sweep unchanged — fully
   backward compatible. **Verified live**: calibrated to an arbitrary test
   reference point (pan=0.0, tilt=0.0 — no real venue available this
   session, see note below), forced `FullSpectrumHit` (one of the widest
   raw sweeps in the catalog), measured actual DMX bytes going to the real
   fixture — pan stayed within 0-23 and tilt within 0-18 (out of 0-255),
   tightly bounded around home instead of the raw sweep's ~13-242 range —
   then confirmed visually by Josh: "sweep was relatively narrow... would
   cover a stage. It looked good." 9 new tests (4 in `test_fixtures.py`, 1 in
   `test_rig.py`, 1 in `test_merge.py`) — 148 tests passing (was 139).

   **Idea captured, not yet built** (Josh, 2026-09-01): a venue-aware floor
   plan for the rig-layout canvas — let the operator set a base venue
   shape/size (e.g. a 100ft×100ft square or a 50ft-diameter circle) so
   fixture positions carry real-world scale instead of being an unscaled
   abstract schematic. This is also the missing piece for option B above
   (true trigonometric aim needs real distances) and fits the "many
   people's rigs" platform goal. Deliberately deferred — bigger than step
   3's actual scope, no real venue was available this session to calibrate
   against anyway.
4. Laser onset-triggered flashing (the audio pipeline it needs is now real).

Each step is independently testable on real hardware before moving to the next —
same verify-before-building-on-it discipline as the rest of tonight.
