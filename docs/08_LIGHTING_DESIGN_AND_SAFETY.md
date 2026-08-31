# 08 — Lighting Design & Safety

Because you have no Josh to answer "what should a drop feel like?", this document substitutes researched domain expertise: the **frequency→color verdict**, the **aesthetic model** to emulate, a **concrete starter scene catalog**, transition/loop behavior, and the **safety rules** (laser & strobe) — the latter checked against actual regulations. Distinguishes established fact from aesthetic choice throughout.

---

## 1. The frequency→color rule: verdict

The spec calls **bass→red, mid→pink/magenta, high→cyan, all→white** a "non-negotiable" rule justified by neuroscience ("the brain pairs low frequency with red"). Splitting that into what's true and what's convention:

### What IS perceptually grounded (keep, lean in)
There's a robust, replicated cross-modal correspondence between **auditory pitch/energy and visual BRIGHTNESS** — *not hue*: **high pitch/loud → bright/light/white; low/quiet → dark.** It's found in infants and even non-human animals (chimps, monkeys, dogs, tortoises), implying it's low-level perception, not learned culture. Loudness maps to brightness *and* saturation. (Sources: Ludwig et al., chimpanzee pitch-luminance, PNAS 2011; crossmodal reviews PMC5835347, PMC6407832.)
- So **energy → brightness + saturation is real science.** Full-spectrum/peak → bright **white** is the most perceptually correct moment in the scheme. Honor this strictly.

### What is NOT science (it's house style)
The specific **hue** mapping (bass=red, high=cyan) is **an aesthetic convention, not a perceptual law.** Where hue associates with sound at all, it's usually **mediated by emotion** (happy/major → warm/bright; sad/minor → cool/dark) — which can even *invert* the spec's mapping. Practitioners describe pitch→hue mappings as "fundamentally arbitrary but useful when consistent." (Sources: Palmer et al., music-color mediated by emotion, PNAS 2013; "Mapping Sound to Color," designingsound.org.)

### Verdict
**Keep the rule locked — but for the right reason.** Its value is **consistency**: any sensible color convention applied *every time* reads as intentional; randomized color reads as broken. That's the actual justification, and it's a strong one. Just **don't encode the false neuroscience claim** in code comments (a future maintainer will discover it's wrong and distrust the rest).

### Implementation
- Model **two independent axes**: **energy → brightness/saturation** (grounded, mandatory) and **band-dominance → hue** (convention, tunable data).
- Drive the dimmer/saturation off the *energy* estimate; drive hue off *which EQ band dominates*.
- **Desaturate toward white as all bands engage / on peak hits** — the perceptually correct drop move.
- Make the band→hue table **data**, not constants, so a warm→cool *ramp* (red→pink→white→cyan as energy climbs) can be A/B'd against discrete buckets.

---

## 2. The aesthetic to emulate

Reference DJs (from the spec) and what an automated system should copy:

- **Dom Dolla** — restrained, color/wash-driven, club-minimalist. Deep blues/reds in bass sections; bright whites/golds on vocal moments; **uses darkness deliberately** (plunge to shadow, then burst). Sparing on strobes. *Copy: color and contrast over flash; comfort holding a single look; blackout/dimness as a tool.*
- **John Summit** — lean, punchy, high-contrast; decisive **beat-locked hits**; strobes/lasers **reserved for drops** so they keep impact. *Copy: hard, on-grid hits; ration the "wow" tools.*
- **Zedd** — choreographed, precision-timed; "looks timecoded even though it's run live." *Copy: every cue feels deliberate and on the grid — the north star for automation.*

**Unifying principle:** musical, not chaotic. The thing that separates pro automation from amateur is **restraint + timing + anticipation**, not maximalism. The eight things automated rigs get wrong (and the fix) are in §6.

---

## 3. Starter scene catalog (12 scenes, implementable on this exact rig)

Rig: 2 moving heads (pan/tilt/dimmer/color-wheel/gobo), 2 RGB lasers (CH1 boots 0=off), 2 RGBW pars (no dimmer/strobe channel — do it in software), 2 RGBW wash bars (6ch). Color logic uses §1's two-axis model. Merge is max-of/last-write per [05](05_ARCHITECTURE_REVIEW.md).

