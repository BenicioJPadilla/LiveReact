"""Stage 2 of the staged spec/conformance.md audit (see spec/LIGHTING_BIBLE.md
§2 merge algebra, §12 failsafe ladder) — test vectors for confirmed gaps
between the corrected spec and the current merge/arbitration/failsafe code.

**These tests are INTENTIONALLY FAILING as of this commit.** They encode the
spec's expected behavior, not the code's current behavior, per the audit's
own rule: "write the failing test rather than describing the bug." Running
`pytest` right now will show these as red — that's the point, not a
regression. Each one cites the exact conformance.md rule ID it targets;
resolving that rule (a Stage 6 concern, not this one) should make the
corresponding test pass without editing the test itself. No engine code was
changed to produce this file.

A few of these directly contradict an EXISTING test elsewhere in this suite
that encodes the current (pre-correction) design intent as correct — noted
per-test below. Reconciling those two is also Stage 6's job, not this
file's.

Since 2026-10-16 the still-open gaps are marked ``xfail(strict=True)``: the
suite stays green while they're open, and the day one starts passing, strict
turns it into a failure so the marker has to come off in the same change.
"""

from __future__ import annotations

import pytest

from livereact.fixtures.rig import load_rig
from livereact.merge.merge import Contribution, ManualParams, finalize, merge_contributions


def _rig():
    return load_rig()


# --- MERGE-03 (LIGHTING_BIBLE.md §2.1): "Hue (working space): LTP by
# priority. Never average." -----------------------------------------------


def test_hue_merges_by_priority_not_by_per_channel_max():
    """CONTRADICTS `tests/test_merge.py::test_color_and_dimmer_merge_by_max`,
    which asserts the CURRENT max-merge behavior is correct -- that test
    only ever varies R and G independently in the SAME direction (0.2/0.8
    red-ish, 1.0/0.1 green-ish), so per-channel max happens to look sane
    there. This test uses two genuinely different, incompatible hues (pure
    red vs. pure blue) -- the case where per-channel max provably produces
    a THIRD color neither engine intended (magenta), instead of the
    higher-priority engine's actual hue winning.

    Priority order here matches ReactiveLayerEngine (lower) vs PhraseEngine
    (higher) per MERGE-18's stack -- phrase's blue should win outright."""
    rig = _rig()
    par = rig.fixture("par_l")
    reactive_c, phrase_c = Contribution(), Contribution()
    reactive_c.priority, phrase_c.priority = 25, 50  # LIGHTING_BIBLE.md §2.3's Titan tiers
    par.set_color(reactive_c, 1.0, 0.0, 0.0)  # reactive layer: pure red
    par.set_color(phrase_c, 0.0, 0.0, 1.0)    # phrase layer: pure blue, higher priority

    merged = merge_contributions([reactive_c, phrase_c], rig)

    # Spec: phrase's blue should win (LTP by priority). Actual: R and B both
    # max out (255, 0, 255) -- magenta, a color neither layer commanded.
    assert merged[par.offset + 1] == 0    # R should be phrase's 0, not reactive's 255
    assert merged[par.offset + 3] == 255  # B should be phrase's 255 (this half already passes)


# --- MERGE-06 / MERGE-12 / MERGE-13: color-wheel slot must be LTP+snap,
# never per-channel max -- confirmed live this week as the root cause of
# "still blue during the drop." -------------------------------------------


def test_color_wheel_slot_is_snap_by_priority_not_byte_max():
    """The moving head's color-wheel byte is tagged ChannelKind.COLOR (see
    fixtures/profiles.py MovingHead.channel_kinds()), so it inherits the
    same per-channel max() as RGB brightness instead of LTP+snap. Rigged so
    the LOWER-priority write has the numerically HIGHER wheel-slot byte
    (magenta=56) and the HIGHER-priority write has a LOWER one (red=8) --
    max() picks the wrong (lower-priority) slot specifically because slot
    numbers aren't ordered by write recency or priority, they're ordered by
    hue. A coincidental same-direction case would hide this exact failure
    mode, which is why the values are chosen this way rather than at
    random."""
    rig = _rig()
    mh = rig.fixture("mh_l")
    reactive_c, phrase_c = Contribution(), Contribution()
    reactive_c.priority, phrase_c.priority = 25, 50  # LIGHTING_BIBLE.md §2.3's Titan tiers
    mh.set_color(reactive_c, 1.0, 0.0, 1.0)  # magenta -> wheel slot 56 (lower priority)
    mh.set_color(phrase_c, 1.0, 0.0, 0.0)    # red -> wheel slot 8 (higher priority)

    merged = merge_contributions([reactive_c, phrase_c], rig)

    assert merged[mh.offset + 7] == 8  # phrase's red slot should win; actual is 56 (magenta)


