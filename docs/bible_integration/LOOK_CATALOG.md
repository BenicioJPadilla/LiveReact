# Bible look catalog — full extraction

Extracted from `spec/LIGHTING_BIBLE.md` (all line numbers refer to that file as
checked out 2026-09-10). 30 named looks total: 3 unnumbered `break_*` + 27
numbered (`4.` through `30.`). Cross-reference: `spec/conformance.md`'s `LOOK-*`
rows track implementation status per rule; this file tracks the *look catalog
itself* as data, for Phase 5's build-out.

Fields not present on a given look are the Bible's own gap, not an extraction
omission — noted explicitly where that's the case.

## BREAK (§5, lines 743-761 — unnumbered)

### `break_low_wash` (744-752)
`[BREAK]`, both genres. `requires{wash, rgb, atm 0.0, wash≥1}`. `degrade_to: null`.
`scaling{1:single centre; 2:L/R unison; 3-4:even; 5-8:symmetric pairs; 9+:2-group}`.
`roles{wash 15–35%, cold_steel}`. `reactivity{audio:[wash.dimmer, soft RMS
breathing], static:[hue], kick_follow:false, justification:"a break has no
transients to chase, so only a slow envelope earns reactivity; hue static to
avoid churn"}`. `fog_lead 0`, `priority 50`, `dark 60%`, `min_hold 16`.
`transition_in crossfade_bars:2`. `conflicts[peak_strobe_blackout]`.

### `break_single_spot_special` (753-756)
`[BREAK]`. `requires{spot, pan_tilt, atm 0.0}`. `degrade_to: break_low_wash`.
`roles{spot 40–70%, narrow, position dj_booth}`. `reactivity{static all,
kick_follow:false}`. `dark 80%`, `min_hold 16`.

### `break_ceiling_drift` (757-760)
`[BREAK]`, techhouse. `requires{spot, pan_tilt, atm 0.0}`. `movement{tilt_drift,
sine, period_bars 8, tilt_amp 15%}`. `dark 50%`, `min_hold 16`.

## BUILD (§5, lines 764-780)

### `build_riser_wash` (canonical build) (764-771)
`[BUILD]`, both. `requires{wash, atm 0.0}`. `roles{wash dimmer ramp 20→95% over
build length}`. `reactivity{audio:[wash.dimmer tied to bar-count envelope],
static:[hue], kick_follow:false, justification:"the ramp IS the build; drive it
from bar position, not audio, to stay predictable"}`. `dark 30→0%`, `min_hold 8`.
Escalation: "dimmer + fixture count rise; strobe/laser/prism held for the drop."
**Already mostly built** in `engines/reactive.py`'s `_bucket_wash_level` BUILD
branch (`LOOK-04`, confirmed PASS). **Built 2026-09-12**: `scenes/library.py`'s
`BuildRiserWash` gives it a real `Scene` identity; "static:[hue]" NOT
implemented for this specific look, disclosed in the class's own docstring.

### `build_snare_accent` (772-776)
`[BUILD]`, bigroom. `requires{wash or blinder, native strobe or dimmer}`.
`reactivity{audio:[accent flashes locked to detected snare subdivision,
quantized to 1/8], kick_follow:false, justification:"the snare roll is the one
place transient-following reads as intentional"}`. "Flashes obey §13."
`dark 20%`, `min_hold 8`. **Depends on new snare-roll subdivision detection —
see plan doc's Phase 5/Question 7.**

### `build_beam_raise` (777-780)
`[BUILD]`, both. `requires{spot, pan_tilt, atm 0.5}`. `degrade_to:
build_riser_wash`. `movement{tilt_raise, ramp, period=build, tilt 20→70%}`.
`fog_lead 8`, `min_hold 8`. **Atm-gated — always degrades on this rig.**

## DROP (§5, lines 784-816)

