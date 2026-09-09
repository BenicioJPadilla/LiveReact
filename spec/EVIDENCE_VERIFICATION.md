# LIGHTING_BIBLE.md — Evidence Verification Report

## Empirical & Technical Grounding for the LiveReact DMX Engine

### TL;DR

The design-philosophy and standards claims verify strongly; the frame-counted
behavioral data does not exist publicly. Items 9–13 (color science, HTP/LTP,
fog physics, laser regs) can be tagged **[VERIFIED]** against primary
sources; items 1–8 (cadence, hue counts, kick-follow, blackout, laser
spacing, strobe timing, mover parking, negative space) remain
**[CONVENTION]** at best, because no professional EDM lighting show has been
publicly frame-counted and no lighting-director interview gives hard
per-bar numbers.

**Two high-value corrections emerged:** (a) Oklab/Oklch has *zero*
stage-lighting footprint — the lighting industry's perceptual/
device-independent color standard is CIE (1931 xy / 1976 u'v') per PLASA
E1.54, not Oklab; and (b) the three consoles do NOT share one HTP/LTP
default — grandMA3 and Avolites use intensity-HTP/everything-else-LTP, while
Hog 4 defaults to LTP for *all* parameters.

**A genuine standards gap is confirmed:** there is no live-event-specific
photosensitive-epilepsy standard from ESTA/PLASA; all quantitative flash
guidance derives from broadcast frameworks (Harding/ITU/Ofcom/WCAG) or
general-health bodies (UK HSE ≤4 Hz; Epilepsy Foundation <2 Hz). Document
this as **[NOT FOUND]**.

---

### Key Findings (by item, with evidence tag)

#### Behavioral / design questions (items 1–8)

**1. Look-change cadence per energy state / school — [NOT FOUND] for
numbers; [DOCUMENTED] for structure.** No public source frame-counts look
changes per bar for John Summit, Dom Dolla, Chris Lake, Zedd or The
Chainsmokers, nor gives an LD-stated bar cadence per BREAK/BUILD/DROP/
PEAK/OUTRO. What *is* documented: EDM lighting is structured to 4/4 phrase
architecture, and changes are hung on musical structure rather than a fixed
clock. Steve Lieberman (SJ Lighting; designer for EDC, Ultra, and the
Coachella Yuma tent) states it directly: "a lot of EDM is based on musical
theory with a verse, a chorus, a bridge… A lot of the music uses standard
4/4 timing. So, if you can count to four… you can probably pick up enough to
hit the changes on the beat" (HARMAN Professional interview, 2017). The
busking / punting / timecode programming taxonomy is documented (Duck
Lights; ControlBooth). Practitioner consensus is that looks change on
phrase boundaries (commonly 8/16/32-bar) with accent hits on the downbeat,
but no hard dataset exists. Confidence: structure **[DOCUMENTED]**; specific
bar counts **[NOT FOUND]**.

**2. Simultaneous hues live at once by energy state — [CONVENTION].** No
EDM-specific quantified hue-count data exists. However, a consistent
rule-of-thumb appears across lighting-design literature: keep the palette
small. One trade guide states designers should "limit palette to 3 to 5
hues" because "mixing too many colors can lead to muddy or graying light"
(XMLite) and lower effective CRI. Another gives "two to four colors per
scene—one dominant wash, one contrast color for separation, an accent
color… and a warm/neutral key" (Siterui SFX). A concert-lighting color
guide (HARMAN) discusses dominance/contrast but gives no count. These are
general stage/concert guidelines, not EDM measurements. Confidence:
**[CONVENTION]** — a defensible 2–4 (up to 5) hue design heuristic, not
empirical show data.

