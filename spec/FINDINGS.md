# spec/FINDINGS.md — Consolidated failures, Stages 1–5

**Stage 6 progress (session 1 — critical safety, per the fix ordering:
strobe band, laser clamps, fog fail-closed):**
- `LASER-08/09/10/11` (and the `MANIFEST-01`/`SAFE-10/11` rows that
  cross-reference it): **beam-height half RESOLVED** — see the updated row
  below. FDA-variance half deliberately left as won't-fix (Josh's explicit
  call). `rigs/josh_rig.json` still needs Josh's real laser mount height
  before this is live on his actual hardware.
- `SAFE-01/02/03`: **partially mitigated, not resolved** — see the updated
  row. An interim conservative cap shipped; the real fix (measured Hz
  clamp) is still blocked on hardware calibration nobody has done yet.
- Fog fail-closed: nothing to fix (no fog subsystem exists).
Everything else below is unchanged from Stage 5 and still open.

Every row in `spec/conformance.md` with a confirmed defect in EXISTING code
(`FAIL`, or a `PARTIAL` whose gap is a real bug rather than an unmeasured
number), plus every `critical`-severity gap regardless of whether it's a
`FAIL` or a `NOT-IMPLEMENTED` absence — because by this audit's own
severity rule, a missing critical mechanism (a laser with no beam-height
clamp, a strobe with no Hz ceiling) is exactly as much a "failure" as a
wrong line of code.

