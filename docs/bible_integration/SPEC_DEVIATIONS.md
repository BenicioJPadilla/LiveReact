# Bible-integration spec deviations

**Status: living document.** Distinct from `spec/03-lighting-bible-corrections.md`
(that file records corrections found by the original evidence-verification
pass against the source PDFs — factual errors in the Bible's own text).
This file records places where the Bible's text is accurate and not in
dispute, but this specific hardware/software stack cannot implement it as
literally written — a deliberate, disclosed substitution, not a bug or a
someday-TODO. Each entry: what the Bible asks for, why it can't be built as
written, what LiveReact does instead, and what would change the answer.

---

## D1 — §9.6 predictive scheduling: no phrase-boundary data exists on this hardware

**What the Bible asks for.** §9.6's "predictive scheduling model": Pro DJ
Link supplies exact bar/beat/phrase position; when PDL indicates the current
phrase ends (a drop) at bar N, pre-arm the cue to fire ON that predicted
downbeat, with audio only used afterward as confirmation. The stated intent:
audio-only detection is structurally late (a drop is only classifiable after
it begins), so scheduling ahead of time is how the light is never behind.

**Why it can't be built as written.** Confirmed directly against this
project's own code and Pro DJ Link usage (not assumed): the data LiveReact
actually receives from the XDJ-XZ over Pro DJ Link is tempo, current
beat-phase, beat-in-bar, bar count (a locally-reconstructed counter, not the
track's real position — see `core/show_state.py`'s own docstring), transport
state, and which deck is on-air/master. There is no phrase-boundary field,
no song-section label, no "a drop happens at bar N" signal anywhere in what
this hardware transmits. §9.6's central mechanism has no data to schedule
against — this is a hardware/protocol limitation, not an unbuilt feature.

**What LiveReact does instead (Bible-integration Phase 3, approved by Josh
2026-09-12, "acceptable for now").** Beat-quantized reactive firing: once
the classifier confirms a drop (still purely reactive, off real audio, same
mechanism as before), the commitment is held for the fraction of a beat it
takes to land on the next real downbeat, rather than firing mid-bar wherever
the confirming tick happened to fall. This satisfies the achievable half of
§9.6's intent — cues land on a clean beat boundary, never mid-bar — without
fabricating a phrase-prediction signal that doesn't exist. It does NOT
provide genuine foresight: the light still only finds out about a drop the
same moment it always did.

**Partial mitigation, tracked separately, not yet built.** A plain heuristic
(not the prediction this section describes, and not machine learning) using
signals already computed — how long the classifier has dwelled in DROP/PEAK,
and the same-track `drop_cycle` count — as soft leading indicators that a
transition is statistically likely soon. Scoped into Phase 3 as a
`transition_likely` signal, verified via simulation before use.

**What would change this answer.** A different input source that actually
carries song-structure metadata (e.g. if a future DJ platform exposes phrase
or cue-point data over its own protocol), or a deliberately separate,
explicitly-scoped R&D effort to train a real online structure-recognition
model — discussed with Josh 2026-09-12 and intentionally NOT started: it's a
genuinely different, larger initiative (real-time-from-nothing music
structure segmentation is an open problem in general, not just for this
project), requiring either a labeled dataset or self-labeling off this
project's own imperfect classifier, a model cheap enough to run live, and
real validation against tracks it wasn't trained on. Revisit only if the
heuristic version above hits an evidenced ceiling worth that investment.

**Untracked gap, found 2026-09-13 (full Phase 1-6 re-audit)**: §9.7's
"Mis-prediction recovery" text ("build that doesn't resolve: hold the
pre-drop state for max 1 bar past prediction... resume `build_riser_wash`
at current intensity and re-predict"; "unexpected cut: audio RMS collapse
sustained ≥1 bar → fall to `break_low_wash` via a 1-bar crossfade") has
**no corresponding rule ID anywhere in `spec/conformance.md`'s 170-row
taxonomy**, and isn't built. Distinct from `FAIL-03` (audio signal *loss*,
a hardware/connection event) — this is about the track *staying connected
but suddenly going quiet or not dropping when expected*, a musical event,
not a signal fault. Given D1 above, this section's literal "re-predict"
framing doesn't apply either (there's no prediction to have gotten wrong)
— but the underlying behavioral intent (don't hang in a bad state when a
build overruns, gracefully recover from a real unexpected quiet passage)
is still a real, currently-unaddressed gap, independent of D1's own
predictive-scheduling substitution. Not scheduled into any phase; flagged
here rather than left invisible.

---

## D2 — §14 "manual = biases and caps, never an override": Synth Sync is an operator-chosen reactivity mode

**What the Bible asks for.** The console's manual controls are biases and
caps on a fully automated show (master brightness, strobe cap, color bias,
laser arm, blackout/freeze). The operator never picks *what reacts to
what*; the engine does, from the energy-state model.

**Why it's deviated from.** Josh (2026-09-15): in UK garage the prominent
sound is the synth/chord stab, not the kick, and the bucket model's
wash behavior (held level in a drop, ramp in a build) reads flat against
that music. He asked for a UI toggle that makes the par + wash bar "literally
mimic the synths." No automated classifier can tell "this is a stab-driven
track" from the audio LiveReact has (see D1: no song-structure data), so
the human who knows the track makes the call -- the same reasoning as the
planned DJ drop cue (`Metronome.request_manual_bucket`).

**What LiveReact does instead.** `ManualParams.synth_sync` (console
checkbox / `S` key, never persisted, off at every start). While on and real
audio is fresh: the wash dimmer follows a baseline-excess envelope on the
mid band (`engines/envelope.py`, `engines/reactive.py`'s `SYNTH_*`), and
every automated strobe is suppressed so two signals never fight one dimmer
channel. Par + wash bar only; the moving head, color, movement and laser
are untouched. Known limit: band amplitude can't separate instruments --
vocal chops and snare body share the mids.

**What would change the answer.** A stab/chord detector that could identify
the instrument (not just the band) could gate this automatically; nothing
like that exists here today.
