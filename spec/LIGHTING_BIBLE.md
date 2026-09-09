# LIGHTING_BIBLE.md

Technical reference specification for the LiveReact autonomous DMX engine.
The reader is a code-generating agent. Every rule reduces to a number,
range, waveform, or boolean. Claims are tagged `[VERIFIED]` (confirmed
against a primary/manufacturer source), `[SPEC-DERIVED]` (inferred from a
spec or standard), `[CONVENTION]` (professional practice, contested cases
flagged), or `[NOT FOUND]` (searched, no public source exists — a genuine
gap, not a rounding choice). Fixture specs and DMX libraries for this class
of hardware are frequently wrong — prefer empirical verification (§15) over
any datasheet.

**This file has been corrected against an evidence-verification pass — see
`03-lighting-bible-corrections.md` for the full patch list and citations.**
Six corrections are applied inline below, each marked
`**[CORRECTED, see 03-lighting-bible-corrections.md §C_]**` at the point it
applies. Read the corrections file's own preamble before changing anything
this document governs: **auditing code against the uncorrected version of
this document produces a clean report and an unsafe engine** (see §13's
strobe rule, correction C1).

Global constants. DMX frame = 25 ms (40 Hz). Effective strobe ceiling ≈ 20 Hz
(Nyquist of the frame rate) **for dimmer-toggle strobing only — see the
corrected §13 for the real safety ceiling, which is lower and for a
different reason.** Audio capture ~31 ms. BPM band 125–132 → beat 480–454
ms, bar 1.92–1.82 s, 32-bar phrase ~61–58 s.

## TL;DR

Build the engine around a **capability-tier manifest** (never product
names), a **console-grade merge algebra** (HTP for intensity, LTP + snap for
everything else, priority stack Transition > Phrase > Reactive — corrected
below to name which real console this mirrors), and a **predict-then-confirm
timeline** where cues fire on the PDL beat and audio only confirms — because
end-to-end latency (~65–95 ms) makes pure reactive light late by
construction.

Treat **fog as a scheduled, stateful, consumable resource** modeled as a 0–1
density variable that rises on a thermally-gated burst and decays
(τ ≈ 40 s); gate every beam/laser look on estimated density, and make **half
the look library viable at density 0** because clear air is the default
state between bursts. **[CORRECTED — this whole model applies to a
fogger-only rig; a rig with a hazer bypasses it almost entirely. See the
corrected §4.]**

Impact comes from **scarcity and contrast**: cap live hues at 3, reserve a
declared fraction of fixtures dark in every energy mode, hold every look
≥ 8 bars, ban continuous kick-following, and enforce laser/strobe/fog safety
as hard code clamps — not warnings. **[CORRECTED — the strobe safety clamp
as originally specified had a real gap; see §13.]**

## Key Findings (decision summary)

**The merge problem is already solved by consoles — adopt it verbatim.**
HTP for intensity, LTP for all other parameters is the documented standard
on moving-light desks. `[VERIFIED]` **[CORRECTED, see
03-lighting-bible-corrections.md §C2 — this is true of grandMA3 and
Avolites Titan specifically, NOT Hog 4, which defaults to LTP for
everything including intensity. §2 below names Avolites Titan explicitly as
the model LiveReact mirrors, since it's also the most explicitly documented
release/priority semantics of the three.]** Add a 4-tier priority stack and
a hard non-interpolable list (wheel, gobo, prism, laser pattern, mode enums)
that snap instead of tween.

**React late, predict early.** Audio-event-to-visible-light is ~65–95 ms; a
beat at 125–132 BPM is 455–480 ms; light reads as lagging beyond ~80–100 ms.
Fire structural cues on the PDL-predicted beat; use audio as confirmation
only.

**Fog is the master scheduler — on a fogger-only rig.** Because a 600 W
fogger needs ~15 s of lead and reheats for ~45 s, the drop-serving burst
must fire ~8 bars ahead — which forces the whole prediction architecture to
exist. **[CORRECTED — on a rig with a hazer instead, this entire
predictive-scheduling requirement disappears; see §4.3's corrected
preamble.]**

**Continuous kick-follow is the amateur signature.** Make it a ≤15%-of-set
opt-in at 1 pulse/bar; the default intensity driver is phrase-position-
scheduled envelopes. **[CORRECTED, see 03-lighting-bible-corrections.md §C6
— no source documents this exact 15% figure as pro practice; the DIRECTION
is confirmed (continuous kick-follow is not the professional norm) but the
number itself is `[INFERRED]`, not `[CONVENTION]`, and should be treated as
a tunable default, not a measured target.]**

**Safety is arithmetic, not advice.** 3 W = Class 4; beams must stay ≥ 3 m
above any standable surface; general strobe ≤ 4 Hz. These become clamps
that make the unsafe command impossible. **[CORRECTED, see
03-lighting-bible-corrections.md §C1 — the ≤4 Hz sustained figure is right,
but the original §13 also allowed short bursts up to fixture-native max
(20–25 Hz), which drives straight through the documented 10–25 Hz
photosensitive-seizure provocation band. §13 below replaces that allowance
entirely.]**

---

## 1. Fixture capability taxonomy and rig manifest schema

### 1.1 Capability axes and tiers

**Color model** (ordered by tint capability):

- `white_only` — intensity only. No hue.
- `wheel_discrete` — dichroic color wheel, N fixed slots. Snap-only, no
  interpolation. `[VERIFIED]` (reference-rig spots).
- `rgb` — additive R/G/B, **no white**. Saturated primaries good; pastels
  crush and hue-shift. `[VERIFIED]` (common on budget pars).
- `rgbw` — adds a white emitter for tints/pastels.
- `rgba` / `rgbaw` — adds amber; extends warm/pastel gamut.
- `cmy` — subtractive flags, continuous, smooth crossfade, matches RGB
  well. `[VERIFIED]`
- `multi` — RGBWAUV / 6-color, widest gamut.

**Intensity control:** `virtual_only` (no dimmer channel — intensity via RGB
scaling), `master_dimmer`, `dimmer_plus_shutter` (native strobe channel
present).

**Movement:** `static`, `pan_only`, `pan_tilt`, `pan_tilt_16bit`
(coarse+fine).

**Beam shaping:** `none`, `gobo_fixed`, `gobo_rotate`, `prism`, `zoom`,
`frost`, `focus`.

**Strobe:** `none`, `dimmer_toggle_only` (must synthesize — unreliable
above ~8 Hz), `native_strobe_channel`.

**Atmosphere:** `none`, `fogger`, `hazer`, `fogger_fan` (fan-assisted).
**[CORRECTED, see 03-lighting-bible-corrections.md §C4 — `hazer` must be a
first-class value here, not a fogger variant; its state model is
structurally different, see §4.]**

**Macro/effect:** `none`, `macro_channel`, `self_animating_channels` (laser
class — §8).

### 1.2 Manifest JSON schema

```json
{
  "rig_id": "string",
  "dmx_refresh_hz": 40,
  "venue": { "detectors_active": false, "detector_type": "photoelectric|ionization|dual|none",
      "ventilation": "unknown|low|high" },
  "fixtures": [{
    "id": "spot_sl",
    "role": "spot | wash | laser | atmosphere | blinder | beam",
    "start_channel": 1,
    "channel_count": 15,
    "capability": {
      "color_model": "wheel_discrete",
      "color_slots": [
        {"slot": 0, "dmx": 0, "hue_deg": null, "name": "open_white"},
        {"slot": 1, "dmx": 8, "hue_deg": 0,  "name": "red"},
        {"slot": 2, "dmx": 16, "hue_deg": 30, "name": "amber"}
      ],
      "intensity": "master_dimmer",
      "movement": "pan_tilt_16bit",
      "beam": ["gobo_rotate", "prism", "zoom", "frost"],
      "strobe": "native_strobe_channel",
      "macro": "none"
    },
    "position": { "x_norm": -1.0, "depth": "front|mid|back", "height_m": 2.4, "order_index": 0 },
    "safety": { "dimmer_max_pct": 100, "strobe_max_hz": 10, "thermal_duty_max_pct": 100 },
    "latency_ms": 45,
    "motion_limits": {
      "pan_range_deg": 540, "tilt_range_deg": 270,
      "pan_max_deg_per_s": 260, "tilt_max_deg_per_s": 200, "pan_accel_deg_per_s2": 900,
      "invert_pan": false, "home_pan_dmx": 128, "home_tilt_dmx": 0, "audience_safe_tilt_min_dmx": 40
    }
  }],
  "atmosphere_devices": [{
    "id": "fog_sl", "dmx_addressable": true,
    "interface": "none_timer | level_1ch | level_fan_2ch | level_fan_3ch",
    "output_channel": 20, "fan_channel": 21,
    "wattage_class": 600, "heatup_s": 180, "burst_max_s": 15, "reheat_s": 45,
    "duty_max_pct": 35, "tank_level_known": false, "fluid_type": "water",
    "position": {"x_norm": -0.8, "depth": "back", "height_m": 0.3}
  }],
  "laser_devices": [{
    "id": "laser_c", "class": "4", "power_mw": 3000, "mount_height_m": 2.8,
    "safe_projection": { "min_beam_height_m": 3.0, "tilt_locked_above_horizon": true,
      "audience_envelope_declared": false },
    "fda_variance_on_file": false
  }],
  "position_palette": {
    "dancefloor_centre": {"pan_dmx": 128, "tilt_dmx": 60},
    "back_wall":         {"pan_dmx": 128, "tilt_dmx": 20},
    "ceiling_bounce":    {"pan_dmx": 128, "tilt_dmx": 10},
    "dj_booth":          {"pan_dmx": 110, "tilt_dmx": 90},
    "audience_upstage_safe": {"pan_dmx": 128, "tilt_dmx": 40}
  }
}
```

`x_norm` is the spatial ordering key: -1.0 = extreme stage-left, +1.0 =
extreme stage-right, 0 = centre. All chases/fans/sweeps sort fixtures by
`x_norm`, never by DMX address. `order_index` breaks ties.

`invert_pan` is derived automatically (§6.2): leftmost fixture = reference
(`invert_pan=false`); a fixture with opposite `x_norm` sign in a symmetric
effect is inverted. If geometry is undeclared, symmetric effects default OFF
with a logged warning.

### 1.3 Worked example — reference rig (2 spots, 2 RGB/RGBW washes, 1 laser, 2 non-DMX foggers, no hazer)

