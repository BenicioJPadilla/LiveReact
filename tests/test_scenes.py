"""Tests for the scene catalog: rendering, distinctness, laser gating, buckets."""

from __future__ import annotations

from livereact.core.show_state import ShowSnapshot
from livereact.fixtures.rig import _rig_from_dict, load_rig
from livereact.scenes.base import SAFE_DEFAULT, EnergyBucket, Scene
from livereact.scenes.catalog import SceneCatalog, bucket_for_energy
from livereact.scenes.library import ALL_SCENES, BeamFanLaserTunnel, Converge, DeepWashBreathe


def _snap(**kw) -> ShowSnapshot:
    base = dict(bpm=124.0, energy=0.7, fader_a=1.0, eq_low_a=1.0, eq_mid_a=0.4, eq_high_a=0.4)
    base.update(kw)
    return ShowSnapshot(**base)


def test_eighteen_scenes_across_all_buckets():
    """Bible-integration Phase 2: OUTRO is still a genuinely new state (see
    EnergyBucket's own docstring) with no scene yet -- an expected, interim
    gap, not a bug; a later Phase 5 wave builds looks for it. 18 = the
    original 8 + Phase 5's first wave (DropBlackoutHit, DropStrobeStab,
    BuildRiserWash) + second wave (PeakFullRig, PeakColorPulseClear,
    PeakAltHitsClear) + third wave (BreakLowWash, BreakSingleSpotSpecial,
    BreakCeilingDrift, BreakColorHoldClear)."""
    cat = SceneCatalog()
    assert len(ALL_SCENES) == 18
    for bucket in (EnergyBucket.BREAK, EnergyBucket.BUILD, EnergyBucket.DROP, EnergyBucket.PEAK):
        assert cat.bucket(bucket), f"{bucket} has no scenes"
    assert not cat.bucket(EnergyBucket.OUTRO), "OUTRO unexpectedly has a scene already -- update this test"


def test_every_scene_renders_some_output():
    rig = load_rig()
    snap = _snap()
    for cls in ALL_SCENES:
        c = cls().render(rig, snap, 1.0)
        assert any(c.touched), f"{cls.__name__} rendered nothing"


def test_only_drop_scenes_touch_laser_channels():
    """One-directional: a non-DROP scene must NEVER touch laser channels.
    The reverse isn't required -- Bible-integration Phase 5 added DROP
    scenes (DropBlackoutHit, DropStrobeStab) that deliberately don't use
    lasers at all (restraint, TIME-21 -- not every DROP look needs every
    fixture)."""
    rig = load_rig()
    snap = _snap(energy=1.0)
    laser = rig.fixture("laser_l")
    for cls in ALL_SCENES:
        scene = cls()
        c = scene.render(rig, snap, 1.0)
        touched_laser = any(c.touched[laser.offset + i] for i in range(12))
        if touched_laser:
            assert scene.bucket == EnergyBucket.DROP, cls.__name__


def test_scenes_are_visually_distinct():
    rig = load_rig()
    snap = _snap()
    a = DeepWashBreathe().render(rig, snap, 1.0).values
    b = BeamFanLaserTunnel().render(rig, snap, 1.0).values
    assert a != b


def test_bucket_thresholds():
    """Bible-integration Phase 2: BUILD_MAX moved 0.55 -> 0.80 (HOLD's old
    range folded into BUILD's upper tail); PEAK/OUTRO aren't reachable from
    a raw level at all (see EnergyBucket's docstring), so this stateless
    function only ever returns BREAK/BUILD/DROP."""
    assert bucket_for_energy(0.1) == EnergyBucket.BREAK
    assert bucket_for_energy(0.45) == EnergyBucket.BUILD
    assert bucket_for_energy(0.7) == EnergyBucket.BUILD
    assert bucket_for_energy(0.95) == EnergyBucket.DROP


def test_round_robin_avoids_repeating_current():
    cat = SceneCatalog()
    first = cat.pick(EnergyBucket.DROP)
    second = cat.pick(EnergyBucket.DROP, exclude=first)
    assert second is not first


def test_pick_without_a_rig_skips_capability_gating_entirely():
    """Backward compatibility: existing callers that don't pass `rig` (the
    default, None) get byte-identical behavior to before this parameter
    existed -- confirmed by exercising a scene with an impossible
    `requires` that would fail any real gate check."""
    class _Impossible(Scene):
        name, bucket = "Impossible", EnergyBucket.DROP
        requires = frozenset({"a_capability_no_rig_has"})
    cat = SceneCatalog([_Impossible()])
    assert isinstance(cat.pick(EnergyBucket.DROP), _Impossible)  # no rig -> gate never runs


