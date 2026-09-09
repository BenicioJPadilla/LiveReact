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


# Dimmer/intensity-specific curve (LIGHTING_BIBLE.md §3.7, [VERIFIED]): budget
# LED pars shift hue and show visible discrete "steps" on a raw linear fade
# below ~10-15% output, so a straight `_to8` (used everywhere else — color,
# position, strobe, scale) is the wrong mapping specifically for dimmer
# channels. Two things, both from the Bible, not guessed:
#   - gamma/square-law curve (perceived brightness relates to measured output
#     by roughly a square law: ~1% measured looks like ~10% perceived), so a
#     linear fade dumps nearly all visible change into the bottom of the
#     range; `output = 255 * level^2.2` spreads it evenly instead.
#   - a hard floor at 12% (DMX 31): never dwell in the DMX 1-30 "stepping
#     zone" — any level intent above true zero (however dim) still shows at
#     AT LEAST the floor, and only a genuine zero intent produces true 0, so a
#     fade passing near zero cuts straight to black instead of crawling
#     visibly through the broken low range.
DIMMER_GAMMA = 2.2
DIMMER_FLOOR_DMX = 31  # 12% of 255


def _intensity_to8(level01: float) -> int:
    """Map a 0..1 intensity to a 0-255 DMX byte via the gamma+floor curve
    above. Use this (not `_to8`) for every fixture's actual dimmer channel."""
    if level01 <= 0.0:
        return 0
    curved = 255.0 * (min(1.0, level01) ** DIMMER_GAMMA)
    return max(DIMMER_FLOOR_DMX, _clamp8(round(curved)))


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
        # Optional custom position on the virtual rig canvas (normalized 0..1,
        # the fixture's on-screen center). None -> the visualizer's default
        # role/side layout. Set by the rig loader from a slot's "x"/"y", or
        # live by dragging the fixture in the console's Show tab, so an
        # operator can arrange the virtual rig to match a real venue's
        # physical layout per event.
        self.layout_x: float | None = None
        self.layout_y: float | None = None
        # Calibrated "facing the stage" pan/tilt (normalized 0..1), docs/14 §4.
        # None -> apply_home_position() is a no-op, keeping the old raw
        # 0.5-centered sweep behavior until a fixture is calibrated. Set by the
        # rig loader from a slot's "home_pan"/"home_tilt", or via the
        # fixture-test panel's "Save as Home Position" button.
        self.home_pan: float | None = None
        self.home_tilt: float | None = None
        # Laser beam-height safety geometry (LIGHTING_BIBLE.md §8.6,
        # LASER-08/09/10/11 -- Stage 6 audit fix, 2026-09-09). Generic on the
        # base class (same pattern as home_pan/home_tilt) though only `Laser`
        # currently checks it in apply_safety(). Fail-closed on undeclared
        # geometry, matching the spec literally: `mount_height_m is None`
        # (never configured) forces the laser off, same as a declared height
        # below `min_beam_height_m`. `fda_variance_on_file` is deliberately
        # NOT modeled or enforced here: Josh has explicitly deprioritized
        # that paperwork for solo/no-audience testing (see
        # [[livereact-lighting-bible]] memory) -- this is a real eye-safety
        # geometry check, not a compliance gate, so it doesn't depend on
        # variance status.
        self.mount_height_m: float | None = None
        self.min_beam_height_m: float = 3.0

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
    def apply_home_position(self, uni: bytearray, bound: float = 0.20) -> None: ...
    def apply_slew_limit(self, uni: bytearray, dt: float) -> None: ...
    def apply_onset_gate(self, uni: bytearray, flash_active: bool) -> None: ...

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

    # Slew-rate limits (LIGHTING_BIBLE.md §6.6) — PLACEHOLDER values copied
    # from the Bible's own reference-rig example, NOT measured against this
    # specific SHEHDS 180W unit's real motor speed. The exact numbers matter
    # less than having SOME clamp at all: `[VERIFIED]` per the Bible, instant
    # dead-stop-to-full-speed jumps (e.g. a scene switch commanding a big
    # position change in one tick) produce visible stepping and motor stress
    # on real moving-head hardware. Verify/tune these against real hardware
    # before trusting them as final — same "measure, don't guess" rule as
    # everywhere else in this project.
    PAN_RANGE_DEG = 540.0
    TILT_RANGE_DEG = 270.0
    PAN_MAX_DEG_PER_S = 260.0
    TILT_MAX_DEG_PER_S = 200.0

    def __init__(self, address: int, label: str, role: str, side: str) -> None:
        super().__init__(address, label, role, side)
        self._prev_pan_dmx: int | None = None
        self._prev_tilt_dmx: int | None = None

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
        self._set(buf, 6, _intensity_to8(level01))

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

    def apply_home_position(self, uni: bytearray, bound: float = 0.20) -> None:
        """Remap whatever raw pan/tilt a scene/engine set (all of them assume a
        0.5-centered convention) around this fixture's calibrated "facing the
        stage" position, scaled into a bounded range — docs/14 §4. A no-op
        until calibrated (home_pan/home_tilt are None), so uncalibrated rigs
        keep the old raw sweep behavior.

        Deliberately a finalize-stage transform, not a rewrite of every
        scene's position math: it preserves each scene's relative motion
        *shape* (Converge's spread-to-center, FullSpectrumHit's big fast
        moves, etc.) while re-centering and re-scaling the *output* uniformly.
        """
        if self.home_pan is None or self.home_tilt is None:
            return
        raw_pan = uni[self.offset + 0] / 255
        raw_tilt = uni[self.offset + 2] / 255
        new_pan = self.home_pan + (raw_pan - 0.5) * bound
        new_tilt = self.home_tilt + (raw_tilt - 0.5) * bound
        uni[self.offset + 0] = _to8(max(0.0, min(1.0, new_pan)))
        uni[self.offset + 2] = _to8(max(0.0, min(1.0, new_tilt)))

    def apply_slew_limit(self, uni: bytearray, dt: float) -> None:
        """Clamp the commanded pan/tilt delta per frame so a scene switch or
        crossfade can't slam the motor from a dead stop to full-range in one
        tick (LIGHTING_BIBLE.md §6.6). Large moves still complete, just ramped
        over multiple frames instead of one. Runs AFTER apply_home_position,
        so it clamps the final commanded position, not the pre-remap one.

        First tick after construction (no prior commanded value yet) passes
        the command through unclamped — there's nothing to ramp from.
        """
        pan_i, tilt_i = self.offset + 0, self.offset + 2
        self._prev_pan_dmx = self._slew(uni, pan_i, self._prev_pan_dmx,
                                         self.PAN_MAX_DEG_PER_S, self.PAN_RANGE_DEG, dt)
        self._prev_tilt_dmx = self._slew(uni, tilt_i, self._prev_tilt_dmx,
                                          self.TILT_MAX_DEG_PER_S, self.TILT_RANGE_DEG, dt)

    @staticmethod
    def _slew(uni: bytearray, i: int, prev: int | None,
              max_deg_per_s: float, range_deg: float, dt: float) -> int:
        commanded = uni[i]
        if prev is None:
            return commanded
        max_delta = max_deg_per_s * dt / range_deg * 255.0
        delta = max(-max_delta, min(max_delta, commanded - prev))
        new_value = _clamp8(round(prev + delta))
        uni[i] = new_value
        return new_value

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

    Channel map VERIFIED ON HARDWARE (2026-09-06) by isolated probing, cross-
    checked against the real QLC+ fixture file bundled with the app (`Shehds-
    3000mW-RGB-Laser.qxf`, author Bram Janssen — a genuine match by model name,
    NOT a web guess) — but that file's exact shape NAMES and a couple of its
    channel descriptions turned out wrong for this physical unit; only what's
    listed below was actually confirmed live, same "verify empirically, don't
    trust the manual" rule as everywhere else in this project:
      CH1  mode (0-41 off, 42-83 manual — confirmed, matches the file)
      CH2  "Pattern A 1": pattern group, changes roughly every 32 values.
           PATTERN_A1_DOTTED_LINE=118 (group ~96-127) is the only value
           mapped so far — flattens the default circle into a line. The
           file's own shape names for other groups (e.g. "Circle Part Fan")
           did NOT match what actually appeared on this unit — treat any
           other CH2 value as unmapped, not as the file's stated name.
      CH3  "Pattern A 2": sub-pattern within whichever CH2 group is selected.
           Held at 0 throughout — not otherwise explored for CH2's dotted-
           line group.
      CH7  horizontal sweep — 0-127 static position (untested), 128-255 =
           sweep speed (confirmed). Speed now driven by audio intensity.
      CH9  "scale" per the file (claimed a plain static 0-255 zoom level) —
           WRONG. Confirmed on hardware: any nonzero value makes the pattern
           breathe/cycle size on its own (128 grows steadily, 64 shrinks
           steadily, 96 sawtooths — shrink then snap back, repeating; not a
           simple speed-around-a-center-point model either). SCALE_STATIC=0
           is the ONLY value found that holds a fixed size. Never set this
           to anything else without re-verifying live.
      CH11 "Pattern A Scan" — 0-127 scan speed (untested), 128-255 =
           "Pattern Lattice" per the file, CONFIRMED on hardware: turns the
           shape's outline into dots. SCAN_DOTS=190 verified good.
      CH12 color — confirmed, matches the file's named bands exactly
           (spot-checked: Green 32-39 in the file matched a real green output).
    """

    type_name = "shehds_3w_laser"
    channel_count = 12
    MANUAL_PATTERN_MODE = 60        # within the 42-83 manual range
    PATTERN_A1_DOTTED_LINE = 118    # CH2 — flattens the circle into a line (confirmed)
    PATTERN_A2_DEFAULT = 0          # CH3 — sub-pattern within the group; unexplored otherwise
    SCALE_STATIC = 0                # CH9 — MUST stay 0, see class docstring
    SCAN_DOTS = 190                 # CH11 — "Pattern Lattice", outline -> dots (confirmed)
    SWEEP_SPEED_MIN = 128           # CH7 — bottom of the confirmed speed sub-range
    SWEEP_SPEED_MAX = 255           # CH7 — top of the confirmed speed sub-range

    # CH12 color macros — middle of each named band in the QLC+ file, confirmed
    # for Green; the rest inferred from the same file's explicit ranges (not yet
    # individually spot-checked on hardware beyond Green and White).
    COLOR_WHITE = 11
    COLOR_RED = 19
    COLOR_YELLOW = 27
    COLOR_GREEN = 35
    COLOR_CYAN = 43
    COLOR_BLUE = 51
    COLOR_PURPLE = 59

    def channel_kinds(self) -> list[ChannelKind]:
        return [ChannelKind.LASER] * self.channel_count

    def boot_defaults(self, buf: Buffer) -> None:
        for ch in range(1, self.channel_count + 1):
            self._set(buf, ch, 0)  # everything off; CH1=0 is LASER OFF

    def set_dotted_line_sweep(self, buf: Buffer, color: int, sweep_intensity: float) -> None:
        """The one fully-verified pattern (2026-09-06): a flattened line, its
        outline turned to dots, sweeping horizontally at a speed driven by
        real audio intensity (0..1) — "translate the audio directly," same
        principle as wash/par. `color` should be one of the COLOR_* constants.
        Only meaningful inside a drop scene / while the laser is armed."""
        self._set(buf, 1, self.MANUAL_PATTERN_MODE)
        self._set(buf, 2, self.PATTERN_A1_DOTTED_LINE)
        self._set(buf, 3, self.PATTERN_A2_DEFAULT)
        self._set(buf, 7, self._sweep_speed(sweep_intensity))
        self._set(buf, 9, self.SCALE_STATIC)
        self._set(buf, 11, self.SCAN_DOTS)
        self._set(buf, 12, _clamp8(color))

    def _sweep_speed(self, intensity: float) -> int:
        intensity = max(0.0, min(1.0, intensity))
        span = self.SWEEP_SPEED_MAX - self.SWEEP_SPEED_MIN
        return int(self.SWEEP_SPEED_MIN + intensity * span)

    def apply_safety(self, uni: bytearray, laser_enabled: bool) -> None:
        # Fail-safe: unless explicitly enabled this run, the entire fixture is zeroed
        # (CH1=0 => laser off). Drop-scene gating is layered on top in Phase 4.
        #
        # Beam-height geometry check (LIGHTING_BIBLE.md §8.6, LASER-08/09/10/11
        # -- Stage 6 audit fix, 2026-09-09, Josh's explicit call): this unit
        # has no pan/tilt (channel_kinds() is all ChannelKind.LASER, confirmed
        # in the conformance audit) -- its beam trajectory is fixed by
        # physical installation, not DMX-controllable, so this is a one-time
        # installation-time check, not a per-tick dynamic clamp. Fails closed
        # on undeclared geometry, matching the spec literally: `mount_height_m
        # is None` (never configured in the rig manifest) forces off, same as
        # a declared height below `min_beam_height_m`. Deliberately does NOT
        # check `fda_variance_on_file` -- see `__init__`'s comment on why.
        geometry_unsafe = self.mount_height_m is None or self.mount_height_m < self.min_beam_height_m
        if not laser_enabled or geometry_unsafe:
            for i in range(self.offset, self.offset + self.channel_count):
                uni[i] = 0

    def apply_onset_gate(self, uni: bytearray, flash_active: bool) -> None:
        """docs/14 §3: additive to (not a replacement for) apply_safety above —
        a scene can be armed and eligible (uses_lasers + laser_enable) and the
        laser still only shows through during a real detected onset flash
        window, instead of held on for the whole scene. Deliberately a
        SEPARATE method rather than folded into apply_safety, so the already-
        verified-on-hardware safety-critical arm/disarm path stays untouched."""
        if not flash_active:
            for i in range(self.offset, self.offset + self.channel_count):
                uni[i] = 0

    def visual_state(self, uni: bytes) -> VisualState:
        mode = uni[self.offset + 0]
        active = mode > 41
        # CH12 is color; map coarsely through the same wheel for display.
        r, g, b = color_wheel_to_rgb(uni[self.offset + 11]) if active else (0, 0, 0)
        return VisualState(self.label, self.role, self.side, r, g, b, 1.0 if active else 0.0, 0.5, 0.5, active)


class Par(Fixture):
    """RGB Par — 4CH, VERIFIED ON HARDWARE (real fixture, 2026-08-31) by isolated
    channel probing: 1 Dimmer · 2 Red · 3 Green · 4 Blue. No White channel — a
    5th channel was tested and produced no additional effect. This replaces an
    earlier written-spec guess (R/G/B/W, no dimmer channel at all) that didn't
    match this fixture: color-only with the dimmer at 0 produced nothing, and
    dimmer-only with color at 0 also produced nothing (confirmed both ways) —
    it's a genuine two-part gate like the WashBar's, not a scale-in-software
    model."""

    type_name = "rgb_par"
    channel_count = 4

    def channel_kinds(self) -> list[ChannelKind]:
        return [ChannelKind.DIMMER, ChannelKind.COLOR, ChannelKind.COLOR, ChannelKind.COLOR]

    def boot_defaults(self, buf: Buffer) -> None:
        for ch in range(1, 5):
            self._set(buf, ch, 0)

    def set_color(self, buf: Buffer, r: float, g: float, b: float, w: float = 0.0) -> None:
        # No white channel on this fixture; fold any white intent into R/G/B.
        self._set(buf, 2, _to8(min(1.0, r + w)))
        self._set(buf, 3, _to8(min(1.0, g + w)))
        self._set(buf, 4, _to8(min(1.0, b + w)))

    def set_intensity(self, buf: Buffer, level01: float) -> None:
        self._set(buf, 1, _intensity_to8(level01))  # ch1 dimmer

    def apply_master_brightness(self, uni: bytearray, factor01: float) -> None:
        i = self.offset  # ch1 dimmer
        uni[i] = _clamp8(uni[i] * factor01)

    def apply_color_bias(self, uni: bytearray, bias: float) -> None:
        if bias == 0.0:
            return
        rf, bf = _bias_factors(bias)
        uni[self.offset + 1] = _clamp8(uni[self.offset + 1] * rf)  # R ch2
        uni[self.offset + 3] = _clamp8(uni[self.offset + 3] * bf)  # B ch4

    def visual_state(self, uni: bytes) -> VisualState:
        dim = uni[self.offset + 0] / 255
        r, g, b = (uni[self.offset + k] for k in range(1, 4))
        return VisualState(self.label, self.role, self.side, r, g, b, dim, 0.5, 0.5, dim > 0 and max(r, g, b) > 0)


class WashBar(Fixture):
    """OK-103-288WL Wash Bar — 6CH (docs/04 §3.4).
    1 Master Dimmer · 2 Strobe · 3 Red · 4 Green · 5 Blue · 6 White.

    VERIFIED ON HARDWARE (real fixture, 2026-08-31): this channel layout is
    correct, but note a real physical quirk — R/G/B light a different LED zone
    ("outer") than White ("center"). This is not a true RGBW mixing pixel;
    it's discrete single-color LED clusters along the bar. Mixed colors won't
    blend into one smooth hue the way a Par's RGBW pixel does — worth knowing
    when designing scenes/color logic for this fixture specifically."""

    type_name = "ok103_wash_bar"
    channel_count = 6

    def channel_kinds(self) -> list[ChannelKind]:
        K = ChannelKind
        return [K.DIMMER, K.STROBE, K.COLOR, K.COLOR, K.COLOR, K.COLOR]

    def boot_defaults(self, buf: Buffer) -> None:
        for ch in range(1, 7):
            self._set(buf, ch, 0)

    def set_intensity(self, buf: Buffer, level01: float) -> None:
        self._set(buf, 1, _intensity_to8(level01))

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
