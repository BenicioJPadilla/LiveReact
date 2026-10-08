# Phase 5/6 hardware smoke-test checklist

Everything in `spec/LIGHTING_BIBLE.md`'s look catalog (29 scenes now in
`ALL_SCENES`, spanning all 5 energy buckets) has been verified so far by ONE
method only: replaying `recordings/session-20260909-171454/state.jsonl`
through the real `Metronome`/`PhraseEngine`/merge pipeline in a script, plus
direct-rendering a handful of scenes against every row of that same capture
on the real rig config. **That is not the same as a real `--hardware
--record` session** — it proves the logic against one old recording's timing,
not against a real fixture, real PDL/MIDI, or a track this content has never
seen. This checklist is what to actually watch for the first time this
content runs live, on top of `TESTING.md`'s general "Test 4 — Full
end-to-end" procedure (read that first if you haven't run a session before).

```
python -m livereact --hardware --visualize --record --rig rigs/josh_rig.json
```

Play a real set covering as many of the 5 states as you can: a breakdown, a
build with a snare roll if the track has one, a drop, a sustained peak, and
an outro. Longer is better — several of the waves below were only reached by
round-robin's luck of timing in the mp3-replay verification, so a short
session may not exercise everything either.

## Per-bucket, what to actually look for

- **BREAK**: does `Break Low Wash` read as a genuine "the music has no
  transients to chase" moment (cold, calm, slow breathing), distinct from
  the older `Deep Wash Breathe`/`Slow Color Cycle`? Does `Break Ceiling
  Drift`'s tilt drift actually read as ceiling-bounce ambience, or does the
  ±15% amplitude look too big/small for the room? `Break Single Spot
  Special`'s "position dj_booth" is a **guessed** pan/tilt (`0.5, 0.70`) —
  does it actually point near the booth, or does it need a real number?
- **BUILD**: does `Chase Wash L/R` genuinely read as an alternating L/R
  chase, or does it look muddy/simultaneous (would suggest the two wash
  fixtures' `side` values or DMX addresses are swapped)? Does
  `Build Beam Raise` ever actually show — it shouldn't, it's atm-gated and
  should always degrade to `Build Riser Wash` (see "always-degrading looks"
  below).
- **DROP**: `Full Spectrum Hit`/`Beam Fan + Laser Tunnel` are GONE (retired
  Phase 6) — the drop should now be carried by `Drop Blackout Hit`, `Drop
  Strobe Stab`, `Drop Color Slam Bigroom`, `Drop Wash Slam Clear`, `Drop
  Blinder Clear`, and `Drop Laser Punctuation`. Does the drop still feel
  populated/exciting across a few different drops in one set, or does the
  rotation feel thinner without the old two? Does `Drop Color Slam
  Bigroom`'s wash/spot color split actually read as two distinct "sunset"
  hues, or does the moving head's nearest-color-wheel-slot approximation
  (`rgb_to_color_wheel`) land somewhere unexpectedly off?
- **PEAK**: does `Peak Beam Sweep`'s triangle-wave sweep ever show (it
  shouldn't — atm-gated, degrades to `Peak Full Rig`)? Does `Peak Full
  Rig`'s 4-bar fan and `Peak Color Pulse Clear`'s downbeat pulse both read
  as distinct from a plain drop, i.e. does PEAK actually feel like a real
  escalation past DROP?
- **OUTRO**: does `Outro Fade Wash`'s 40%→15% fade actually feel like a
  wind-down, and does `Outro Single Beam`'s "position ceiling_bounce"
  guess (`0.5, 0.85`, reusing the existing "tilted up" convention) look
  right, or does it need real aiming? Confirm it only lights ONE spot even
  though the packaged default rig has 2 — this rig only has 1, so this
  specific check needs the real `rigs/josh_rig.json`, not a synthetic test.

## Always-degrading looks — confirm they degrade cleanly, not glitch

`Build Beam Raise`, `Drop Beam Fan`, `Drop Laser Punctuation`, `Peak Beam
Sweep`, `Peak Laser Tunnel`, `Mirror Cross Beam`, and `Drop Gobo Projection
Clear` should **never** actually render on this rig (no haze hardware, no
gobo capability) — `SceneCatalog` should silently substitute their
`degrade_to` target (or drop them entirely for the gobo/laser-recursive
cases) every time round-robin lands on one. Watch for: a visible glitch/gap
right as the scene rotation hits one of these (would mean the degrade
substitution isn't as seamless live as the unit tests suggest), or — much
more concerning — any of these 7 names ever showing in the console's
current-scene display at all (would mean the capability gate itself isn't
being applied live the way it is in the replay/test harness).

## Safety items unrelated to Phase 5 content, but worth re-confirming while hardware's connected

- Laser stays forced off until armed (L); the beam-height gate that used
  to sit alongside the arm switch was removed on 2026-10-03 at Josh's
  request.
- The strobe Hz-safety gap (see `[[livereact-lighting-bible]]` memory) is
  still unresolved and still deprioritized per Josh's 2026-09-09 call —
  not something this checklist is asking you to fix, just don't mistake a
  quiet moment on that front for it having been resolved.

## After the session

Hand the recorded session folder back the same way `TESTING.md` describes.
Specifically useful for a Claude follow-up pass: re-run the same
full-pipeline replay method used for verification so far (see
`[[livereact-project]]` memory's "Verification pattern" note) against the
NEW real capture instead of the 2026-09-09 one, and compare which of the 23
new scenes get real airtime this time that didn't before.