def test_pick_with_a_rig_filters_out_ineligible_scenes():
    class _NeedsHaze(Scene):
        name, bucket = "Needs Haze", EnergyBucket.DROP
        requires = frozenset({"laser"})
        min_atmosphere_density = 0.6
    class _Plain(Scene):
        name, bucket = "Plain", EnergyBucket.DROP
    rig = load_rig()  # has lasers, but atm is always 0.0 -- no haze hardware
    cat = SceneCatalog([_NeedsHaze(), _Plain()])
    for _ in range(5):  # round-robin would otherwise eventually return _NeedsHaze
        assert isinstance(cat.pick(EnergyBucket.DROP, rig), _Plain)


def test_pick_walks_one_degrade_hop_when_ineligible():
    class _Fallback(Scene):
        name, bucket = "Fallback", EnergyBucket.DROP
    class _NeedsHaze(Scene):
        name, bucket = "Needs Haze", EnergyBucket.DROP
        requires = frozenset({"laser"})
        min_atmosphere_density = 0.6
        degrade_to = _Fallback
    rig = load_rig()
    cat = SceneCatalog([_NeedsHaze(), _Fallback()])
    picked = cat.pick(EnergyBucket.DROP, rig)
    assert isinstance(picked, _Fallback)


def test_pick_falls_back_to_round_robin_if_nothing_is_eligible_even_degraded():
    """Never hard-fail selection (this project's standing "selection never
    fails" guarantee) -- even with zero eligible scenes anywhere, pick()
    still returns something rather than raising."""
    class _NeedsHaze(Scene):
        name, bucket = "Needs Haze", EnergyBucket.DROP
        min_atmosphere_density = 1.0
    rig = load_rig()
    cat = SceneCatalog([_NeedsHaze()])
    assert cat.pick(EnergyBucket.DROP, rig) is not None


def test_pick_excludes_a_scene_that_conflicts_with_the_current_one():
    """Bible-integration Phase 4, LOOK-06 + Open Question #4's approved
    default: a conflicting look is simply never selected while the
    conflicting one is active -- no forced pre-emption of the current look."""
    class _A(Scene):
        name, bucket = "A", EnergyBucket.DROP
        conflicts = frozenset({"B"})
    class _B(Scene):
        name, bucket = "B", EnergyBucket.DROP
    cat = SceneCatalog([_A(), _B()])
    a = cat.bucket(EnergyBucket.DROP)[0]
    for _ in range(5):  # round-robin would otherwise eventually return B
        assert cat.pick(EnergyBucket.DROP, exclude=a).name == "A"


def test_pick_conflict_check_is_bidirectional():
    """The Bible declares conflicts[] one-sidedly per look -- checked both
    ways so a look doesn't need to declare the conflict on both sides."""
    class _A(Scene):
        name, bucket = "A", EnergyBucket.DROP
        conflicts = frozenset({"B"})  # only A declares the conflict
    class _B(Scene):
        name, bucket = "B", EnergyBucket.DROP
    cat = SceneCatalog([_A(), _B()])
    b = cat.bucket(EnergyBucket.DROP)[1]
    for _ in range(5):
        assert cat.pick(EnergyBucket.DROP, exclude=b).name == "B"  # A excluded even though B didn't declare it


def test_pick_never_hard_fails_even_if_everything_conflicts():
    class _A(Scene):
        name, bucket = "A", EnergyBucket.DROP
        conflicts = frozenset({"B"})
    class _B(Scene):
        name, bucket = "B", EnergyBucket.DROP
        conflicts = frozenset({"A"})
    cat = SceneCatalog([_A(), _B()])
    a = cat.bucket(EnergyBucket.DROP)[0]
    assert cat.pick(EnergyBucket.DROP, exclude=a) is not None  # never fails to select something


# --- Bible-integration Phase 5, first wave: DropBlackoutHit, DropStrobeStab, BuildRiserWash

def test_drop_blackout_hit_alternates_blood_red_and_cold_steel_by_drop_cycle():
    from livereact.scenes.library import BLOOD_RED, COLD_STEEL, DropBlackoutHit
    rig = load_rig()
    par = rig.fixture("par_l")
    even = DropBlackoutHit().render(rig, _snap(drop_cycle=2), 1.0)
    odd = DropBlackoutHit().render(rig, _snap(drop_cycle=3), 1.0)
    r, g, b = (round(v * 255) for v in BLOOD_RED)
    assert (even.values[par.offset + 1], even.values[par.offset + 2], even.values[par.offset + 3]) == (r, g, b)
    r, g, b = (round(v * 255) for v in COLD_STEEL)
    assert (odd.values[par.offset + 1], odd.values[par.offset + 2], odd.values[par.offset + 3]) == (r, g, b)