```json
{
  "rig_id": "reference_cal", "dmx_refresh_hz": 40,
  "venue": {"detectors_active": false, "detector_type": "none", "ventilation": "unknown"},
  "fixtures": [
    {"id":"laser_c","role":"laser","start_channel":1,"channel_count":12,
     "capability":{"color_model":"wheel_discrete","color_slots":[
       {"slot":0,"dmx":0,"name":"white"},{"slot":1,"dmx":32,"hue_deg":0,"name":"red"},
       {"slot":2,"dmx":64,"hue_deg":120,"name":"green"},{"slot":3,"dmx":96,"hue_deg":240,"name":"blue"},
       {"slot":4,"dmx":128,"hue_deg":60,"name":"yellow"},{"slot":5,"dmx":160,"hue_deg":300,"name":"magenta"},
       {"slot":6,"dmx":192,"hue_deg":180,"name":"cyan"}],
      "movement":"static","beam":["gobo_fixed"],"strobe":"none","macro":"self_animating_channels"},
     "position":{"x_norm":0.0,"depth":"back","height_m":2.8,"order_index":0}},
    {"id":"wash_par","role":"wash","start_channel":13,"channel_count":4,
     "capability":{"color_model":"rgb","intensity":"master_dimmer","movement":"static","strobe":"none"},
     "position":{"x_norm":-0.6,"depth":"back","height_m":2.2,"order_index":0}},
    {"id":"spot_sl","role":"spot","start_channel":17,"channel_count":15,
     "capability":{"color_model":"wheel_discrete","intensity":"master_dimmer",
       "movement":"pan_tilt","beam":["gobo_rotate","prism"],"strobe":"native_strobe_channel"},
     "position":{"x_norm":-0.5,"depth":"mid","height_m":2.4,"order_index":0},
     "motion_limits":{"pan_range_deg":540,"tilt_range_deg":270,"pan_max_deg_per_s":260,
       "tilt_max_deg_per_s":200,"invert_pan":false,"home_pan_dmx":128,"home_tilt_dmx":0}},
    {"id":"spot_sr","role":"spot","start_channel":32,"channel_count":15,
     "capability":{"color_model":"wheel_discrete","intensity":"master_dimmer",
       "movement":"pan_tilt","beam":["gobo_rotate","prism"],"strobe":"native_strobe_channel"},
     "position":{"x_norm":0.5,"depth":"mid","height_m":2.4,"order_index":1},
     "motion_limits":{"pan_range_deg":540,"tilt_range_deg":270,"pan_max_deg_per_s":260,
       "tilt_max_deg_per_s":200,"invert_pan":true,"home_pan_dmx":128,"home_tilt_dmx":0}},
    {"id":"wash_bar","role":"wash","start_channel":47,"channel_count":6,
     "capability":{"color_model":"rgbw","intensity":"dimmer_plus_shutter","movement":"static",
       "strobe":"native_strobe_channel"},
     "position":{"x_norm":0.0,"depth":"front","height_m":1.8,"order_index":0}}
  ],
  "atmosphere_devices":[
    {"id":"fog_sl","dmx_addressable":false,"interface":"none_timer","wattage_class":600,
     "heatup_s":180,"burst_max_s":15,"reheat_s":45,"duty_max_pct":35,"tank_level_known":false,
     "fluid_type":"water","position":{"x_norm":-0.8,"depth":"back","height_m":0.3}},
    {"id":"fog_sr","dmx_addressable":false,"interface":"none_timer","wattage_class":600,
     "heatup_s":180,"burst_max_s":15,"reheat_s":45,"duty_max_pct":35,"tank_level_known":false,
     "fluid_type":"water","position":{"x_norm":0.8,"depth":"back","height_m":0.3}}
  ],
  "laser_devices":[
    {"id":"laser_c","class":"4","power_mw":3000,"mount_height_m":2.8,
     "safe_projection":{"min_beam_height_m":3.0,"tilt_locked_above_horizon":true,
       "audience_envelope_declared":false},"fda_variance_on_file":false}
  ]
}
```

---

## 2. Parameter merge algebra

Three writers (Reactive, Phrase, Transition) target the same channels. The
merge layer sits between them and `DmxWriter`. The model is taken directly
from professional console practice — **[CORRECTED, see
03-lighting-bible-corrections.md §C2]: this is specifically the Avolites
Titan model, not a universal console default.** grandMA3 shares Titan's
intensity-HTP/everything-else-LTP split, but Hog 4 defaults to LTP for
*all* parameters (including intensity, unless a cuelist explicitly opts in
to intensity-HTP). LiveReact mirrors **Avolites Titan** specifically,
because it's also the most explicitly documented source for the
release/priority semantics this section needs (§2.3's release masks and
named priority tiers below come directly from the Titan manual).

| Console | Intensity default | Non-intensity | Note |
|---|---|---|---|
| grandMA3 | HTP | LTP | Standard moving-light model |
| **Avolites Titan (mirrored here)** | HTP | LTP | Release masks with fade time; Kill Action incl. "Release HTP"; priority tiers Low/Normal/High/Programmer/Very High |
| Hog 4 | LTP (default) | LTP (always) | Optional per-cuelist HTP for intensity only; priority in steps of 10; HTP-highest beats LTP priority when enabled |

### 2.1 Per-parameter-type merge table

| Parameter class | Merge rule | Notes |
|---|---|---|
| Intensity / dimmer | **HTP** (max of all layers) | Builds a light "floor"; highest wins. `[VERIFIED]` |
| R,G,B,W as intensity | **HTP per emitter within one look**; cross-look = LTP by priority | Averaging two hues yields mud. |
| Hue (working space) | **LTP** by priority | Never average. |
| Saturation / value | LTP by priority | |
| Pan / tilt | **LTP base + additive signed offset**, then slew-clamp | Base = LTP; effect engine adds offset (§6). |
| Color-wheel slot | **LTP + snap** | Never interpolate. |
| Gobo index | **LTP + snap** | Never interpolate. |
| Prism engage | **LTP + snap** | |
| Laser pattern / group | **LTP + snap**, quantize to 32-value block | §8. |
| Strobe rate | LTP by priority; if two layers strobe, HTP-of-active | |
| Fog output | **max, gated by thermal model** (§4); fail-closed | |

### 2.2 Non-interpolable parameter list (snap rule)

These MUST NOT be crossfaded, averaged, or additively blended. Additive
blending is correct for intensity and workable for pan/tilt as offsets, but
it is meaningless for hue and **actively broken for discrete channels** — a
color wheel at the midpoint of two slots lands on a third color, a gobo
index between 3 and 4 is a different gobo, and the laser pattern channel
steps in ~32-value blocks.

- Color-wheel position
- Gobo-wheel index (fixed and rotating-select)
- Prism insert / rotate engage
- Laser pattern-group and sub-pattern channels (quantize to nearest 32-value
  block; hold in the 0–127 static band — §8)
- Laser mode / control-source channel
- Shutter / strobe mode enums
- Any channel whose manifest marks `snap: true`

**Snap rule:** `output = target` at the assertion frame; no tween. If a
crossfade timer targets a snap channel, evaluate it as a single step at the
crossfade midpoint (50%) so the mechanical change lands once, decisively.

### 2.3 Precedence and simultaneous-write resolution

Playback priority stack (higher wins for LTP params) — **named tiers per
Avolites Titan, [CORRECTED, see 03-lighting-bible-corrections.md §C2]:**

| Layer | Priority | Titan tier name | Rationale |
|---|---|---|---|
| Safety / failsafe clamp | 255 | **Very High** | Always final; can only lower. |
| TransitionEngine | 100 | **Programmer** | A transition must seize control of a running phrase look. |
| PhraseEngine | 50 | **Normal** | Structural base look. |
| ReactiveLayerEngine | 25 | **Low** | Audio decoration on top of the base. |

Per-frame (25 ms) resolution:

Each engine writes to its own buffer with a priority tag.

- **Intensity:** HTP across all buffers (safety clamp applied last, can only
  reduce).
- **LTP channels:** value from the highest-priority buffer that wrote this
  frame; if none wrote, hold last.
- **Additive-offset (pan/tilt):** `base(LTP) + Σ offsets`, then slew-clamp
  (§6.6).
- **Snap channels:** highest-priority writer, no tween.
- **Safety layer** applies last (clamps, laser envelope, strobe limit, fog
  thermal).

**Transition assertion:** when TransitionEngine activates, it writes at
priority 100 to every channel it owns for that transition; Phrase writes to
those channels are masked until the transition completes, then
TransitionEngine stops writing (releases) and Phrase resumes control.

**Release semantics [NEW, added by correction C2 — the original draft only
gestured at this]:**

```
MERGE-14  A layer releases a channel explicitly, not by ceasing to write.
MERGE-15  Release carries a fade time (default 0 for snap channels, 0.5 bar for intensity).
MERGE-16  On release, HTP intensity fades out; LTP channels retain last value until
          another layer asserts. (Avolites Titan semantics.) [VERIFIED]
MERGE-17  A "kill" action releases HTP and kills LTP, returning the fixture to the
          Phrase-layer base.
```

### 2.4 Negative-space allocation rule (resolves C9)

Darkness is an allocated resource, not a leftover — additive layering
biases the rig toward "more on," but contrast is where impact lives. Each
energy mode declares `dark_fixtures_pct`; the merge layer forces that
fraction of fixtures-in-role to zero intensity **after** merge:

| Energy mode | dark_fixtures_pct |
|---|---|
| BREAK | 50–70% |
| BUILD | 30% (→ 0 at build end) |
| DROP | 10–25% |
| PEAK | 10% |
| OUTRO | 60% |

**[CORRECTED, see 03-lighting-bible-corrections.md §C6 — negative space as a
*principle* is `[DOCUMENTED]`; these specific per-state percentages are
`[NOT FOUND]` in any public source. Treat this table as a calibration
default (see §16), not a validated target.]**

Which fixtures go dark: preserve symmetry — dark the highest-`x_norm`
fixtures (edges) first for a centred look, or alternate `order_index % 2`
for a dashed look. **Never random per-frame** (flicker). The choice is
frozen at look entry and re-rolled only on look change.

---

## 3. Color system

### 3.1 Working color space (resolves A6)

**[CORRECTED, see 03-lighting-bible-corrections.md §C3 — the original
justification below implied Oklab is an industry standard. It is not; the
paragraph is replaced.]**

**Recommendation: author/store in HSV, but perform all fades and
cross-fixture matching in Oklab/OkLCH, converting to fixture-native only at
the last stage in `DmxWriter`.**

**Corrected rationale:** LiveReact adopts Oklab/OkLCH internally as a
**deliberate engineering choice**, not because it is a lighting-industry
convention. The established lighting-industry standard for
device-independent color is **CIE xy (1931) and u'v' (1976)**, with the RGB
gamut triangle defined per **PLASA standard E1.54** — this is what ETC Eos
and grandMA3 expose in their color pickers. `[VERIFIED]` **Oklab has no
known prior stage-lighting adoption**; its documented application domain is
web/UI color (it's in the W3C CSS Color 4/5 drafts, supported in Chrome
111+, Safari 15.4+, Firefox 113+). `[NOT FOUND — verified across multiple
independent query angles, a genuine negative]` It is selected here for
perceptually uniform interpolation and cross-fixture matching in a software
pipeline that has no console color engine to inherit from — this makes
LiveReact's use *novel*, which is more accurate and more defensible than
implying precedent. If LiveReact ever needs to exchange color with console
hardware or fixture calibration data, **CIE xyY is the interchange format**,
and Oklab remains internal.

**Also correct** (flagged by the same review): ETC's "x7 Color System" is a
**seven-emitter hardware array** (red, red-orange, amber, green, cyan,
blue, indigo), not a perceptual color space. Do not cite it as color-space
math anywhere in this document or the code.

Measurable technical properties of Oklab itself remain `[VERIFIED]`: Oklab
(Björn Ottosson, 23 December 2020) "has improved hue linearity, hue
uniformity, and chroma uniformity compared to CIELCH," and CSS Color 4 uses
it as an explicit interpolation space (e.g. `linear-gradient(in oklab, …)`,
`color-mix(in oklch, …)`). The motivation for interpolating in OkLCH is hue
control: a constant-chroma sweep in hue follows the arc a designer expects,
whereas a straight (a,b) segment cuts across it and desaturates.

