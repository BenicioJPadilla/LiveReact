"""Fixture profiles: translate semantic intent (intensity, color, position, strobe)
to/from DMX channels, and own the per-fixture boot defaults + safety clamps.

Channel maps are reproduced from docs/04 §3 and are "verified on Josh's unit" only
— treat them as hypotheses to confirm on hardware via the fixture-test panel
(Phase 7). They live here as data, never hard-coded into engine/scene logic.

Coordinate conventions used across the app:
  - intensity / color components / pan / tilt / strobe-rate are floats in [0, 1].
  - DMX channel addresses are 1-based (matching the rig docs); the universe buffer
    is 0-based, so channel N lives at index N-1.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class ChannelKind(IntEnum):
    """How the merge layer should combine a channel across engine contributions."""

    OTHER = 0       # last-write-wins, no special handling
    DIMMER = 1      # max across contributions
    COLOR = 2       # max across contributions
    MOVEMENT = 3    # last-write-wins (averaging pan/tilt would swing through center)
    STROBE = 4      # max, then rate-capped at finalize
    LASER = 5       # gated off unless explicitly enabled at finalize


@dataclass(frozen=True)
class VisualState:
    """What the visualizer needs to draw one fixture, derived from live channels."""

    label: str
    role: str
    side: str
    r: int          # 0-255 base color (before brightness)
    g: int
    b: int
    brightness: float  # 0..1
    pan: float         # 0..1 (0.5 = center)
    tilt: float        # 0..1
    active: bool


def _clamp8(value: float) -> int:
    """Clamp a number to a valid DMX byte (0-255)."""
    return 0 if value <= 0 else 255 if value >= 255 else int(value)


def _to8(level01: float) -> int:
    """Map a 0..1 level to a 0-255 DMX byte."""
    return _clamp8(round(level01 * 255))


def _bias_factors(bias: float) -> tuple[float, float]:
    """(red_factor, blue_factor) for a warm/cool bias in [-1, +1].

    bias < 0 = warm (boost red, cut blue); bias > 0 = cool (cut red, boost blue).
    """
    warmth = -bias
    return (1.0 + 0.5 * warmth, 1.0 - 0.5 * warmth)


# Approximate color-wheel slot -> RGB for moving heads. The SHEHDS wheel slot
# boundaries are not documented in the manuals we have, so this is a reasonable
# default to be corrected on hardware (assumption A1). Used only for display and
# as a coarse target when a scene asks an MH for an RGB-ish color.
_MH_COLOR_WHEEL = [
    (0, (255, 255, 255)),    # open / white
    (8, (255, 0, 0)),        # red
    (16, (255, 120, 0)),     # orange/amber
    (24, (255, 255, 0)),     # yellow
    (32, (0, 255, 0)),       # green
    (40, (0, 200, 255)),     # cyan
    (48, (0, 0, 255)),       # blue
    (56, (255, 0, 255)),     # magenta/pink
]


def color_wheel_to_rgb(value: int) -> tuple[int, int, int]:
    """Map a moving-head color-wheel channel value to an approximate RGB."""
    chosen = _MH_COLOR_WHEEL[0][1]
    for threshold, rgb in _MH_COLOR_WHEEL:
        if value >= threshold:
            chosen = rgb
        else:
            break
    return chosen


def rgb_to_color_wheel(r: int, g: int, b: int) -> int:
    """Pick the nearest color-wheel slot value for a target RGB (coarse)."""
    best_value, best_dist = 0, 1 << 30
    for value, (cr, cg, cb) in _MH_COLOR_WHEEL:
        dist = (cr - r) ** 2 + (cg - g) ** 2 + (cb - b) ** 2
        if dist < best_dist:
            best_value, best_dist = value, dist
    return best_value


class Buffer:
    """Minimal write-target protocol shared by ``Contribution`` and bare universes.

    Fixtures write through ``set(channel_1based, value)`` so the same semantic
    setters work whether an engine is building a sparse contribution or code is
    assembling a boot universe directly.
    """

    def set(self, channel_1based: int, value: int) -> None:  # pragma: no cover
        raise NotImplementedError


class Fixture:
    """Base class. Subclasses declare their channel count + kinds and override the
    semantic setters they support; unsupported ones are no-ops."""

    type_name: str = "generic"
    channel_count: int = 0

    def __init__(self, address: int, label: str, role: str, side: str) -> None:
        self.address = address  # 1-based DMX start address
        self.label = label
        self.role = role        # 'spot' | 'wash' | 'laser'
        self.side = side        # 'left' | 'right'

    # --- geometry ---
    @property
    def offset(self) -> int:
        """0-based index of this fixture's first channel in the universe buffer."""
        return self.address - 1

    def channels(self) -> range:
        """1-based DMX channels this fixture occupies."""
        return range(self.address, self.address + self.channel_count)

    def channel_kinds(self) -> list[ChannelKind]:
        """Per-local-channel kinds; length == channel_count. Override per fixture."""
        return [ChannelKind.OTHER] * self.channel_count

    # --- helpers ---
    def _set(self, buf: Buffer, local_1based: int, value: int) -> None:
        buf.set(self.address + local_1based - 1, value)

    # --- boot ---
    def boot_defaults(self, buf: Buffer) -> None:
        """Write the fixture's safe power-on state. Override as needed."""

    # --- semantic setters (override what the fixture supports) ---
    def set_intensity(self, buf: Buffer, level01: float) -> None: ...
    def set_color(self, buf: Buffer, r: float, g: float, b: float, w: float = 0.0) -> None: ...
    def set_position(self, buf: Buffer, pan01: float, tilt01: float) -> None: ...
    def set_strobe(self, buf: Buffer, rate01: float) -> None: ...

    # --- finalize-stage clamps (operate on the assembled universe bytearray) ---
    def apply_master_brightness(self, uni: bytearray, factor01: float) -> None: ...
    def cap_strobe(self, uni: bytearray, cap01: float) -> None: ...
    def apply_safety(self, uni: bytearray, laser_enabled: bool) -> None: ...
    def apply_color_bias(self, uni: bytearray, bias: float) -> None: ...
    def apply_strobe_burst(self, uni: bytearray, cap01: float) -> None: ...

    # --- visualization ---
    def visual_state(self, uni: bytes) -> VisualState:  # pragma: no cover - overridden
        return VisualState(self.label, self.role, self.side, 0, 0, 0, 0.0, 0.5, 0.5, False)


