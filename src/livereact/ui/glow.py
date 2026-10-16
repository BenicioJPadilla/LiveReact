"""The glow: the live light colour that tints the console (design v2).

``GlowSource`` reads the latest DMX universe the show engine published
(core/frame_buffer.py's single slot: one brief lock to read a reference, the
same read the console's refresh does) on a UI-thread QTimer, 15 times a
second (under the 30 fps cap). It averages the colour the fixtures put out,
weighted by brightness, eases toward it, and hands the result to ``Glow``.
How bright the rig is only decides lit or dark, so a beat-pulsing dimmer
doesn't move the glow; ``Glow`` emits ``changed`` only when the colour moves
by a visible step, so the widgets that follow it repaint only while the
hue is actually changing.

Nothing here writes to the show: it is a read of the output, like the floor
plan's beams.
"""

from __future__ import annotations

import time

from PySide6 import QtCore, QtGui

from . import theme

FPS = 15                # the cap is 30; 15 is plenty for a colour that eases
EASE_PER_S = 4.0        # how fast the glow follows the light (the prototype's dt*4)
STEP = 4                # quantum per channel: smaller moves don't repaint anything
DARK_LEVEL = 0.45       # nothing lit: keep the last hue, dimmed
MIN_LUMA = 0.24         # a deep blue rig, or a dark room, still tints the UI visibly
_NEUTRAL = QtGui.QColor(theme.TEXT_3)
_REC709 = (0.2126, 0.7152, 0.0722)


def _luma(rgb) -> float:
    """Rec. 709 luma of gamma-encoded 0..1 values."""
    return sum(k * v for k, v in zip(_REC709, rgb))


def _linear(v: float) -> float:
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


class Glow(QtCore.QObject):
    """The current glow colour. ``changed`` fires when it moves by a step."""

    changed = QtCore.Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._c = QtGui.QColor(_NEUTRAL)

    def color(self, alpha: float = 1.0) -> QtGui.QColor:
        c = QtGui.QColor(self._c)
        if alpha < 1.0:
            c.setAlphaF(max(0.0, alpha))
        return c

    def ink(self) -> QtGui.QColor:
        """Text colour on a glow fill: whichever of near-black and white has
        the higher contrast against it (WCAG relative luminance)."""
        y = _luma(_linear(v) for v in (self._c.redF(), self._c.greenF(), self._c.blueF()))
        on_dark = (y + 0.05) / (0.0051 + 0.05)      # vs #0C0D0F
        on_light = (0.8467 + 0.05) / (y + 0.05)     # vs #EDEEF0
        return QtGui.QColor(theme.ON_TEXT if on_dark >= on_light else theme.TEXT)

    def set_rgb(self, r: int, g: int, b: int) -> bool:
        q = tuple(min(255, int(round(v / STEP)) * STEP) for v in (r, g, b))
        if q == (self._c.red(), self._c.green(), self._c.blue()):
            return False
        self._c = QtGui.QColor(*q)
        self.changed.emit()
        return True


def output_color(rig, uni: bytes) -> tuple[tuple[float, float, float], float] | None:
    """(hue as 0..255 rgb at full value, how lit 0..1) of what the rig puts
    out in ``uni``, or None when nothing is lit."""
    r = g = b = w = lit = 0.0
    for fx in rig.fixtures:
        vs = fx.visual_state(uni)
        if not vs.active or vs.brightness <= 0.02:
            continue
        k = vs.brightness
        r += vs.r * k; g += vs.g * k; b += vs.b * k; w += k
        lit = max(lit, k)
    if w <= 0.0:
        return None
    r, g, b = r / w, g / w, b / w
    peak = max(r, g, b)
    if peak <= 1.0:
        return None
    return (r * 255 / peak, g * 255 / peak, b * 255 / peak), min(1.0, lit)


def lift(rgb: tuple[float, float, float]) -> list[float]:
    """The hue mixed toward white just enough to reach ``MIN_LUMA``."""
    y = _luma(v / 255 for v in rgb)
    if y >= MIN_LUMA:
        return list(rgb)
    t = (MIN_LUMA - y) / (1.0 - y)
    return [v + (255 - v) * t for v in rgb]


class GlowSource(QtCore.QObject):
    """Drives ``glow`` from ``frame_buffer`` on a UI-thread timer."""

    def __init__(self, glow: Glow, rig, frame_buffer, parent=None) -> None:
        super().__init__(parent)
        self.glow = glow
        self.rig = rig
        self.frame_buffer = frame_buffer
        self._rgb = [float(_NEUTRAL.red()), float(_NEUTRAL.green()), float(_NEUTRAL.blue())]
        self._hue = list(self._rgb)
        self._t = time.monotonic()
        self.timer = QtCore.QTimer(self)
        self.timer.setTimerType(QtCore.Qt.TimerType.CoarseTimer)
        self.timer.timeout.connect(self.tick)

    def start(self) -> None:
        self.timer.start(round(1000 / FPS))

    def tick(self) -> None:
        now = time.monotonic()
        dt = min(0.25, now - self._t)
        self._t = now
        uni = self.frame_buffer.latest()
        out = output_color(self.rig, uni) if uni else None
        if out is None:
            level = DARK_LEVEL
        else:
            self._hue = list(out[0])
            level = 1.0
        k = min(1.0, dt * EASE_PER_S)
        for i in range(3):
            self._rgb[i] += (self._hue[i] * level - self._rgb[i]) * k
        self.glow.set_rgb(*lift(self._rgb))