Pipeline: (1) palettes defined as OkLCH triplets (L 0–1, C 0–~0.4, H
0–360); (2) fades interpolate in OkLCH along the shortest hue arc,
chroma-gated near the achromatic axis to avoid the hue singularity; (3)
convert target → linear sRGB → fixture emitters at output; (4) cross-fixture
matching maps the OkLCH target into each fixture's achievable gamut (clamp
chroma to the gamut edge, preserving L and H).

### 3.2 Named palettes for 125–132 house

OkLCH anchor + RGB (no-white par) + RGBW quad + wheel strategy + white-only
fallback. Values `[SPEC-DERIVED]`, calibrated for saturated club output.

| # | Name | OkLCH (L,C,H) | RGB | RGBW | Wheel strategy | White-only |
|---|---|---|---|---|---|---|
| 1 | `blood_red` | 0.55,0.22,25 | 255,0,0 | 255,0,0,0 | nearest red slot | 100% |
| 2 | `deep_amber` | 0.75,0.15,70 | 255,90,0 | 255,70,0,20 | amber/orange slot | 70% |
| 3 | `acid_yellow` | 0.90,0.17,100 | 255,220,0 | 255,200,0,25 | yellow slot | 90% |
| 4 | `toxic_green` | 0.85,0.20,145 | 0,255,40 | 0,255,40,0 | green slot | n/a |
| 5 | `cyan_ice` | 0.85,0.13,195 | 0,220,255 | 0,200,255,15 | cyan slot | 80% |
| 6 | `cold_steel` | 0.70,0.09,230 | 40,120,255 | 30,100,255,20 | blue slot | 60% |
| 7 | `deep_blue` | 0.45,0.16,265 | 0,20,255 | 0,10,255,0 | blue slot | 40% |
| 8 | `uv_violet` | 0.45,0.18,300 | 130,0,255 | 120,0,255,0 | congo/UV slot | 40% |
| 9 | `hot_magenta` | 0.60,0.22,340 | 255,0,150 | 255,0,140,0 | magenta slot | n/a |
| 10 | `warm_white` | 0.95,0.03,80 | 255,200,140 | 120,90,60,255 | open white | 100% |
| 11 | `neutral_wash` | 0.90,0.00,0 | 255,255,255 | 40,40,40,255 | open white | 100% |
| 12 | `sunset_split` | pair 2+9 | — | — | split by role | — |

### 3.3 Mixed color models on one stage (resolves A1)

**LED-mixing class leads; wheel fixtures match to it.** `[CONVENTION]` The
flexible, continuous class (RGB/RGBW/CMY) sets the target because a
discrete wheel cannot reach arbitrary hues. CMY subtractive fixtures match
additive RGB well. `[VERIFIED]`

Wheel-matching algorithm for target hue `H_t`:

Find the wheel slot minimizing `|H_slot - H_t|`.
- ≤ 20° → use that slot.
- 20–45° → use it, flag "approximate," and desaturate the LED fixtures
  ~15% so both read as one family.
- 45° (no near slot) → **fallback**: pull the wheel to open-white/neutral
  and let it act as a brightness/beam element while LEDs carry color; OR,
  if the look declares `wheel_contrast: true`, deliberately place the wheel
  at `H_t ± 180°` as an intentional split (a clean complement, never a
  near-miss that reads as an error).

### 3.4 RGB-without-white tints (resolves A2)

A no-white par makes tints only by raising the two "off" channels, which
crushes saturation and shifts hue. Rules:

- Saturated primary/secondary hues (palettes 1,4,7,9): render full on RGB —
  this is the no-white par's strength.
- Pastels/tints allowed only down to an **OkLCH saturation floor of C =
  0.25**; below that the hue is unstable → **exclude the no-white par**
  from that look (go dark or reassign it a saturated role) rather than
  showing a muddy near-white.
- Never render `warm_white`/`neutral_wash` as a *color* on a no-white par —
  only as a broadband "all channels up" cold-white blast.

### 3.5 RGBW white-channel policy (resolves A3)

Blending W into a saturated hue produces muddy pastels. `[CONVENTION]`

- W held at 0 whenever target chroma **C > 0.10** (any saturated hue).
- W used only for: intentional pastels (C < 0.10), true-white looks, or a
  warm-white low-intensity base.
- Rule: `W = 255 · max(0, 1 - C/0.10) · intensity` — W ramps in only as
  chroma approaches zero.

### 3.6 Simultaneous hue cap (resolves A4)

**Hard cap: 3 distinct hues live at once.** `[CONVENTION]` Exceptions: (a)
one fixture doing a fast color-chase counts as one budget slot; (b) a
white/amber base does not count; (c) big-room school may reach 4 for a
single drop, never sustained.

**Hypothesis verdict:** the claim that amateur rigs look bad primarily
because too many hues are live is **substantially confirmed but not the
sole cause**. Un-unified color (unmatched mixed models, §3.3) and
continuous kick-flashing (§13, C5) are co-equal offenders. Default target:
1–2 hues tech-house, 2–3 big-room.

**[CORRECTED, see 03-lighting-bible-corrections.md §C6 — this hue-count
cap is `[CONVENTION]` and stays `[CONVENTION]` ("supported"): trade guides
independently converge on a similar 3–5 palette / 2–4-per-scene limit, so 3
is a defensible number — but it remains a design heuristic, not measured
EDM show data. Treat it as a calibration default (§16).]**

### 3.7 Dimmer floor and curve (resolves A5)