class MovingHead(Fixture):
    """SHEHDS 180W Beam Moving Head — 15CH (docs/04 §3.1).

    1 Pan · 2 Pan-fine · 3 Tilt · 4 Tilt-fine · 5 Speed · 6 Dimmer · 7 Strobe ·
    8 Color wheel · 9 Gobo · 10 Prism · 11 Focus · 12 Frost · 13 Macro(keep 0) ·
    14 Macro-speed · 15 Reset.
    """

    type_name = "shehds_180w_mh"
    channel_count = 15

    def channel_kinds(self) -> list[ChannelKind]:
        K = ChannelKind
        return [
            K.MOVEMENT, K.MOVEMENT, K.MOVEMENT, K.MOVEMENT,  # 1-4 pan/pan-fine/tilt/tilt-fine
            K.OTHER,                                          # 5 speed
            K.DIMMER, K.STROBE, K.COLOR,                      # 6-8 dimmer/strobe/color wheel
            K.OTHER, K.OTHER, K.OTHER, K.OTHER,               # 9-12 gobo/prism/focus/frost
            K.OTHER, K.OTHER, K.OTHER,                        # 13-15 macro/macro-speed/reset
        ]

    def boot_defaults(self, buf: Buffer) -> None:
        self._set(buf, 1, 128)   # pan center
        self._set(buf, 3, 80)    # tilt angled down
        self._set(buf, 5, 128)   # movement speed mid
        self._set(buf, 6, 0)     # dimmer off
        self._set(buf, 13, 0)    # macro off (drive via DMX, not built-in macros)

    def set_intensity(self, buf: Buffer, level01: float) -> None:
        self._set(buf, 6, _to8(level01))

    def set_color(self, buf: Buffer, r: float, g: float, b: float, w: float = 0.0) -> None:
        slot = rgb_to_color_wheel(_to8(r), _to8(g), _to8(b))
        self._set(buf, 8, slot)

    def set_position(self, buf: Buffer, pan01: float, tilt01: float) -> None:
        self._set(buf, 1, _to8(pan01))
        self._set(buf, 3, _to8(tilt01))

    def set_strobe(self, buf: Buffer, rate01: float) -> None:
        self._set(buf, 7, _to8(rate01))

    def apply_master_brightness(self, uni: bytearray, factor01: float) -> None:
        i = self.offset + 5  # ch6 dimmer
        uni[i] = _clamp8(uni[i] * factor01)

    def cap_strobe(self, uni: bytearray, cap01: float) -> None:
        i = self.offset + 6  # ch7 strobe
        uni[i] = min(uni[i], _to8(cap01))

    def apply_strobe_burst(self, uni: bytearray, cap01: float) -> None:
        uni[self.offset + 6] = _to8(cap01)  # ch7 strobe at the capped rate

    def visual_state(self, uni: bytes) -> VisualState:
        dim = uni[self.offset + 5] / 255
        r, g, b = color_wheel_to_rgb(uni[self.offset + 7])
        pan = uni[self.offset + 0] / 255
        tilt = uni[self.offset + 2] / 255
        return VisualState(self.label, self.role, self.side, r, g, b, dim, pan, tilt, dim > 0)