def test_drop_blackout_hit_color_is_static_not_audio_reactive():
    """"reactivity: static all, kick_follow:false -- the cut IS the effect."""
    from livereact.scenes.library import DropBlackoutHit
    rig = load_rig()
    quiet = DropBlackoutHit().render(rig, _snap(energy=0.1, drop_cycle=0, eq_low_a=0.9, eq_mid_a=0.05, eq_high_a=0.05), 1.0)
    loud = DropBlackoutHit().render(rig, _snap(energy=1.0, drop_cycle=0, eq_low_a=0.05, eq_mid_a=0.05, eq_high_a=0.9), 1.0)
    par = rig.fixture("par_l")
    assert quiet.values[par.offset + 1:par.offset + 4] == loud.values[par.offset + 1:par.offset + 4]


def test_drop_blackout_hit_conflicts_with_every_build_scene():
    from livereact.scenes.library import ALL_SCENES, DropBlackoutHit
    build_scene_names = {cls().name for cls in ALL_SCENES if cls().bucket == EnergyBucket.BUILD}
    assert build_scene_names <= DropBlackoutHit.conflicts


def test_drop_strobe_stab_does_not_touch_the_strobe_channel_itself():
    """The strobe stab itself belongs to ReactiveLayerEngine's own strobe
    channel (a separate DMX byte) -- this scene only provides color context."""
    from livereact.scenes.library import DropStrobeStab
    rig = load_rig()
    bar = rig.fixture("bar_l")
    c = DropStrobeStab().render(rig, _snap(), 1.0)
    assert not c.touched[bar.offset + 1]  # ch2 = strobe, untouched by this scene


def test_build_riser_wash_does_not_set_wash_intensity():
    """paint_wash deliberately never sets intensity -- that's owned
    exclusively by ReactiveLayerEngine's own bar-position ramp."""
    from livereact.scenes.library import BuildRiserWash
    rig = load_rig()
    bar = rig.fixture("bar_l")
    c = BuildRiserWash().render(rig, _snap(), 1.0)
    assert not c.touched[bar.offset]  # ch1 = dimmer, untouched


# --- Bible-integration Phase 5, second wave: PeakFullRig, PeakColorPulseClear, PeakAltHitsClear

def test_peak_full_rig_spots_at_full_intensity():
    from livereact.scenes.library import PeakFullRig
    rig = load_rig()
    mh = rig.fixture("mh_l")
    c = PeakFullRig().render(rig, _snap(), 1.0)
    assert c.values[mh.offset + 5] == 255  # ch6 dimmer, "spot 100%"


def test_peak_full_rig_fan_completes_one_cycle_every_four_bars():
    from livereact.scenes.library import PeakFullRig
    rig = load_rig()
    mh = rig.fixture("mh_l")
    scene = PeakFullRig()
    at_0 = scene.render(rig, _snap(bar=0, beat_in_bar=1, beat_phase=0.0), 1.0).values[mh.offset]
    at_4 = scene.render(rig, _snap(bar=4, beat_in_bar=1, beat_phase=0.0), 1.0).values[mh.offset]
    assert abs(at_0 - at_4) <= 1  # a full period_bars=4 cycle returns to the same pan (+-1 byte fp rounding)


def test_peak_color_pulse_clear_only_pulses_on_the_downbeat():
    from livereact.scenes.library import PeakColorPulseClear
    rig = load_rig()
    bar = rig.fixture("bar_l")
    scene = PeakColorPulseClear()
    on_beat = scene.render(rig, _snap(beat_in_bar=1, beat_phase=0.0), 1.0)
    off_beat = scene.render(rig, _snap(beat_in_bar=2, beat_phase=0.0), 1.0)
    assert on_beat.values[bar.offset] > 0
    assert off_beat.values[bar.offset] == 0


def test_peak_color_pulse_clear_decays_across_the_downbeat():
    from livereact.scenes.library import PeakColorPulseClear
    rig = load_rig()
    bar = rig.fixture("bar_l")
    scene = PeakColorPulseClear()
    early = scene.render(rig, _snap(beat_in_bar=1, beat_phase=0.0), 1.0).values[bar.offset]
    late = scene.render(rig, _snap(beat_in_bar=1, beat_phase=0.9), 1.0).values[bar.offset]
    assert early > late