Budget LED shifts hue and steps visibly below ~10–15%. `[VERIFIED]`
(practitioner reports of visible "steps" during low dimming on
budget/"Chinese" LED pars that don't integrate a dimming curve).

**Usable floor: 12% (DMX 31).** No dwelling between DMX 1 and 30; snap to 0
instead.
**Curve: gamma/square-law.** `output_dmx = 255 · (level_norm)^2.2`, clamped
to floor. `[VERIFIED]` — perceived brightness relates to measured output by
roughly a square law (≈1% measured ≈ 10% perceived; 50% measured ≈ 80%
perceived), so a raw-linear fade dumps nearly all visible change into the
bottom of the range; square-law spreads perceived change evenly. A
standard square-law curve can over-compensate and go "steppy" at the very
bottom — hence the hard floor cut.
Fades passing near zero cut to 0 at the floor rather than crawling the
stepping zone.

### 3.8 Frequency→hue mapping (resolves A7)

**Recommendation: choose hue from the active palette on phrase boundaries
only; let audio frequency content drive saturation, intensity
distribution, and fixture selection — never continuous hue.**
`[SPEC-DERIVED]` This keeps the standing bias (music→color) while
eliminating hue churn.

On each 16/32-bar boundary, pick the palette hue via a deterministic
energy-mode map (BREAK cool, DROP saturated primary, etc.).
Spectral centroid → saturation: bass-heavy → higher chroma; bright/hat-heavy
→ slightly desaturated toward white accents.
Spectral band energy → which fixtures light: sub/bass → floor washes; mids
→ spots; highs → laser/accents.
Hue frozen for the whole phrase; only saturation and distribution move
within it.

---

## 4. Atmosphere system

### 4.1 Fog vs haze, quantified (resolves D1)

**[CORRECTED, see 03-lighting-bible-corrections.md §C4 — the tag on this
subsection was over-claimed. The fog figures below were sourced alongside
haze manufacturer data and inherited its `[VERIFIED]` tag; only the HAZE
figures deserve that tag. Fogger figures are retagged `[DOCUMENTED, trade]`
below.]**

A fogger produces a dense opaque burst that dissipates in **30 seconds to a
few minutes** in a small room `[DOCUMENTED, trade]`; usable diffusion
density arrives within **a few seconds** (a fogger can fill a diffusion
effect "in a matter of 5 seconds") `[DOCUMENTED, trade]`.

A hazer produces a fine even suspension hanging **up to an hour** —
manufacturer data for a real reference unit (Look Solutions Unique 2.1,
1500 W, water/glycol): ~60 s warm-up, **continuous output with no reheat
interruption**, a 2 L canister lasts ~50 h continuous. `[VERIFIED]` — **but
this rig has no hazer.**

Fan-assisted dispersal (fan across the fogger output) breaks the plume into
pseudo-haze and widens even distribution, but it remains consumable and
decays on fogger — not hazer — timescales, and airflow causes uneven
distribution. Place foggers low and upstage/behind, output crossing beam
paths, never aimed at audience or DJ.

**New device type — hazer as first-class, not a fogger variant**
`[NEW, correction C4]`:

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

**Practice finding** `[NEW, correction C4, DOCUMENTED]`:

```
ATMO-20  Professional rigs run HAZERS, charged before doors, and do not fire atmosphere
         during the set. Documented counts: Zedd 5 hazers; Chainsmokers World War Joy 10;
         EDC Las Vegas kineticFIELD 60+ fog/haze machines. [DOCUMENTED, PLSN / Laserworld]
ATMO-21  The predictive burst-scheduling subsystem (§4.3) exists solely to compensate for
         fogger-only rigs. On a rig declaring a hazer, the engine pre-charges before the set,
         holds density near target, and BYPASSES predictive scheduling entirely.
```

**Engineering note:** on a hazer rig, §4.2 (thermal state model), §4.3
(predictive scheduling) and the mis-prediction recovery in §9.7 all become
**inactive**. This is the largest single complexity reduction available to
the project — if the physical rig ever gains a hazer, revisit whether §4.2–
4.3/9.7 need to run at all for that venue.

### 4.2 Thermal / duty-cycle state model (resolves D2)

**[CORRECTED, see 03-lighting-bible-corrections.md §C4 — retag the whole
table below from `[VERIFIED]` to `[DOCUMENTED, trade]`: these are trade-
guide generalizations by wattage class, not per-model bench data, and
require per-unit empirical calibration before being trusted.]**

```
COLD —(heatup_s)→ READY —(fire)→ OUTPUTTING —(burst elapsed)→ RECOVERING —(reheat_s)→ READY
```

Realistic timings by wattage class `[DOCUMENTED, trade — NOT bench data]`:

| Class | Heat-up (cold) | Burst | Reheat | Notes |
|---|---|---|---|---|
| 400 W | 4–6 min | 5–10 s | 4–6 min | thin; single small room |
| 600 W | 3–5 min | 10–15 s | ~45 s | **reference rig** |
| 700–1000 W | 2.5–3 min | 10–15 s | 30 s–2 min | fills medium room ~90 s |
| 1000 W+ | ~2 min | sustained <2 min / "always ready" | | DMX + timer common |

**Hard rules:** never command a burst unless `state == READY`; a burst
arriving during RECOVERING is dropped and logged (do **not** queue-stack).
Track `duty_used_pct` over a rolling 10-min window and refuse bursts past
`duty_max_pct` even when READY. `[VERIFIED]` — foggers draw full rated
wattage only during heat-up; reheat draws a small fraction, and the reheat
cycle is real and non-bypassable.

**Fluid awareness:** when `tank_level_known == false`, assume worst case —
cap total bursts per set conservatively and never fire both foggers dry at
once. If two consecutive bursts produce no inferred density rise (§4.4),
mark the unit `suspected_empty` and stop commanding it.

### 4.3 Predictive burst scheduling (resolves D3)

**[CORRECTED, see 03-lighting-bible-corrections.md §C4 — this entire
subsection is fogger-only scope. Per ATMO-21 above, a rig with a hazer
bypasses it entirely.]**

Fog lead time is tens of seconds, so a burst fired *on* the drop is wasted.
A bar at 125–132 BPM ≈ 1.82–1.92 s; to have usable density *at* the drop, a
600 W unit must fire ≥ 8 bars ahead (~15 s), more if COLD.

`fog_lead_bars` per look; default 8, range 6–16.
Scheduler couples to the phrase pre-arm (§9): when PhraseEngine predicts a
drop at bar N (from PDL phrase data), fog fires at bar `N - fog_lead_bars`
only if the target look has `min_atmosphere_density > 0`.
**Mis-prediction after fog committed:** fog cannot be recalled. If the drop
doesn't arrive, committed density simply persists and decays; the engine
reuses it for the next opportunity within the decay window rather than
firing again. No penalty — the fog is already spent.

### 4.4 Density as a modeled state variable (resolves D4)

Sensorless estimate, updated each frame:

```
on burst fire:  density += burst_gain       # ≈ 0.5 per full 600W burst, small room
each frame:     density *= exp(-dt / tau)   # tau = 40s small room; ≈ 90s fan-assisted
                density = clamp(density, 0, 1)
```

`density` (0–1) replaces the boolean `requires_haze`. Looks declare
`min_atmosphere_density`; a look is **gated** (not selectable) until
`density ≥ min_atmosphere_density`. Beam/laser looks typically require
0.4–0.7; wash/color looks require 0.0. `tau` is a per-venue manifest
tunable (default 40 s), shortened by ventilation.

### 4.5 Placement and multi-unit strategy (resolves D5)

Asymmetric placement (SL + SR, both upstage-low) buys wider, more even
coverage and lets beams cross two plumes. **Alternate rather than co-fire:**
firing A then B offset by roughly half a reheat cycle keeps one unit always
READY while the other recovers — roughly doubling effective availability.
Co-fire only for a single "wall of fog" pre-peak moment. Declared via
`atmosphere_devices[].position.x_norm`.

### 4.6 Over-fogging back-off (resolves D6)

`[VERIFIED]` past a threshold the room whites out, fixtures wash, the DJ
vanishes.

**Upper bound: density ≥ 0.85 → suspend all bursts** until density decays
below 0.6 (hysteresis band 0.6–0.85). If beam looks are washing out (high
density + flat-reading intensity), prefer gobo/surface projection (§7) over
aerial beams.

### 4.7 Venue hard rules (resolves D7)

If `venue.detectors_active == true` with photoelectric or dual-sensor heads
in the space: **the engine must refuse all fog output entirely.**
`[VERIFIED]` — fog particles are smoke-sized and reliably scatter light in
photoelectric/dual-sensor detectors, tripping them; ionization heads are
less sensitive but not safe to assume, so the refuse rule holds unless the
venue explicitly clears fog.
Water-based fluid only; log `fluid_type`. (These foggers use glycol/water
fluid, not the oil that leaves hazer film — still flag residue.)
Ventilation dependence: `tau` shortens with ventilation; if unknown, assume
40 s.
**Fog fails closed** (§12): any signal loss or fault → output 0.

### 4.8 DMX interface variance (resolves D8)

Manifest `interface`:

- `none_timer` — not DMX-addressable (**the reference rig's case**). The
  engine cannot fire on the beat; it can only estimate density from the
  unit's own timer, gate looks strictly, and never assume on-demand fog.
  All §4.3 predictive scheduling degrades to "gate on estimated density."
- `level_1ch` — single 0–255 output level; burst = raise then zero.
- `level_fan_2ch` — output + fan (fan drives pseudo-haze).
- `level_fan_3ch` — output + fan + timer/interval.

Because `none_timer` is common, **at least half the look library must be
viable at density 0** (§5).

---

## 5. Look library

30 named looks, schema per the brief (compressed here; each expands to
valid JSON). **16 of 30 require `min_atmosphere_density: 0.0`** — viable in
clear air, the default state between bursts. Every energy mode is covered,
including a good BREAK and OUTRO. Each look notes intent and its failure
mode if implemented wrong.

**[CORRECTED — every numbered constant inside these look definitions
(kick-follow duty, laser gating, strobe burst/gap, hue counts, dark
fractions) inherits the retagging in §16's config table (correction C6):
treat every number below as a calibration default awaiting per-venue
tuning, not a validated target.]**

### BREAK

- `break_low_wash` — hold the room dim and colored during a breakdown.
  `[BREAK]`, both. requires{wash, rgb, atm 0.0, wash≥1}. degrade→null.
  scaling{1:single centre; 2:L/R unison; 3-4:even; 5-8:symmetric pairs;
  9+:2-group}. roles{wash 15–35%, `cold_steel`}. reactivity{audio:
  [wash.dimmer, soft RMS breathing], static:[hue], kick_follow:false,
  justification:"a break has no transients to chase, so only a slow
  envelope earns reactivity; hue static to avoid churn"}. fog_lead 0.
  priority 50. dark 60%. min_hold 16. transition_in crossfade_bars:2.
  conflicts[`peak_strobe_blackout`]. Fail mode: adding motion/hue churn
  kills the "rest."
- `break_single_spot_special` — one slow spot featuring the DJ. `[BREAK]`.
  requires{spot, pan_tilt, atm 0.0}. degrade→`break_low_wash`.
  roles{spot 40–70%, narrow, position dj_booth}. reactivity{static all,
  kick_follow:false}. dark 80%. min_hold 16.
- `break_ceiling_drift` — slow tilt drift on ceiling bounce, no aerial
  needed. `[BREAK]`, techhouse. requires{spot, pan_tilt, atm 0.0}.
  movement{tilt_drift, sine, period_bars 8, tilt_amp 15%}. dark 50%.
  min_hold 16.

### BUILD

4. `build_riser_wash` (canonical build) — intensity climbs across the
   build. `[BUILD]`, both. requires{wash, atm 0.0}. roles{wash dimmer ramp
   20→95% over build length}. reactivity{audio:[wash.dimmer tied to
   bar-count envelope], static:[hue], kick_follow:false,
   justification:"the ramp IS the build; drive it from bar position, not
   audio, to stay predictable"}. dark 30→0%. min_hold 8. Escalation:
   dimmer + fixture count rise; strobe/laser/prism held for the drop.
5. `build_snare_accent` — accent the snare-roll acceleration. `[BUILD]`,
   bigroom. requires{wash or blinder, native strobe or dimmer}.
   reactivity{audio:[accent flashes locked to detected snare subdivision,
   quantized to 1/8], kick_follow:false, justification:"the snare roll is
   the one place transient-following reads as intentional"}. Flashes obey
   §13. dark 20%. min_hold 8.
6. `build_beam_raise` — spots tilt floor→sky as build peaks. `[BUILD]`,
   both. requires{spot, pan_tilt, atm 0.5}. degrade→`build_riser_wash`.
   movement{tilt_raise, ramp, period=build, tilt 20→70%}. fog_lead 8.
   min_hold 8.

### DROP

7. `drop_blackout_hit` — the pre-drop blackout then full hit; the
   signature tech-house move. `[DROP]`, techhouse. requires{any, atm
   0.0}. transition_in blackout_beat. roles{wash full, spot full open}.
   color{`blood_red` or `cold_steel`, unison}. reactivity{static all,
   kick_follow:false, justification:"the cut IS the effect; nothing
   reacts"}. dark 10%. min_hold 8. conflicts[all build looks].
8. `drop_beam_fan` — mirrored beam fan on the drop. `[DROP,PEAK]`, both.
   requires{spot, wheel+, pan_tilt, atm 0.6, spot≥2}. degrade→
   `drop_blackout_hit`. scaling{1:single sweep; 2:mirrored pan 180° phase,
   SR inverted; 3-4:symmetric fan from centre; 5-8:even phase across pan;
   9+:phase + alternating subgroup}. roles{spot 60–100%, narrow, gobo
   open, position dancefloor_centre}. movement{fan, sine, period_bars 2,
   phase_offset 180, pan_amp 30%, tilt_amp 15%, mirror_pan true}.
   color{`cold_steel`, unison}. reactivity{static pan+hue,
   kick_follow:false, justification:"choreographed motion reads pro;
   audio-reacting a fan looks broken"}. fog_lead 8. dark 25%. min_hold 8.
   Fail mode: SR not inverted → both heads swing the same way, fan
   collapses.
9. `drop_strobe_stab` — native-strobe stabs on drop accents. `[DROP]`,
   both. requires{wash or blinder, native_strobe_channel}.
   reactivity{audio:[strobe gated to drop-accent bars only],
   kick_follow:false}. Uses native strobe channel, never dimmer toggling
   (§11). ≤ §13 limit. dark 20%. min_hold 8.
10. `drop_color_slam_bigroom` — dense saturated color on the drop.
    `[DROP,PEAK]`, bigroom. requires{wash, spot, atm 0.0}.
    color{`sunset_split`, split_by_role, ≤3 hues}. reactivity{static hue,
    audio:[wash.dimmer emphasis on first beat of each bar only],
    kick_follow:false}. dark 10%. min_hold 8.
11. `drop_laser_punctuation` — a laser moment on the drop (§8). `[DROP,
    PEAK]`, both. requires{laser, atm 0.6}. degrade→`drop_beam_fan`.
    roles{laser active, pattern static beam-fan held in 0–127 band}.
    fog_lead 8. min_hold 8. Gated hard on density ≥ 0.6 — laser into
    clear air is wasted. conflicts[break looks].

### PEAK

12. `peak_full_rig` — everything committed. `[PEAK]`, bigroom. requires
    {wash, spot, atm 0.0}. roles{wash 85–100%, spot 100%}. color{≤3
    hues}. movement{spots slow fan, period_bars 4}. reactivity{static
    hue+pan, kick_follow:false}. dark 10%. min_hold 8.
13. `peak_beam_sweep` — wide synchronized sweep. `[PEAK]`, techhouse.
    requires{spot, pan_tilt, atm 0.6}. degrade→`peak_full_rig`.
    movement{sweep, triangle, period_bars 2, pan_amp 40%, mirror_pan
    true}. fog_lead 8. dark 15%. min_hold 8.
14. `peak_strobe_blackout` — strobe punctuated by blackouts. `[PEAK]`,
    techhouse. requires{blinder or wash, native strobe}. strobe bursts ≤
    1.5 s then blackout, ≤ §13. min_hold 4. conflicts[`break_low_wash`].
15. `peak_laser_tunnel` — laser tunnel at peak. `[PEAK]`, both. requires
    {laser, atm 0.7}. degrade→`peak_beam_sweep`. roles{laser tunnel
    pattern, static rotation band}. Gated density ≥ 0.7. min_hold 8.

### OUTRO

16. `outro_fade_wash` — slow warm fade to close. `[OUTRO]`, both.
    requires{wash, atm 0.0}. roles{wash 40→15%}. color{`warm_white`/
    `deep_amber`}. dark 60%. min_hold 16. transition_in crossfade_bars:2.
17. `outro_single_beam` — one beam to ceiling as the set ends. `[OUTRO]`.
    requires{spot, atm 0.0}. roles{one spot ceiling_bounce, dim}. dark
    80%. min_hold 16.

### Clear-air (density 0.0) drop/peak alternatives

18. `drop_wash_slam_clear` — color+intensity drop, zero atmosphere.
    `[DROP,PEAK]`, both. requires{wash, atm 0.0}. color{`blood_red`,
    unison}. static. dark 20%. min_hold 8.
19. `peak_color_pulse_clear` — bar-synced color pulse, no beams. `[PEAK]`.
    requires{wash, atm 0.0}. reactivity{audio:[wash.dimmer on bar
    downbeat only, 1/bar], kick_follow:false, justification:"one pulse
    per bar is bar emphasis, not kick-following"}. dark 15%. min_hold 8.
20. `drop_gobo_projection_clear` — spots project gobos on surfaces when
    there is no fog (§7). `[DROP]`. requires{spot, gobo, atm 0.0}.
    roles{gobo rotate, position back_wall, wide zoom}. static. dark 20%.
    min_hold 8.
21. `build_wash_clear` — `build_riser_wash` gated atm 0.0 (primary
    build).
22. `break_color_hold_clear` — single static color field, no motion/fog.
    `[BREAK]`. requires{wash, atm 0.0}. color{`deep_blue`}. static. dark
    50%. min_hold 16.
23. `peak_alt_hits_clear` — two spots alternate snap-hits to position, no
    aerial. `[PEAK]`. requires{spot, pan_tilt, atm 0.0}.
    scaling{2:alternate L/R snap each bar}. movement{snap_alternate,
    period_bars 1}. static. dark 25%. min_hold 8.
24. `drop_blinder_clear` — audience blinder hit on the drop. `[DROP]`.
    requires{wash or blinder, atm 0.0}. roles{full white/warm}. min_hold
    4.

### Utility / structural

25. `all_dark` — reserved darkness / cut. any mode. roles all 0.
    transition snap. min_hold 1 (momentary).
26. `safe_default` — failsafe look (§12). any mode. roles{wash 40%
    `neutral_wash`, static}. No movers moving, no laser, no fog. Baseline
    priority.
27. `spot_position_change` — reposition-only cue (palette move, not a
    motion effect). movement{snap or 1-bar move to named position}. Used
    on phrase events (§6.3).
28. `chase_wash_lr` — L→R chase across washes. `[BUILD,PEAK]`.
    requires{wash≥2}. movement{chase, period_bars 2, phase by x_norm}.
    scaling{2:L then R; 3-4:sequential by x_norm; 5-8:even phase;
    9+:phase+subgroup}. dark 30%. min_hold 8.
29. `mirror_cross_beam` — two spots cross beams at centre. `[DROP,PEAK]`.
    requires{spot≥2, atm 0.6}. movement{cross, sine, period_bars 4, phase
    180, pan_amp 25%, mirror_pan true}. degrade→`peak_beam_sweep`.
    min_hold 8.
30. `build_to_drop_bridge` — managed handoff for the pre-drop bar.
    `[BUILD→DROP]`. transition_in blackout_beat. Holds dark on the final
    bar, releases to the DROP look on the downbeat. min_hold 1.

---

## 6. Movement vocabulary and position palettes

All periods in bars. All stable at 40 Hz: a 2-bar sine at 130 BPM ≈ 3.69 s
= ~148 frames/cycle (smooth). Fastest usable period ≈ 0.5 bar (~0.9 s, ~37
frames); below that pan/tilt reads as jitter, not motion.

### 6.1 Patterns

| Pattern | Waveform | Period (bars) | Amplitude (% range) | Phase rule (N fixtures) |
|---|---|---|---|---|
| sweep | triangle | 2–4 | pan 30–50% | all in phase |
| fan | sine | 2 | pan 25–40%, tilt 10–20% | phase = 360°·(i/N), mirror by x_norm sign |
| spread | static offsets | n/a | pan spaced across range | even spacing by x_norm |
| circle | sine pan + cosine tilt | 4 | pan 20%, tilt 20% | phase = 360°·(i/N) |
| figure-8 | sine pan + sine(2f) tilt | 4–8 | pan 25%, tilt 15% | 90° offset pairs |
| ballyhoo | sine pan (f1) + sine tilt (f2, incommensurate) | 2–4 | pan 30%, tilt 20% | random static phase per fixture, frozen |
| mirrored_pan | sine | 2 | pan 30% | SR inverted vs SL |
| tilt_dip | sine | 1–2 | tilt 15% | in phase |
| snap_alternate | square (snap) | 1 | to named positions | parity by order_index |

### 6.2 Pan inversion and geometry (resolves E2)

Reference fixture = lowest `x_norm` (most stage-left); `invert_pan=false`.
Any fixture with `x_norm` sign opposite the reference in a symmetric effect
→ `invert_pan=true` → `pan_out = pan_home - offset` instead of `+ offset`.
A symmetric fan **requires** SR inverted, or both heads swing the same way
and the effect collapses. The engine sets `invert_pan` automatically from
`x_norm`.

**Mis-declared rig detection:** if two fixtures in a mirrored effect share
`x_norm` sign, or all `x_norm` are 0, the engine cannot mirror → it
disables `mirror_pan`, runs unison, logs a warning.
Convention: leftmost = reference; positive offset = beam travels toward
stage-right.

### 6.3 Position palettes (resolves E3)

**Position change** (move to a named position) on: phrase boundaries,
section changes, a featured DJ moment. Use `spot_position_change`; slow
(1–2 bar) move or snap.
**Motion effect** (continuous waveform) on: DROP and sustained PEAK energy.
**Two movers are soloists working as a pair, not a texture.** Boundary: at
≤ 4 movers, every fixture is individually legible — choreograph explicitly
(mirror, cross, alternate). At **5–8**, treat as an even-phase group; at
**9+**, phase distribution + alternating subgroups, individual fixtures no
longer read singly. `[CONVENTION]`

### 6.4 Beam vs coverage (resolves E4)

Two narrow beams light two small areas — good for aerials in fog, poor for
washing a floor. Run **wide/frost/zoom-out for coverage** when density <
0.4 (no aerial payoff) or during BREAK/OUTRO where texture beats punch. Run
narrow when density ≥ 0.6 and energy is DROP/PEAK.

### 6.5 Single-mover fallback (resolves E5)

One mover: genuine single-fixture equivalents — sweep, tilt-dip,
snap-to-position, ballyhoo. No genuine equivalent — mirrored pan,
cross-beams, symmetric fan, 180° phase (all need ≥ 2); degrade to sweep or
a position special. Never fake a fan with one head.

### 6.6 Slew limits (resolves C7)

Manifest `pan_max_deg_per_s`, `tilt_max_deg_per_s`, `pan_accel_deg_per_s2`.
Per-frame max delta = `max_deg_per_s · 0.025 / range_deg · 255` DMX units.
E.g. 260°/s over a 540° range → ≈ **3.07 DMX/frame** max pan step.
The engine clamps every commanded pan/tilt delta to this; large jumps ramp
over multiple frames (acceleration-limited) rather than slamming the motor
or triggering the fixture's own unpredictable internal smoothing.
`[VERIFIED]` — instant dead-stop-to-full-speed jumps produce visible
stepping and motor stress; gradual accel/decel is required for smooth
moves.
**Homing/startup:** on arm, move to `home_pan_dmx`/`home_tilt_dmx` at
half-slew, hold until the first cue. **On signal loss, movers hold last
position** (do not slam home).

---

## 7. Beam, gobo, prism, zoom

**Worth using on a small rig:** zoom (coverage vs beam control),
gobo-on-surfaces, color wheel.
**Decoration / low ROI at two fixtures:** prism (splits already-scarce
beams into dimmer multiples — PEAK only, density ≥ 0.6), rotating-gobo
aerials (need fog).
**Invisible below density:** aerial beams, prism aerials, tunnel/fan
projections need density ≥ 0.5–0.6; below that they do nothing in the
air.
**Substitute when density has decayed: gobo/surface projection.** Project
break-up/textured gobos onto the back wall, side walls, or downstage floor
— visible at zero atmosphere. `[CONVENTION]` Best gobos for house:
break-up/foliage textures (motion interest) and dots/lines (rhythm); avoid
detailed logo gobos (read as cheesy). Use `drop_gobo_projection_clear`.

---

## 8. Lasers

### 8.1 Generic DMX animation-laser channel archetype

Budget ILDA/DMX lasers (SHEHDS, Laserworld, X-Laser, generic clones) in
8–16 CH modes share this skeleton. **Channel ORDER is not universal** (this
composite is `[SPEC-DERIVED]`); the **value-band LOGIC is universal**
(`[VERIFIED]` across ≥ 4 manufacturer charts — SHEHDS 34 CH, QTX Mesmerizer
21 CH, Laserworld ShowNET DJ mode, generic 12 CH clones). Canonical 12-CH
form:

| CH | Function | Canonical 0–255 sub-ranges | Tag |
|---|---|---|---|
| 1 | Mode / master | clones: `0-49 off/sound · 50-99 auto · 100-149 auto-anim · 150-255 DMX`; SHEHDS: `0 off / 1-254 on` (34 CH mode: `255 = OFF again` — trap) | [VERIFIED] |
| 2 | Pattern group | `0 = laser off; 1-255 = group` | [VERIFIED] |
| 3 | Sub-pattern select | `0-255, each value = one pattern` | [VERIFIED] |
| 4 | Rotation (Z) | `0-127 static indexed angle; 128-255 continuous rotation, increasing speed (CW/CCW split)` | [VERIFIED] |
| 5 | X position | `0-127 static position; 128-255 auto scroll, increasing speed` | [VERIFIED] |
| 6 | Y position | `0-127 static position; 128-255 auto scroll, increasing speed` | [VERIFIED] |
| 7 | Horizontal scroll | `0-255 slow→fast` (often ALWAYS self-animating, no static band) | [VERIFIED] |
| 8 | Vertical scroll | `0-255 slow→fast` | [VERIFIED] |
| 9 | Zoom / scale | `0-127 static size; 128-255 dynamic zoom` | [VERIFIED] |
| 10 | Size / wave / lattice | `0 normal; 1-255 small→big`, or wave `0-9 none; 10-255 range+speed` | [VERIFIED] |
| 11 | Color | banded full-color / R / G / B / mixes, or line↔spot | [VERIFIED] |
| 12 | Speed / twinkle / draw | `0-255 slow→fast` | [VERIFIED] |

### 8.2 The self-animation trap (code-critical)

**Confirmed in manufacturer manuals — not folklore.** `[VERIFIED]` On
rotation, X-position, Y-position, and zoom channels the **low band (0–127)
is a static/indexed position; the high band (128–255) makes the channel
self-animate at a speed proportional to value.** A fader parked mid-travel
produces unwanted spinning/drifting.

**Engine rule:** to hold a static geometry, keep rotation/X/Y/zoom channels
in the **0–127 band** (prefer 0 or a specific low index). On
always-animating scroll channels, 0 is the only stop. Some fixtures split
at 192/193 or subdivide the high band into four 32-wide sub-bands
(128–159/160–191/192–223/224–255). `[VERIFIED]` — so **quantize
pattern/mode channels to the nearest 32-value block and never interpolate**
(consistent with §2.2). CH1 semantics vary: SHEHDS uses a plain on/off
(with the `255 = off` trap on some modes); clones/Laserworld use CH1 as a
control-source band selector. Pattern selection is two-tier (group channel
+ sub-pattern channel — SHEHDS CH3+CH4, QTX CH6+CH7). `[VERIFIED]`

### 8.3 Usable patterns vs gimmicks

**Usable in a real house show:** line, dot-matrix, tunnel, fan, grating
(raster/grid), simple geometric beams — punctuation and structure.
**Gimmicks (avoid):** cartoon animations, text/logo frames, complex
graphics — read as cheesy in a club.

### 8.4 Atmosphere dependency

Laser is gated on the §4 density model exactly like beams: laser looks
require `min_atmosphere_density ≥ 0.6`. A laser fired into clear air is
wasted (only the terminal dots on surfaces show). Schedule laser moments
against fog availability via the §9 timeline — never fire a laser look
unless density is present or predicted present.

### 8.5 Musical role / duty cycle

**[CORRECTED, see 03-lighting-bible-corrections.md §C6 — the numbers below
are retagged from `[CONVENTION]` to `[NOT FOUND]`: no published moments/
hour or spacing figure exists for any in-scope artist. The DIRECTION
("punctuation not continuous texture") remains `[CONVENTION]`/
`[DOCUMENTED]`-supported; the exact 10% and "2 phrases" numbers are
calibration defaults awaiting measurement — see §16.]**

In house, lasers are **punctuation, not continuous texture**.

- Active ≤ 10% of set time.
- Drops and peaks only (except one build-climax reveal).
- Minimum spacing between laser moments ≥ 2 phrases (~2 min) so it stays
  special.

### 8.6 Safety as code-enforced constraints (resolves §8 safety)

A 3 W RGB unit is **Class 4**; Class 4 begins at **500 mW** (per IEC
60825-1, Class 3B's upper AEL for a CW visible laser is 500 mW, above
which there is no AEL for Class 4). `[VERIFIED]`

Primary-source rules, translated to code:

**US FDA/CDRH:** Class 3B/4 laser light shows may be presented only under
an **approved FDA variance** — file **FDA Form 3640** ("Reporting Guide for
Laser Light Shows and Displays") to CDRH and **FDA Form 3147**
("Application for a Variance from 21 CFR 1040.11(c)"). `[VERIFIED]` Lasers
above 5 mW used in a show require the variance.

**No beam above 1 mW may fall below 3 m (≈10 ft)** from any surface a
person could reasonably stand on; side clearance ≥ 2.5 m (8.2 ft).
`[VERIFIED]` — per FDA 21 CFR 1040.11(c) as summarized by
laserwshowsafety.info: "any laser beam above 1 mW cannot be lower than 3 m
(10 ft) from the floor or other surface on which a person could reasonably
be expected to stand."

**Projection into audience/accessible areas is prohibited except diffuse
atmospheric scattering.** `[VERIFIED]` — FDA: "Scanning, projection, or
reflection of laser and collateral radiation into audience or other
accessible uncontrolled areas will not be permitted except for diffuse
reflections produced by the atmosphere, added atmospheric scattering
media, and target screens." Fanned beams still count as audience scanning.
Some US states add separate registration.

Code enforcement:

Manifest fields: `mount_height_m`, `safe_projection.min_beam_height_m`
(default 3.0), `tilt_locked_above_horizon`, `audience_envelope_declared`,
`fda_variance_on_file`.
**Clamp logic:** compute the lowest point any commanded beam reaches from
`mount_height_m`, tilt, and throw; if it drops below 3.0 m at any standable
location, clamp tilt so the beam stays ≥ 3.0 m. It must be **impossible to
command a beam below the safe plane.**
**Fail-safe when geometry undeclared:** if `mount_height_m` or
`safe_projection` is missing, or `fda_variance_on_file == false`, or
`mount_height_m < 3.0` → **laser forced OFF entirely** (refuse to emit).
**Forced OFF on signal loss** (§12): laser → 0 immediately, never hold last
value.

---

## 9. Phrase, timing and prediction

House at 125–132 is built in 8/16/32-bar phrases. `[VERIFIED]` — 16/32/64-
bar sections; a major change every 16 bars and a minor change every 8;
intros/outros 16–32 bars, builds typically 8 bars, drops 8–16 bars.

### 9.1 What light does at each position

| Position | Behavior |
|---|---|
| Intro (16–32 bars) | `safe_default`/low wash; establish 1 hue |
| Break/breakdown | `break_*`, 50–70% dark, slow, static hue |
| Build (8 bars) | `build_riser_wash`: intensity + fixture count climb, strobe held back |
| Pre-drop (final bar/beat) | blackout — §9.2 |
| Drop (8–16 bars) | full-intensity hit; hold before varying — §9.3 |
| Peak | `peak_*`, full commitment, ≤ 3 hues |
| Outro | `outro_*`, slow warm fade |

**[CORRECTED, see 03-lighting-bible-corrections.md §C5 — this table
describes the STRUCTURAL/timecode-adjacent view of a set. §9.9 below adds
the professional **busking** discipline this section was missing entirely:
repeated sections should reuse their prior look, and no look should ever
use every available fixture/role/effect at once.]**

### 9.2 Pre-drop blackout timing

Blackout on the final beat of the build, resolving to full on the drop
downbeat. `[CONVENTION]` Cut to black on the **last 1 beat** (≈ 455–480 ms)
for a tight tech-house cut, up to the **last 1 bar** (~1.8 s) for a
big-room suck-out. Configurable `predrop_blackout_beats` (default 1, range
0.5–4). Always a hard snap (§10), never a fade.

**[CORRECTED, see 03-lighting-bible-corrections.md §C6 — retag confirmed:
stays `[CONVENTION]`. The precise phrasing found in review is "half a
beat" in trade writing and "half-bar to full-bar" in music-production
sourcing, which converts to ≈ 0.9–1.9 s at 125–132 BPM — consistent with,
and slightly wider than, the 0.5–4 beat range already configured above.]**

### 9.3 Drop-hit hold and variation

Full intensity holds a **minimum of 8 bars** (`min_hold_bars`) before the
look may change or add variation.
**Maximum change rate: no look change more often than every 8 bars (16 in
breaks). This is the single most important number in this document.**
Faster than ~1 change per 4 bars reads as seizure-y automation, not musical
reaction. Within a held look, parameter *motion* (sweeps) continues, but
the look identity is frozen ≥ 8 bars.

**[CORRECTED, see 03-lighting-bible-corrections.md §C6 —
`min_hold_bars = 8` retagged from asserted to `[CONVENTION]`: one
adjacent-genre review (an Anyma/melodic-techno show writeup) states "every
four or eight bars something shifted, never randomly," which supports but
does not prove this exact number for the in-scope tech-house/big-room
artists. Treat as a calibration default (§16).]**

### 9.4 Build escalation

Over the build (typically 8 bars): dimmer 20→95%, dark fixtures 30→0%,
fixture count rising. **Held back for the drop:** strobe, laser, prism,
full color saturation, beam fans. The build must leave headroom or the
drop cannot exceed it.

### 9.5 Breakdown / outro

Breakdown: strip to 1–2 fixtures, one static hue, 50–70% dark, no strobe,
no fast motion. Outro: warm fade, decreasing intensity, minimal motion.

### 9.6 Predictive scheduling model (resolves C3)

`[SPEC-DERIVED]` PDL supplies exact bar/beat/phrase position, and house at
125–132 is metrically predictable. Audio-derived energy detection is
structurally late — a drop is only classifiable after it begins. Therefore:

**Pre-arm** phrase-boundary events from PDL: when PDL indicates the current
phrase ends (drop) at bar N, schedule the drop cue to fire **on the
metronome beat at bar N — not on audio detection.**
Audio detection = **confirmation only**: if the expected transient arrives
within ±1 beat of the predicted downbeat, confirm; the light already fired
on the beat so it is never late.
Fog (§4.3) schedules off the **same** predicted N, firing at
`N - fog_lead_bars`.

### 9.7 Mis-prediction recovery

**Build that doesn't resolve:** hold the pre-drop state for max 1 bar past
prediction; if unconfirmed, treat as an extended build — resume
`build_riser_wash` at current intensity and re-predict. Never
blackout-and-hang.
**Unexpected cut:** audio RMS collapse sustained ≥ 1 bar → fall to
`break_low_wash` via a 1-bar crossfade. Committed fog persists (§4.3) —
reused, not re-fired.

**[CORRECTED, see 03-lighting-bible-corrections.md §C5 — this mis-
prediction path handles a *timing* miss. C5 adds a musically-triggered
counterpart for a different failure class (a mis-predicted drop that
never was one at all, or a detected genre/tempo change): see TRANS-10 in
§10.]**

### 9.8 Energy-state dwell / hysteresis matrix (resolves C4)

Five states: BREAK, BUILD, DROP, PEAK, OUTRO. To stop threshold flapping:

**Minimum dwell (before any exit):** BREAK 8 bars, BUILD 4 bars, DROP 8
bars, PEAK 8 bars, OUTRO 16 bars.

**[CORRECTED, see 03-lighting-bible-corrections.md §C6 — these dwell
minimums are the same class of number as `min_hold_bars` (§9.3) above:
`[CONVENTION]`, a calibration default, not a measured value. LiveReact's
own implementation independently converged on a conceptually identical
mechanism — a real dwell-time debounce on its own (4-state, not 5-state)
energy classifier — and found by direct measurement that its *first*
guess at a dwell constant was insufficient against real playback and had
to be raised; treat any number in this matrix the same way, as a starting
point to be tuned against real hardware, not trusted as-is.]**

**Asymmetric entry/exit:** entering a higher-energy state uses a lower
threshold and is fast (≥ 2 confirming beats); exiting to lower energy
requires a higher threshold sustained ≥ 4 beats. Hysteresis band = ±15% of
the RMS/flux threshold between entry and exit.

**Legal transition matrix (from → to):**

| From \ To | BREAK | BUILD | DROP | PEAK | OUTRO |
|---|---|---|---|---|---|
| BREAK | — | ✓ | ✓ (cut-in) | ✗ | ✓ |
| BUILD | ✓ (fail) | — | ✓ | ✗ | ✗ |
| DROP | ✓ | ✗ | — | ✓ | ✓ |
| PEAK | ✓ | ✗ | ✓ | — | ✓ |
| OUTRO | ✗ | ✗ | ✗ | ✗ | — |

Illegal transitions are ignored (state holds) until a legal path or dwell
expiry. BUILD→PEAK is illegal (must pass through DROP). Pre-arm (9.6) +
recovery (9.7) + dwell (9.8) + fog lead (4.3) share one clock.

### 9.9 Busking discipline: repetition and restraint (NEW, resolves correction C5)

**[NEW SECTION, see 03-lighting-bible-corrections.md §C5 — the original
document had no equivalent to this. It is the strongest architectural
finding surfaced by the evidence-verification pass, and it is a real gap
in every mechanism above: nothing in §9.1–9.8 has any memory of what look
was used the LAST time this phrase type occurred, and nothing constrains a
look from using every fixture/role/effect it has access to.]**

Source: Brad Schiller, *Lighting&Sound America*, "The Basics of Busking"
(Dec 2024) `[DOCUMENTED]`. The documented professional toolkit: three
combinable stacks — a **position** stack, a **color/color-combination**
stack (organized by fixture type or physical location), and a
**gobo/effect** stack — plus premade speed-adjustable chases (dimmer
chase, ballyhoo, color chase) driven by tap-to-tempo, plus a
"get-out-of-jail-free" transitional cue (see `TRANS-10`, §10) that kills
all chases/effects and leaves clean stage light.

```
TIME-20  Repetition: when a musical section repeats, repeat the look used for it.
         The engine must remember the look assigned to the previous instance of the
         current phrase type and prefer it over a novel selection.
         Basis: Schiller - recreate the same chorus look each chorus. [DOCUMENTED]
TIME-21  Restraint: do not use every fixture, role, or effect in every look.
         Basis: Schiller - "utilize restraint by not using everything for every song
         while also creating a dynamic and changing set of looks." [DOCUMENTED]
         This is the human-practice confirmation of the negative-space rule (§2.4).
```

**TIME-20 is a genuine architectural addition**, not a retag: it implies
the Phrase-selection mechanism (§14's "PhraseEngine cue list") needs a
short **look-history keyed by phrase type**, which nothing in §5's
round-robin-style look library or §9's state machine currently has.

Also worth recording as design validation for §0: professional DJ-set
lighting is documented as **busked, not timecoded**, because timecoding
requires locking the setlist — exactly the constraint an autonomous,
setlist-agnostic engine is built to avoid. Zedd's own LD put it directly:
earlier tours were "manually operated in all departments," with timecode
layered on only for elements too fast to hit by hand. This is precisely
this engine's problem statement.

---

## 10. Transitions

| Type | When | Rule |
|---|---|---|
| `snap` | drops, accents, energy jumps up | instant, one frame |
| `crossfade_bars:N` | break/build/outro, same-energy swaps | fade intensity + interpolate LTP color in Oklab over N bars |
| `blackout_beat` | pre-drop | cut to 0 on the final beat, full on the downbeat |
| `blackout_reveal` | dramatic section change | dark 1 beat then reveal new look |

**Choosing rule:** energy increasing or an accent → snap/blackout; energy
steady or decreasing → crossfade; pre-drop → `blackout_beat` always.

**Never crossfade (snap only, consistent with §2.2):** color-wheel
position, gobo index, prism engage, laser pattern index, mode/enum
channels. During a crossfade these snap at the 50% mark.

**`TRANS-10` — RESET cue (NEW, resolves correction C5):**

```
TRANS-10 The engine must implement a RESET cue: kills all chases, effects and reactive
         layers, releases to a clean lit state, holds until the next phrase boundary.
         Distinct from `safe_default` (a failsafe, §12) - this one is musical, and is the
         correct response to a mis-predicted drop or a detected genre/tempo change.
```

`TRANS-10` differs from `safe_default` (§12) and from the §9.7
mis-prediction recovery paths: those are *failure* responses (a signal
was lost, or a specific timing prediction missed). `TRANS-10` is a
*musical* choice an operator (or the engine, standing in for one) reaches
for when the whole read on the track was wrong — this is the documented
"get-out-of-jail-free" cue from §9.9's busking toolkit, and it should use
the `RESET` mechanism, not `safe_default`, when the cause is musical
rather than a hard failure.

---

## 11. Latency and refresh budget (resolves C6)

End-to-end: audio capture ~31 ms + output quantization to the 25 ms frame
(avg +12.5 ms) + fixture PWM/driver smoothing 20–50 ms (budget LED) =
**~65–95 ms audio-event-to-visible-light.** `[SPEC-DERIVED]`
Perceptual "late" threshold at 125–132 BPM: a beat is 455–480 ms; light
reads as lagging beyond roughly **80–100 ms** (> ~1/5 beat). Pure
audio-reactive light is therefore borderline late by construction —
reinforcing §9.6 (fire on the predicted beat, not on detection).
**Measurement method (captures fixture response, not inference):** point a
photodiode or high-speed camera at the fixture, emit a known DMX step, and
measure the time from DMX frame send to 90% optical rise. Repeat per
fixture class; store as `latency_ms` in the manifest and phase-advance
reactive cues by that amount.
**Why frame-rate strobing fails at 40 Hz:** DMX updates every 25 ms, so
toggling dimmer values gives ~20 Hz effective (Nyquist) and, in practice,
inconsistent/uneven flashing because on/off frames don't align to the
fixture's PWM. `[VERIFIED]` — practitioner testing: "DMX has an update rate
of 25 Hz/40ms… any strobe faster than that will result in inconsistent
flashing… effectively 20 Hz (Nyquist)." **Therefore, for any strobe above
~8 Hz, use the fixture's native strobe channel** (internal
microcontroller/PWM at tens of kHz), never dimmer toggling. Dimmer-toggle
strobe is permitted only for slow (< 6 Hz) deliberate pulses.

**[CORRECTED, see 03-lighting-bible-corrections.md §C1 — this section's
"effective strobe ceiling ≈ 20 Hz (Nyquist of the frame rate)" describes
the DMX *protocol's* mechanical limit for dimmer-toggle strobing. It is
NOT a safety ceiling and must never be read as one — §13's corrected
safety ceiling (4 Hz sustained, hard-forbidden 10–25 Hz band) is far lower
and exists for an entirely different, human-safety reason. A native-strobe
channel is easily capable of running well past the safe band on real
hardware (fixture-native max is commonly 20–25 Hz), so §13's clamp must be
enforced at the DMX-value level, not assumed to be naturally limited by
frame rate.]**

---

## 12. Failsafe and degradation ladder (resolves C8)

The metronome free-runs on the last known BPM (from PDL) via internal
clock when inputs drop.

| Signal lost | Behavior |
|---|---|
| PDL (beat/bar/phrase) | Metronome free-runs on last BPM; PhraseEngine holds the current look, disables new predictive cues (no reliable phrase position); movement continues on the internal clock; degrade to time-based looks. |
| MIDI (fader/EQ/xfader) | MIDI-reactive params → neutral; everything else holds. Low severity. |
| Audio (CoreAudio) | Disable ReactiveLayerEngine (priority 25 stops writing); PhraseEngine + metronome continue on PDL; looks run structurally without audio decoration. |
| All three | Fall to `safe_default` (40% neutral wash, no motion, no laser, no fog) via a 2-bar fade; hold. |

**Hard rules:**

**Laser forces OFF on ANY signal loss — never hold last value.**
`[VERIFIED]` safety requirement.
**Fog fails closed** — output 0 on any signal loss or fault. `[VERIFIED]`
Movers hold last position (do not slam home).
The safety clamp layer (priority 255) always runs regardless of input
state.

Ladder order on total failure: kill laser → kill fog → freeze movers →
fade dimmers to `safe_default`.

**Cross-reference to §13's safety correction:** the safety clamp layer
referenced throughout this section is the SAME priority-255 layer that now
also enforces the corrected strobe Hz limits (SAFE-01..08) and the
photosensitivity-warning-at-arm-time requirement (SAFE-07) — a signal-loss
failsafe and a strobe-Hz clamp are two rules enforced by one layer, not two
separate systems.

---

## 13. Negative constraints — "never do this" (testable assertions)

**[CORRECTED, see 03-lighting-bible-corrections.md §C1 — CRITICAL. The
strobe rule in this section had a real, dangerous gap: it capped
*sustained* strobing at 4 Hz but separately allowed short bursts "to
fixture-native max" (commonly 20–25 Hz on real LED strobes) as long as
they stayed ≤ 1.5 s and were spaced ≥ 5 s apart. Published clinical work
places the peak photosensitive-seizure provocation frequency near 16 Hz,
with 15–25 Hz the most provocative band and 10–20 Hz the range designers
are advised to avoid outright (Fisher et al., *Epilepsia* 2005 and 2026).
The old burst allowance drove straight through that band. The assertion
and the numbered rules below replace the original text entirely — do not
reconstruct the old "burst to fixture-native max" allowance from any other
part of this document.]**

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

**Intensity at drops must come from brightness, fixture count, and
contrast — not from rate.** This costs nothing visually and removes the
only genuine hazard in this document.

Every other assertion below is unchanged from the original document:

```
assert strobe_burst_duration <= 1.5s then a mandatory gap.
assert not (strobe_full_field and strobe_hz > 4) - a large bright area plus fast flash is the
  highest-risk combination.
assert no saturated red strobe > 3Hz - red flashing is higher-risk and gets a dedicated test
  in the standards (see SAFE-06 above, which supersedes this with an explicit number).
assert laser_beam_height_m >= 3.0 at all standable points; else clamp or refuse.
assert laser_off if (signal_lost or geometry_undeclared or variance_on_file==false or
  mount_height_m<3.0).
assert no_laser_audience_scanning - no beam/fan into audience except diffuse atmospheric
  scatter.
assert fog_output==0 if detectors_active.
assert fog_output==0 on signal_loss (fail closed).
assert not fog_burst unless fogger_state==READY and duty_used_pct < duty_max_pct.
assert kick_follow duty <= 15% of set and only 1 pulse/bar at DROP/PEAK (see below).
assert look_change_interval_bars >= min_hold_bars (>=8 drop/peak, >=16 break).
assert pan_delta_dmx <= slew_max_per_frame every frame.
assert no_mover_motion during a held drop unless the look declares it - no idle drifting on
  a committed hit.
assert hues_live <= 3.
assert dimmer==0 or dimmer>=floor(12% ~ DMX 31) - never dwell in the 1-30 stepping zone.
assert not interpolate(wheel|gobo|prism|laser_pattern|mode) - snap only.
assert dark_fixtures_pct >= mode_minimum - negative space reserved.
assert not strobe_via_dimmer_toggle if strobe_hz > 8 - use the native channel.
```

**Continuous kick-follow (resolves C5 [internal, unrelated to correction
C5 above — this is the original document's own numbering]):** continuous
kick-envelope-following on wash brightness is the amateur-rig signature
and is NOT an always-on default in professional house shows.
`[CONVENTION]` Reference-show design — Dom Dolla and John Summit
(tech/bass house: sparse, saturated, blackout- and strobe-driven) vs. Zedd
and The Chainsmokers (big-room/pop-EDM) use denser color and larger drop
architecture but still drive intensity from song structure, not a
continuous kick envelope. Verdict: make kick-follow a **per-look opt-in
with a duty-cycle budget** — ≤ 15% of set time, only at DROP/PEAK, on the
bar downbeat (1 pulse/bar), never every quarter note, and never in
BREAK/BUILD/OUTRO. Default intensity driver = phrase-position-scheduled
envelopes (build ramps, drop holds). A rig pulsing on every quarter note
for a whole set is a defined failure mode.

**[CORRECTED, see 03-lighting-bible-corrections.md §C6 — the DIRECTION
here is `[CONVENTION]`-supported (no source documents continuous
quarter-note pulsing as professional practice, and a human busking a 128
BPM set cannot hand-fire every kick — Zedd's own LD statement confirms
pre-timecode shows were fully manual). The exact **15%** duty figure,
however, is `[INFERRED]`, not directly sourced — keep the rule, treat the
number as a tunable default (§16), not a measured constant.]**

---

## 14. Console paradigm mapping

`[VERIFIED]` grandMA3 / Hog 4 / Avolites structure a show as:

**Groups** — fixtures addressed collectively → LiveReact `role` +
`x_norm` selections.
**Palettes** — reusable Position/Color/Beam reference values →
`position_palette`, named color palettes (§3), beam presets. Store
*intent*, not raw DMX, so one look works on any rig.
**Effects engine ("Phaser" on MA3)** — a waveform (sine/ramp/step) × size
(amplitude) × speed × **phase-per-fixture** distribution, applied on top
of a base value. `[VERIFIED]` This maps directly onto §6: LiveReact's
`{waveform, amplitude_pct, period_bars, phase_offset_deg}` **is** a
phaser, with phase distributed across fixtures by `x_norm` exactly as MA3
distributes per-fixture phase.
**HTP/LTP + playback priority** (§2) — **[CORRECTED, see
03-lighting-bible-corrections.md §C2]: this is specifically the Avolites
Titan merge algebra**, not a single universal console default — see §2's
corrected table for how grandMA3, Avolites, and Hog 4 actually differ.
**Cue/executor stack** — PhraseEngine cue list + TransitionEngine playbacks
with priority.

Adopt this abstraction wholesale (base values + palettes + phaser effects
+ HTP/LTP merge + priority playbacks). Do not invent a parallel model.

### 14.1 The busking model (NEW subsection, resolves correction C5)

**[NEW, see 03-lighting-bible-corrections.md §C5.]** The console-paradigm
mapping above describes *mechanism* (how a console structures groups,
palettes, effects, priority). It says nothing about *operating
philosophy* — and the strongest architectural finding in the whole
evidence-verification pass concerns exactly that gap.

Professional DJ-set lighting is documented as **busked, not timecoded**:
Brad Schiller's toolkit (§9.9) — position stack, color stack, gobo/effect
stack, tap-tempo chases, and a get-out-of-jail-free reset — is built for
an operator who does not know the setlist in advance and cannot lock cues
to specific track timestamps. Zedd's LD is explicit that this is the
*default* mode, with timecode added on top only for sub-frame accents no
human could hit by hand: "The past tours and all other shows and
festivals were all manually operated in all departments." This is
precisely LiveReact's own problem statement (§0) — an autonomous engine
with no setlist, reacting to a live PDL/audio feed it cannot predict in
advance beyond the current phrase.

**Practical implication for LiveReact's cue/executor stack (§14's own
mapping above):** `PhraseEngine`'s cue list should be modeled after the
busking toolkit's three stacks (position/color/gobo), not as a single
flat look library indexed only by energy bucket — and per §9.9's TIME-20,
it needs a short look-history so a repeated phrase type reuses its prior
look rather than always picking freshly.

---

## 15. Unknown-fixture verification protocol

A repeatable probe to populate a manifest for an unfamiliar fixture.
`[SPEC-DERIVED]` — specs and libraries are frequently wrong, so verify
empirically.

**Channel-sweep order:**

Set all channels to 0; observe (usually blackout; note any channel that
self-animates at 0 — likely a mode channel).
Raise a master/dimmer candidate slowly 0→255; the channel that
monotonically changes overall brightness is the dimmer. Note where output
first appears (the dimmer floor).
One channel at a time, 0→255 in steps of 8, holding others at a known
state; log behavior per band.

**Static-position vs self-animating:** hold the channel at 64 for 5 s,
then 200 for 5 s. If output is stationary at 64 and moving/spinning at
200, it is a static-low/animate-high channel (§8.2) — probe the split
point (test 100, 120, 128, 190). If it moves at both, it is always-
animating (0 = stop).

**Color-wheel slot boundaries:** sweep the suspected color channel 0→255
in steps of 2; log DMX values where color changes discretely (slots) vs
continuously (CMY/LED). Record each slot's centre DMX value and measured
hue → `color_slots[]`.

**Mode/reassignment channels:** set a candidate mode channel to each
32-value block; after each, re-sweep 2–3 other channels. If another
channel's *meaning* changes between blocks (e.g. CH4 selects patterns in
one block, colors in another), the candidate is a mode channel — record
which blocks reassign which channels and mark all such channels
`snap: true`.

**Populate:** `color_model` (slot vs continuous), intensity type, movement
(any pair sweeping position = pan/tilt), strobe (a channel that flashes at
increasing rate = native_strobe), macro/self-animating flags, dimmer
floor, and for movers the slew limit (command a full-range jump, measure
seconds to complete → deg/s).

---

## 16. Configuration reference and empirical-validation status (NEW, resolves correction C6)

**[NEW SECTION, see 03-lighting-bible-corrections.md §C6.]** No
frame-counted behavioral data exists for any in-scope artist or show. Every
timing, hue-count, and duty-cycle number named throughout this document is
a **calibration default**, not a measured target, unless its row below
says otherwise. `empirically_validated` is `false` for every row until
real footage or real hardware measurement changes it — see
`03-lighting-bible-corrections.md`'s "Optional: the measurement path" for
how to actually do that.

| Config key | Section | Default | Correct tag | empirically_validated |
|---|---|---|---|---|
| `min_hold_bars` | §9.3, §9.8 | 8 (16 for BREAK/OUTRO) | `[CONVENTION]` | false |
| hue cap (`hues_live`) | §3.6 | 3 | `[CONVENTION]` — supported by trade guides (3–5 palette / 2–4 per scene) | false |
| `predrop_blackout_beats` | §9.2 | 1 (range 0.5–4) | `[CONVENTION]` | false |
| `kick_follow` duty cap | §13 | ≤ 15% of set, DROP/PEAK only, 1/bar | `[INFERRED]` — direction confirmed, number not sourced | false |
| laser duty cap | §8.5 | ≤ 10% of set time | `[NOT FOUND]` — no published figure for any in-scope artist | false |
| laser minimum spacing | §8.5 | ≥ 2 phrases (~2 min) | `[NOT FOUND]` | false |
| `dark_fixtures_pct` per mode | §2.4 | 10–70% by mode (see table) | `[NOT FOUND]` for the numbers — negative space itself is `[DOCUMENTED]` as a principle | false |
| strobe burst/gap (design, not safety) | §8.5-adjacent, look library | 1.5 s / 5 s | `[CONVENTION]` — no EDM-specific burst/gap convention published; do not confuse with the SAFETY numbers in §13, which are limits, not design choices | false |
| mover position-change period | §6 | 2–4 bars (pattern-dependent) | `[CONVENTION]` — directional guidance only (static base first, movement added after) | false |
| `fog_lead_bars` | §4.3 | 8 (range 6–16) | `[SPEC-DERIVED]` from BPM/reheat arithmetic, not measured against a real set | false |
| `tau` (fog decay constant) | §4.4 | 40 s (≈90 s fan-assisted) | `[DOCUMENTED, trade]` | false |
| `burst_gain` | §4.4 | ≈ 0.5 per full 600 W burst | `[SPEC-DERIVED]`, unsensored estimate — verify by eye during first bursts of a set | false |

**Safety keys are the one exception** — SAFE-01 through SAFE-06's numbers
(§13) are `[VERIFIED]` against primary clinical/regulatory sources and are
NOT calibration defaults; they are hard limits and must not be loosened by
this table's spirit of "everything is tunable."

```
safety.strobe_sustained_max_hz     = 4.0   [VERIFIED, not tunable below the range given]
safety.strobe_absolute_max_hz      = 8.0   [VERIFIED]
safety.strobe_forbidden_band_hz    = [10.0, 25.0]   [VERIFIED, not user-editable]
safety.strobe_strict_mode_max_hz   = 2.0   [VERIFIED]
safety.strobe_red_max_hz           = 3.0   [VERIFIED]
```

---

## Recommendations (staged build order)

**Ship the manifest + merge algebra + safety layer first (§1, §2, §12,
§13).** Nothing else is safe to run without them. Benchmark: the engine
can load the reference rig and an arbitrary 1-mover/no-laser/no-fog rig and
produce `safe_default` with all §13 assertions passing. Change trigger: if
any assertion can be violated by a look, stop and fix the clamp before
adding looks.
**Add the phrase/prediction timeline (§9) and the look library (§5)
against PDL only**, audio disabled. Benchmark: cues fire on the predicted
downbeat with no look changing faster than every 8 bars. Change trigger:
if state-flapping appears, tighten dwell (§9.8) before touching thresholds.
**Layer in the atmosphere model (§4) and gate beam/laser looks on
density.** Benchmark: on the reference (non-DMX foggers), ≥ 16 looks run
at density 0 and beam looks never fire below their
`min_atmosphere_density`. Change trigger: raise `tau` toward 90 s only if
a fan is added. **If the rig declares a hazer instead, skip most of §4
entirely per ATMO-21.**
**Enable the ReactiveLayerEngine last (priority 25), narrowly.** Only the
reactive params each look explicitly justifies. Kick-follow off by
default. Benchmark: disabling audio leaves a competent structural show.
Change trigger: if the rig visibly pulses every quarter note, the
kick-follow budget (§13) is being violated.
**Turn on the laser only after §8.6 clamps are proven.** Benchmark: with
`fda_variance_on_file=false` or `mount_height_m<3.0`, the laser cannot
emit. This threshold is non-negotiable — do not relax it for testing
convenience.
**Implement the busking discipline (§9.9, §14.1) once the base engine is
stable.** TIME-20's look-history is a real, if small, architectural
addition — do not retrofit it as an afterthought once `PhraseEngine`'s
selection logic is already load-bearing elsewhere.

---

## Caveats

**Contested practice, defaults given anyway.** The 3-hue cap, the ≤10%
laser duty cycle, "LED leads/wheel matches," and "no continuous
kick-follow" are `[CONVENTION]` positions, not measured constants — they
are defensible defaults, not laws. Where the tech-house and big-room
schools diverge, the look library carries a `school` tag and both
parameter sets. **[CORRECTED, see 03-lighting-bible-corrections.md §C6 —
several of these are now `[NOT FOUND]` rather than `[CONVENTION]`; see §16
for the corrected tag on each specific number.]**
**Named-artist LD detail is thin in public sourcing.** The Dom Dolla/John
Summit vs Zedd/Chainsmokers contrast is drawn from documented show
*character* (minimalist/blackout-driven vs maximalist/dense) rather than
published cue sheets; treat the school parameters as informed synthesis,
not transcribed rigs.
**Fog timings are class-typical, not per-unit.** Reheat/burst figures span
a wide range within a wattage class and specific budget units vary; the
engine must read them from the manifest and, ideally, be calibrated per
unit. The density model (`burst_gain`, `tau`) is unsensored estimation —
verify by eye during the first bursts of a set.
**Laser law is US-federal (FDA/CDRH) plus variable state registration.**
The 3 m/1 mW/variance rules are `[VERIFIED]` against FDA primary sources,
but venue permitting, insurance, and non-US jurisdictions add requirements
the engine does not model. The safe default (refuse to emit when in doubt)
is intentional.
**DMX/latency numbers assume the Enttec Pro at 40 Hz.** Faster or jittery
interfaces change the strobe ceiling and latency budget; re-measure
fixture optical response (§11) rather than trusting these figures if
hardware changes.
**Anti-requirement honored:** no per-channel DMX charts for the reference
light fixtures are reproduced (those are hardware-verified in the
codebase); the laser archetype is the one exception, given explicitly as a
generic capability aid for driving unknown lasers.
**No live-event-specific photosensitive-epilepsy standard exists.**
`[NOT FOUND, see SAFE-08]` Every quantitative strobe-safety number in this
document (§13) is voluntarily adopted from broadcast (UK HSE) or
general-health (Epilepsy Foundation) guidance, not a purpose-built
ESTA/PLASA live-event standard. Document this in code, not just here.
