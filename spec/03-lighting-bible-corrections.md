# LIGHTING_BIBLE.md — Correction Patch List

**Status: apply all six before running any code audit against LIGHTING_BIBLE.md.**
Auditing LiveReact's code against the *uncorrected* Bible produces a clean
report and an unsafe engine — see C1.

**Source documents** (both PDFs, not yet in this repo):
`~/Downloads/LIGHTING_BIBLE.md — Evidence Verification Report.pdf` and
`~/Downloads/SHOW_EVIDENCE.md — Observational Evidence Log- Light Use in
Professional House Shows.pdf`.

**How to use this file**: it patches specific sections of the original
28-page `LIGHTING_BIBLE.md` reference (`~/Downloads/Claude.pdf`). It does
NOT attempt to reproduce the Bible in full — only the corrected sections are
given here, verbatim from the evidence-verification pass. Wherever this file
and the original Bible disagree, this file wins. See
`[[livereact-lighting-bible]]` (Claude's memory) for how these corrections
interact with LiveReact's actual current code.

---

## C1 — Strobe safety: close the provocation band (§13) — **CRITICAL**

Current Bible text permits sustained strobe ≤ 4 Hz, with short bursts allowed
"to fixture-native max" if ≤ 1.5 s and spaced ≥ 5 s.

**Problem.** Fixture-native max on a modern LED strobe is 20–25 Hz.
Published clinical work places the peak photosensitive-seizure provocation
near 16 Hz, with 15–25 Hz the most provocative band and 10–20 Hz the range
designers are advised to avoid outright. The current burst allowance drives
straight through it.

**Replace with:**

```
SAFE-01  Sustained strobe rate must not exceed 4.0 Hz.
         Basis: UK HSE recommendation for strobe lighting in clubs and at public
         performances, max 4 flashes/second. [VERIFIED]
SAFE-02  No commanded strobe rate may fall within 10.0-25.0 Hz, for any duration,
         including single bursts. This band is clamped to 4.0 Hz.
         Basis: Fisher et al., Epilepsia 2026 (doi:10.1111/epi.18702) - avoid bright
         flashing in the 10-20 Hz range; Fisher et al., Epilepsia 2005;46:1423-1425 -
         15-25 Hz most provocative, peak response ~16 Hz. [VERIFIED]
SAFE-03  Absolute strobe ceiling is 8.0 Hz. Above 8.0 Hz the safety layer clamps to 4.0 Hz.
SAFE-04  Burst duration <= 1.5 s, minimum gap >= 5.0 s, never full-field above 4.0 Hz.
SAFE-05  A strictly-conforming mode caps all strobe at 2.0 Hz.
         Basis: Epilepsy Foundation Professional Advisory Board. [VERIFIED]
SAFE-06  Red-dominant strobe is capped at 3.0 Hz. Red is an independent risk factor.
SAFE-07  The engine must surface a photosensitivity warning at arm time.
SAFE-08  Document in code and in this spec that NO live-event-specific photosensitive
         epilepsy standard exists from ESTA or PLASA. These limits are voluntarily
         adopted from broadcast and general-health guidance. [NOT FOUND - genuine gap]
```

**Config keys:**

```
safety.strobe_sustained_max_hz     = 4.0   [1.0-4.0]
safety.strobe_absolute_max_hz      = 8.0   [2.0-8.0]
safety.strobe_forbidden_band_hz    = [10.0, 25.0]   (not user-editable)
safety.strobe_strict_mode_max_hz   = 2.0
safety.strobe_red_max_hz           = 3.0
```

Intensity at drops must come from brightness, fixture count, and contrast —
not from rate. This costs nothing visually and removes the only genuine
hazard in the document.

**Direct implication for LiveReact's actual code, not just the spec** (added
here, not part of the original evidence report): `engines/reactive.py`'s
current strobe path (`STROBE_MAX`, `STROBE_MAX_BURST_S`,
`STROBE_MIN_SPACING_S`) has **zero Hz-based awareness at all** — it writes a
raw 0..1 DMX rate byte with no measured or modeled mapping to an actual flash
frequency on the real fixture. Per SAFE-08's own honesty about the gap, and
per this project's standing "never trust a spec, verify on hardware" rule,
none of SAFE-01 through SAFE-06 can actually be enforced in code until that
DMX-byte-to-Hz curve is measured on the real wash bar (a camera/photodiode
count, same method the Bible's own §11 already recommends). **This is a real,
currently-unaddressed safety gap in the running system**, not just a
documentation correction — see the note in `[[livereact-lighting-bible]]`.

---

## C2 — Merge algebra: name the reference console (§2, §14)

Current text implies grandMA3, Hog 4 and Avolites share one HTP/LTP default.
They do not.

| Console | Intensity default | Non-intensity | Note |
|---|---|---|---|
| grandMA3 | HTP | LTP | standard moving-light model |
| Avolites Titan | HTP | LTP | release masks with fade time; Kill Action incl. "Release HTP"; priority tiers Low / Normal / High / Programmer / Very High |
| Hog 4 | LTP | LTP (always) | optional per-cuelist HTP for intensity only; priority in steps of 10; HTP-highest beats LTP priority when enabled |

Edit §2.3 to state explicitly: **LiveReact mirrors the Avolites Titan
model** — intensity HTP, all other parameters LTP, with an explicit release
mask and named priority tiers. Then map:

```
Safety clamp        -> Very High
TransitionEngine     -> Programmer
PhraseEngine         -> Normal
ReactiveLayerEngine  -> Low
```

Add release semantics, which the current draft only gestures at:

```
MERGE-14  A layer releases a channel explicitly, not by ceasing to write.
MERGE-15  Release carries a fade time (default 0 for snap channels, 0.5 bar for intensity).
MERGE-16  On release, HTP intensity fades out; LTP channels retain last value until
          another layer asserts. (Avolites Titan semantics.) [VERIFIED]
MERGE-17  A "kill" action releases HTP and kills LTP, returning the fixture to the
          Phrase-layer base.
```

Edit §14 to present three distinct console defaults rather than one, and
state which LiveReact mirrors and why.

**Implication for LiveReact's actual code**: `merge/merge.py`'s current
model (DIMMER/COLOR/STROBE = max, MOVEMENT/LASER/OTHER = last-write) is a
much cruder approximation than named priority tiers + explicit release —
there is currently no "release" concept at all (an engine that stops writing
a channel simply stops contributing to the max/last-write comparison, it
never explicitly hands it back), and no named tier ordering beyond engine
list order. This is a real architecture gap worth the code audit's attention,
separate from any specific bug.

---

## C3 — Color space: reframe Oklab as a deliberate choice (§3.1)

Keep Oklab. It remains the right interpolation space for this application.
Only the provenance is wrong.

Replace the justification paragraph with:

> LiveReact adopts Oklab / OkLCH internally as a deliberate engineering
> choice. The established lighting-industry standard for device-independent
> color is CIE xy (1931) and u'v' (1976), with the RGB gamut triangle defined
> per PLASA E1.54 — this is what ETC Eos and grandMA3 expose in their color
> pickers. [VERIFIED] Oklab has no known prior stage-lighting adoption; its
> documented application domain is web and UI color. [NOT FOUND — verified
> across multiple query angles] It is selected here for perceptually uniform
> interpolation and cross-fixture matching in a software pipeline that has
> no console color engine to inherit from. If LiveReact ever needs to
> exchange color with console hardware or fixture calibration data, CIE xyY
> is the interchange format, and Oklab remains internal.

Also correct: ETC's "x7 Color System" is a seven-emitter hardware array, not
a perceptual color space. Do not cite it as color-space math if it appears
anywhere in the draft.

**Note for LiveReact's actual code**: current color math (`color.py`'s
`hsv_to_rgb`, `engines/color.py`'s `two_axis_color`) is plain HSV, not Oklab
at all — this correction describes what the Bible *recommends*, which the
codebase hasn't adopted yet. Not a bug, just a gap between spec and
implementation worth the audit noting.

---

## C4 — Fog: the cited data is hazer data (§4)

The Look Solutions Unique 2.1 figures (60 s warm-up, continuous output, no
reheat interruption, 2 L ≈ 50 h) describe a **hazer**. They do not apply to
foggers and must not be used to calibrate the fogger state model.

**Correct fogger figures:**

```
Fog burst settles/dissipates in still air:  ~30-90 s   [DOCUMENTED, trade sources]
Heated foggers:                             30 s to a few minutes   [DOCUMENTED]
Warm-up by wattage class:                   trade-guide generalization, NOT bench data
```

Retag every fogger timing in §4.2 as `[CONVENTION]` or `[DOCUMENTED, trade]`,
never `[VERIFIED]`, and mark all of them as requiring per-unit empirical
calibration.

Add the practice finding:

```
ATMO-20  Professional rigs run HAZERS, charged before doors, and do not fire atmosphere
         during the set. Documented counts: Zedd 5 hazers; Chainsmokers World War Joy 10;
         EDC Las Vegas kineticFIELD 60+ fog/haze machines. [DOCUMENTED, PLSN / Laserworld]
ATMO-21  The predictive burst-scheduling subsystem (§4.3) exists solely to compensate for
         fogger-only rigs. On a rig declaring a hazer, the engine pre-charges before the set,
         holds density near target, and BYPASSES predictive scheduling entirely.
```

Add a manifest branch so a hazer is a first-class device type, not a fogger
variant:

```json
"atmosphere_devices": [{
  "type": "hazer",
  "warmup_s": 60,
  "continuous_output": true,
  "precharge_before_set": true,
  "target_density_norm": 0.55,
  "output_channel": 20,
  "fan_channel": 21
}]
```

Engineering note for the section preamble: on a hazer rig, §4.2 (thermal
state model), §4.3 (predictive scheduling) and the mis-prediction recovery
in §9.7 all become inactive. This is the largest single complexity reduction
available to the project.

**Note for LiveReact's actual rig**: not currently relevant — `josh_rig.json`
has zero haze/fog fixtures of either kind (confirmed 2026-09-07). Keep this
patch for whenever that changes.

---

## C5 — Add the busking model (new subsection in §14, plus rules in §9)

`SHOW_EVIDENCE.md` surfaced the strongest architectural finding in either
document, and it is absent from the Bible: Brad Schiller's documented
busking discipline (*Lighting&Sound America*, "The Basics of Busking," Dec
2024). It describes exactly the problem LiveReact solves.

The toolkit: three combinable stacks — a position stack, a color /
color-combination stack (organized by fixture type or physical location),
and a gobo/effect stack — plus premade speed-adjustable chases (dimmer
chase, ballyhoo, color chase) driven by tap-to-tempo, plus a
"get-out-of-jail-free" transitional cue that kills all chases and effects
and leaves clean stage light. `[DOCUMENTED]`

Two principles the Bible currently lacks:

```
TIME-20  Repetition: when a musical section repeats, repeat the look used for it.
         The engine must remember the look assigned to the previous instance of the
         current phrase type and prefer it over a novel selection.
         Basis: Schiller - recreate the same chorus look each chorus. [DOCUMENTED]
TIME-21  Restraint: do not use every fixture, role, or effect in every look.
         Basis: Schiller - "utilize restraint by not using everything for every song
         while also creating a dynamic and changing set of looks." [DOCUMENTED]
         This is the human-practice confirmation of the negative-space rule (MERGE §2.4).
TRANS-10 The engine must implement a RESET cue: kills all chases, effects and reactive
         layers, releases to a clean lit state, holds until the next phrase boundary.
         Distinct from `safe_default` (a failsafe) - this one is musical, and is the
         correct response to a mis-predicted drop or a detected genre/tempo change.
```

**TIME-20 is a genuine architectural addition.** It implies `PhraseEngine`
needs a short look-history keyed by phrase type, which the current design
does not have — `SceneCatalog.pick()` today is pure round-robin within a
bucket, with no memory of what was played the last time this bucket type
came around.

Also worth recording as design validation: professional DJ-set lighting is
documented as **busked, not timecoded**, because timecoding requires locking
the setlist. Zedd's LD: earlier tours were "manually operated in all
departments," with timecode layered on only for elements too fast to hit by
hand. This is precisely LiveReact's problem statement, and it is worth
stating in §0 as the design's justification.

**Note for LiveReact's actual code**: `TRANS-10` (a RESET/"get out of jail
free" cue) does not exist anywhere in the current engine set —
`ManualParams.blackout`/`freeze` are the closest things, but both are hard
kills, not a musical "clean base, wait for the next phrase" cue.

---

## C6 — Re-tag every behavioral number

No frame-counted data was obtained. Every timing, hue-count and duty-cycle
number in the Bible is convention or inference, and must be tagged so, with
an explicit note that it is a calibration default awaiting measurement.

| Bible value | Current tag | Correct tag | Note |
|---|---|---|---|
| `min_hold_bars = 8` | asserted | `[CONVENTION]` | one adjacent-genre review: "every four or eight bars something shifted, never randomly" |
| hue cap = 3 | `[CONVENTION]` | `[CONVENTION]` — supported | trade guides give 3-5 palette limit; 2-4 per scene. 3 is defensible |
| pre-drop blackout 1 beat | `[CONVENTION]` | `[CONVENTION]` | trade phrasing is "half a beat"; music convention is a half-bar to full-bar cut ≈ 0.9-1.9 s at 125-132 BPM |
| kick-follow ≤ 15% duty | asserted | `[INFERRED]` — direction confirmed | no source documents continuous quarter-note pulsing as pro practice; a human busking 128 BPM cannot hand-fire every kick. Keep the rule, soften the number |
| laser duty ≤ 10%, spacing ≥ 2 phrases | asserted | `[NOT FOUND]` | no published moments/hour or spacing figure exists for any in-scope artist |
| `dark_fixtures_pct` per mode | asserted | `[NOT FOUND]` for numbers | negative space is `[DOCUMENTED]` as a principle; no per-state percentage published |
| strobe burst 1.5 s / gap 5 s | asserted | `[CONVENTION]` | no EDM burst/gap convention published; safety limits are limits, not design values |
| mover period in bars | asserted | `[CONVENTION]` | design guidance is directional only: static base first, movement added after |

Add to the §16 config table a boolean column, `empirically_validated`, set
`false` for every row above. When footage is eventually logged, that column
is the work list.

**Direct cross-reference to LiveReact's own code** (added here): several of
these already have a real, current implementation whose values are exactly
this kind of unvalidated default —
`BUCKET_MIN_DWELL_S=3.0`, `HYSTERESIS_MARGIN=0.05`, `WASH_CROSSFADE_TAU_S=0.6`,
`STROBE_MIN_SPACING_S=8.0` (all `engines/reactive.py`/`core/metronome.py`,
all explicitly commented in-code as "not yet tuned by ear"), plus the
laser's `MIN_SPACING_S=120.0`/`MAX_DUTY=0.10` (`core/laser_trigger.py`,
directly corresponds to the "laser duty ≤ 10%, spacing ≥ 2 phrases" row
above, now correctly `[NOT FOUND]` rather than asserted). None of these
should be treated as validated targets in a code audit — they're
calibration defaults, same status as this table says.

### Optional: the measurement path

Items C6 marks `[NOT FOUND]` are unobtainable from public sources. The only
route to real numbers is logging footage with `SHOW_EVIDENCE.md`'s Part 1
schema — Cercle, Boiler Room, Tomorrowland/EDC/Ultra official uploads. Two or
three independently coded sets per artist per energy state would allow
re-tagging those claims as an internal empirical dataset.

Expect a high unusable rate: pro-shot EDM uploads are heavily color-graded
and rapidly cut, LED-wall content dominates the frame, and the rig is
frequently off-camera during the exact drop moments that matter.

This is a nice-to-have. The engine ships on defaults; the config table
exists so the numbers can be tuned without touching code.