def test_peak_color_pulse_clear_is_actually_visible_through_reactives_htp_hold():
    """Verified, not just theorized: DIMMER merges by HTP (max), so this
    scene's pulse could in principle be masked by ReactiveLayerEngine's own
    PEAK hold -- confirmed it genuinely shows through for realistic
    drop_hit_intensity values, only disappearing once the hit itself is
    already near-maximum (both sides already at the ceiling)."""
    from livereact.clock import FakeClock
    from livereact.core.show_state import ShowSnapshot
    from livereact.engines.reactive import ReactiveLayerEngine
    from livereact.merge.merge import merge_contributions
    from livereact.scenes.library import PeakColorPulseClear
    rig = load_rig()
    bar = rig.fixture("bar_l")
    scene = PeakColorPulseClear()

    def _merged_at(hit: float, beat_in_bar: int) -> int:
        reactive = ReactiveLayerEngine(FakeClock())
        snap = ShowSnapshot(energy=1.0, energy_norm=1.0, bucket="peak", drop_hit_intensity=hit,
                             beat_in_bar=beat_in_bar, beat_phase=0.0, fader_a=1.0, eq_low_a=0.5)
        c_r = reactive.tick(snap, rig)
        c_r.priority = reactive.priority
        c_p = scene.render(rig, snap, 1.0)
        c_p.priority = 50
        return merge_contributions([c_r, c_p], rig)[bar.offset]

    assert _merged_at(0.85, beat_in_bar=1) > _merged_at(0.85, beat_in_bar=3)  # a real, typical hit: pulse visible


def test_peak_alt_hits_clear_alternates_by_bar_on_a_single_fixture():
    from livereact.scenes.library import PeakAltHitsClear
    rig = load_rig()
    mh = rig.fixture("mh_l")
    scene = PeakAltHitsClear()
    bar0 = scene.render(rig, _snap(bar=0), 1.0).values[mh.offset]
    bar1 = scene.render(rig, _snap(bar=1), 1.0).values[mh.offset]
    bar2 = scene.render(rig, _snap(bar=2), 1.0).values[mh.offset]
    assert bar0 != bar1  # snaps between the two positions each bar
    assert bar0 == bar2  # and returns on the next even bar -- true alternation, not drift


# --- Bible-integration Phase 5, third wave: BreakLowWash, BreakSingleSpotSpecial, BreakCeilingDrift, BreakColorHoldClear

def test_break_low_wash_does_not_set_wash_intensity():
    """paint_wash deliberately never sets intensity -- the 15-35% breathing
    envelope is owned exclusively by ReactiveLayerEngine's own BREAK branch,
    same pattern as BuildRiserWash."""
    from livereact.scenes.library import BreakLowWash
    rig = load_rig()
    bar = rig.fixture("bar_l")
    c = BreakLowWash().render(rig, _snap(), 1.0)
    assert not c.touched[bar.offset]  # ch1 = dimmer, untouched


def test_break_low_wash_uses_cold_steel():
    from livereact.scenes.library import COLD_STEEL, BreakLowWash
    rig = load_rig()
    par = rig.fixture("par_l")
    c = BreakLowWash().render(rig, _snap(), 1.0)
    r, g, b = (round(v * 255) for v in COLD_STEEL)
    assert (c.values[par.offset + 1], c.values[par.offset + 2], c.values[par.offset + 3]) == (r, g, b)


def test_break_low_wash_conflicts_with_peak_strobe_blackout():
    """peak_strobe_blackout isn't built yet -- this just confirms the
    Bible's conflicts[] pairing is declared, ready for when it is."""
    from livereact.scenes.library import BreakLowWash
    assert "Peak Strobe Blackout" in BreakLowWash.conflicts


def test_break_single_spot_special_degrades_to_break_low_wash():
    from livereact.scenes.library import BreakLowWash, BreakSingleSpotSpecial
    assert BreakSingleSpotSpecial.degrade_to is BreakLowWash


def test_break_single_spot_special_spot_level_is_static_not_audio_reactive():
    from livereact.scenes.library import BreakSingleSpotSpecial
    rig = load_rig()
    mh = rig.fixture("mh_l")
    quiet = BreakSingleSpotSpecial().render(rig, _snap(energy=0.0), 1.0)
    loud = BreakSingleSpotSpecial().render(rig, _snap(energy=1.0), 1.0)
    assert quiet.values[mh.offset + 5] == loud.values[mh.offset + 5]  # ch6 dimmer -- "reactivity: static all"