### Breakdown / low energy (lasers OFF, strobe OFF)
1. **Deep Wash Breathe** — whole room one deep saturated color (blue/magenta), wash+pars at 20–40% slowly oscillating ±10%; MHs off or dim, tilted up. *Intros, atmospheric breaks.*
2. **Single Roaming Spot** — one MH slow wide pan sweep through fog, narrow beam; everything else near-dark; cool color. *Minimal techno breakdowns; "negative space."*
3. **Slow Color Cycle Ambient** — soft full-rig wash, hue drifts one step per phrase, never hits white. *Long atmospheric sections; default "idle" look.*

### Build / rising energy (lasers OFF; strobe ramps but capped)
4. **Rising Tide** — wash ramps 40→90% over 16 bars, MH dimmer + movement speed climbing, warming toward white. *The canonical build into a drop.*
5. **Strobe Pre-Roll** — wash-bar strobe rate tracks the accelerating snare roll (1/4→1/8→1/16), **hard-capped**; pars flash in software in sync; MHs hold a bright beam; white. *Final 4–8 bars before a drop.*
6. **Converge** — both MHs pan from outward toward center over the build, dimmer rising; wash mid. *Telegraphs the drop ("pointing at" it).*

### Drop / peak energy (lasers MAY enable; strobe within cap)
7. **Full Spectrum Hit** — everything full; white punch on each kick (Reactive pulse), returns to band hue between hits; MHs big fast moves; lasers on (above head height). *Main drop.*
8. **Beam Fan + Laser Tunnel** — MHs narrow beam/gobo in symmetric mirror pan-fan on the beat; lasers in a **static** above-head pattern (manual range, **never** sound-active 168–251); wash low so beams read. *Instrumental "Zedd" drop.*
9. **Beat-Lock Punch** — restrained drop: saturated color bump on each kick, near-black between (high contrast); MHs hold a static beam; strobe off or only at phrase-end. *Bass/tech-house drops where contrast > brightness.*
10. **Strobe Drop** (use sparingly) — short full-white strobe burst across the rig within the rate cap; **auto-disengage after 2–4 bars**. *Biggest peak only — ration it.*

### Hold / sustain (loops, post-transition, plateaus)
11. **Locked Hold** — freeze the current look; no rotation, no new color; only the Reactive Layer's gentle beat pulse continues. *`loop_active=true` and the mandatory 4-bar post-transition hold.*
12. **Pulse-and-Drift Sustain** — steady mid-energy groove: wash 60–70%, slow MH drift, beat pulse on pars, hue holds, no strobe/laser. *Extended groove sections; the "default running" state so the show never feels empty.*

Aim to ship ~8 of these for v1, add the rest during tuning.

---

## 4. Transition, loop, and drop behavior
- **During a mix:** Transition Engine has priority — **hold** the current scene, nudge brightness up ~20%, do **not** rotate. The crossfader moves *before* the audio, giving lead time.
- **At mix completion:** crossfade to a new scene **synced to the new track's first downbeat**; optionally wash through neutral/desaturated to bridge two palettes cleanly. **Hold the new look ≥4 bars** before the Phrase Engine may rotate (prevents "slot-machine" whiplash).
- **Loop:** hold (scene 11); release on loop exit at the next phrase boundary, not mid-bar.
- **Drop:** the strongest sync moment. Ideal sequence: brief darken/contract on the last beat of the build → **full hit on bar 1 beat 1 of the drop.** The dip makes the hit read bigger (lighting analog of the pre-drop silence). Lock to the *downbeat* via the interpolated metronome, never raw PDL packets.
- **Timing rules of thumb:** scene changes on 8/16-bar boundaries; new scene held ≥4 bars; strobe bursts auto-expire 2–4 bars; drops on bar 1.

---

## 5. Safety (accurate — checked against regulation)

### 5.1 Lasers — the spec is correct and it's load-bearing
The rig's 3 W lasers are **well into variance-required territory** if ever pointed at people.
- **US:** laser light shows are regulated under FDA **21 CFR 1040.10/1040.11(c)**; operating a show with a >5 mW product legally requires an **FDA-approved variance** (Form FDA-3147) plus per-show reports. **Audience scanning** is the high-risk category and is **not permitted without a variance and certified safety engineering** (measured irradiance, MPE compliance, a scan-fail interlock that kills the beam in 1–10 ms, trained operator with e-stop, signage). The practical hobby rule: **keep all beams above ~3 m / audience head height** (21 CFR 1040.11(c)), never scan the crowd.
- **International:** **IEC 60825-1** classifies products and defines MPE.
- **ILDA's own bottom line:** do **not** attempt audience scanning without qualified expert safety planning and written authority.