**Deliberately excluded, to keep this list actionable rather than a
re-listing of the whole 170-row table**: the wholesale absence of entire
out-of-current-scope subsystems (the atmosphere/fog-haze system in full,
`CONSOLE`/`PROBE`'s rule set, most of the Oklab/OkLCH color-space adoption)
where the gap is "never built yet" rather than "built wrong" — those are
summarized as single line items at the end instead of one row each. No
code was changed producing this file. No patches included, per the stage
instruction — descriptions and one-sentence fix proposals only.

---

## CRITICAL

| Rule ID | File:line | Description | Proposed fix |
|---|---|---|---|
| `SAFE-01`/`02`/`03`/`05`/`06` | `engines/reactive.py:43-74` | **PARTIALLY MITIGATED, Stage 6, NOT resolved.** `STROBE_MAX` lowered `0.30→0.15` (byte ~76→~38) as a deliberately conservative interim placeholder, Josh's explicit choice — genuinely lower risk, but still not backed by any real Hz measurement, so the underlying rule remains open. `SAFETY_STROBE_*_HZ` named constants added as documented (unwired) targets for the real fix. | Still: measure the wash bar's real DMX-byte-to-Hz curve on hardware (photodiode/camera, per §11's own method), then add a Hz-aware clamp in `finalize()` that rejects/remaps any commanded byte whose measured frequency falls in 10-25 Hz or exceeds 4 Hz sustained — **this remains the single highest-priority open item in the whole audit.** |
| `SAFE-04` (partial) | `engines/reactive.py:56,74` | Burst duration/spacing are enforced in real time (good), but "never full-field above 4 Hz" can't be checked — no Hz concept, no full-field-vs-strobe-state cross-reference. | Once the Hz clamp above exists, add a check that refuses a strobe command whenever the wash bar's dimmer is also above some "full-field" brightness threshold. |
| `MERGE-03`/`MERGE-06` | `merge/merge.py:67-68`; `engines/phrase.py:148-149` | Hue and the moving head's color-wheel byte merge by flat per-channel `max()`, not LTP-by-priority/snap — two engines' different color intents combine into a third, unintended color. Confirmed as the live root cause of "still blue during the drop." | Give `ChannelKind.COLOR` a dedicated merge function that selects the highest-priority contributor's whole RGB triple atomically (not per-channel), and move the color-wheel byte specifically to snap-by-priority treatment like `LASER`. |
| `MERGE-05` | `merge/merge.py:69-70` | `ReactiveLayerEngine`'s own moving-head movement is entirely discarded every tick whenever any scene also sets position — which is always, since `PhraseEngine` is later in engine order and `MOVEMENT` merges by bare last-write-wins. That reactive-layer movement code has never had any real effect. | Change `MOVEMENT` merge from last-write-wins to `base(Phrase, LTP) + Σ offsets(Reactive)`, matching the spec's own §2.1 formula, so both layers actually combine. |
| `LOOK-08`/`FAIL-04` | `merge/merge.py:95-96` | `auto_blackout` is an instant, hard, all-zero cut — not the spec's 2-bar fade to a 40%-lit `safe_default`. No `safe_default` look exists anywhere. | Build a real `safe_default` scene (40% `neutral_wash`, static, no motion/laser/fog) and have `finalize()` crossfade the output toward it over ~2 bars when `auto_blackout` triggers, instead of returning `bytes(UNIVERSE_SIZE)` directly. |
| `LASER-08`/`09`/`10`/`11` | `fixtures/profiles.py:429-445`; `fixtures/rig.py:120-127` | **RESOLVED (beam-height half), Stage 6.** `mount_height_m`/`safe_projection.min_beam_height_m` are now real manifest fields; `Laser.apply_safety` fails closed on undeclared or unsafe geometry, tested (`tests/test_fixtures.py`, `tests/test_merge.py`). FDA-variance gate (`LASER-08`) deliberately NOT implemented — Josh's explicit call, solo-testing context. | ~~Add `mount_height_m`/`safe_projection`/`fda_variance_on_file` fields...~~ Done for geometry. **Remaining**: Josh needs to supply the laser's real mounted height for `rigs/josh_rig.json` — until then this fix correctly but inconveniently forces the laser off on his real hardware. |
| `LOOK-03` | `scenes/library.py` `FullSpectrumHit.render()`, `BeamFanLaserTunnel.render()` | Both real DROP-bucket scenes are audio/beat-reactive (a per-beat white punch; continuous hue), directly contradicting their own "the cut IS the effect, nothing reacts" design intent — and matching Josh's own live complaint, "beating to kicks felt random." | Remove `FullSpectrumHit`'s `beat_pulse`-driven white punch and freeze `BeamFanLaserTunnel`'s hue at scene entry, so both render fully static color/intensity for the held drop, per the Bible's own look definition. |
| `MOVE-03`/`LOOK-02` | `engines/reactive.py:353`; `scenes/library.py:84,150,172,194` | No mis-declared-rig detection exists — a fixture's `side` field set to anything but exactly `"left"` silently inverts, with zero warning, and a mirrored-fan look has no way to know its symmetry assumption is broken. | At rig-load time, validate that every fixture in a role expected to mirror has a `side` in `{"left","right"}` and that at least one of each exists before enabling any mirrored effect; log and disable mirroring (running unison instead) otherwise. |
| `FAIL-08` | `merge/merge.py:95-108` | The safety-clamp loop (`apply_safety`, `cap_strobe`, etc.) is skipped entirely during a blackout, because the early `return` on line 96 happens before it — contradicts "the safety layer always runs," even though the resulting all-zero output happens to be at least as safe. | Move the `blackout`/`auto_blackout` check to apply as a final clamp inside (or immediately after) the fixture loop, rather than an early return that bypasses it. |
| `TIME-13` | `scenes/catalog.py` `bucket_for_energy_with_hysteresis` | No legal-transition table exists; a large energy spike can commit BREAKDOWN directly to DROP in one step, skipping BUILD/HOLD, with nothing architecturally preventing it. | Add an explicit adjacency table so a committed bucket can only move one step toward the target per classification cycle, requiring successive commits (each still gated by dwell/hysteresis) to reach a non-adjacent state. |

## MAJOR

| Rule ID | File:line | Description | Proposed fix |
|---|---|---|---|
| `MERGE-02` | `merge/merge.py:55-71` | Same root cause as `MERGE-03` — no "within one look" vs "across looks" distinction exists for RGBW-as-intensity channels either. | Resolved by the same `MERGE-03` fix (a real per-look color-priority merge). |
| `MERGE-07`/`MERGE-08` | `fixtures/profiles.py` `MovingHead.channel_kinds()` (CH9-12 tagged `OTHER`) | Gobo/prism/focus/frost channels inherit max-merge instead of snap, latent since nothing currently writes them. | Give these channels their own snap-enforcing `ChannelKind` (or a generic `snap: true` manifest flag per `MERGE-12`) before any future scene starts using them. |
| `MERGE-19` | `engines/transition.py` | `TransitionEngine`'s "masking" only works today because its white lift commands the literal maximum byte (255) on every channel — there is no real seize/override mechanism. | Give `TransitionEngine` an explicit high-priority "assert" contribution type in the merge algebra that truly overrides LTP channels, not just wins by coincidence via `max()`. |
| `TIME-12` | `scenes/catalog.py` `HYSTERESIS_MARGIN=0.05`; `core/metronome.py` `BUCKET_MIN_DWELL_S=3.0` | Hysteresis and dwell are completely symmetric — entering and exiting any bucket use the identical margin and timer, contradicting the spec's explicit asymmetric design (fast/easy entry, slow/hard exit). | Split both into direction-aware pairs (e.g. `HYSTERESIS_MARGIN_UP`/`_DOWN`, `DWELL_ENTER_S`/`DWELL_EXIT_S`) with entry values lower/faster than exit values. |
| `TIME-20` | `scenes/catalog.py` `SceneCatalog.pick()` | Pure round-robin counter, no memory of which look was last used for a given phrase type. | Add `PhraseEngine._last_scene_by_bucket: dict[EnergyBucket, Scene]`, consulted before `catalog.pick()` and updated when `_next` is assigned (design detailed in `conformance.md`'s `TIME-20` row). |
| `TIME-21` | `scenes/library.py` `FullSpectrumHit.render()` | Uses wash, spot, AND laser simultaneously — the opposite of "don't use everything in every look." | Split into two alternating variants (e.g. wash+spot only vs. spot+laser only), selected via the `TIME-20` look-history rotation so neither always uses everything. |
| `TRANS-02` | `engines/phrase.py:148-149` | Crossfades blend raw DMX bytes via `max()` — no real intensity fade, no Oklab color interpolation. | Implement an actual time-parameterized lerp for intensity and a hue-aware color blend for the crossfade window, replacing the per-tick `max()`. |
| `FAIL-01` | `engines/phrase.py` `_maybe_rotate` | Never checks `snap.pdl_fresh` — keeps rotating scenes off the free-running bar count during PDL loss, contradicting "PhraseEngine holds the current look." | Add a `snap.pdl_fresh` check to `_maybe_rotate` that suspends new rotations (but not the current crossfade, if one's in progress) while PDL is stale. |
| `FAIL-03` | `engines/reactive.py` `tick()` | Keeps computing and writing a full contribution every tick regardless of `snap.audio_fresh`, using stale `energy_norm`. | Gate the bucket-driven wash/par/MH output on `snap.audio_fresh`, falling back to a neutral static contribution (or holding the frozen bucket) when audio is stale, matching priority-25's intended "audio decoration, disabled without audio" role. |
| `MOVE-07` | `engines/reactive.py`'s spot loop; `scenes/library.py` | Continuous MH movement runs unconditionally every tick, in every bucket — not reserved for DROP/sustained PEAK as the spec wants (and contradicts `TIME-06`'s "no fast motion during breakdown"). | Gate the sweep's amplitude by `snap.bucket` — near-zero during BREAKDOWN/BUILD, full during DROP/HOLD — instead of a constant amplitude always. |
| `MOVE-06` | `scenes/library.py` | No distinct snap-to-position cue exists separate from the always-on continuous sweep. | Add a `spot_position_change`-style cue triggered on phrase-boundary/section-change events, using a slow move or snap instead of the permanent sine sweep. |
| `MOVE-09` | `fixtures/profiles.py:253-258` (`MovingHead.boot_defaults`) | Boot defaults are hardcoded (128/80), ignoring the fixture's own configured `home_pan`/`home_tilt`; no half-slew startup ramp exists. | Have `boot_defaults` read the fixture's configured home position (falling back to the current constants only when unset) and ramp to it via `apply_slew_limit` on the first real tick rather than writing it directly. |
| `LASER-14` | `core/laser_trigger.py` `update()` | The DROP-only gate has no exception for a single build-climax reveal, as the spec explicitly names. | Add a one-shot manual or auto-detected flag that bypasses the DROP-only check exactly once per set for a designated climax moment, still subject to the existing spacing/duty caps. |
| `COLOR-13`/`COLOR-14` | `engines/reactive.py` `_maybe_update_hue`; `merge/merge.py:67-68` | The phrase-frozen hue this project already built is correctly computed but never wins the merge over a scene's simultaneously-written continuous hue — same root cause as `MERGE-03`. | Resolved by the same `MERGE-03` fix. |
| `COLOR-09`/`SAFE-20` | `engines/color.py` `two_axis_color` | No hue-cap mechanism exists at all — nothing counts or limits distinct live hues. | Count distinct hues across all fixture contributions per tick before merge, desaturating or reassigning beyond the cap of 3. |
| `LOOK-06` | `scenes/base.py`, `scenes/catalog.py` | No `conflicts[...]` field or check exists on `Scene`. | Add a `conflicts: tuple[str, ...]` field to `Scene` and check it in `PhraseEngine._begin_rotation`/`SceneCatalog.pick()` before committing a rotation. |
| `TRANS-10` | `merge/merge.py` `ManualParams` | No musical RESET cue exists, distinct from the hard failsafe blackout. | Add a `ManualParams.reset: bool` flag that suppresses `ReactiveLayerEngine`/`PhraseEngine`'s normal output in favor of the (also-to-be-built) `safe_default` look, auto-clearing at the next phrase boundary (design detailed in `conformance.md`'s `TRANS-10` row). |
| `LATENCY-01` | `fixtures/rig.py:96-125` | No `latency_ms` field exists in the manifest; reactive cues are never phase-advanced to compensate for fixture response time. | Add a `latency_ms` field to the fixture manifest schema (measured per fixture class via a real photodiode/DMX-step test) and phase-advance bucket/scene-transition cues by that amount per fixture. |

## MINOR

| Rule ID | File:line | Description | Proposed fix |
|---|---|---|---|
| `TIME-07` | `scenes/base.py` `EnergyBucket` | No distinct OUTRO state exists — an actual outro just classifies as BREAKDOWN with no deliberate warm-color bias. | Add a lightweight "outro" heuristic (e.g. a time-since-last-DROP threshold) that biases BREAKDOWN's hue selection toward the warm end when active, without a full 5th bucket state. |

---

## Summarized, not itemized (out-of-current-scope subsystems)

- **The entire atmosphere/fog-haze system** (`ATMO-01` through `ATMO-19`, `ATMO-21`, plus `BEAM-01`, `LASER-05`/`06`, `MOVE-11`): zero code exists for either a fogger or hazer model. Consistent with the real rig having no atmosphere fixtures at all — building this is a scope decision for whenever hardware is added, not a bug to patch.
- **The negative-space/`dark_fixtures_pct` mechanism** (`MERGE-21`/`22`, `SAFE-23`, and the `dark_fixtures_pct` rows of the config table): entirely unbuilt. Meaningful to add once the rig has enough same-role fixtures for a fractional dark-selection to matter (currently only 2 wash-role fixtures).
- **Oklab/OkLCH color-space adoption** (`COLOR-01`/`02`/`03`): a deliberate architectural choice not yet made, not a defect in the current plain-HSV pipeline — worth doing alongside the `MERGE-03` color-merge fix if that work is undertaken, since both touch the same code path.
- **The full manifest/`x_norm` schema, capability-tier taxonomy, and console-paradigm named-priority-tiers** (`MANIFEST-01`/`02`/`03`, `CONSOLE-01`-`05`): LiveReact's simpler `role`+`side`+engine-list-order model achieves most of the same practical outcomes for the current 4-fixture rig; revisit if the rig grows past 2 fixtures per mirrored role.
- **`SAFE-05`/`07` (strict-mode strobe cap, arm-time photosensitivity warning)**: both genuinely NOT-IMPLEMENTED and both cheap to add once `SAFE-01`/`02`'s Hz clamp exists — bundle with that work rather than doing separately.