**3. Kick-follow (pulse par/wash on every kick) vs phrase accents —
[CONVENTION].** No LD interview gives a hard rule. Practitioner sources
indicate both behaviors exist: cheap sound-to-light rigs literally trigger
on the kick via an audio threshold (ControlBooth: input the "drummers kick
or snare and have that trigger the steps… you will have to have very good
control over the level… so that only those beats are triggered"), while
professional EDM is described as mostly pre-programmed/timecoded, where
"DROP THE BEAT lights flash and blind lasers shoot off" on structural hits
rather than continuous kick-tracking (ControlBooth). A fixture vendor
markets beam movers that sync "with every kick drum and snare hit," which
reflects marketing aspiration, not documented pro practice. Design tutorials
warn "constant movement makes every cue look the same" (SHEHDS), implying
pros reserve per-hit pulsing for high-energy moments rather than running it
continuously. Confidence: **[CONVENTION]** — continuous kick-follow is a
small-rig/auto-mode behavior; pro shows favor phrase/downbeat accents with
kick-synced strobe reserved for drops.

**4. Pre-drop blackout duration; hard cut vs roll-through — [CONVENTION],
borrowed from music production.** No lighting-specific dataset. The musical
convention is well documented and lighting mirrors it: producers cut
"everything for a half or full bar before the drop" (Icon Collective), often
"the last bar before the drop (the last four beats)… cut and mute the kick
and the bass, leaving a small bit of silence" (Boombox.io) — i.e., a
half-bar to one-bar silence, which at 125–132 BPM equals roughly
**0.9–1.9 s**. Lighting practice ("call blackouts and restores at ends of
songs," ControlBooth) and design guides ("occasional blackouts for big
drops," Betopper) confirm blackout-into-drop is a standard accent, but the
fraction of builds resolving in a hard cut vs a roll-through is not
quantified anywhere public. Confidence: blackout-before-drop
**[CONVENTION]**; duration inferred from musical structure **[DOCUMENTED]**
for music, not lighting.

**5. Laser moments/hour and minimum cue spacing — [NOT FOUND].** No laser
programmer interview or ILDA/Pangolin/Kvant case study gives a "moments per
hour" rate or minimum spacing between laser cues. Documented instead: lasers
are pre-programmed/choreographed to set structure — e.g., the Laserface
productions (laser designer Ryan "Z" and team) map "each track in [the] set
linked to specific laser cues" (Wikipedia). Safety/duty-cycle guidance
exists (the ILDA audience-scanning panel; Pangolin) but concerns exposure
limits, not aesthetic cue cadence. Confidence: **[NOT FOUND]** for cadence;
laser-as-drop-accent is **[CONVENTION]**.

**6. Strobe burst duration and gap timing — [NOT FOUND] for EDM
conventions; physics [DOCUMENTED].** No console-vendor training or tutorial
gives canonical EDM strobe-burst/gap numbers. Physical facts: xenon/LED
strobe flashes are sub-millisecond to a few ms per flash (the Prism Science
Works SPOT is cited at ≈0.5 μs; capacitor-discharge strobes "will always be
fractions of a second," ControlBooth). Safety ceilings (see item 12) cap
sustained rates but are safety limits, not design conventions. Confidence:
burst physics **[DOCUMENTED]**; EDM burst/gap timing conventions
**[NOT FOUND]**.

**7. Mover position-change period; parked-vs-moving fraction —
[CONVENTION].** No frame-counted data. Design guidance is directional and
consistent: build a static base first, "add movement only after the visual
base is working," and "reserve quick moves, prism changes, and strobe
effects for a musical drop or finale," because "constant movement makes
every cue look the same" (SHEHDS moving-head guide). This supports a design
principle that movers are parked or slow-moving for much of a sustained
section and snap/sweep on accents, but no percentage split is published.
Confidence: **[CONVENTION]**.

**8. Negative-space fraction (rig dark) by energy state — [CONVENTION],
from general lighting theory.** No EDM-specific percentage. Negative space
is an established lighting-design principle: "by reducing or eliminating
light in the areas that are not focal points, you increase the perceived
brightness… of the areas that are" and perceived brightness is relative to
surroundings, not absolute (Smile Lighting). Design guides warn against
"overusing light sources, resulting in a cluttered and chaotic atmosphere"
(Number Analytics). No source assigns a numeric dark-fraction by energy
state. Confidence: principle **[DOCUMENTED]**; per-state percentages
**[NOT FOUND]**.

#### Technical / standards questions (items 9–13)

**9. Oklab/Oklch in lighting — properties [VERIFIED]; lighting adoption
[NOT FOUND / genuine gap].** Oklab (Björn Ottosson, 23 December 2020) is a
perceptual color space fitted with CAM16 data for lightness/chroma and IPT
data for hue, designed to fix CIELAB's blue-hue nonlinearity and to give
perceptually uniform lightness and clean gradient interpolation; Oklch is
its cylindrical (L, C, H) form. Both are in the W3C CSS Color 4/5 drafts and
supported in all major browsers (Chrome 111+, Safari 15.4+, Firefox 113+).
Its documented application domain is **web/UI/design only**. **No lighting
console, fixture manufacturer, or lighting-industry technical source
references Oklab or Oklch** (verified across multiple independent query
angles — a strong negative). The lighting industry's perceptual/
device-independent color layer is **CIE-based**: ETC Eos uses a CIE xy
(1931) default color picker with a CIE u'v' (1976) option, with the RGB
gamut triangle defined per **PLASA standard E1.54**, plus per-fixture color
calibration data and up to 1000 user-definable "color paths" that let a fade
emulate a different color space; grandMA3 offers a CIE color-space picker
(x, y, Brightness, Quality faders) with fixture emitter data and universal
CIE X/Y presets for cross-fixture consistency. **Correction to flag:** ETC's
"x7 Color System" is a seven-emitter *hardware* array (red, red-orange,
amber, green, cyan, blue, indigo), not a perceptual color space — do not
cite it as color-space math. No peer-reviewed paper on perceptually-uniform
mixing for stage RGBW fixtures was found; the primary technical literature
is patents using CIE xyY normalization. Confidence: Oklab math
**[VERIFIED]**; CIE-in-consoles **[VERIFIED]**; Oklab-in-lighting
**[NOT FOUND]**.

**10. HTP/LTP across grandMA3, Hog 4, Avolites — [VERIFIED], with an
important correction.** HTP (Highest Takes Precedence) and LTP (Latest
Takes Precedence) are indeed the standard terms and mechanisms. But the
three consoles do NOT share one default:

- **grandMA3 (MA Lighting):** intensity defaults to HTP; non-intensity
  (color/position/beam) is LTP. HTP suits intensity (a definite
  higher/lower); LTP suits parameters with no ordinal "greater" value (e.g.,
  color, gobo). Source: MA Lighting help + ACT Academy grandMA3 training.
  **[VERIFIED]**
- **Avolites Titan:** the classic model — "Dimmer or intensity channels
  work on the principle of 'Highest Takes Precedence' (HTP)… All other
  channels work on the principle of 'Latest Takes Precedence' (LTP)." On
  kill, HTP fades out with the cue; LTP channels retain their values until
  changed. Titan adds explicit **release masks** (with a release fade time)
  and a **Kill Action** including a "Release HTP" mode (releases HTP, kills
  LTP), plus priority tiers Low / Normal / High / Programmer / Very High.
  Source: Avolites official manual (manual.avolites.com). **[VERIFIED]**
- **Hog 4 (High End / ETC):** differs from the other two — "By default,
  Hog 4 OS uses LTP for all parameters, but you can assign individual
  cuelists to use HTP for intensities (all other parameters are still
  LTP)." Cuelist priority defaults to 0, assignable in steps of 10
  (negatives allowed); when intensity HTP is enabled, HTP-highest wins
  regardless of LTP playback priority. Source: Hog 4 online manual +
  ETC-staff forum confirmation. **[VERIFIED]**

**Summary table:**

| Console | Intensity default | Non-intensity | Notes |
|---|---|---|---|
| grandMA3 | HTP | LTP | Standard moving-light model |
| Avolites Titan | HTP | LTP | Rich release-mask + Kill Action ("Release HTP"); priority Low→Very High |
| Hog 4 | LTP (default) | LTP (always) | Optional per-cuelist HTP for intensity only; priority in steps of 10; HTP-highest beats LTP priority |

**11. Fog vs haze physics — [VERIFIED] for haze (manufacturer data);
[DOCUMENTED] for fog hang/decay.**

- **Haze (Look Solutions Unique 2.1, 1500 W, water/glycol):** warm-up ≈ 60 s;
  **continuous output with no reheat interruption** — "the machine is ready
  for operation after only 1 minute and will not shut down to reheat after
  warm-up is complete"; pump and fan independently adjustable in 99 steps; a
  2 L canister lasts ~50 h continuous. Haze hang time is minutes-to-hours in
  still air (Look Solutions operating manual + distributor specs; Wikipedia
  haze article corroborates long persistence). This is the strongest
  primary datapoint in the set. **[VERIFIED]**
- **Fog:** in still air a fog burst typically settles/dissipates within
  ~30–90 s (Berkland Goods: "a burst of fog typically settles and
  dissipates within 30-90 seconds"); heated foggers give "30 seconds to a
  few minutes" (TopProSound). Time-to-usable-density and decay are
  described qualitatively, not as manufacturer decay curves.
  **[DOCUMENTED]**
- **Warm-up by wattage class:** standard foggers 400–1000 W (portable,
  DJ/small room); high-output 1500–3000 W (fast warm-up, sustained output).
  Trade-guide generalizations, not per-model bench data. **[DOCUMENTED]**

**12. Photosensitive-epilepsy guidance for LIVE stage/laser — [NOT FOUND]
as a purpose-built ESTA/PLASA standard; the gap is real.** No live-
event-industry standard (ESTA/PLASA) purpose-built for photosensitive-
seizure risk from stage lighting/lasers was found. Extant quantitative
guidance is broadcast-derived or general-health:

- **UK HSE:** per Epilepsy Society (information reviewed by Dr F.J.
  Rugg-Gunn, Consultant Neurologist, Chalfont Centre for Epilepsy; produced
  April 2025) — "The Health and Safety Executive recommends that strobe
  lighting, in clubs or at public performances, flashes at a maximum rate
  of four Hertz (flashes per second) or less."
- **Epilepsy Foundation (Professional Advisory Board):** "The flash rate be
  kept to under 2 Hertz with breaks every so often between flashes," and
  "Flashing lights should be placed at a distance from each other and set
  to flash together at the same time to avoid an increase in the number of
  individual flashes."
- **Peak-provocation frequency:** the Epilepsy Foundation of America
  Working Group (Fisher et al., *Epilepsia* 2005;46:1423-1425) found
  "frequencies 15–25 Hz are most provocative, but the range is 1–65 Hz; red
  color is a factor"; the 2025 gap-analysis (PMC11872230) places the peak
  response near 16 Hz. The updated consensus (Fisher et al., *Epilepsia*
  2026, doi:10.1111/epi.18702) advises designers "to avoid bright flashing
  patterns in the 10–20 Hz range, repetitive color flashes, and oscillating
  or static stripes of ~1–8 cycles per visual degree."
- **Broadcast/screen frameworks:** Harding/ITU/Ofcom, ISO, and WCAG 2.3.1
  (three-flash rule) all target screen content; the PMC gap-analysis
  confirms the "five major guidelines (from the U.K., Japan, ISO, ITU, and
  W3C)… are not fully harmonized" — with ISO alone treating "65 flashes or
  more in a second as safe" — none purpose-built for live stage/laser.

Confidence: **[NOT FOUND]** for a live-event PSE standard — recommend
documenting the absence explicitly and adopting the HSE ≤4 Hz / Epilepsy
Foundation <2 Hz limits as *voluntary* defaults.

**13. FDA/CDRH laser regs (21 CFR 1040.10/1040.11) — [VERIFIED] and current
for 2025–2026.** The variance regime is active and unchanged in substance.
Confirmed from FDA variance letters on regulations.gov, including a docket
numbered **FDA-2026-V-1057**: audience/uncontrolled-area scanning is
prohibited except for diffuse atmospheric reflections; Class I audience
limits apply; and Class-I-exceeding radiation is not permitted "at any point
less than 3.0 meters above any surface upon which such persons are
permitted to stand or 2.5 meters below or in lateral separation" from
audience areas. Setup/alignment procedures must reference **ANSI Z136.1**
(FDA templates cite Z136.1:2007 or an equivalent user-consensus standard).
Variances now typically run with annual-report renewal (one FDA template
terminates the variance December 31, 2025 unless extended annually, up to
five years). US audience scanning requires FDA-recognized safety hardware
(Pangolin PASS). Confidence: **[VERIFIED]** against FDA primary documents
dated into 2026.

### Details / Source Reliability Notes

- **Strongest primary sourcing:** items 9 (CIE-in-consoles; Oklab math), 10
  (all three console manuals), 11 (Look Solutions haze manual), 13 (FDA
  variance letters). → **[VERIFIED]**.
- **Trade/secondary:** item 1 structure (HARMAN Lieberman interview), item
  11 fog hang/decay (production guides). → **[DOCUMENTED]**.
- **Practitioner consensus, no hard data:** items 2, 3, 4, 7, 8 (color
  counts, kick-follow, blackout, mover parking, negative space). →
  **[CONVENTION]**.
- **Searched, no public data:** items 1 (bar-cadence numbers), 5 (laser
  cadence), 6 (strobe burst/gap conventions), 9 (Oklab-in-lighting), 12
  (live-event PSE standard). → **[NOT FOUND]**.
- **Conflicts/cautions:** flash-rate guidance answers *different questions*
  and must be stated as such — HSE ≤4 Hz and Epilepsy Foundation <2 Hz are
  *safe sustained ceilings*, whereas the 15–25 Hz band (peak ~16 Hz) is the
  *most provocative frequency range*; do not conflate them. Fixture-vendor
  blogs (DJClub, Betopper, SHEHDS, XMLite, Vello) are marketing-adjacent —
  usable for design conventions but not as empirical measurement.

### Recommendations

- **Apply the tag mapping now.** Reserve **[VERIFIED]** for items 9–11 and
  13; downgrade all cadence/hue/kick-follow/blackout/mover/negative-space
  claims to **[CONVENTION]** or **[NOT FOUND]**. This preserves the
  document's evidence discipline and prevents a reviewer from finding an
  over-claimed number.
- **Correct the color-space framing.** If LIGHTING_BIBLE currently implies
  Oklab is an industry convention, replace with: "LiveReact adopts
  Oklab/Oklch internally as a deliberate engineering choice; the
  established lighting-industry standard for device-independent color is
  CIE xy / u'v' per PLASA E1.54, and Oklab has no known prior stage-lighting
  adoption." This positions LiveReact's use as *novel*, which is more
  accurate and more defensible than implying precedent.
- **Fix the HTP/LTP section to three defaults, not one.** State grandMA3
  and Avolites as intensity-HTP / non-intensity-LTP, and Hog 4 as
  all-LTP-by-default with optional per-cuelist intensity HTP. If LiveReact
  emulates a merge model, name which console's semantics it mirrors, and
  specify release/handback behavior (Avolites' release-mask model is the
  most explicitly documented reference).
- **Adopt explicit safety defaults given the standards gap.** Hard-code a
  sustained strobe ceiling at ≤4 Hz (offer a stricter <2 Hz mode), require a
  photosensitivity warning, avoid the 15–25 Hz provocation band for any
  sustained effect, and gate laser output behind the FDA 3.0 m vertical /
  2.5 m lateral clearance + ANSI Z136.1 model. Document in-code that no
  live-event PSE standard exists and that these limits are adopted
  voluntarily from broadcast/health guidance.
- **If frame-counted behavioral data is essential, generate it in-house.**
  Items 1, 5, 6, 7 have no public dataset; the only route from
  **[CONVENTION]** to a documented internal dataset is your own timestamped
  annotation of official Cercle / Boiler Room / Tomorrowland / EDC / Ultra
  uploads. **Benchmark to change the tag:** once you have ≥3 independently
  coded sets per artist per energy-state with inter-coder agreement, re-tag
  those claims as an internal empirical dataset rather than convention.

### Caveats

- "Not found" reflects public availability as of September 2026 within this
  search pass; proprietary LD show files and paid console-training
  curricula may hold harder numbers not indexed publicly.
- Musical-production conventions (drop/build/silence timing) are well
  documented and used here as a proxy for lighting cadence, but lighting
  cadence is an *inference* from musical structure, not a measured lighting
  behavior — keep that distinction visible in the document.
- The Look Solutions figures are model-specific (Unique 2.1, 1500 W,
  water-based); other wattage classes and compressor/oil-based hazers (MDG,
  Antari, DF-50) differ, and fog decay depends heavily on venue HVAC and
  door traffic in a small indoor room.
- FDA variance conditions are federal; US state agencies (e.g., Arizona
  R9-7-1441) and non-US jurisdictions add requirements not covered here.
- The console color-space and HTP/LTP details reflect current shipping
  software; verify against the exact firmware version LiveReact targets, as
  MA/ETC/Avolites revise color pipelines between major releases.