**What LiveReact must do (and the spec already says):** CH1 **boots at 0**; software **never auto-enables lasers outside explicit drop scenes**; **never** uses the fixture's own sound-active modes (168–251) — LiveReact owns all timing; only ever outputs **static/above-head** patterns; provides a hard kill; **fails safe** (any fault → lasers off); never exposes laser-enable on a generic "panic"/brightness control. Aim safety is verified by a **human at install**, never compensated for at runtime. **This conservative posture is correct precisely because the legal/safety burden of audience exposure cannot be met by software alone.**

### 5.2 Strobe — photosensitive epilepsy
- ~3% of people with epilepsy are photosensitive; the danger band is roughly **3–30 Hz (worst ~15–20 Hz)**; seizures are rare **below 3 Hz**. Guidance consensus (**WCAG 2.3.1 "Three Flashes"**, Epilepsy Foundation, Harding) is **≤3 flashes/second**, with a **stricter rule for saturated red**.
- **The tension:** club strobe culture deliberately runs at 10–25 Hz (the hardware supports it). You can't make a club strobe "WCAG-safe" and still feel like a club. Defensible posture: **treat ~3 Hz as the known-safe line for any sustained/automated strobing, and reserve high-rate bursts for short, deliberate, drop-only moments.**
- **Rules for LiveReact:** software-cap the rate on **every** path that writes a strobe channel or software-flashes pars; conservative automated default; high rates only as **short bursts that auto-expire (2–4 bars)**; **be extra cautious with saturated-red flashing** (the bass→red convention + flashing = most-provocative color flashing — prefer white for strobe, or slow/low-contrast any red strobe); strobe is **opt-in per scene, never a global default**; always respect an instant operator cap/kill. (Venue norm: post a "strobe in use" warning — out of software scope but note it in show-day docs.)

---

## 6. Eight things automated rigs get wrong (and the fix)
1. **Too many changes = chaos.** Change *looks* on musical boundaries (8/16 bars); let the Reactive Layer only *pulse intensity* on the beat. (The Phrase/Reactive split already does this — preserve it.)
2. **No restraint / no negative space.** Keep breakdowns genuinely dim; reserve white/full/strobe/laser for drops.
3. **Beats off-grid/jittery.** Local interpolated metronome, never raw packet timing.
4. **Reacting too late.** Audio-derived energy lags (mastered tracks compressed — exactly why v1 struggled); use PDL position + MIDI intent to *anticipate* the drop.
5. **Hue ignoring energy.** Drive brightness/saturation off energy, hue off band (the two-axis model).
6. **Strobe/laser overuse.** Ration; auto-expire bursts; lasers off by default.
7. **Random fixture movement looks broken.** Pair the two MHs as **symmetric mirror** by default; reserve asymmetry for deliberate effects (the "choreographed" quality).
8. **Rotating scenes mid-mix.** Hold during the mix; resolve on the new downbeat; hold ≥4 bars.

**Pro tip that ties it together:** land big moments on **bar 1 of a phrase**, make movement/brightness **monotonic through a build**, and **hold looks longer than feels necessary**. "Looks timecoded but runs live" is the bar.

---

### Key sources
Perception: PNAS 2011 (chimpanzee pitch-luminance), PNAS 2013 (music-color via emotion), PMC5835347/PMC6407832 (crossmodal reviews), designingsound.org (hue-mapping arbitrariness). Laser safety: FDA "Laser Light Shows" + Laser Notice 55 (21 CFR 1040.10/1040.11c), ILDA audience-scanning safety, IEC 60825-1. Strobe: WCAG 2.3.1, Epilepsy Foundation photosensitivity. Aesthetics: EDM Identity / Pollstar / Robe / Resolume coverage of Dom Dolla, John Summit, Zedd; Duck Lights EDM programming; Ticket Fairy timecode-vs-busking.
