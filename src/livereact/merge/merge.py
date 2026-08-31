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
    """Fold contributions onto the rig's boot universe using per-kind rules."""
    out = rig.boot_universe()
    if not contributions:
        return out

    for ch in range(UNIVERSE_SIZE):
        # Gather, in engine order, the contributions that touched this channel.
        touched_vals = [c.values[ch] for c in contributions if c.touched[ch]]
        if not touched_vals:
            continue  # untouched -> keep the boot default
        kind = rig.kind_at(ch)
        if kind in (ChannelKind.DIMMER, ChannelKind.COLOR, ChannelKind.STROBE):
            out[ch] = max(touched_vals)
        else:  # MOVEMENT, LASER, OTHER -> last writer wins
            out[ch] = touched_vals[-1]
    return out


def finalize(merged: bytearray, rig: Rig, manual: ManualParams) -> bytes:
    """Apply manual biases/caps + safety clamps and return the wire-ready universe.

    ``freeze`` is intentionally not handled here — holding the last frame is the
    show engine's job (it simply doesn't publish a new frame). ``blackout`` is hard
    and wins over everything.
    """
    if manual.blackout:
        return bytes(UNIVERSE_SIZE)

    out = bytearray(merged)
    for fx in rig.fixtures:
        fx.apply_master_brightness(out, manual.master_brightness)
        fx.apply_color_bias(out, manual.warm_cool_bias)
        if manual.strobe_burst:
            fx.apply_strobe_burst(out, manual.strobe_cap)  # within the cap
        fx.cap_strobe(out, manual.strobe_cap)              # safety: always cap
        fx.apply_safety(out, manual.laser_enable)          # laser fail-safe
    return bytes(out)


def render_universe(
    contributions: list[Contribution], rig: Rig, manual: ManualParams | None = None
) -> bytes:
    """Convenience: merge + finalize in one call."""
    return finalize(merge_contributions(contributions, rig), rig, manual or ManualParams())
