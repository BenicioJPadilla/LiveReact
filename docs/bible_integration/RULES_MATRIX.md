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

## Phase 1 delta log (updated as Phase 1 code lands)

| Rule | Before | After | Evidence |
|---|---|---|---|
| `LOOK-08` | FAIL (hard instant blackout) | PARTIAL — target fixed | `scenes/base.py`'s `SafeDefault`/`SAFE_DEFAULT`; `merge/merge.py`'s `finalize(..., safe_default_frame=...)`; `core/show_engine.py`'s `bible_failsafe_enabled` flag (off by default — gig-safe); tests: `tests/test_scenes.py::test_safe_default_renders_static_neutral_wash_no_motion_no_laser`, `tests/test_merge.py::test_auto_blackout_renders_safe_default_when_a_frame_is_given` |
| `FAIL-04` | FAIL (hard instant blackout, no distinction from a genuine "all signals lost" state) | PARTIAL — target fixed, no fade timing yet, and note: this Phase 1 slice wires `auto_blackout` (the existing no-music detector) to the new target, not literally "all three signals lost" specifically — see `merge.py`'s `finalize()` docstring for the scoping note | same as above |
| `LOOK-01` (capability-gating mechanism) | NOT-IMPLEMENTED | PARTIAL — mechanism built (`Scene.requires`/`degrade_to`, `Fixture.capabilities()`, `Rig.capabilities()`, `SceneCatalog.pick(rig=...)`), not yet exercised by any real look declaring non-empty `requires` (that's Phase 5) | `fixtures/profiles.py` (`Fixture.capabilities()`, `MovingHead` override), `fixtures/rig.py` (`Rig.capabilities()`, `Rig.atm`), `scenes/base.py` (`Scene` schema v2 fields), `scenes/catalog.py` (`SceneCatalog._capability_filter`/`_eligible`/`_instance_of`); tests: `tests/test_fixtures.py` (4 new), `tests/test_rig.py` (2 new), `tests/test_scenes.py` (5 new) |
