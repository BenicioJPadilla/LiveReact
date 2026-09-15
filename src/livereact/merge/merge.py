"""Merge layer: combine engine contributions into one universe, then apply manual
biases/caps and non-negotiable safety clamps.

Combine rules per channel kind (docs/05 §3, docs/08 §5):
  - DIMMER, COLOR : max across contributions (additive layering)
  - MOVEMENT      : last-write-wins (averaging pan/tilt would swing through center)
  - STROBE        : max across contributions, then rate-capped at finalize
  - LASER, OTHER  : last-write-wins

Manual params are *biases and caps*, never an "off switch" for automation — except
the two hard switches, blackout and freeze. Safety clamps (laser fail-safe, strobe
cap) run on every path and cannot be bypassed.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.frame_buffer import UNIVERSE_SIZE
from ..fixtures.profiles import Buffer, ChannelKind
from ..fixtures.rig import Rig


class Contribution(Buffer):
    """One engine's sparse write into the universe: values + a touched mask.

    Engines write via the fixture semantic setters (which call ``set``); only the
    channels they actually touch participate in the merge, so an engine that
    doesn't set, say, movement leaves another engine's movement intact.
    """

    def __init__(self) -> None:
        self.values = bytearray(UNIVERSE_SIZE)
        self.touched = bytearray(UNIVERSE_SIZE)
        # LIGHTING_BIBLE.md §2.3's Titan tiers (Bible-integration Phase 4):
        # set by the caller (core/show_engine.py) to the producing engine's
        # own `priority` class attribute right after tick() returns this.
        # Defaults to 0 -- lower than every real engine's tier (25/50/100),
        # so a Contribution nobody explicitly tagged never outranks a real
        # one on a tie (matters for tests/render_universe's one-shot use
        # that construct a bare Contribution directly).
        self.priority = 0

    def set(self, channel_1based: int, value: int) -> None:
        i = channel_1based - 1
        self.values[i] = 0 if value < 0 else 255 if value > 255 else value
        self.touched[i] = 1


@dataclass
class ManualParams:
    """Operator biases/caps. Defaults = fully automatic, nothing clamped."""

    master_brightness: float = 1.0   # 0..1 scales dimmers / par color
    strobe_cap: float = 1.0          # 0..1 max strobe-rate channel value
    laser_enable: bool = False       # lasers stay off until explicitly enabled
    warm_cool_bias: float = 0.0      # -1 warm .. +1 cool
    strobe_burst: bool = False       # momentary operator strobe (within the cap)
    blackout: bool = False           # hard: zero everything
    freeze: bool = False             # hard: hold last frame (handled by show engine)


def merge_contributions(contributions: list[Contribution], rig: Rig) -> bytearray:
    """Fold contributions onto the rig's boot universe using per-kind rules.

    Bible-integration Phase 4 (LIGHTING_BIBLE.md §2.1/§2.3, MERGE-02/03/05/
    06/07/08/19): DIMMER/STROBE stay genuinely HTP (max across every
    contribution -- true additive-brightness semantics, e.g. a Reactive
    beat-pulse and a Phrase scene both wanting the wash brighter should
    combine, not fight). Everything else (COLOR, MOVEMENT, LASER, OTHER) is
    now LTP **by explicit priority**, not a per-channel max or an accident
    of the caller's list order: the highest-priority contributor that
    touched this channel wins outright, its whole value, every time --
    closing the "still blue during the drop" bug (a scene's own hue used to
    out-max the Reactive layer's frozen hue on the blue channel specifically,
    producing a color neither engine intended) and the color-wheel/gobo/
    prism mistagging findings (a discrete slot value must never be blended
    with another one, which max() implicitly attempted). `Contribution.
    priority` is set by the caller (core/show_engine.py) to the producing
    engine's own Titan-tier number (see engines/reactive.py's own comment).

    NOT yet built: LIGHTING_BIBLE.md's full pan/tilt formula (`base(LTP) +
    Σ offsets`) for MOVEMENT specifically -- that needs each layer's
    movement expressed as a relative offset rather than an absolute
    position, a deeper change to how the engines compute movement at all,
    not just how the merge picks a winner. This resolves MOVEMENT's most
    concrete prior defect (Reactive's own movement being discarded via a
    last-write-wins accident of list order) by making the winner explicit
    and principled instead of accidental, but Phrase (priority 50) still
    outright wins over Reactive (25) on any channel both touch, same
    practical outcome as before for this specific case -- see
    docs/bible_integration/RULES_MATRIX.md's MERGE-05 row.
    """
    out = rig.boot_universe()
    if not contributions:
        return out

    for ch in range(UNIVERSE_SIZE):
        touched = [c for c in contributions if c.touched[ch]]
        if not touched:
            continue  # untouched -> keep the boot default
        kind = rig.kind_at(ch)
        if kind in (ChannelKind.DIMMER, ChannelKind.STROBE):
            out[ch] = max(c.values[ch] for c in touched)  # HTP
        else:  # COLOR, MOVEMENT, LASER, OTHER -> LTP by priority
            out[ch] = max(touched, key=lambda c: c.priority).values[ch]
    return out


def finalize(merged: bytearray, rig: Rig, manual: ManualParams, auto_blackout: bool = False,
             laser_on: bool = False, dt: float = 1.0 / 60.0,
             safe_default_frame: bytes | None = None, drop_pending: bool = False) -> bytes:
    """Apply manual biases/caps + safety clamps and return the wire-ready universe.

    ``freeze`` is intentionally not handled here — holding the last frame is the
    show engine's job (it simply doesn't publish a new frame). ``blackout`` (the
    operator's hard switch) and ``auto_blackout`` (docs/14 §2: no music detected —
    see core/silence.py) both win over everything, kept as two independent
    triggers rather than one shared flag so the operator's manual switch and the
    system's automatic one never fight over the same piece of state.

    ``laser_on`` (engines/laser.py's LaserEngine.active) additionally gates
    the laser specifically — armed (apply_safety, unchanged) is still
    required; this only controls whether the laser layer's DROP/PEAK moment
    is currently open, so nothing else can light the laser outside one.

    ``dt`` (LIGHTING_BIBLE.md §6.6, 2026-09-08) is the real elapsed time since
    the last finalized frame, used by movement slew-limiting (a no-op on
    fixtures that don't support it) — defaults to a 60Hz tick for callers that
    don't track real time (e.g. tests, render_universe's one-shot use).

    ``safe_default_frame`` (Bible-integration Phase 1, `LOOK-08`/`FAIL-04`,
    optional/default None): when given, ``auto_blackout`` renders this frame
    instead of an instant hard zero — LIGHTING_BIBLE.md §12's actual failsafe
    target is a static 40% neutral wash (`scenes/base.py`'s `SAFE_DEFAULT`),
    not total darkness. ``manual.blackout`` (the operator's own hard kill
    switch) is deliberately UNCHANGED by this — an operator hitting "kill"
    wants instant black, not a dim wash, so it still always short-circuits to
    ``bytes(UNIVERSE_SIZE)`` regardless of this parameter. Omitting
    ``safe_default_frame`` (the default) preserves the old instant-hard-zero
    behavior for auto_blackout too, so every existing caller/test is
    unaffected until a caller opts in (gig-safe: the old failsafe stays
    selectable until this is wired in and approved for real hardware use).
    NOTE: this is the *target* fix only — a real ~2-bar fade FROM the live
    frame TOWARD this one (rather than an instant switch) is still open,
    tracked in docs/bible_integration/RULES_MATRIX.md against FAIL-04.

    ``drop_pending`` (Bible-integration Phase 5, `build_to_drop_bridge`,
    `TRANS-03`'s `blackout_beat`): true for the brief window between a DROP
    being confirmed and the next real downbeat actually releasing it (see
    core/metronome.py's `_pending_drop_release`, Phase 3's beat-
    quantization). "Holds dark on the final bar, releases to the DROP look
    on the downbeat" — a genuine hard cut, matching `blackout_beat`'s own
    literal "cut to 0 on the final beat" wording, not a dim/faded state like
    `safe_default`. Checked after ``manual.blackout``/``auto_blackout`` (an
    operator kill or a real no-music failsafe should still win outright)
    but before anything else -- in practice these shouldn't co-occur, since
    a real pending drop implies fresh audio/PDL.
    """
    if manual.blackout:
        return bytes(UNIVERSE_SIZE)
    if auto_blackout:
        return bytes(safe_default_frame) if safe_default_frame is not None else bytes(UNIVERSE_SIZE)
    if drop_pending:
        return bytes(UNIVERSE_SIZE)

    out = bytearray(merged)
    for fx in rig.fixtures:
        fx.apply_master_brightness(out, manual.master_brightness)
        fx.apply_color_bias(out, manual.warm_cool_bias)
        if manual.strobe_burst:
            fx.apply_strobe_burst(out, manual.strobe_cap)  # within the cap
        fx.cap_strobe(out, manual.strobe_cap)              # safety: always cap
        fx.cap_brightness_while_strobing(out)               # safety: never full-bright while strobing (Josh, 2026-09-14)
        fx.apply_safety(out, manual.laser_enable)          # laser fail-safe
        fx.apply_home_position(out)                        # docs/14 §4: bound around a calibrated home
        fx.apply_slew_limit(out, dt)                        # LIGHTING_BIBLE.md §6.6: protect motors from instant jumps
        fx.apply_laser_gate(out, laser_on)                  # engines/laser.py: only during a laser moment
    return bytes(out)


def render_universe(
    contributions: list[Contribution], rig: Rig, manual: ManualParams | None = None,
    auto_blackout: bool = False, laser_on: bool = False,
) -> bytes:
    """Convenience: merge + finalize in one call."""
    return finalize(merge_contributions(contributions, rig), rig, manual or ManualParams(),
                     auto_blackout, laser_on)