# --- MERGE-05: "Pan / tilt: LTP base + additive signed offset, then
# slew-clamp." Not a bare last-write-wins replacement. ---------------------


@pytest.mark.xfail(strict=True, reason="MERGE-05 open: MOVEMENT merge is bare last-write-wins")
def test_reactive_layer_movement_is_not_wholly_discarded_by_phrase_movement():
    """Confirmed real consequence, not just a spec technicality:
    ReactiveLayerEngine sets moving-head position every tick
    (engines/reactive.py's spot loop), and so does every single scene in
    scenes/library.py's render() -- both target the SAME MOVEMENT-kind
    channel. merge_contributions' rule for MOVEMENT is bare last-write-wins
    (merge/merge.py: `touched_vals[-1]`), and PhraseEngine's contribution is
    always later in engine order than ReactiveLayerEngine's (app.py's
    `self.engines` list) -- so ReactiveLayerEngine's own MH sweep has NO
    effect on the real merged output whenever any scene also sets position,
    which is always. The spec's "base + additive offset" model would let
    both contribute; the current bare-replacement model lets only one."""
    rig = _rig()
    mh = rig.fixture("mh_l")
    reactive_c, phrase_c = Contribution(), Contribution()
    # Bible-integration Phase 4 (2026-09-12): priorities set explicitly to
    # match real runtime values (core/show_engine.py tags every
    # Contribution with its producing engine's own priority) -- WITHOUT
    # this, both default to 0 and the test passes for the wrong reason (a
    # tie-break accident picking whichever is listed first), which would
    # hide that MERGE-05's real fix (additive offsets) still isn't built.
    reactive_c.priority, phrase_c.priority = 25, 50
    mh.set_position(reactive_c, 0.1, 0.1)  # what ReactiveLayerEngine would compute
    mh.set_position(phrase_c, 0.9, 0.9)    # what a scene independently computes

    merged = merge_contributions([reactive_c, phrase_c], rig)

    # The merged result must not simply equal phrase's raw value outright --
    # that would mean reactive's contribution was discarded, not combined.
    assert merged[mh.offset + 0] != round(0.9 * 255)


# --- FAIL-04 / LOOK-08: total signal loss falls to `safe_default` (a
# 40%-lit neutral wash) via a 2-bar fade -- not an instant hard blackout. ---


@pytest.mark.xfail(strict=True, reason="FAIL-04 open: auto_blackout is a hard zero unless --bible-failsafe")
def test_auto_blackout_fades_to_safe_default_not_hard_zero():
    """CONTRADICTS `tests/test_merge.py::test_auto_blackout_zeros_the_frame_
    independently_of_manual`, which asserts today's instant all-zero output
    is correct. Per the corrected spec, `auto_blackout` should represent
    "no confirmed music" degrading to `safe_default` (LIGHTING_BIBLE.md §5,
    §12: "wash 40% neutral_wash, static... no motion, no laser, no fog"),
    not a literal blackout -- `all_dark`/`manual.blackout` is the spec's
    actual name for a true hard cut, and it's a SEPARATE, deliberate
    operator switch. Today `finalize()` treats both triggers identically
    (merge/merge.py:95-96, `return bytes(UNIVERSE_SIZE)` either way)."""
    rig = _rig()
    par = rig.fixture("par_l")
    c = Contribution()
    par.set_intensity(c, 1.0)
    par.set_color(c, 1.0, 1.0, 1.0)

    merged = merge_contributions([c], rig)
    blacked = finalize(merged, rig, ManualParams(), auto_blackout=True)

    # Spec's safe_default is a real, dim, colored wash -- not literal zero.
    assert any(blacked), "auto_blackout should degrade to a 40%-lit safe_default, not true black"
