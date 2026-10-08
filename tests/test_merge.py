"""Tests for the merge + finalize layer — these encode the Phase 2 acceptance
criteria (docs/12 Phase 2)."""

from __future__ import annotations

from livereact.fixtures.profiles import Laser
from livereact.fixtures.rig import load_rig
from livereact.merge.merge import (
    Contribution,
    ManualParams,
    finalize,
    merge_contributions,
    render_universe,
)


def _rig():
    return load_rig()


def test_dimmer_merges_by_max_htp():
    """Bible-integration Phase 4: DIMMER stays genuinely HTP (max across
    every contribution) -- true additive-brightness semantics, unaffected
    by the priority-tiered change to COLOR/MOVEMENT/LASER/OTHER below.
    Priorities set backwards on purpose (lower priority gets the brighter
    value) to prove this is real max-across-all, not accidentally still
    picking a priority winner."""
    from livereact.fixtures.profiles import _intensity_to8
    rig = _rig()
    bar = rig.fixture("bar_l")
    dim, bright = Contribution(), Contribution()
    dim.priority, bright.priority = 50, 25  # the BRIGHTER one has LOWER priority
    bar.set_intensity(dim, 0.2)
    bar.set_intensity(bright, 0.8)
    merged = merge_contributions([dim, bright], rig)
    assert merged[bar.offset] == _intensity_to8(0.8)  # the brighter value wins regardless of priority


def test_color_merges_ltp_by_priority_not_per_channel_max():
    """Bible-integration Phase 4 (MERGE-02/03, closes the "still blue during
    the drop" root cause): COLOR is no longer a per-channel max -- the
    highest-priority contributor's whole color wins outright. Old behavior
    (max red, max green independently) is exactly the bug that could
    produce a third, unintended color neither engine commanded."""
    rig = _rig()
    par = rig.fixture("par_l")
    low, high = Contribution(), Contribution()
    low.priority, high.priority = 25, 50
    par.set_color(low, 0.2, 1.0, 0.0)   # R=51,  G=255
    par.set_color(high, 0.8, 0.1, 0.0)  # R=204, G=25 -- higher priority
    merged = merge_contributions([low, high], rig)
    assert merged[par.offset + 1] == 204  # high's red, not max(51,204)
    assert merged[par.offset + 2] == 26   # high's green (_to8(0.1)=26), not max(255,26) -- the old bug's exact case


def test_movement_is_ltp_by_priority():
    """Bible-integration Phase 4: MOVEMENT is LTP by explicit priority now,
    not a bare accident of the caller's list order -- same practical
    winner in this case (the higher-priority write), but for a principled
    reason, verified by putting the higher priority on the FIRST-listed
    contribution (which last-write-wins would have gotten wrong)."""
    rig = _rig()
    mh = rig.fixture("mh_l")
    low, high = Contribution(), Contribution()
    low.priority, high.priority = 25, 50
    mh.set_position(high, 1.0, 1.0)  # higher priority, but listed FIRST
    mh.set_position(low, 0.0, 0.0)   # lower priority, listed last -- old last-write-wins would pick this
    merged = merge_contributions([high, low], rig)
    assert merged[mh.offset + 0] == 255  # high's pan wins despite being listed first
    assert merged[mh.offset + 2] == 255  # high's tilt wins despite being listed first


def test_finalize_slew_limits_moving_head_position_between_frames():
    """LIGHTING_BIBLE.md §6.6: finalize() threads dt through to each fixture's
    apply_slew_limit, so a large position jump between two finalize() calls on
    the same rig (e.g. a scene switch) gets ramped, not slammed instantly."""
    rig = _rig()
    mh = rig.fixture("mh_l")
    manual = ManualParams()

    c1 = Contribution()
    mh.set_position(c1, 0.0, 0.0)
    finalize(merge_contributions([c1], rig), rig, manual, dt=0.025)  # establishes prev=0

    c2 = Contribution()
    mh.set_position(c2, 1.0, 1.0)  # an instant full-range jump
    out = finalize(merge_contributions([c2], rig), rig, manual, dt=0.025)
    assert 0 < out[mh.offset + 0] < 255  # ramping toward the target, not slammed


def test_untouched_channels_keep_boot_defaults():
    rig = _rig()
    merged = merge_contributions([Contribution()], rig)  # empty contribution
    assert merged[0] == 128  # MH Left pan stays centered (boot default)


def test_blackout_zeros_everything():
    rig = _rig()
    par = rig.fixture("par_l")
    c = Contribution()
    par.set_color(c, 1.0, 1.0, 1.0)
    out = render_universe([c], rig, ManualParams(blackout=True))
    assert out == bytes(512)


