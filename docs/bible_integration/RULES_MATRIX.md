# Bible-integration rules matrix

**This is an index and phase-tracker, not a duplicate.** The authoritative per-rule
table — Rule ID | Assertion | Severity | Status | Evidence (file:line) | Notes — is
`spec/conformance.md` (170 rows, maintained since the original 6-stage audit). This
file adds the two things that table doesn't carry: which Bible-integration **phase**
resolves each category, and a per-phase before→after status delta as work lands.
Re-derive the summary counts below from `spec/conformance.md` directly if this file
and that one ever disagree — `spec/conformance.md` is the source of truth for status.

Plan: `/Users/joshuaracimora/.claude/plans/adaptive-squishing-pebble.md`.

## Status snapshot (re-verified 2026-09-10, before any Phase-1 code changes)

| Status | Count |
|---|---|
| NOT-IMPLEMENTED | 70 |
| PARTIAL | 28 |
| PASS | 26 |
| FAIL | 18 |
| N/A | 5 |
| UNKNOWN | 5 |
| (parsing-artifact rows, need manual reconciliation) | 18 |

## Category → phase map

| Prefix | Count | Bible-integration phase | Notes |
|---|---|---|---|
| MANIFEST | 6 | **Corrected 2026-09-13 (audit finding)**: Phase 1 never actually resolved this category -- its own plan text only ever promised `LOOK-08`/`FAIL-04`. Only `MANIFEST-01` has any real fix, and that's from the pre-Bible-integration Stage 6 audit, not Phase 1. `MANIFEST-02/03/04/05/06` remain NOT-IMPLEMENTED/never-evaluated -- unscheduled, not owned by any phase. | This row previously overclaimed Phase 1 ownership of the whole category; `Fixture.capabilities()`/`Rig.capabilities()` (genuinely Phase 1) cover a narrower slice than the full MANIFEST taxonomy (x_norm ordering, atmosphere-device schema fields, brand-name-free capability tiers) implies. |
| MERGE | 22 | Phase 4 (priority-tiered merge) | MERGE-14..17 (release/fade) explicitly deferred — see plan §Phase 6 note |
| COLOR | 15 | Phase 4 (LTP-by-priority closes most of these) | |
| ATMO | 21 | Out of scope — no haze/fog hardware exists | Revisit only if hardware is added |
| LOOK | 9 | Phase 1 (LOOK-08) + Phase 5 (the rest) | |
| MOVE | 12 | Phase 5 (MOVE-03/07/09), Phase 4 (MOVE-05 via merge) | |
| BEAM | 4 | Phase 5, atm-gated stub looks (Phase 5's last wave) | |
| LASER | 15 | Already substantially PASS (prior sessions' audit); untouched by this migration | |
| TIME | 15 | Phase 2 (TIME-11/12/13), Phase 3 (TIME-01/04 reframed), Phase 6 (TIME-20/21) | |
| TRANS | 5 | **Explicitly excluded** — Josh's hold, separate future session | |
| LATENCY | 3 | LATENCY-03 is a documentation-hygiene item, not a build task | |
| FAIL | 9 | Phase 1 (FAIL-04), Phase 3 (FAIL-01, PDL-loss handling) | |
| SAFE | 24 | Already substantially PASS/PARTIAL (prior sessions); SAFE-01..06 Hz-calibration explicitly deferred (separate, tracked project) | |
| CONSOLE | 5 | Not touched by this migration | |
| PROBE | 5 | Not touched by this migration | |

## Every FAIL, individually (active defects, not "doesn't exist yet")

**Reconciled 2026-09-12 (Phase 6 audit sync)**: this list itself had drifted —
`MERGE-02`/`MERGE-03`/`MERGE-06`/`MERGE-19` (resolved Phase 4, `8a68bd5`),
`TIME-12` (resolved Phase 2, `3953283`), `LOOK-03`/`TIME-21` (resolved Phase 6,
`8e91245`) were all still listed here despite being genuinely fixed, in some
cases for a full session already — the per-phase delta logs below were kept
current as work landed, but this summary table and `spec/conformance.md`'s
own per-rule rows were not synced to match at the same time. Removed from
this list below; `spec/conformance.md` rows updated in the same pass as this
file. **Still genuinely open** (unchanged by anything built this session):

| Rule | Assertion | Resolving phase |
|---|---|---|
| `MERGE-05` | Pan/tilt merges as `base(LTP) + Σ offsets`, slew-clamped | Phase 4 — still PARTIAL, honestly (see Phase 4 delta log) |
| `MERGE-07` | Gobo index merges LTP+snap (latent) | Phase 4 — latent, nothing writes these channels yet |
| `MERGE-08` | Prism-engage merges LTP+snap (latent) | Phase 4 — latent, nothing writes these channels yet |
| `LOOK-02` | Mirrored-fan requires inverted opposite-side geometry | Phase 5 — NOT built this session |
| `LOOK-08` | `safe_default` = static 40% neutral wash, no motion/laser/fog | **Phase 1 — target fixed, fade-timing still open** |
| `MOVE-03` | Mis-declared mirror geometry disables mirroring, warns | Phase 5 — NOT built this session |
| `MOVE-07` | Continuous motion reserved for DROP/sustained PEAK | Phase 5 — mechanism (`ReactiveLayerEngine`'s own spot loop) unchanged; Scene-layer content now differentiated by bucket, see `spec/conformance.md`'s updated row |
| `MOVE-09` | Movers home at half-slew on arm | Phase 5 — NOT built this session (Phase 5 was scene/look content, not fixture boot sequencing) |
| `TRANS-02` | Crossfade interpolates LTP color in Oklab | **Excluded — Josh's hold** |
| `FAIL-03` | On audio loss, Reactive stops writing | Phase 3 |
| `FAIL-04` | Total signal loss fades to `safe_default` over 2 bars | **Phase 1 — target fixed (instant switch), fade-timing still open** |

## UNKNOWN rows to resolve

- `MOVE-10`/`FAIL-07` — possible spec self-contradiction (movers hold-vs-home on signal loss). Needs the Bible's own text re-read side-by-side before Phase 5 locks target behavior.
- `LATENCY-03` — documentation-hygiene only (don't conflate the ~20Hz frame-rate Nyquist ceiling with the real SAFE-01..08 safety ceiling in future comments).
- `FAIL-02` — MIDI-loss behavior likely already correct; needs a dedicated test to convert honestly from UNKNOWN.
- `SAFE-09` — "full-field" definition needed before this can be evaluated; proposed default in the plan doc, flagged as safety-adjacent (needs Josh's read).

## Phase 2 delta log (2026-09-11 -- state model, asymmetric hysteresis, legal transitions, PEAK/OUTRO, drop marker)

| Rule | Before | After | Evidence |
|---|---|---|---|
| `TIME-11` | NOT-IMPLEMENTED (different model -- 4 states, no PEAK) | PASS | `scenes/base.py`'s `EnergyBucket` (5 values: BREAK/BUILD/DROP/PEAK/OUTRO); `core/metronome.py`'s `PER_STATE_DWELL_BARS`/`PER_STATE_DWELL_S` (bars converted at `NOMINAL_BPM=128`); PEAK/OUTRO reached only via `_apply_bucket_overlay`, never a raw energy level (see `EnergyBucket`'s own docstring for why) |
| `TIME-12` | FAIL (flat 5% hysteresis, symmetric) | PASS | `scenes/catalog.py`'s `HYSTERESIS_MARGIN_UP=0.05`/`HYSTERESIS_MARGIN_DOWN=0.15`, direction-aware in `bucket_for_energy_with_hysteresis`; `core/metronome.py`'s `FAST_ENTRY_DWELL_S`/`EXIT_CONFIRM_DWELL_S`, direction-aware in `_derive_bucket` |
| `TIME-13` | NOT-IMPLEMENTED (no legality concept, a bucket could jump BREAK->DROP directly) | PARTIAL — one real illegal case enforced | `core/metronome.py`'s `_derive_bucket`: the one pairing that actually matters given the 3-value base classifier (DROP falling straight back to BUILD) is explicitly rejected; BREAK->DROP "cut-in" is correctly still legal per the Bible's own matrix (not a bug); full `LEGAL_TRANSITIONS` table lives in `scenes/catalog.py` for reference even though only the DROP->BUILD case is reachable in practice at the base-classifier level; tests: `tests/test_metronome.py::test_classifier_uses_the_declared_legal_transition_matrix`. **2026-09-17 (D3)**: DROP->BUILD is now DECLARED LEGAL as a confirmed exit (two-bar `CUT_EXIT_CONFIRM_S`) — see `SPEC_DEVIATIONS.md` D3 and conformance TIME-13; `test_drop_falls_back_to_build_only_after_two_bars_of_build_range_energy` pins it |
| — (new, not a numbered rule) | — | Loud-to-quiet-to-loud drop marker + same-track `drop_cycle` counter, corroborating signal alongside (not gating) bucket classification | `core/metronome.py`'s `_derive_drop_marker`; **verified against the real capture that exposed the original scene-desync bug** (`recordings/session-20260909-171454`): correctly found 2 real DROP->PEAK cycles (this track's two actual drops) plus one extra marker coinciding with an OUTRO->BUILD swing, not a real second drop -- disclosed honestly as a real limitation (the heuristic catches any qualifying dip-then-rebound, not exclusively "the big drop"), not smoothed over; tests: `tests/test_metronome.py::test_drop_marker_fires_after_a_qualifying_dip_and_rebound`, `::test_drop_marker_does_not_fire_on_a_normal_short_gap`, `::test_drop_cycle_resets_on_a_track_transition` |
| — (new, not a numbered rule) | — | Manual-override entry point (`Metronome.request_manual_bucket`), unused until Phase 5's DJ-trigger buttons | `core/metronome.py`; tests: `tests/test_metronome.py::test_manual_bucket_override_takes_priority_and_is_consumed_once` |

**Re-verified via the same real capture used for Phase 1's scene-rotation fix**: 17 total bucket-state transitions across the ~300s track (vs. the pre-fix baseline's 26 flips in ~4 minutes that originally motivated `BUCKET_MIN_DWELL_S`/`HYSTERESIS_MARGIN`) — no flapping regression from the new per-state dwell/asymmetric-hysteresis/legal-transition machinery. One noted characteristic, not a bug: PEAK can toggle back to a plain DROP display on a single tick where `energy_norm` dips just under `BUILD_MAX(0.80)` (seen twice in the real capture, at t=49.4s and t=131.3s) -- both states render at nearly the same brightness (`DROP_INTENSITY=0.9` vs `PEAK_INTENSITY=0.97`), so this is a low-risk, likely-imperceptible category of transition, unlike the old BREAK<->DROP-class flapping.

## Phase 3 delta log (2026-09-12 -- beat-quantized DROP release, transition_likely heuristic)

| Rule | Before | After | Evidence |
|---|---|---|---|
| `TIME-01`/`TIME-04`/`LOOK-09`/`TRANS-03` | NOT-IMPLEMENTED (different architecture -- no PDL phrase prediction exists on this hardware, confirmed a genuine data-source limitation, not an unbuilt feature) | PARTIAL — intent satisfied via a disclosed substitution, not literal §9.6 | `docs/bible_integration/SPEC_DEVIATIONS.md`'s D1 entry (formal, disclosed deviation, matching the project's `spec/03-lighting-bible-corrections.md` pattern); `core/metronome.py`'s `_pending_drop_release`/`_commit_drop` (a confirmed DROP waits for the next real downbeat rather than committing mid-bar); tests: `tests/test_metronome.py::test_drop_commits_immediately_when_already_on_a_downbeat`, `::test_drop_waits_for_the_next_downbeat_when_confirmed_mid_bar`, `::test_pending_drop_release_cancels_if_energy_backs_off_first` |
| — (new, not a numbered rule) | — | `transition_likely` heuristic (dwell-in-DROP/PEAK past a typical duration, or several drops already in-track) -- plain rule, not ML, unconsumed seam for a future phase | `core/metronome.py`'s `TYPICAL_EXTENDED_PEAK_S`/`TRANSITION_LIKELY_DROP_CYCLE_THRESHOLD`; tests: `tests/test_metronome.py::test_transition_likely_after_a_typically_long_peak`, `::test_transition_likely_after_several_drops_in_one_track` |

**Re-verified against the same real capture, this time feeding its actual recorded `beat` field** (earlier Phase 1/2 verification passes left `beat_in_bar` at the Metronome's default the whole time, meaning they never actually exercised beat-quantization at all -- caught and corrected here): the track's first drop happened to land already on beat 1 (no delay); the second drop incurred a real, small 0.4s wait for the next downbeat -- both well within the expected "at most one bar" bound, no correctness issue. `transition_likely` fired at exactly 30.0s into the first sustained drop (16 bars × 1.875s/bar at the nominal 128 BPM), precisely matching the configured threshold, and correctly did NOT fire for the second drop (which only lasted ~24s, genuinely under the threshold).

## Phase 4 delta log (2026-09-12 -- priority-tiered merge, conflict arbitration)

| Rule | Before | After | Evidence |
|---|---|---|---|
| `MERGE-02` | FAIL | PASS | Same mechanism as MERGE-03 below (shared root cause) |
| `MERGE-03` | FAIL (confirmed live root cause of "still blue during the drop") | PASS | `engines/{reactive,phrase,transition}.py`'s `priority` class attrs (25/50/100, LIGHTING_BIBLE.md §2.3's Titan tiers); `core/show_engine.py` tags each `Contribution` with its producing engine's priority; `merge/merge.py`'s `merge_contributions` -- COLOR now LTP-by-priority (highest-priority toucher's whole value wins), not a per-channel max; tests: `tests/test_spec_conformance_gaps.py::test_hue_merges_by_priority_not_by_per_channel_max` (now PASSES, was one of the 5 original intentionally-failing tests), `tests/test_merge.py::test_color_merges_ltp_by_priority_not_per_channel_max` |
| `MERGE-05` | FAIL | **Still PARTIAL, honestly** — MOVEMENT is now real LTP-by-priority (principled, not an accident of list order), but the Bible's full `base(LTP) + Σ offsets` additive formula is NOT built -- Phrase (50) still outright wins over Reactive (25) on any channel both touch, same practical outcome as before for this specific case. Caught and fixed a real false-positive during this same pass: `tests/test_spec_conformance_gaps.py::test_reactive_layer_movement_is_not_wholly_discarded_by_phrase_movement` initially appeared to flip to PASS, but only because neither `Contribution` in the test had an explicit priority set (both defaulted to 0, so a tie-break accident -- not genuine combination -- picked the first-listed one). Fixed the test to set real priorities matching production; it correctly fails again. | `merge/merge.py`'s own docstring documents this gap explicitly; `docs/bible_integration/RULES_MATRIX.md` (this row) |
| `MERGE-06` | FAIL (color-wheel slot merged by max, could land on a numerically-higher but wrong-priority slot) | PASS | Same LTP-by-priority mechanism, applied uniformly to COLOR (the wheel byte is tagged COLOR, MERGE-06/mistagging itself untouched -- see below); tests: `tests/test_spec_conformance_gaps.py::test_color_wheel_slot_is_snap_by_priority_not_byte_max` (now PASSES, was one of the 5 original intentionally-failing tests) |
| `MERGE-07`/`MERGE-08` | NOT-IMPLEMENTED (latent -- nothing writes gobo/prism yet) | Still NOT-IMPLEMENTED in the sense that no code writes these channels, but now correctly LTP-by-priority (not max) the moment anything does, since OTHER/COLOR both route through the same fixed logic | `merge/merge.py` |
| `MERGE-19` | FAIL ("as specified" -- worked today only by accident, TransitionEngine's white lift happened to win via literal max(255)) | PASS (mechanism now real) | `TransitionEngine.priority = 100`, genuinely the highest tier, so its writes now win by declared priority, not by coincidentally writing the numeric maximum |
| `LOOK-06` | NOT-IMPLEMENTED (`conflicts[]` declared on `Scene` since Phase 1, never enforced) | PASS | `scenes/catalog.py`'s `SceneCatalog._conflicts`/`pick()`'s conflict filter (Open Question #4's approved default: exclude the conflicting candidate, no forced pre-emption of the current look, bidirectional check since the Bible declares conflicts one-sidedly); tests: `tests/test_scenes.py::test_pick_excludes_a_scene_that_conflicts_with_the_current_one`, `::test_pick_conflict_check_is_bidirectional`, `::test_pick_never_hard_fails_even_if_everything_conflicts` |

**Re-verified against the real capture, replaying the actual `ReactiveLayerEngine`+`PhraseEngine` pipeline with real priorities** (not just isolated unit tests): during the real first drop, the OLD max()-merge produced a visibly flickering, muddy composite color on the wash bar -- tick-to-tick values like (74,133,255) -> (135,135,255) -> (106,133,255) -> (81,133,255), never settling -- while the NEW priority-LTP merge holds a clean, stable (51,133,255) for the entire window. This is a more concrete, more visually-relevant demonstration of the fix's value than the unit tests alone show: the original bug wasn't just "sometimes the wrong color wins," it was real per-tick color instability from two engines' independently-fluctuating values being max-merged together, which reads as exactly the "doesn't feel clean" quality problem from the original live complaints.

## Phase 5 delta log (2026-09-12, first wave -- BUILD/DROP families)

Scope note: Phase 5 covers all 30 Bible looks eventually; this pass covers
the first, highest-impact wave (the looks most directly tied to tonight's
original live-test complaints). Remaining DROP looks
(`drop_color_slam_bigroom`, `drop_wash_slam_clear`, `drop_gobo_projection_
clear`, `drop_blinder_clear`), `build_snare_accent` (needs new audio-
transient infrastructure, tracked separately), and the PEAK/BREAK/OUTRO/
utility/atmosphere-gated waves are follow-up work under the same phase.

| Rule | Before | After | Evidence |
|---|---|---|---|
| `build_to_drop_bridge` (new look, [BUILD→DROP]) | NOT-IMPLEMENTED | PASS | `merge/merge.py`'s `finalize(..., drop_pending=...)` -- reuses Phase 3's `_pending_drop_release` directly: a confirmed-but-not-yet-released DROP now forces a genuine hard cut (not `safe_default`'s dim wash) until the downbeat releases it. `core/show_state.py`'s `drop_pending` field, `core/show_engine.py` wiring; tests: `tests/test_merge.py::test_drop_pending_forces_a_hard_cut`, `::test_manual_blackout_wins_over_drop_pending` |
| `drop_blackout_hit` (new look, [DROP]) | NOT-IMPLEMENTED | PASS | `scenes/library.py`'s `DropBlackoutHit` -- static color/position (no beat-pulse, no continuous hue, matching "the cut IS the effect"), alternates `blood_red`/`cold_steel` by `drop_cycle` (not audio -- Josh's "doesn't have to be white" preference, satisfied without contradicting "static, nothing reacts"), `conflicts` with every BUILD-bucket scene name; tests: `tests/test_scenes.py::test_drop_blackout_hit_alternates_blood_red_and_cold_steel_by_drop_cycle`, `::test_drop_blackout_hit_color_is_static_not_audio_reactive`, `::test_drop_blackout_hit_conflicts_with_every_build_scene` |
| `drop_strobe_stab` (new look, [DROP]) | NOT-IMPLEMENTED | PARTIAL | `scenes/library.py`'s `DropStrobeStab` -- provides the color/movement context; the actual "native-strobe stabs" are already produced by `ReactiveLayerEngine`'s own strobe channel (a separate DMX byte, unaffected by which Phrase scene is active) -- this look deliberately doesn't touch that channel itself. Still subject to the pre-existing, separately-tracked SAFE-01..06 Hz-calibration gap (unrelated to this look, not re-litigated here); test: `tests/test_scenes.py::test_drop_strobe_stab_does_not_touch_the_strobe_channel_itself` |
| `build_riser_wash` (new look, [BUILD]) | NOT-IMPLEMENTED (ramp existed only inside `ReactiveLayerEngine`, no selectable look identity) | PARTIAL | `scenes/library.py`'s `BuildRiserWash` -- gives the existing, already-correct (`LOOK-04`, PASS) bar-position ramp a real catalog identity; does NOT implement "static:[hue]" for this specific look (disclosed, not faked -- would need new per-scene state tracking); test: `tests/test_scenes.py::test_build_riser_wash_does_not_set_wash_intensity` |

**Re-verified against the real capture, running the full pipeline** (`Metronome` → `ReactiveLayerEngine`/`PhraseEngine` → merge/finalize, not just isolated unit tests): `Drop Blackout Hit` was genuinely selected and rendered during a real drop (t=80.9s); the `drop_pending` blackout fired a real, clean 0.4s hard cut immediately before the second drop's release, confirmed all-zero via the actual `finalize()` output, then released cleanly the instant the downbeat arrived. `Drop Strobe Stab`/`Build Riser Wash` weren't round-robin-selected in this particular ~380s replay (11 scenes now share the rotation cursor) -- not a defect, just this replay's luck of timing; both are directly exercised by their own unit tests. Caught and fixed a verification-script bug during this same pass: an earlier version of the replay script fed `energy_norm`/`beat_in_bar` into a fresh `Metronome` instance but never advanced its internal `bar` counter, which silently froze `PhraseEngine`'s rotation check (it only acts "on a new bar") for the entire replay -- worth remembering alongside Phase 3's similar caught-in-verification lesson.

## Phase 5 delta log, second wave (2026-09-12 -- PEAK family)

PEAK went from zero looks (a real, total gap -- the state is new, nothing
had ever populated it) to three.

| Rule | Before | After | Evidence |
|---|---|---|---|
| `peak_full_rig` (new look) | NOT-IMPLEMENTED | PARTIAL | `scenes/library.py`'s `PeakFullRig` -- full spot intensity, a genuine slow 4-bar fan (distinct from DROP scenes' much faster sweeps); "static hue" not fully implemented (same disclosed gap as `BuildRiserWash`); tests: `tests/test_scenes.py::test_peak_full_rig_spots_at_full_intensity`, `::test_peak_full_rig_fan_completes_one_cycle_every_four_bars` |
| `peak_color_pulse_clear` (new look) | NOT-IMPLEMENTED | PASS | `scenes/library.py`'s `PeakColorPulseClear` -- a real bar-downbeat-only pulse, deliberately overriding wash intensity (the one exception to "Reactive owns dimmer," justified since this is a slow 1/bar quantized signal, not a competing per-tick chase). **Verified, not just theorized**, that the pulse actually shows through Reactive's own HTP dimmer hold for realistic `drop_hit_intensity` values (255 on-beat vs. 192-217 off-beat at 0.85-0.90), only disappearing once the hit itself is already ~0.97+ (both sides already maxed); tests: `tests/test_scenes.py::test_peak_color_pulse_clear_only_pulses_on_the_downbeat`, `::test_peak_color_pulse_clear_decays_across_the_downbeat`, `::test_peak_color_pulse_clear_is_actually_visible_through_reactives_htp_hold` |
| `peak_alt_hits_clear` (new look) | NOT-IMPLEMENTED | PASS | `scenes/library.py`'s `PeakAltHitsClear` -- generalized for this rig's single spot fixture the same way `Converge` was (`MOVE-12`): snaps between two positions every bar rather than a smooth sweep, matching `snap_alternate`'s "snap, don't sweep" semantics; tests: `tests/test_scenes.py::test_peak_alt_hits_clear_alternates_by_bar_on_a_single_fixture` |

**Re-verified against the real capture, full pipeline**: `Peak Full Rig` was genuinely selected and rendered during a real PEAK-bucket window (t=228.5s-238.9s); `Drop Strobe Stab`, `Peak Alt Hits Clear`, and `Peak Color Pulse Clear` were also exercised during the same replay (as crossfade participants, not necessarily long-settled). `Build Riser Wash` and `Locked Hold` weren't picked in this particular ~380s replay -- round-robin timing across 14 scenes now sharing the cursor, not a defect; both remain directly unit-tested.

## Phase 5 delta log, third wave (2026-09-12 -- BREAK family, commit `1922b29`)

BREAK went from 2 pre-Bible looks (`DeepWashBreathe`/`SlowColorCycleAmbient`)
to 6.

| Rule | Before | After | Evidence |
|---|---|---|---|
| `break_low_wash` (new look) | NOT-IMPLEMENTED | PASS | `scenes/library.py`'s `BreakLowWash` -- color only (`cold_steel`), wash intensity stays owned by `ReactiveLayerEngine`'s existing BREAK breathing envelope; `conflicts[peak_strobe_blackout]` forward-declared by name even though that PEAK look isn't built yet; tests: `tests/test_scenes.py::test_break_low_wash_does_not_set_wash_intensity`, `::test_break_low_wash_uses_cold_steel`, `::test_break_low_wash_conflicts_with_peak_strobe_blackout` |
| `break_single_spot_special` (new look) | NOT-IMPLEMENTED | PARTIAL | `scenes/library.py`'s `BreakSingleSpotSpecial` -- static 40-70% spot special, degrades to `BreakLowWash`; "position dj_booth" has no named-position mechanism in this codebase, expressed as a disclosed hardcoded pan/tilt guess; tests: `tests/test_scenes.py::test_break_single_spot_special_degrades_to_break_low_wash`, `::test_break_single_spot_special_spot_level_is_static_not_audio_reactive` |
| `break_ceiling_drift` (new look) | NOT-IMPLEMENTED | PASS | `scenes/library.py`'s `BreakCeilingDrift` -- slow sine tilt drift, period_bars 8, tilt_amp 15%; tests: `tests/test_scenes.py::test_break_ceiling_drift_tilt_completes_one_cycle_every_eight_bars`, `::test_break_ceiling_drift_stays_within_the_declared_tilt_amplitude` |
| `break_color_hold_clear` (new look) | NOT-IMPLEMENTED | PASS | `scenes/library.py`'s `BreakColorHoldClear` -- fully static `deep_blue`; test: `tests/test_scenes.py::test_break_color_hold_clear_is_static_color_and_position` |

**Verified against real capture data**: 0 crashes across all 3779 ticks;
`Break Low Wash` and `Break Single Spot Special` both genuinely
round-robin-selected during real BREAK windows and rendered correctly.
`Break Ceiling Drift`/`Break Color Hold Clear` weren't reached by
round-robin in this capture's dwell time -- disclosed, not claimed.

## Phase 5 delta log, fourth wave (2026-09-12 -- OUTRO family, commit `f666c8d`)

OUTRO went from zero looks (a genuinely new state, `SceneCatalog.pick()`
fell back to the full flattened catalog whenever the bucket was OUTRO) to two.

| Rule | Before | After | Evidence |
|---|---|---|---|
| `outro_fade_wash` (new look) | NOT-IMPLEMENTED | PASS | `scenes/library.py`'s `OutroFadeWash` -- color only (`warm_white`), wash intensity stays owned by `ReactiveLayerEngine`'s existing OUTRO_HIGH->OUTRO_LOW fade; test: `tests/test_scenes.py::test_outro_fade_wash_does_not_set_wash_intensity` |
| `outro_single_beam` (new look) | NOT-IMPLEMENTED | PARTIAL | `scenes/library.py`'s `OutroSingleBeam` -- a real departure from every other scene: deliberately does NOT paint the wash at all (would fight the look's own "dark 80%" last-beam intent), lights only the FIRST spot fixture (`rig.by_role("spot")[:1]`, "one spot" taken literally); "ceiling_bounce" is another disclosed named-position gap; tests: `tests/test_scenes.py::test_outro_single_beam_does_not_touch_wash_at_all`, `::test_outro_single_beam_lights_only_the_first_spot` |

**Verified against real capture data**: 0 crashes; BOTH `Outro Fade Wash`
and `Outro Single Beam` genuinely round-robin-selected during real OUTRO
windows and rendered correctly -- better real-data coverage than BREAK got.

## Phase 5 delta log, fifth wave (2026-09-12 -- bridge/utility, commit `15ad2e4`)

| Rule | Before | After | Evidence |
|---|---|---|---|
| `all_dark` (new look) | NOT-IMPLEMENTED (LOOK-07 was N/A for lack of this look) | PASS | `scenes/base.py`'s `AllDark`/`ALL_DARK` -- "reserved darkness/cut, any mode," deliberately NOT part of `ALL_SCENES`/rotation (same treatment as `SafeDefault`); no automatic trigger wired since the Bible gives none; test: `tests/test_scenes.py::test_all_dark_zeroes_every_intensity_channel_no_motion_no_laser` |
| `chase_wash_lr` (new look) | NOT-IMPLEMENTED | PARTIAL | `scenes/library.py`'s `ChaseWashLr` -- a genuine per-fixture wash INTENSITY chase (this rig's wash fixtures have no pan/tilt), a deliberate disclosed exception to "never set wash intensity" (same justification as `peak_color_pulse_clear`); filed under BUILD only (Bible tags `[BUILD,PEAK]`, `Scene.bucket` is single-valued); added to `DropBlackoutHit.conflicts`; tests: `tests/test_scenes.py::test_chase_wash_lr_alternates_left_and_right_out_of_phase`, `::test_chase_wash_lr_completes_one_cycle_every_two_bars` | `spot_position_change` deliberately NOT built -- the Bible's own catalog entry flags it as under-specified (no `requires{}`/`degrade`/`conflicts`/`color`/`dark%`/`min_hold` at all) and it needs the same named-position mechanism this codebase doesn't have; deferred like `build_snare_accent`, not fabricated.

**Verified against real capture data**: 0 crashes; `ChaseWashLr` wasn't
reached by round-robin in this capture, so it was additionally
direct-rendered against every row of the same capture on the real rig
config (`rigs/josh_rig.json`): 0 crashes, both wash fixtures' output
genuinely oscillates in opposite phase.

## Phase 5 delta log, sixth wave (2026-09-12 -- atmosphere-gated stubs, commit `e24fb47`)

All 6 looks whose `requires{}` names an `atm` threshold > 0 -- see
`spec/conformance.md`'s updated `LOOK-01`/`BEAM-01` rows for the full
mechanism explanation. This is the first wave where `requires{}`/
`min_atmosphere_density` are load-bearing on any real `Scene`.

| Rule | Before | After | Evidence |
|---|---|---|---|
| `build_beam_raise`/`drop_beam_fan`/`drop_laser_punctuation`/`peak_beam_sweep`/`peak_laser_tunnel`/`mirror_cross_beam` (6 new looks) | NOT-IMPLEMENTED | PASS (as always-degrading stubs -- genuinely correct per the Bible's own "always degrades on this rig" note) | `scenes/library.py` -- `BuildBeamRaise`->`BuildRiserWash`, `DropBeamFan`->`DropBlackoutHit`, `PeakBeamSweep`->`PeakFullRig` (single-hop degrade succeeds); `DropLaserPunctuation`->`DropBeamFan` and `PeakLaserTunnel`/`MirrorCrossBeam`->`PeakBeamSweep` (recursive-degrade cases -- the one-hop-only target is ALSO ineligible, so the scene is dropped entirely, not double-hopped); tests: `tests/test_scenes.py::test_all_six_atmosphere_gated_scenes_are_always_ineligible_on_this_rig` + 3 per-bucket "never surfaces directly" tests (30 picks each, exhaustive round-robin coverage) |

**Verified against real capture data**: 0 crashes across all 3779 ticks,
and NONE of the 6 new stub names ever appear in the actual scene-selection
trace -- real, end-to-end confirmation the degrade-walk intercepts every
one before real DMX output.

## Phase 5 delta log, seventh (final) wave (2026-09-12 -- remaining DROP looks, commit `21ab082`)

Closes Phase 5's entire look-building backlog.

| Rule | Before | After | Evidence |
|---|---|---|---|
| `drop_color_slam_bigroom` (new look) | NOT-IMPLEMENTED | PASS | `scenes/library.py`'s `DropColorSlamBigroom` -- wash and spot get genuinely different static hues (`SUNSET_WASH`/`SUNSET_SPOT`); bar-downbeat wash pulse reuses `peak_color_pulse_clear`'s mechanic; test: `tests/test_scenes.py::test_drop_color_slam_bigroom_splits_wash_and_spot_hues` |
| `drop_wash_slam_clear` (new look) | NOT-IMPLEMENTED | PASS | `scenes/library.py`'s `DropWashSlamClear` -- fully static `blood_red`; test: `tests/test_scenes.py::test_drop_wash_slam_clear_is_static_blood_red` |
| `drop_gobo_projection_clear` (new look) | NOT-IMPLEMENTED | PASS (as an always-ineligible, no-degrade stub -- correctly matches the Bible's own "no gobo capability... always degrades" note) | `scenes/library.py`'s `DropGoboProjectionClear` -- requires a `"gobo"` token that exists nowhere in `Rig.capabilities()`; NO `degrade_to` (unlike the atm-gated stubs) -- dropped from its bucket's eligible set outright; test: `tests/test_scenes.py::test_drop_gobo_projection_clear_is_always_ineligible_and_has_no_degrade_target` |
| `drop_blinder_clear` (new look) | NOT-IMPLEMENTED | PASS | `scenes/library.py`'s `DropBlinderClear` -- "wash or blinder" resolves to always-eligible (this rig has wash, no blinder fixture); genuinely reachable via round-robin, not a stub; test: `tests/test_scenes.py::test_drop_blinder_clear_is_eligible_and_reachable_via_round_robin` |

**Verified against real capture data**: 0 crashes; `Drop Wash Slam Clear`
genuinely selected multiple times as a pure round-robin pick during real
DROP windows. The other 3 weren't reached by round-robin in this capture
(`DropGoboProjectionClear` correctly never surfacing IS the desired
outcome) -- `DropColorSlamBigroom`/`DropBlinderClear` were additionally
direct-rendered against every row of the same capture on the real rig
config: 0 crashes for both.

## Phase 6 delta log (2026-09-12 -- Cutover: retire old scenes, audit sync)

| Rule | Before | After | Evidence |
|---|---|---|---|
| `LOOK-03` | FAIL (`FullSpectrumHit`/`BeamFanLaserTunnel` both audio/beat-reactive despite DROP's static intent) | PASS | Both scenes retired (commit `8e91245`) -- Phase 5's full Bible-aligned DROP family already covers the same territory with real restraint |
| `TIME-21` | FAIL (both scenes touched wash+spot+laser simultaneously) | PASS | Same retirement -- confirmed no remaining scene touches all three roles; `DropLaserPunctuation`/`PeakLaserTunnel` are laser-only by design |
| `MERGE-02`/`MERGE-03`/`MERGE-06`/`MERGE-19` | Still shown FAIL in `spec/conformance.md` (stale -- actually resolved Phase 4, `8a68bd5`) | PASS | `spec/conformance.md` rows reconciled to match this file's own Phase 4 delta log, which had been correct all along |
| `LOOK-01` | PARTIAL ("mechanism built, not yet exercised") | PASS | Genuinely exercised for the first time by the sixth wave's 6 real always-degrading scenes |
| `LOOK-06` | Still shown NOT-IMPLEMENTED in `spec/conformance.md` (stale -- actually resolved Phase 4, `8a68bd5`) | PASS | Reconciled, same as the MERGE rows above |
| `LOOK-09` | Still shown NOT-IMPLEMENTED in `spec/conformance.md` (stale -- actually resolved Phase 5 first wave, `b3964dc`, via `build_to_drop_bridge`) | PASS | Reconciled |
| `BEAM-01` | NOT-IMPLEMENTED | PASS | Genuinely exercised by the sixth wave's 6 atm-gated looks |
| `BEAM-02`/`BEAM-03`/`BEAM-04` | Blank (never actually evaluated by the original audit) | NOT-IMPLEMENTED / N/A, filled in honestly | No prism or gobo control mechanism exists on any real fixture in this codebase -- nothing to gate |
| `MOVE-06` | NOT-IMPLEMENTED ("every scene is continuous," now factually false) | PARTIAL | Several Phase 5 scenes are now static or snap-quantized; no distinct "position-change cue" TYPE exists yet, so not a full PASS |
| `MOVE-07` | FAIL | FAIL (mechanism unchanged), evidence refreshed | `ReactiveLayerEngine`'s own spot loop is untouched by Phase 5 -- still not bucket-gated -- but Scene-layer movement now genuinely differs by bucket; not upgraded since the rule's own named mechanism is still failing |

Also: `spec/conformance.md`'s and this file's own "Every FAIL, individually"
summary tables had drifted from the phase delta logs below them (some rows
resolved a full session or more ago were still listed as active) --
reconciled in the same pass. **Not attempted this session**: a full
line-by-line re-verification of all 170 `spec/conformance.md` rows --
out of scope for one Phase 6 pass; only rows directly tied to Phase 4/5/6
work were touched. README/architecture docs and the hardware smoke-test
checklist are tracked separately (see `[[livereact-project]]` memory).

## Phase 1 delta log (updated as Phase 1 code lands)

| Rule | Before | After | Evidence |
|---|---|---|---|
| `LOOK-08` | FAIL (hard instant blackout) | PARTIAL — target fixed | `scenes/base.py`'s `SafeDefault`/`SAFE_DEFAULT`; `merge/merge.py`'s `finalize(..., safe_default_frame=...)`; `core/show_engine.py`'s `bible_failsafe_enabled` flag (off by default — gig-safe); tests: `tests/test_scenes.py::test_safe_default_renders_static_neutral_wash_no_motion_no_laser`, `tests/test_merge.py::test_auto_blackout_renders_safe_default_when_a_frame_is_given` |
| `FAIL-04` | FAIL (hard instant blackout, no distinction from a genuine "all signals lost" state) | PARTIAL — target fixed, no fade timing yet, and note: this Phase 1 slice wires `auto_blackout` (the existing no-music detector) to the new target, not literally "all three signals lost" specifically — see `merge.py`'s `finalize()` docstring for the scoping note | same as above |
| `LOOK-01` (capability-gating mechanism) | NOT-IMPLEMENTED | PARTIAL — mechanism built (`Scene.requires`/`degrade_to`, `Fixture.capabilities()`, `Rig.capabilities()`, `SceneCatalog.pick(rig=...)`), not yet exercised by any real look declaring non-empty `requires` (that's Phase 5) | `fixtures/profiles.py` (`Fixture.capabilities()`, `MovingHead` override), `fixtures/rig.py` (`Rig.capabilities()`, `Rig.atm`), `scenes/base.py` (`Scene` schema v2 fields), `scenes/catalog.py` (`SceneCatalog._capability_filter`/`_eligible`/`_instance_of`); tests: `tests/test_fixtures.py` (4 new), `tests/test_rig.py` (2 new), `tests/test_scenes.py` (5 new) |

## Post-cutover delta log (2026-09-17 -- classifier + accent work after the live runs)

| Rule | Before | After | Evidence |
|---|---|---|---|
| `TIME-13` (DROP→BUILD) | PARTIAL -- DROP→BUILD hard-rejected | DEVIATES (D3) | `scenes/catalog.py` `LEGAL_TRANSITIONS[DROP]` now declares BUILD; `core/metronome.py` `_derive_bucket` gives it DROP→BREAK's two-bar `CUT_EXIT_CONFIRM_S`; `docs/bible_integration/SPEC_DEVIATIONS.md` D3; tests `tests/test_metronome.py::test_drop_falls_back_to_build_only_after_two_bars_of_build_range_energy`, `::test_a_drop_tail_with_gaps_between_hits_holds_the_drop` |
| `build_snare_accent` (§5 look 5: "accent flashes locked to detected snare subdivision") | PARTIAL -- level-ratio `RollRiseDetector` (2026-09-15), never fired live: run 5's roll was only ~2x the build's own hats | PARTIAL -- density path added, UNVERIFIED LIVE | `inputs/audio.py` `ONSET_*` / `_onset_density` (high-band spectral flux → onsets/s at block rate; the 10 Hz recorder can't see 16ths), `core/messages.py` `high_flux`/`high_onset_rate`, `core/show_state.py` `audio_high_onset_rate`, `core/snare_trigger.py` `RollRiseDetector` density path (`ROLL_MIN_RATE` 6/s, `ROLL_DENSITY_RATIO` 1.4 vs the build's own hat rate, OR'd with the level path), `recorder.py` `onset_rate`/`high_flux`/`roll_path`/`roll_rate_base`; tests `tests/test_audio.py::test_high_onset_rate_counts_synthetic_clicks`, `::test_white_noise_and_a_noise_riser_produce_no_onsets`, `tests/test_snare_trigger.py::test_a_16th_roll_by_onset_density_arms_over_8th_hats_at_a_flat_level`. Not "quantized to 1/8" -- the accent is still the strobe at `STROBE_MAX`/flash 255 while the roll holds. Thresholds are [CONVENTION]: measurement caps near 12 onsets/s (3-block refractory), so 32nds over 16th hats read ~1.4x; to be tuned from the first `--record` run that logs `onset_rate`. |
| Energy normalizer warm-up (§9.8 "first 40 s can only be BREAK", disclosed cost of `ENERGY_NORM_MIN_SAMPLES`) | 40 s blind at every launch | Seeded from the last real session | `config.py` `energy_norm_seed`/`energy_norm_record` (gain+device fingerprint, never from demo), `app.py` `_energy_norm_seed`/shutdown save, `Metronome(seed_range=)` blending by n/40, `--no-norm-seed`; tests `tests/test_metronome.py::test_a_seeded_normalizer_classifies_from_the_first_second`, `::test_the_seed_hands_over_to_the_live_window_without_a_jump`, `tests/test_config.py` seed tests |
| §9.6 / D1 predictive cue (mix-in builds invisible to loudness) | NOT-IMPLEMENTED -- C key only | PARTIAL -- `core/build_rule.py` `KickLevelBuildRule` (kick back at 30-65 % of the last drop's bar-mean low level for 4 bars while base is BREAK → the held BUILD cue, 24-bar hold, released if the kick leaves the band 4 bars without a drop); `core/metronome.py` `_derive_build_rule`, `cue_build` upgrades an auto cue instead of cancelling; `ShowSnapshot.build_cue_source`, recorder `build_cue_src`; console label. Scored with `replay_state.py --no-cue` on all 10 captures: 3 fires, all followed by a drop within 13 bars (run 3's mix-in build 12 bars early, run 4's and run 5's second builds), 0 false; unchanged under seeded normalizers. Cannot see a set's first build (no reference). Tests `tests/test_build_rule.py`. UNVERIFIED LIVE. |