### `drop_blackout_hit` (784-789)
`[DROP]`, techhouse. `requires{any, atm 0.0}`. `transition_in blackout_beat`.
`roles{wash full, spot full open}`. `color{blood_red or cold_steel, unison}`.
`reactivity{static all, kick_follow:false, justification:"the cut IS the
effect; nothing reacts"}`. `dark 10%`, `min_hold 8`.
`conflicts[all build looks]`. **Built 2026-09-12**: `scenes/library.py`'s
`DropBlackoutHit`. `transition_in blackout_beat` is handled separately by
`build_to_drop_bridge`'s merge-level mechanism, not this class.

### `drop_beam_fan` (790-801)
`[DROP,PEAK]`, both. `requires{spot, wheel+, pan_tilt, atm 0.6, spot≥2}`.
`degrade_to: drop_blackout_hit`. `scaling{1:single sweep; 2:mirrored pan 180°
phase, SR inverted; 3-4:symmetric fan from centre; 5-8:even phase across pan;
9+:phase + alternating subgroup}`. `roles{spot 60–100%, narrow, gobo open,
position dancefloor_centre}`. `movement{fan, sine, period_bars 2, phase_offset
180, pan_amp 30%, tilt_amp 15%, mirror_pan true}`. `color{cold_steel, unison}`.
`reactivity{static pan+hue, kick_follow:false, justification:"choreographed
motion reads pro; audio-reacting a fan looks broken"}`. `fog_lead 8`,
`dark 25%`, `min_hold 8`. **Atm-gated — always degrades to `drop_blackout_hit`
on this rig** (also only 1 spot fixture — `spot≥2` unmet regardless of atm).

### `drop_strobe_stab` (802-806)
`[DROP]`, both. `requires{wash or blinder, native_strobe_channel}`.
`reactivity{audio:[strobe gated to drop-accent bars only], kick_follow:false}`.
"Uses native strobe channel, never dimmer toggling (§11). ≤ §13 limit."
`dark 20%`, `min_hold 8`. **Built 2026-09-12**: `scenes/library.py`'s
`DropStrobeStab` — real, hardware-verified strobe path already exists
(`WashBar.set_strobe`, owned by `ReactiveLayerEngine`, unaffected by which
Phrase scene runs); this class supplies color/movement context only.

### `drop_color_slam_bigroom` (807-811)
`[DROP,PEAK]`, bigroom. `requires{wash, spot, atm 0.0}`. `color{sunset_split,
split_by_role, ≤3 hues}`. `reactivity{static hue, audio:[wash.dimmer emphasis
on first beat of each bar only], kick_follow:false}`. `dark 10%`, `min_hold 8`.