def test_master_brightness_scales_dimmers():
    rig = _rig()
    bar = rig.fixture("bar_l")
    c = Contribution()
    bar.set_intensity(c, 1.0)  # ch1 dimmer = 255
    full = render_universe([c], rig, ManualParams(master_brightness=1.0))
    half = render_universe([c], rig, ManualParams(master_brightness=0.5))
    assert full[bar.offset] == 255
    assert half[bar.offset] == 127  # scaled


def test_lasers_cannot_be_nonzero_unless_enabled():
    """Isolates the arm gate specifically — laser_on=True so the
    docs/14 §3 onset gate (tested separately above) doesn't also zero it."""
    rig = _rig()
    laser = rig.fixture("laser_l")
    c = Contribution()
    laser.set_dotted_line_sweep(c, color=Laser.COLOR_WHITE, sweep_intensity=0.5)

    off = render_universe([c], rig, ManualParams(laser_enable=False), laser_on=True)
    assert all(off[laser.offset + i] == 0 for i in range(12))  # fail-safe

    on = render_universe([c], rig, ManualParams(laser_enable=True), laser_on=True)
    assert on[laser.offset] == Laser.MANUAL_PATTERN_MODE  # CH1 enabled



def test_strobe_capped_on_finalize():
    rig = _rig()
    bar = rig.fixture("bar_l")
    c = Contribution()
    bar.set_strobe(c, 1.0)  # ch2 strobe full
    out = render_universe([c], rig, ManualParams(strobe_cap=0.2))
    assert out[bar.offset + 1] == 51  # ~0.2 * 255


def test_auto_blackout_zeros_the_frame_independently_of_manual():
    """docs/14 §2: auto_blackout and manual.blackout are independent triggers
    — the operator's switch must not need to be flipped for the automatic
    one to work, and vice versa."""
    rig = _rig()
    mh = rig.fixture("mh_l")
    c = Contribution()
    mh.set_intensity(c, 1.0)
    lit = render_universe([c], rig, ManualParams())
    assert any(lit)

    merged = merge_contributions([c], rig)
    blacked = finalize(merged, rig, ManualParams(), auto_blackout=True)
    assert blacked == bytes(len(blacked))


def test_auto_blackout_renders_safe_default_when_a_frame_is_given():
    """LOOK-08/FAIL-04 (Bible-integration Phase 1): auto_blackout's real
    failsafe target is a static 40% neutral wash, not total darkness --
    opt-in via safe_default_frame so this doesn't change behavior for any
    caller that doesn't pass one (see the test above, still unaffected)."""
    from livereact.scenes.base import SAFE_DEFAULT
    from livereact.core.show_state import ShowSnapshot

    rig = _rig()
    mh = rig.fixture("mh_l")
    c = Contribution()
    mh.set_intensity(c, 1.0)
    merged = merge_contributions([c], rig)

    safe_frame = render_universe([SAFE_DEFAULT.render(rig, ShowSnapshot(), 1.0)], rig, ManualParams())
    out = finalize(merged, rig, ManualParams(), auto_blackout=True, safe_default_frame=safe_frame)
    assert out == safe_frame
    assert any(out)  # NOT a hard zero -- the whole point of this fix


def test_drop_pending_forces_a_hard_cut():
    """Bible-integration Phase 5, build_to_drop_bridge/blackout_beat: "holds
    dark on the final bar, releases to the DROP look on the downbeat" -- a
    genuine hard cut, distinct from safe_default's dim wash."""
    rig = _rig()
    mh = rig.fixture("mh_l")
    c = Contribution()
    mh.set_intensity(c, 1.0)
    merged = merge_contributions([c], rig)
    out = finalize(merged, rig, ManualParams(), drop_pending=True)
    assert out == bytes(len(out))


def test_manual_blackout_wins_over_drop_pending():
    rig = _rig()
    mh = rig.fixture("mh_l")
    c = Contribution()
    mh.set_intensity(c, 1.0)
    merged = merge_contributions([c], rig)
    out = finalize(merged, rig, ManualParams(blackout=True), drop_pending=True)
    assert out == bytes(len(out))  # both agree on hard-zero here, just confirming no crash/precedence issue


def test_manual_blackout_still_wins_instantly_even_with_a_safe_default_frame():
    """The operator's own hard kill switch is deliberately unchanged by this
    fix -- it's a different concern from the automatic no-music failsafe."""
    from livereact.scenes.base import SAFE_DEFAULT
    from livereact.core.show_state import ShowSnapshot

    rig = _rig()
    mh = rig.fixture("mh_l")
    c = Contribution()
    mh.set_intensity(c, 1.0)
    merged = merge_contributions([c], rig)

    safe_frame = render_universe([SAFE_DEFAULT.render(rig, ShowSnapshot(), 1.0)], rig, ManualParams())
    out = finalize(merged, rig, ManualParams(blackout=True), auto_blackout=False,
                   safe_default_frame=safe_frame)
    assert out == bytes(len(out))  # manual.blackout ignores safe_default_frame entirely


