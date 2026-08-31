"""Reactive Layer — the always-on base of the show (docs/02 FR-2.1, docs/12 Phase 3).

Beat-locked intensity pulses on the washes, BPM-locked symmetric movement on the
moving heads, and frequency-driven color from the two-axis model. This is what
makes the rig feel musical even before scenes and transitions exist; it reads only
the metronome's interpolated clock, never raw packet timing.
"""

from __future__ import annotations

import math

from ..core.show_state import ShowSnapshot
from ..fixtures.profiles import Par, WashBar
from ..fixtures.rig import Rig
from ..merge.merge import Contribution
from .color import two_axis_color

PULSE_TAU = 0.09        # s; exponential decay of the per-beat pulse (~200 ms tail)
PULSE_FLOOR = 0.30      # washes keep this fraction of brightness between beats
STROBE_THRESHOLD = 0.85  # energy above which a gentle reactive strobe engages
STROBE_MAX = 0.30       # conservative cap on the reactive strobe rate (0..1)


class ReactiveLayerEngine:
    """Always-on beat/energy/color reactivity."""

    @property
    def name(self) -> str:
        return "reactive"

    def tick(self, snap: ShowSnapshot, rig: Rig) -> Contribution:
        c = Contribution()
        r, g, b = two_axis_color(snap)
        pulse = self._beat_pulse(snap)
        wash_level = snap.energy * (PULSE_FLOOR + (1.0 - PULSE_FLOOR) * pulse)
        strobe = self._strobe_rate(snap)

        # --- washes: pulse on the beat, hue from the bands ---
        for fx in rig.by_role("wash"):
            if isinstance(fx, (Par, WashBar)):
                # VERIFIED ON HARDWARE: Par has a real dimmer channel, same as
                # WashBar (not "baked into color" as previously assumed — that
                # left the dimmer at 0 and the real fixture never lit).
                fx.set_intensity(c, wash_level)
                fx.set_color(c, r, g, b)
                if strobe > 0 and isinstance(fx, WashBar):  # Par has no strobe channel
                    fx.set_strobe(c, strobe)

        # --- moving heads: steady-ish dimmer, mirrored BPM-locked sweep ---
        position = self._musical_position(snap)
        for fx in rig.by_role("spot"):
            fx.set_intensity(c, snap.energy)
            fx.set_color(c, r, g, b)
            mirror = 1.0 if fx.side == "left" else -1.0
            pan = 0.5 + 0.4 * math.sin(position * 0.4) * mirror
            tilt = 0.45 + 0.15 * math.sin(position * 0.2)
            fx.set_position(c, pan, tilt)

        return c

    # ------------------------------------------------------------------ helpers
    def _beat_pulse(self, snap: ShowSnapshot) -> float:
        """1.0 on the beat, decaying exponentially across it (one peak per beat)."""
        if snap.bpm <= 0:
            return 0.0
        beat_dur = 60.0 / snap.bpm
        t_in_beat = snap.beat_phase * beat_dur
        return math.exp(-t_in_beat / PULSE_TAU)

    def _strobe_rate(self, snap: ShowSnapshot) -> float:
        if snap.energy <= STROBE_THRESHOLD:
            return 0.0
        scaled = (snap.energy - STROBE_THRESHOLD) / (1.0 - STROBE_THRESHOLD)
        return min(STROBE_MAX, scaled * STROBE_MAX)

    def _musical_position(self, snap: ShowSnapshot) -> float:
        """Continuous position in beats, for smooth tempo-locked movement."""
        return snap.bar * 4 + (snap.beat_in_bar - 1) + snap.beat_phase