### `drop_laser_punctuation` (812-816)
`[DROP,PEAK]`, both. `requires{laser, atm 0.6}`. `degrade_to: drop_beam_fan`
(which itself degrades to `drop_blackout_hit` — the recursive-degrade case, see
plan doc's Open Question #3). `roles{laser active, pattern static beam-fan held
in 0–127 band}`. `fog_lead 8`, `min_hold 8`. "Gated hard on density ≥ 0.6."
`conflicts[break looks]`. **Atm-gated.**

### `drop_wash_slam_clear` (846-848)
`[DROP,PEAK]`, both. `requires{wash, atm 0.0}`. `color{blood_red, unison}`.
Static. `dark 20%`, `min_hold 8`.

### `drop_gobo_projection_clear` (853-856)
`[DROP]`. `requires{spot, gobo, atm 0.0}`. `roles{gobo rotate, position
back_wall, wide zoom}`. Static. `dark 20%`, `min_hold 8`. **No gobo capability
exists on this rig — always degrades (no `degrade_to` declared by the Bible;
falls to round-robin per Open Question #3's default) until hardware changes.**

### `drop_blinder_clear` (866-868)
`[DROP]`. `requires{wash or blinder, atm 0.0}`. `roles{full white/warm}`.
`min_hold 4`.

## PEAK (§5, lines 820-833)

### `peak_full_rig` (820-823)
`[PEAK]`, bigroom. `requires{wash, spot, atm 0.0}`. `roles{wash 85–100%, spot
100%}`. `color{≤3 hues}`. `movement{spots slow fan, period_bars 4}`.
`reactivity{static hue+pan, kick_follow:false}`. `dark 10%`, `min_hold 8`.

### `peak_beam_sweep` (824-827)
`[PEAK]`, techhouse. `requires{spot, pan_tilt, atm 0.6}`. `degrade_to:
peak_full_rig`. `movement{sweep, triangle, period_bars 2, pan_amp 40%,
mirror_pan true}`. `fog_lead 8`, `dark 15%`, `min_hold 8`. **Atm-gated.**

### `peak_strobe_blackout` (828-830)
`[PEAK]`, techhouse. `requires{blinder or wash, native strobe}`. "strobe
bursts ≤ 1.5s then blackout, ≤ §13." `min_hold 4`.
`conflicts[break_low_wash]`.

### `peak_laser_tunnel` (831-833)
`[PEAK]`, both. `requires{laser, atm 0.7}`. `degrade_to: peak_beam_sweep`
(itself degrades to `peak_full_rig` — another recursive-degrade case).
`roles{laser tunnel pattern, static rotation band}`. "Gated density ≥ 0.7."
`min_hold 8`. **Atm-gated.**

### `peak_color_pulse_clear` (849-852)
`[PEAK]`. `requires{wash, atm 0.0}`. `reactivity{audio:[wash.dimmer on bar
downbeat only, 1/bar], kick_follow:false, justification:"one pulse per bar is
bar emphasis, not kick-following"}`. `dark 15%`, `min_hold 8`.

### `peak_alt_hits_clear` (862-865)
`[PEAK]`. `requires{spot, pan_tilt, atm 0.0}`. `scaling{2:alternate L/R snap
each bar}`. `movement{snap_alternate, period_bars 1}`. Static. `dark 25%`,
`min_hold 8`. **Only 1 spot on this rig** — reuse `Converge`'s existing
single-fixture-substitution pattern (`MOVE-12`, confirmed PASS) per the plan.

## OUTRO (§5, lines 837-842)

### `outro_fade_wash` (837-839)
`[OUTRO]`, both. `requires{wash, atm 0.0}`. `roles{wash 40→15%}`.
`color{warm_white / deep_amber}`. `dark 60%`, `min_hold 16`.
`transition_in crossfade_bars:2`.

### `outro_single_beam` (840-842)
`[OUTRO]`. `requires{spot, atm 0.0}`. `roles{one spot ceiling_bounce, dim}`.
`dark 80%`, `min_hold 16`.

## Clear-air (atm 0.0) variants not yet listed above

### `build_wash_clear` (857-858)
Alias: "`build_riser_wash` gated atm 0.0 (primary build)" — no separate field
set in the Bible; not a distinct definition. Treat as `build_riser_wash` with
an explicit `min_atmosphere_density=0.0` (already implied — `build_riser_wash`
already requires `atm 0.0`), i.e. this is the Bible naming its own primary
build as also being "the clear-air variant." No separate `Scene` subclass
needed.

### `break_color_hold_clear` (859-861)
`[BREAK]`. `requires{wash, atm 0.0}`. `color{deep_blue}`. Static. `dark 50%`,
`min_hold 16`.

## Utility / structural (§5, lines 872-890)

### `all_dark` (872-873)
"reserved darkness / cut. any mode." `roles all 0`. `transition snap`.
`min_hold 1` (momentary).

### `safe_default` (874-876) — **built in Phase 1**
"failsafe look (§12). any mode." `roles{wash 40% neutral_wash, static}`. "No
movers moving, no laser, no fog. Baseline priority." Implemented:
`scenes/base.py`'s `SafeDefault`/`SAFE_DEFAULT`.

### `spot_position_change` (877-879)
"reposition-only cue (palette move, not a motion effect)." `movement{snap or
1-bar move to named position}`. "Used on phrase events (§6.3)." **No
`requires{}`/`degrade`/`conflicts`/`color`/`dark%`/`min_hold`/`fog_lead`/
`priority` given — under-specified in the Bible itself relative to the other
28 looks, not an extraction gap.**

### `chase_wash_lr` (880-883)
`[BUILD,PEAK]`. `requires{wash≥2}` — satisfied (2 wash-role fixtures exist).
`movement{chase, period_bars 2, phase by x_norm}`. `scaling{2:L then R; 3-4:
sequential by x_norm; 5-8:even phase; 9+:phase+subgroup}`. `dark 30%`,
`min_hold 8`.

### `mirror_cross_beam` (884-887)
`[DROP,PEAK]`. `requires{spot≥2, atm 0.6}`. `movement{cross, sine, period_bars
4, phase 180, pan_amp 25%, mirror_pan true}`. `degrade_to: peak_beam_sweep`
(itself degrades further — recursive-degrade case). `min_hold 8`.
**Atm-gated, and only 1 spot exists (`spot≥2` unmet regardless).**

### `build_to_drop_bridge` (888-890)
`[BUILD→DROP]`. "managed handoff for the pre-drop bar." `transition_in
blackout_beat`. "Holds dark on the final bar, releases to the DROP look on the
downbeat." `min_hold 1`. **No `requires{}`/`degrade`/etc. given — same
under-specification pattern as `spot_position_change`.** **Built
2026-09-12** as a merge-level mechanism, not a `Scene` subclass (it's a
cross-cutting cue, not something `SceneCatalog.pick()` would ever choose)
— reuses Phase 3's `_pending_drop_release` beat-quantization directly;
see `merge/merge.py`'s `finalize(..., drop_pending=...)`.

## Summary tables

### Presence of `requires{}` / `degrade_to` / `conflicts[]` across all 30

| Field | Present on | Missing on |
|---|---|---|
| `requires{}` | 28/30 | `spot_position_change`, `build_to_drop_bridge` |
| `degrade_to` | 7/30 (`break_single_spot_special`, `build_beam_raise`, `drop_beam_fan`, `drop_laser_punctuation`, `peak_beam_sweep`, `peak_laser_tunnel`, `mirror_cross_beam`) | the other 23 |
| `conflicts[]` | 4/30 (`break_low_wash`↔`peak_strobe_blackout`, `drop_blackout_hit`↔"all build looks", `drop_laser_punctuation`↔"break looks", `peak_strobe_blackout`↔`break_low_wash`) | the other 26 |

### Atmosphere-gated (always degrade on this rig — no haze hardware)

`build_beam_raise` (0.5), `drop_beam_fan` (0.6), `drop_laser_punctuation` (0.6),
`peak_beam_sweep` (0.6), `peak_laser_tunnel` (0.7), `mirror_cross_beam` (0.6).

### Recursive-degrade chains (more than one hop — Open Question #3 applies)

`drop_laser_punctuation → drop_beam_fan → drop_blackout_hit`
`peak_laser_tunnel → peak_beam_sweep → peak_full_rig`
`mirror_cross_beam → peak_beam_sweep → peak_full_rig`

### Capability-limited independent of atmosphere (this specific rig's fixture count)

`drop_beam_fan`/`mirror_cross_beam`/`peak_alt_hits_clear` (need `spot≥2`, this
rig has 1), `drop_gobo_projection_clear` (needs `gobo`, no fixture has one).

### Phase 5 build order (from the plan)

1. First wave: `safe_default` (Phase 1, done), `drop_blackout_hit`,
   `build_to_drop_bridge`, `drop_strobe_stab`, `build_riser_wash`-as-a-look.
2. `build_snare_accent` (depends on new audio-transient work).
3. Negative-space (`dark_pct`) infrastructure.
4. Clear-air wave 2: `break_single_spot_special`, `break_ceiling_drift`,
   `drop_color_slam_bigroom`, `peak_full_rig`, `outro_fade_wash`,
   `outro_single_beam`, `drop_wash_slam_clear`, `peak_color_pulse_clear`,
   `drop_gobo_projection_clear`, `build_wash_clear`, `break_color_hold_clear`,
   `peak_alt_hits_clear`, `drop_blinder_clear`, `all_dark`,
   `spot_position_change`, `chase_wash_lr`.
5. Last: the 6 atmosphere-gated looks, as thin degrade-only stubs.
