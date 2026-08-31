"""Tests for the manual biases/caps applied at finalize: warm/cool color bias and
the operator strobe burst (both within safety limits)."""

from __future__ import annotations

from livereact.fixtures.rig import load_rig
from livereact.merge.merge import Contribution, ManualParams, render_universe


def test_warm_bias_boosts_red_relative_to_blue():
    rig = load_rig()
    par = rig.fixture("par_l")
    c = Contribution()
    par.set_color(c, 0.5, 0.0, 0.5)  # equal red and blue

    warm = render_universe([c], rig, ManualParams(warm_cool_bias=-1.0))
    cool = render_universe([c], rig, ManualParams(warm_cool_bias=1.0))

    assert warm[par.offset + 1] > warm[par.offset + 3]   # warm: R (ch2) > B (ch4)
    assert cool[par.offset + 3] > cool[par.offset + 1]   # cool: B (ch4) > R (ch2)


def test_strobe_burst_engages_strobe_within_cap():
    rig = load_rig()
    bar = rig.fixture("bar_l")
    c = Contribution()
    bar.set_intensity(c, 1.0)  # no strobe set by the scene

    calm = render_universe([c], rig, ManualParams())
    burst = render_universe([c], rig, ManualParams(strobe_burst=True, strobe_cap=0.5))

    assert calm[bar.offset + 1] == 0          # strobe off normally
    assert burst[bar.offset + 1] == round(0.5 * 255)  # burst engages, capped at 0.5


def test_strobe_burst_never_exceeds_the_cap():
    rig = load_rig()
    bar = rig.fixture("bar_l")
    c = Contribution()
    out = render_universe([c], rig, ManualParams(strobe_burst=True, strobe_cap=0.1))
    assert out[bar.offset + 1] <= int(0.1 * 255) + 1