class Laser(Fixture):
    """SHEHDS 3W Laser — 12CH, SAFETY-CRITICAL (docs/04 §3.2).

    CH1 mode: 0-41 = OFF (boot here). LiveReact only ever uses static manual
    patterns (42-83) in explicit drop scenes, never the sound-active ranges
    (168-251). All channels are forced off unless laser-enable is set at finalize.
    """

    type_name = "shehds_3w_laser"
    channel_count = 12
    MANUAL_PATTERN_MODE = 60  # within the 42-83 manual range

    def channel_kinds(self) -> list[ChannelKind]:
        return [ChannelKind.LASER] * self.channel_count

    def boot_defaults(self, buf: Buffer) -> None:
        for ch in range(1, self.channel_count + 1):
            self._set(buf, ch, 0)  # everything off; CH1=0 is LASER OFF

    def set_pattern(self, buf: Buffer, pattern: int, color: int = 255, scale: float = 1.0) -> None:
        """Enable a static manual pattern (only meaningful inside a drop scene)."""
        self._set(buf, 1, self.MANUAL_PATTERN_MODE)
        self._set(buf, 2, _clamp8(pattern))
        self._set(buf, 9, _to8(scale))
        self._set(buf, 12, _clamp8(color))

    def apply_safety(self, uni: bytearray, laser_enabled: bool) -> None:
        # Fail-safe: unless explicitly enabled this run, the entire fixture is zeroed
        # (CH1=0 => laser off). Drop-scene gating is layered on top in Phase 4.
        if not laser_enabled:
            for i in range(self.offset, self.offset + self.channel_count):
                uni[i] = 0

    def visual_state(self, uni: bytes) -> VisualState:
        mode = uni[self.offset + 0]
        active = mode > 41
        # CH12 is color; map coarsely through the same wheel for display.
        r, g, b = color_wheel_to_rgb(uni[self.offset + 11]) if active else (0, 0, 0)
        return VisualState(self.label, self.role, self.side, r, g, b, 1.0 if active else 0.0, 0.5, 0.5, active)