def test_finalize_bounds_movement_around_a_calibrated_home_position():
    """docs/14 §4, end-to-end through finalize(): a scene's raw wide sweep
    gets remapped around the fixture's calibrated home once set."""
    rig = _rig()
    mh = rig.fixture("mh_l")
    mh.home_pan, mh.home_tilt = 0.7, 0.3
    c = Contribution()
    mh.set_position(c, 1.0, 0.0)  # a scene sweeping to its raw extreme
    out = render_universe([c], rig, ManualParams())
    assert out[mh.offset + 0] == round((0.7 + 0.5 * 0.20) * 255)  # bounded near home, not raw 255
    assert out[mh.offset + 2] == round((0.3 - 0.5 * 0.20) * 255)


def test_laser_flash_gate_zeros_the_laser_independently_of_scene_and_arm():
    """docs/14 §3: even armed + an eligible scene set a pattern, the laser
    stays off through finalize() unless a real onset flash is active."""
    rig = _rig()
    laser = rig.fixture("laser_l")
    c = Contribution()
    laser.set_dotted_line_sweep(c, color=Laser.COLOR_WHITE, sweep_intensity=0.5)
    armed = ManualParams(laser_enable=True)

    not_flashing = render_universe([c], rig, armed, laser_on=False)
    assert not_flashing[laser.offset] == 0                            # CH1 = 0: the unit's OFF band
    assert not_flashing[laser.offset + 1] == Laser.PATTERN_A1_DOTTED_LINE  # pattern stays primed (2026-09-16)

    flashing = render_universe([c], rig, armed, laser_on=True)
    assert flashing[laser.offset] != 0


def test_one_engine_movement_does_not_clobber_another_engines_color():
    rig = _rig()
    mh = rig.fixture("mh_l")
    color_engine, move_engine = Contribution(), Contribution()
    mh.set_color(color_engine, 1.0, 0.0, 0.0)  # sets color wheel only
    mh.set_position(move_engine, 1.0, 1.0)     # sets movement only
    merged = merge_contributions([color_engine, move_engine], rig)
    assert merged[mh.offset + 7] != 0   # color wheel preserved
    assert merged[mh.offset + 0] == 255  # movement applied


# --- absolute aims + calibration pins (2026-09-18 venue aiming) ----------------

def test_absolute_aim_skips_the_home_remap_but_ordinary_motion_still_remaps():
    from livereact.merge.merge import merge_contributions_ex
    rig = _rig()
    mh_l, mh_r = rig.fixture("mh_l"), rig.fixture("mh_r")
    for mh in (mh_l, mh_r):
        mh.home_pan, mh.home_tilt = 0.7, 0.3
    c = Contribution()
    mh_l.set_aim(c, 1.0, 0.0)        # a computed aim: final
    mh_r.set_position(c, 1.0, 0.0)   # a scene's raw sweep: remapped
    merged, absolute = merge_contributions_ex([c], rig)
    assert mh_l.offset in absolute and mh_r.offset not in absolute
    out = finalize(merged, rig, ManualParams(), absolute_movement=absolute)
    assert out[mh_l.offset + 0] == 255 and out[mh_l.offset + 2] == 0
    assert out[mh_r.offset + 0] == round((0.7 + 0.5 * 0.20) * 255)
    assert out[mh_r.offset + 2] == round((0.3 - 0.5 * 0.20) * 255)


def test_finalize_default_ignores_absolute_marks_so_old_callers_are_unchanged():
    rig = _rig()
    mh = rig.fixture("mh_l")
    mh.home_pan, mh.home_tilt = 0.7, 0.3
    c = Contribution()
    mh.set_aim(c, 1.0, 0.0)
    out = render_universe([c], rig, ManualParams())  # no absolute set passed
    assert out[mh.offset + 0] == round((0.7 + 0.5 * 0.20) * 255)


def test_absolute_mark_only_counts_when_that_contribution_wins():
    from livereact.merge.merge import merge_contributions_ex
    rig = _rig()
    mh = rig.fixture("mh_l")
    low, high = Contribution(), Contribution()
    low.priority, high.priority = 25, 50
    mh.set_aim(low, 1.0, 1.0)         # absolute, but outranked
    mh.set_position(high, 0.0, 0.0)   # ordinary, wins
    _, absolute = merge_contributions_ex([low, high], rig)
    assert mh.offset not in absolute
