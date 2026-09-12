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
| MANIFEST | 6 | Phase 1 (rig capability taxonomy) | |
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

| Rule | Assertion | Resolving phase |
|---|---|---|
| `MERGE-02` | RGBW-as-intensity merges HTP within a look, LTP-by-priority across looks | Phase 4 |
| `MERGE-03` | Hue merges LTP-by-priority, never averaged | Phase 4 |
| `MERGE-05` | Pan/tilt merges as `base(LTP) + Σ offsets`, slew-clamped | Phase 4 |
| `MERGE-06` | Color-wheel slot merges LTP+snap | Phase 4 |
| `MERGE-07` | Gobo index merges LTP+snap (latent) | Phase 4 |
| `MERGE-08` | Prism-engage merges LTP+snap (latent) | Phase 4 |
| `MERGE-19` | TransitionEngine masks Phrase writes at priority 100 | Phase 4 |
| `LOOK-02` | Mirrored-fan requires inverted opposite-side geometry | Phase 5 |
| `LOOK-03` | DROP look with `kick_follow:false` renders fully static | Phase 5 |
| `LOOK-08` | `safe_default` = static 40% neutral wash, no motion/laser/fog | **Phase 1 — target fixed, fade-timing still open** |
| `MOVE-03` | Mis-declared mirror geometry disables mirroring, warns | Phase 5 |
| `MOVE-07` | Continuous motion reserved for DROP/sustained PEAK | Phase 5 |
| `MOVE-09` | Movers home at half-slew on arm | Phase 5 |
| `TIME-12` | Asymmetric hysteresis (±15%, fast entry/slow exit) | Phase 2 |
| `TIME-21` | Restraint — don't use every fixture/role/effect at once | Phase 6 |
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
| `TIME-13` | NOT-IMPLEMENTED (no legality concept, a bucket could jump BREAK->DROP directly) | PARTIAL — one real illegal case enforced | `core/metronome.py`'s `_derive_bucket`: the one pairing that actually matters given the 3-value base classifier (DROP falling straight back to BUILD) is explicitly rejected; BREAK->DROP "cut-in" is correctly still legal per the Bible's own matrix (not a bug); full `LEGAL_TRANSITIONS` table lives in `scenes/catalog.py` for reference even though only the DROP->BUILD case is reachable in practice at the base-classifier level; tests: `tests/test_metronome.py::test_legal_transition_matrix_rejects_drop_falling_back_to_build` |
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

## Phase 1 delta log (updated as Phase 1 code lands)

| Rule | Before | After | Evidence |
|---|---|---|---|
| `LOOK-08` | FAIL (hard instant blackout) | PARTIAL — target fixed | `scenes/base.py`'s `SafeDefault`/`SAFE_DEFAULT`; `merge/merge.py`'s `finalize(..., safe_default_frame=...)`; `core/show_engine.py`'s `bible_failsafe_enabled` flag (off by default — gig-safe); tests: `tests/test_scenes.py::test_safe_default_renders_static_neutral_wash_no_motion_no_laser`, `tests/test_merge.py::test_auto_blackout_renders_safe_default_when_a_frame_is_given` |
| `FAIL-04` | FAIL (hard instant blackout, no distinction from a genuine "all signals lost" state) | PARTIAL — target fixed, no fade timing yet, and note: this Phase 1 slice wires `auto_blackout` (the existing no-music detector) to the new target, not literally "all three signals lost" specifically — see `merge.py`'s `finalize()` docstring for the scoping note | same as above |
| `LOOK-01` (capability-gating mechanism) | NOT-IMPLEMENTED | PARTIAL — mechanism built (`Scene.requires`/`degrade_to`, `Fixture.capabilities()`, `Rig.capabilities()`, `SceneCatalog.pick(rig=...)`), not yet exercised by any real look declaring non-empty `requires` (that's Phase 5) | `fixtures/profiles.py` (`Fixture.capabilities()`, `MovingHead` override), `fixtures/rig.py` (`Rig.capabilities()`, `Rig.atm`), `scenes/base.py` (`Scene` schema v2 fields), `scenes/catalog.py` (`SceneCatalog._capability_filter`/`_eligible`/`_instance_of`); tests: `tests/test_fixtures.py` (4 new), `tests/test_rig.py` (2 new), `tests/test_scenes.py` (5 new) |