def test_break_ceiling_drift_tilt_completes_one_cycle_every_eight_bars():
    from livereact.scenes.library import BreakCeilingDrift
    rig = load_rig()
    mh = rig.fixture("mh_l")
    scene = BreakCeilingDrift()
    at_0 = scene.render(rig, _snap(bar=0, beat_in_bar=1, beat_phase=0.0), 1.0).values[mh.offset + 2]
    at_8 = scene.render(rig, _snap(bar=8, beat_in_bar=1, beat_phase=0.0), 1.0).values[mh.offset + 2]
    assert abs(at_0 - at_8) <= 1  # a full period_bars=8 cycle returns to the same tilt (+-1 byte fp rounding)


def test_break_ceiling_drift_stays_within_the_declared_tilt_amplitude():
    from livereact.scenes.library import BreakCeilingDrift
    rig = load_rig()
    mh = rig.fixture("mh_l")
    scene = BreakCeilingDrift()
    tilts = [
        scene.render(rig, _snap(bar=b, beat_in_bar=1, beat_phase=0.0), 1.0).values[mh.offset + 2]
        for b in range(9)
    ]
    lo, hi = (0.5 - BreakCeilingDrift.TILT_AMP) * 255, (0.5 + BreakCeilingDrift.TILT_AMP) * 255
    assert all(lo - 1 <= t <= hi + 1 for t in tilts)


def test_break_color_hold_clear_is_static_color_and_position():
    """"Fully static" -- neither color nor position should move with energy/bar."""
    from livereact.scenes.library import DEEP_BLUE, BreakColorHoldClear
    rig = load_rig()
    par = rig.fixture("par_l")
    mh = rig.fixture("mh_l")
    a = BreakColorHoldClear().render(rig, _snap(bar=0, energy=0.1), 1.0)
    b = BreakColorHoldClear().render(rig, _snap(bar=5, energy=1.0), 1.0)
    r, g, bl = (round(v * 255) for v in DEEP_BLUE)
    assert (a.values[par.offset + 1], a.values[par.offset + 2], a.values[par.offset + 3]) == (r, g, bl)
    assert a.values[par.offset + 1:par.offset + 4] == b.values[par.offset + 1:par.offset + 4]
    assert a.values[mh.offset] == b.values[mh.offset]  # pan static too


def test_safe_default_renders_static_neutral_wash_no_motion_no_laser():
    """LOOK-08: safe_default is static 40% neutral_wash, no mover motion,
    no laser, no fog."""
    from livereact.fixtures.profiles import _intensity_to8
    rig = load_rig()
    snap = _snap()
    c = SAFE_DEFAULT.render(rig, snap, 1.0)
    par = rig.fixture("par_l")
    assert c.values[par.offset] == _intensity_to8(0.40)  # neutral 40% intensity, gamma+floor curve
    laser = rig.fixture("laser_l")
    assert not any(c.touched[laser.offset + i] for i in range(12))  # laser untouched
    mh = rig.fixture("mh_l")
    assert not c.touched[mh.offset]  # pan untouched -- no motion commanded


def test_converge_two_spots_matches_original_spread():
    """Converge was generalized from a hardcoded 2-fixture L/R split to any
    fixture count — this pins down that the N=2 case still reduces to
    exactly the original 0.15/0.85 spread math."""
    rig = load_rig()  # packaged default: mh_l (left) + mh_r (right)
    prog = 0.6
    snap = _snap(energy=prog)
    c = Converge().render(rig, snap, 1.0)
    mh_l, mh_r = rig.fixture("mh_l"), rig.fixture("mh_r")
    assert c.values[mh_l.offset] == round((0.15 + 0.35 * prog) * 255)
    assert c.values[mh_r.offset] == round((0.85 - 0.35 * prog) * 255)


def test_converge_single_spot_narrows_to_center_as_energy_rises():
    """The old Converge was broken on a 1-fixture rig: both branches of
    `if side == "left"` collapse to the same one, so "converge from the
    other side" never happened. The fix expresses the same arc as a sweep
    that narrows to stillness at center instead."""
    rig = _rig_from_dict({
        "name": "single-mh",
        "slots": [{"slot_id": "mh", "fixture_type": "shehds_180w_mh",
                   "dmx_address": 1, "role": "spot", "side": "left"}],
    })
    mh = rig.fixture("mh")
    # bar=2, beat 1, phase 0 -> musical_bar_position == 2.0, away from a sin() zero-crossing
    low = _snap(energy=0.0, bar=2, beat_in_bar=1, beat_phase=0.0)
    high = _snap(energy=1.0, bar=2, beat_in_bar=1, beat_phase=0.0)
    pan_low = Converge().render(rig, low, 1.0).values[mh.offset]
    pan_high = Converge().render(rig, high, 1.0).values[mh.offset]
    assert pan_high == 128            # full energy -> amplitude 0 -> dead center
    assert abs(pan_low - 128) > 20    # low energy -> meaningfully off-center, still sweeping