class Par(Fixture):
    """RGBW Par — 4CH (docs/04 §3.3). No master dimmer, no strobe channel:
    dim by scaling RGB(W); strobe (if ever needed) is done in software."""

    type_name = "rgbw_par"
    channel_count = 4

    def channel_kinds(self) -> list[ChannelKind]:
        return [ChannelKind.COLOR] * 4

    def boot_defaults(self, buf: Buffer) -> None:
        for ch in range(1, 5):
            self._set(buf, ch, 0)

    def set_color(self, buf: Buffer, r: float, g: float, b: float, w: float = 0.0) -> None:
        self._set(buf, 1, _to8(r))
        self._set(buf, 2, _to8(g))
        self._set(buf, 3, _to8(b))
        self._set(buf, 4, _to8(w))

    def set_intensity(self, buf: Buffer, level01: float) -> None:
        # No dimmer channel; modeled as scaling whatever color is present is done
        # at finalize. As a standalone intent, set a white level.
        v = _to8(level01)
        for ch in range(1, 5):
            self._set(buf, ch, v)

    def apply_master_brightness(self, uni: bytearray, factor01: float) -> None:
        for i in range(self.offset, self.offset + 4):  # scale R,G,B,W together
            uni[i] = _clamp8(uni[i] * factor01)

    def apply_color_bias(self, uni: bytearray, bias: float) -> None:
        if bias == 0.0:
            return
        rf, bf = _bias_factors(bias)
        uni[self.offset + 0] = _clamp8(uni[self.offset + 0] * rf)  # R
        uni[self.offset + 2] = _clamp8(uni[self.offset + 2] * bf)  # B

    def visual_state(self, uni: bytes) -> VisualState:
        r, g, b, w = (uni[self.offset + k] for k in range(4))
        # Fold white into RGB for display.
        rr, gg, bb = min(255, r + w), min(255, g + w), min(255, b + w)
        brightness = max(rr, gg, bb) / 255
        return VisualState(self.label, self.role, self.side, rr, gg, bb, brightness, 0.5, 0.5, brightness > 0)


class WashBar(Fixture):
    """OK-103-288WL Wash Bar — 6CH (docs/04 §3.4).
    1 Master Dimmer · 2 Strobe · 3 Red · 4 Green · 5 Blue · 6 White."""

    type_name = "ok103_wash_bar"
    channel_count = 6

    def channel_kinds(self) -> list[ChannelKind]:
        K = ChannelKind
        return [K.DIMMER, K.STROBE, K.COLOR, K.COLOR, K.COLOR, K.COLOR]

    def boot_defaults(self, buf: Buffer) -> None:
        for ch in range(1, 7):
            self._set(buf, ch, 0)

    def set_intensity(self, buf: Buffer, level01: float) -> None:
        self._set(buf, 1, _to8(level01))

    def set_color(self, buf: Buffer, r: float, g: float, b: float, w: float = 0.0) -> None:
        self._set(buf, 3, _to8(r))
        self._set(buf, 4, _to8(g))
        self._set(buf, 5, _to8(b))
        self._set(buf, 6, _to8(w))

    def set_strobe(self, buf: Buffer, rate01: float) -> None:
        self._set(buf, 2, _to8(rate01))

    def apply_master_brightness(self, uni: bytearray, factor01: float) -> None:
        i = self.offset  # ch1 dimmer
        uni[i] = _clamp8(uni[i] * factor01)

    def cap_strobe(self, uni: bytearray, cap01: float) -> None:
        i = self.offset + 1  # ch2 strobe
        uni[i] = min(uni[i], _to8(cap01))

    def apply_strobe_burst(self, uni: bytearray, cap01: float) -> None:
        uni[self.offset + 1] = _to8(cap01)  # ch2 strobe at the capped rate

    def apply_color_bias(self, uni: bytearray, bias: float) -> None:
        if bias == 0.0:
            return
        rf, bf = _bias_factors(bias)
        uni[self.offset + 2] = _clamp8(uni[self.offset + 2] * rf)  # R ch3
        uni[self.offset + 4] = _clamp8(uni[self.offset + 4] * bf)  # B ch5

    def visual_state(self, uni: bytes) -> VisualState:
        dim = uni[self.offset + 0] / 255
        r, g, b, w = (uni[self.offset + k] for k in range(2, 6))
        rr, gg, bb = min(255, r + w), min(255, g + w), min(255, b + w)
        return VisualState(self.label, self.role, self.side, rr, gg, bb, dim, 0.5, 0.5, dim > 0)


# Registry mapping rig-file ``fixture_type`` -> profile class.
FIXTURE_TYPES: dict[str, type[Fixture]] = {
    cls.type_name: cls for cls in (MovingHead, Laser, Par, WashBar)
}
