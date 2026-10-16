"""Building blocks of the console (design v2, ui/theme.py).

Everything here runs on the UI thread only and is cheap by construction:
the painted widgets keep their last value and call ``update()`` only when
what they would draw actually changes, so the console's 30 Hz refresh does
not turn into 30 Hz repaints (the show engine and the 40 Hz DMX writer
share the interpreter with this thread). Widgets tinted by the live light
colour take a ``Glow`` (ui/glow.py) and repaint on its ``changed`` signal,
which fires only when the colour moves by a visible step.
"""

from __future__ import annotations

from collections import deque
from functools import lru_cache
from typing import Iterable

from PySide6 import QtCore, QtGui, QtWidgets

from . import icons, theme
from .glow import Glow
from .theme import (
    DANGER, DANGER_INK, DANGER_TEXT, OK, ON_TEXT, SURFACE, SURFACE_2, SURFACE_3, SURFACE_4,
    TEXT, TEXT_2, TEXT_3, WARN, WELL, font,
)

_W = QtGui.QFont.Weight
_TONE_COLORS = {"ok": OK, "bad": DANGER, "warn": WARN, "idle": TEXT_3, "off": TEXT_3}
_ALIGN = QtCore.Qt.AlignmentFlag


_c = theme.qcolor
LINE_C = _c(theme.LINE)
LINE_2_C = _c(theme.LINE_2)
HI_C = _c(theme.HIGHLIGHT)


# --- layout helpers -------------------------------------------------------------

def hbox(*widgets, spacing: int = theme.SP2, margins=(0, 0, 0, 0), stretch_at: int | None = None) -> QtWidgets.QHBoxLayout:
    h = QtWidgets.QHBoxLayout()
    h.setContentsMargins(*margins)
    h.setSpacing(spacing)
    for i, w in enumerate(widgets):
        if stretch_at == i:
            h.addStretch(1)
        if isinstance(w, QtWidgets.QLayout):
            h.addLayout(w)
        else:
            h.addWidget(w)
    if stretch_at == len(widgets):
        h.addStretch(1)
    return h


def label(text: str, role: str | None = None, wrap: bool = False) -> QtWidgets.QLabel:
    lbl = QtWidgets.QLabel(text)
    if role:
        lbl.setObjectName(role)
    lbl.setWordWrap(wrap)
    return lbl


def hair(vertical: bool = False) -> QtWidgets.QFrame:
    f = QtWidgets.QFrame()
    f.setObjectName("vhair" if vertical else "hair")
    return f


def icon_label(name: str, color: str = TEXT_3, size: int = 16) -> QtWidgets.QLabel:
    ic = QtWidgets.QLabel()
    ic.setPixmap(icons.pixmap(name, color, size))
    ic.setFixedSize(size, size)
    return ic


def heading(text: str, icon_name: str | None = None, role: str = "h3", color: str = TEXT_3,
            size: int = 16, spacing: int = theme.SP2) -> QtWidgets.QHBoxLayout:
    """A section heading: a quiet glyph and a title."""
    h = QtWidgets.QHBoxLayout()
    h.setSpacing(spacing)
    if icon_name:
        h.addWidget(icon_label(icon_name, color, size))
    h.addWidget(label(text, role))
    h.addStretch(1)
    return h


def press_target(w: QtWidgets.QWidget) -> QtWidgets.QWidget:
    """A control you click, never one that takes the keyboard: B, Space and
    the arrows must stay the show's shortcuts."""
    w.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
    w.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
    return w


def tile(icon_name: str, tone: str, fill: float = 0.08, edge: float = 0.25,
         lbl: QtWidgets.QLabel | None = None) -> QtWidgets.QLabel:
    """A 36 px icon tile tinted by ``tone`` (restyles ``lbl`` if given)."""
    t = lbl or QtWidgets.QLabel()
    t.setFixedSize(36, 36)
    t.setAlignment(_ALIGN.AlignCenter)
    t.setPixmap(icons.pixmap(icon_name, tone, 19))
    theme.set_css(t, f"background:{theme.rgba(tone, fill)}; border:1px solid {theme.rgba(tone, edge)};"
                     f" border-radius:{theme.R_SM}px;")
    return t


def brand_row(mode: str = "", size: int = 22) -> QtWidgets.QHBoxLayout:
    """The mark, the wordmark and an optional mode badge."""
    h = QtWidgets.QHBoxLayout()
    h.setSpacing(theme.SP2)
    h.addWidget(icon_label("logo", TEXT, size))
    h.addWidget(label("LiveReact", "wordmark"))
    h.addStretch(1)
    if mode:
        h.addWidget(label(mode, "modeBadge"), 0, _ALIGN.AlignVCenter)
    return h


class Card(QtWidgets.QFrame):
    """A panel (14 px radius, hairline, top highlight) with an optional
    title and a right-hand accessory slot; content goes in ``body``."""

    def __init__(self, title: str = "", icon_name: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QtWidgets.QVBoxLayout(self)
        self.body.setContentsMargins(theme.SP5, theme.SP4, theme.SP5, theme.SP5)
        self.body.setSpacing(theme.SP3)
        self._head: QtWidgets.QHBoxLayout | None = None
        if title:
            self._head = heading(title, icon_name, role="cardTitle")
            self.title = self._head.itemAt(self._head.count() - 2).widget()
            self.body.addLayout(self._head)

    def add_accessory(self, w: QtWidgets.QWidget) -> None:
        if self._head is not None:
            w.setSizePolicy(w.sizePolicy().horizontalPolicy(), QtWidgets.QSizePolicy.Policy.Fixed)
            self._head.addWidget(w)


def panel(margins=(0, 0, 0, 0), spacing: int = 0, vertical: bool = True) -> tuple[QtWidgets.QFrame, QtWidgets.QBoxLayout]:
    f = QtWidgets.QFrame()
    f.setObjectName("panel")
    lay = QtWidgets.QVBoxLayout(f) if vertical else QtWidgets.QHBoxLayout(f)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return f, lay


def segmented(names: list[str], parent=None, cls=QtWidgets.QPushButton) -> tuple[
        QtWidgets.QFrame, QtWidgets.QButtonGroup, list[QtWidgets.QAbstractButton]]:
    """A sunk well of exclusive buttons (or radio buttons), the picked one raised."""
    frame = QtWidgets.QFrame(parent)
    frame.setObjectName("seg")
    h = QtWidgets.QHBoxLayout(frame)
    h.setContentsMargins(3, 3, 3, 3)
    h.setSpacing(2)
    group = QtWidgets.QButtonGroup(frame)
    group.setExclusive(True)
    buttons = []
    for n in names:
        b = press_target(cls(n))
        b.setObjectName("segItem")
        b.setCheckable(True)
        group.addButton(b)
        h.addWidget(b, 1)
        buttons.append(b)
    return frame, group, buttons


# --- painting helpers -----------------------------------------------------------

@lru_cache(maxsize=1)
def _keycap_font() -> tuple[QtGui.QFont, QtGui.QFontMetricsF]:
    f = font(11, _W.Medium, mono=True)
    return f, QtGui.QFontMetricsF(f)


def draw_keycap(p: QtGui.QPainter, right: float, cy: float, key: str, lit: bool = False,
                ink: QtGui.QColor | None = None, plate: tuple[str, str] | None = None) -> float:
    """A Raycast-style keycap whose right edge is ``right``; returns its width.
    ``plate`` = (fill, edge) colours for a keycap on a light surface."""
    f, fm = _keycap_font()
    w = max(20.0, fm.horizontalAdvance(key) + 10)
    r = QtCore.QRectF(right - w, cy - 10, w, 20)
    p.save()
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    if plate:
        p.setPen(QtGui.QPen(QtGui.QColor(plate[1]), 1))
        p.setBrush(QtGui.QColor(plate[0]))
        text = ink or QtGui.QColor(TEXT_2)
    elif lit:
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 50), 1))
        p.setBrush(QtGui.QColor(0, 0, 0, 46))
        text = ink or QtGui.QColor(0, 0, 0, 220)
    else:
        g = QtGui.QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0, QtGui.QColor(SURFACE_3))
        g.setColorAt(1, QtGui.QColor(SURFACE_2))
        p.setPen(QtGui.QPen(LINE_2_C, 1))
        p.setBrush(g)
        text = ink or QtGui.QColor(TEXT_2)
    p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 5, 5)
    p.setFont(f)
    p.setPen(text)
    p.drawText(r, _ALIGN.AlignCenter, key)
    p.restore()
    return w


def draw_tinted(p: QtGui.QPainter, name: str, x: float, y: float, size: int, color: QtGui.QColor) -> None:
    """An icon in an arbitrary colour (the glow): the white pixmap recoloured
    with SourceIn, kept in a small cache so a repaint doesn't allocate."""
    p.drawImage(QtCore.QPointF(x, y), _tinted(name, size, color.rgba()))


@lru_cache(maxsize=96)
def _tinted(name: str, size: int, rgba: int) -> QtGui.QImage:
    color = QtGui.QColor.fromRgba(rgba)
    src = icons.pixmap(name, "#FFFFFF", size)
    img = QtGui.QImage(src.size(), QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(src.devicePixelRatio())
    img.fill(QtCore.Qt.GlobalColor.transparent)
    ip = QtGui.QPainter(img)
    ip.drawPixmap(0, 0, src)
    ip.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceIn)
    ip.fillRect(img.rect(), color)
    ip.end()
    return img


def draw_switch(p: QtGui.QPainter, r: QtCore.QRectF, on: bool, enabled: bool = True) -> None:
    """The 34x20 switch: graphite off, white on."""
    p.save()
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    p.setPen(QtGui.QPen(LINE_2_C if not on else QtGui.QColor(TEXT), 1))
    p.setBrush(QtGui.QColor(TEXT if on else SURFACE_3))
    if not enabled:
        p.setOpacity(0.4)
    p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), r.height() / 2, r.height() / 2)
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor(ON_TEXT if on else TEXT_2))
    kx = r.right() - 10 if on else r.left() + 10
    p.drawEllipse(QtCore.QPointF(kx, r.center().y()), 7, 7)
    p.restore()


# --- status ---------------------------------------------------------------------

class Dot(QtWidgets.QWidget):
    """A status dot with a soft ring: ``ok`` / ``warn`` / ``bad`` / ``off``."""

    def __init__(self, tone: str = "off", parent=None) -> None:
        super().__init__(parent)
        self._tone = tone
        self.setFixedSize(13, 13)

    def set_tone(self, tone: str) -> None:
        if tone != self._tone:
            self._tone = tone
            self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        c = QtGui.QColor(_TONE_COLORS.get(self._tone, TEXT_3))
        mid = QtCore.QPointF(6.5, 6.5)
        if self._tone != "off":
            ring = QtGui.QColor(c)
            ring.setAlphaF(0.16)
            p.setBrush(ring)
            p.drawEllipse(mid, 6.5, 6.5)
        p.setBrush(c)
        p.drawEllipse(mid, 3.5, 3.5)


class StatusLine(QtWidgets.QWidget):
    """A quiet dot and a plain-language status ("Hearing the music")."""

    def __init__(self, text: str = "", tone: str = "off", role: str = "body2", parent=None) -> None:
        super().__init__(parent)
        self.dot = Dot(tone)
        self.text = label(text, role)
        h = QtWidgets.QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(theme.SP2)
        h.addWidget(self.dot, 0, _ALIGN.AlignVCenter)
        h.addWidget(self.text)

    def set(self, text: str, tone: str) -> None:
        if self.text.text() != text:
            self.text.setText(text)
        self.dot.set_tone(tone)


class StatusPill(QtWidgets.QWidget):
    """A row of ``dot Label`` segments (the technical link dots in Under the
    hood). ``set`` takes the segment index; nothing repaints unless a tone
    changed."""

    def __init__(self, segments: Iterable[tuple[str, str]], parent=None) -> None:
        super().__init__(parent)
        self._segs: list[list] = [[lbl, "", tone] for lbl, tone in segments]   # [label, (unused), tone]
        self._f = font(12, _W.Medium)
        self._fm = QtGui.QFontMetrics(self._f)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)

    def set(self, i: int, tone: str) -> None:
        if self._segs[i][2] != tone:
            self._segs[i][2] = tone
            self.update()

    def _seg_width(self, text: str) -> int:
        return 13 + self._fm.horizontalAdvance(text) + 14

    def sizeHint(self) -> QtCore.QSize:  # noqa: N802
        return QtCore.QSize(sum(self._seg_width(s[0]) for s in self._segs), 22)

    def minimumSizeHint(self) -> QtCore.QSize:  # noqa: N802
        return self.sizeHint()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setFont(self._f)
        cy = self.height() / 2
        x = 0.0
        for text, _v, tone in self._segs:
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor(_TONE_COLORS.get(tone, TEXT_3)))
            p.drawEllipse(QtCore.QPointF(x + 4, cy), 3.2, 3.2)
            p.setPen(QtGui.QColor(TEXT_2))
            p.drawText(QtCore.QPointF(x + 13, cy + self._fm.capHeight() / 2), text)
            x += self._seg_width(text)


class OnAirChip(QtWidgets.QWidget):
    """"Live 1:42:08": the one loud status. Red with a slow ring on a live
    show; graphite in demo, which is never called live."""

    def __init__(self, live: bool, parent=None) -> None:
        super().__init__(parent)
        self.live = live
        self._clock = "0:00:00"
        self._f = font(13, _W.DemiBold)
        self._f_clock = font(13, _W.Medium)
        self.setFixedHeight(28)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)

    def word(self) -> str:
        return "Live" if self.live else "Demo"

    def set_clock(self, text: str) -> None:
        if text != self._clock:
            self._clock = text
            self.update()

    def sizeHint(self) -> QtCore.QSize:  # noqa: N802
        fm, fc = QtGui.QFontMetrics(self._f), QtGui.QFontMetrics(self._f_clock)
        return QtCore.QSize(9 + 8 + 8 + fm.horizontalAdvance(self.word()) + 8 + fc.horizontalAdvance("0:00:00") + 10, 28)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.live:
            p.setPen(QtGui.QPen(_c(DANGER, 0.30), 1))
            p.setBrush(_c(DANGER, 0.10))
        else:
            p.setPen(QtGui.QPen(LINE_2_C, 1))
            p.setBrush(QtGui.QColor(SURFACE_2))
        p.drawRoundedRect(r, theme.R_XS, theme.R_XS)
        cy = r.center().y()
        dot = QtGui.QColor(DANGER if self.live else TEXT_3)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(dot)
        p.drawEllipse(QtCore.QPointF(13, cy), 4, 4)
        if self.live:
            p.setPen(QtGui.QPen(_c(DANGER, 0.45), 1.5))
            p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            p.drawEllipse(QtCore.QPointF(13, cy), 7.5, 7.5)
        fm = QtGui.QFontMetrics(self._f)
        x = 25.0
        p.setFont(self._f)
        p.setPen(QtGui.QColor(DANGER_TEXT if self.live else TEXT_2))
        p.drawText(QtCore.QPointF(x, cy + fm.capHeight() / 2), self.word())
        x += fm.horizontalAdvance(self.word()) + 8
        p.setFont(self._f_clock)
        p.setPen(QtGui.QColor(TEXT))
        p.drawText(QtCore.QPointF(x, cy + fm.capHeight() / 2), self._clock)


# --- meters ---------------------------------------------------------------------

class Meter(QtWidgets.QWidget):
    """A segmented LED meter, 0..100 (QProgressBar-compatible ``setValue`` /
    ``value``): lit segments in the glow, the top ones white-hot. Repaints
    only when the number of lit segments changes."""

    SEGMENTS = 16

    def __init__(self, glow: Glow | None = None, height: int = 8, parent=None) -> None:
        super().__init__(parent)
        self._v = 0
        self._lit = 0
        self.glow = glow
        self.setFixedHeight(height)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        if glow is not None:
            glow.changed.connect(self._glow_changed)

    def _glow_changed(self) -> None:
        if self._lit:
            self.update()

    def setValue(self, v: int) -> None:  # noqa: N802 (QProgressBar API)
        self._v = max(0, min(100, int(v)))
        lit = round(self._v * self.SEGMENTS / 100)
        if lit != self._lit:
            self._lit = lit
            self.update()

    def value(self) -> int:
        return self._v

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        n, gap = self.SEGMENTS, 2.0
        w = (self.width() - gap * (n - 1)) / n
        on = self.glow.color() if self.glow is not None else QtGui.QColor(TEXT_2)
        hot, off = QtGui.QColor("#FFFFFF"), QtGui.QColor(SURFACE_3)
        for i in range(n):
            p.setBrush((hot if i >= n - 3 else on) if i < self._lit else off)
            p.drawRoundedRect(QtCore.QRectF(i * (w + gap), 0, w, self.height()), 1.5, 1.5)


class BeatLeds(QtWidgets.QWidget):
    """Four beat lights: the current beat lit in the glow, beat one white."""

    def __init__(self, glow: Glow, parent=None) -> None:
        super().__init__(parent)
        self.glow = glow
        self._beat = 0                       # 1..4 lit, 0 = none
        self.setFixedSize(4 * 18 + 3 * 4, 12)
        glow.changed.connect(self._glow_changed)

    def _glow_changed(self) -> None:
        if self._beat > 1:
            self.update()

    def set_beat(self, beat: int) -> None:
        if beat != self._beat:
            self._beat = beat
            self.update()

    def beat(self) -> int:
        return self._beat

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        for i in range(4):
            r = QtCore.QRectF(i * 22, 3.5, 18, 5)
            if i + 1 == self._beat:
                c = QtGui.QColor("#FFFFFF") if i == 0 else self.glow.color()
                halo = QtGui.QColor(c)
                halo.setAlphaF(0.35)
                p.setBrush(halo)
                p.drawRoundedRect(r.adjusted(-2, -3, 2, 3), 4, 4)
                p.setBrush(c)
            else:
                p.setBrush(QtGui.QColor(SURFACE_3))
            p.drawRoundedRect(r, 2, 2)


# Section names as the deck says them.
SECTION_NAMES = {"break": "Break", "build": "Build", "drop": "Drop", "peak": "Peak", "outro": "Outro"}


class SectionStrip(QtWidgets.QWidget):
    """The last couple of minutes of the set as sections, with the energy
    curve and "now" at the right edge. Real history only: the XDJ sends no
    track position, so this never pretends to know where the track ends.
    Sampled at 4 Hz by the console's refresh; repaints at that rate."""

    WINDOW_S = 120.0
    SAMPLE_S = 0.25

    def __init__(self, glow: Glow, parent=None) -> None:
        super().__init__(parent)
        self.glow = glow
        self._samples: deque[tuple[float, str, float]] = deque(maxlen=int(self.WINDOW_S / self.SAMPLE_S) + 2)
        self._last = -1e9
        self._f = font(11.5, _W.Medium)
        self.setMinimumHeight(66)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)

    def add(self, t: float, section: str, energy: float) -> bool:
        if t - self._last < self.SAMPLE_S:
            return False
        self._last = t
        self._samples.append((t, section, max(0.0, min(1.0, energy))))
        self.update()
        return True

    def current_run(self) -> tuple[str, float]:
        """(section, seconds in it) for the caption."""
        if not self._samples:
            return "", 0.0
        t_now, sec, _ = self._samples[-1]
        start = t_now
        for t, s, _e in reversed(self._samples):
            if s != sec:
                break
            start = t
        return sec, t_now - start

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        W, H = float(self.width()), float(self.height())
        top = 16.0
        bh = H - top
        glow = self.glow.color()
        # an empty well where there is no history yet
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor(255, 255, 255, 6))
        p.drawRoundedRect(QtCore.QRectF(0, top, W, bh), 4, 4)
        if not self._samples:
            return
        t_now = self._samples[-1][0]
        X = lambda t: W - (t_now - t) / self.WINDOW_S * W  # noqa: E731
        runs: list[list] = []                # [section, t0, t1, energy sum, n]
        for t, s, e in self._samples:
            if runs and runs[-1][0] == s:
                runs[-1][2] = t; runs[-1][3] += e; runs[-1][4] += 1
            else:
                if runs:
                    runs[-1][2] = t
                runs.append([s, t, t, e, 1])
        p.setFont(self._f)
        fm = QtGui.QFontMetricsF(self._f)
        for i, (s, t0, t1, esum, n) in enumerate(runs):
            x0, x1 = max(0.0, X(t0)), X(t1 if i < len(runs) - 1 else t_now)
            if x1 - x0 < 1:
                continue
            cur = i == len(runs) - 1
            c = QtGui.QColor(glow)
            c.setAlphaF(min(1.0, (0.08 + 0.3 * esum / n) * (1.5 if cur else 0.8)))
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(QtCore.QRectF(x0 + 1, top, max(1.0, x1 - x0 - 2), bh), 4, 4)
            name = SECTION_NAMES.get(s, s.title())
            if fm.horizontalAdvance(name) < x1 - x0 - 6:
                p.setPen(QtGui.QColor(TEXT if cur else TEXT_3))
                p.drawText(QtCore.QPointF(x0 + 3, fm.ascent()), name)
        ey = lambda e: top + bh - (e * 0.86 + 0.06) * bh  # noqa: E731
        path = QtGui.QPainterPath()
        for k, (t, _s, e) in enumerate(self._samples):
            pt = QtCore.QPointF(X(t), ey(e))
            if k == 0:
                path.moveTo(pt)
            else:
                path.lineTo(pt)
        pen = QtGui.QPen(glow, 2)
        pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        # now
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor("#FFFFFF"))
        p.drawRect(QtCore.QRectF(W - 1.5, top - 2, 1.5, bh + 2))
        p.drawEllipse(QtCore.QPointF(W - 4, ey(self._samples[-1][2])), 3.5, 3.5)


# --- controls -------------------------------------------------------------------

class CueButton(QtWidgets.QPushButton):
    """A performance pad: title top-left, glyph bottom-left, keycap
    bottom-right. Lit in the glow while checked or while ``set_lit`` says
    the thing it started is still running (a held build, an armed drop).
    The plain ``text()`` stays set for accessibility and tests."""

    def __init__(self, title: str, key: str = "", icon_name: str | None = None,
                 role: str = "cue", checkable: bool = False, variant: str = "", glow: Glow | None = None,
                 parent=None) -> None:
        super().__init__(title, parent)
        self.setObjectName(role)
        if variant:
            self.setProperty("variant", variant)
        self.setCheckable(checkable)
        self._title = title
        self._key = key
        self._icon_name = icon_name
        self._lit = False
        self.glow = glow
        self._f_title = font(12.5, _W.DemiBold)
        press_target(self)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        self.setAccessibleName(f"{title} ({key})" if key else title)   # height: QPushButton#cue in theme.py
        if glow is not None:
            glow.changed.connect(self._glow_changed)

    def _glow_changed(self) -> None:
        if self.lit():
            self.update()

    def lit(self) -> bool:
        return self.isChecked() or self._lit

    def set_lit(self, on: bool) -> None:
        if on != self._lit:
            self._lit = on
            self.update()

    def sizeHint(self) -> QtCore.QSize:  # noqa: N802
        return QtCore.QSize(120, 64)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        down = self.isDown()
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -2.5 if not down else -0.5)
        if down:
            r.translate(0, 2)
        lit = self.lit()
        if lit:
            g = self.glow.color() if self.glow is not None else QtGui.QColor(TEXT)
            halo = QtGui.QColor(g)
            halo.setAlphaF(0.22)
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(halo)
            p.drawRoundedRect(r.adjusted(-0.5, -0.5, 0.5, 2.5), theme.R_SM + 1, theme.R_SM + 1)
            fill = QtGui.QColor(g)
            fill.setAlphaF(0.92)
            # a white edge: "lit" reads even when the glow itself is dim
            p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 210), 1.5))
            p.setBrush(fill)
            ink = self.glow.ink() if self.glow is not None else QtGui.QColor(ON_TEXT)
        else:
            if not down:   # the pad's lip
                p.setPen(QtCore.Qt.PenStyle.NoPen)
                p.setBrush(QtGui.QColor(0, 0, 0, 115))
                p.drawRoundedRect(r.translated(0, 2), theme.R_SM, theme.R_SM)
            g = QtGui.QLinearGradient(r.topLeft(), r.bottomLeft())
            hover = self.underMouse() and self.isEnabled()
            g.setColorAt(0, QtGui.QColor(SURFACE_4 if hover else SURFACE_3))
            g.setColorAt(1, QtGui.QColor(SURFACE_3 if hover else SURFACE_2))
            p.setPen(QtGui.QPen(LINE_2_C, 1))
            p.setBrush(g)
            ink = QtGui.QColor(TEXT if self.isEnabled() else TEXT_3)
        p.drawRoundedRect(r, theme.R_SM, theme.R_SM)
        if not lit:
            p.setPen(QtGui.QPen(HI_C, 1))
            p.drawLine(QtCore.QPointF(r.left() + 8, r.top() + 1), QtCore.QPointF(r.right() - 8, r.top() + 1))
        inner = r.adjusted(10, 9, -10, -9)
        p.setFont(self._f_title)
        p.setPen(ink)
        p.drawText(inner, int(_ALIGN.AlignLeft | _ALIGN.AlignTop | QtCore.Qt.TextFlag.TextWordWrap), self._title)
        sub = QtGui.QColor(ink)
        sub.setAlphaF(0.85 if lit else 1.0)
        if self._icon_name:
            draw_tinted(p, self._icon_name, inner.left(), inner.bottom() - 16, 16,
                        sub if lit else QtGui.QColor(TEXT_3))
        if self._key:
            draw_keycap(p, inner.right(), inner.bottom() - 9, self._key, lit=lit, ink=sub if lit else None)


class BlackoutKey(QtWidgets.QPushButton):
    """The big red key. Pressed (checked): white, "Lights off"."""

    def __init__(self, parent=None) -> None:
        super().__init__("Blackout", parent)
        self.setObjectName("blackout")
        self.setCheckable(True)
        press_target(self)                   # height: QPushButton#blackout in theme.py
        self.setAccessibleName("Blackout (B)")
        self._f_title = font(20, _W.DemiBold, display=True)
        self._f_sub = font(12.5)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.isDown():
            r.translate(0, 1)
        on = self.isChecked()
        if on:
            p.setPen(QtGui.QPen(QtGui.QColor(TEXT), 1))
            p.setBrush(QtGui.QColor(TEXT))
        else:
            g = QtGui.QLinearGradient(r.topLeft(), r.bottomLeft())
            hover = 0.06 if self.underMouse() else 0.0
            g.setColorAt(0, _c(DANGER, 0.16 + hover))
            g.setColorAt(1, _c(DANGER, 0.08 + hover))
            p.setPen(QtGui.QPen(_c(DANGER, 0.40), 1))
            p.setBrush(g)
        p.drawRoundedRect(r, theme.R_MD, theme.R_MD)
        # the key glyph
        k = QtCore.QRectF(r.left() + 18, r.center().y() - 20, 40, 40)
        if not on:
            halo = QtGui.QRadialGradient(k.center(), 34)
            halo.setColorAt(0, _c(DANGER, 0.40))
            halo.setColorAt(1, _c(DANGER, 0.0))
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(halo)
            p.drawEllipse(k.center(), 34, 34)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor(ON_TEXT if on else DANGER))
        p.drawRoundedRect(k, theme.R_SM, theme.R_SM)
        draw_tinted(p, "power", k.left() + 10, k.top() + 10, 20, QtGui.QColor(TEXT if on else DANGER_INK))
        # words
        tx = k.right() + 14
        ink = QtGui.QColor(ON_TEXT if on else TEXT)
        p.setFont(self._f_title)
        p.setPen(ink)
        fm = QtGui.QFontMetricsF(self._f_title)
        p.drawText(QtCore.QPointF(tx, r.center().y() - 2), "Lights off" if on else "Blackout")
        p.setFont(self._f_sub)
        p.setPen(QtGui.QColor("#3A3D44" if on else TEXT_2))
        p.drawText(QtCore.QPointF(tx, r.center().y() + fm.descent() + 12),
                   "Press again to bring them back" if on else "All lights off, instantly")
        draw_keycap(p, r.right() - 18, r.center().y(), "B", ink=QtGui.QColor("#3A3D44") if on else None,
                    plate=("#D5D7DB", "#C2C5CA") if on else None)


class GlowFader(QtWidgets.QSlider):
    """A fader in a sunk well with ticks; the fill is the live light colour
    (or graphite for a bipolar / mono fader). Mouse behaviour is QSlider's
    own. The wheel is ignored, so scrolling the page never moves a fader."""

    def __init__(self, lo: int, hi: int, value: int, glow: Glow | None = None,
                 small: bool = False, mono: bool = False, parent=None) -> None:
        super().__init__(QtCore.Qt.Orientation.Horizontal, parent)
        self.setObjectName("glowFaderSm" if small else "glowFader")
        self.setRange(lo, hi)
        self.setValue(value)
        self.setPageStep(10)
        self.glow = glow
        self.small = small
        self.mono = mono
        press_target(self)                   # height: QSlider#glowFader(Sm) in theme.py
        if glow is not None and not mono:
            glow.changed.connect(self.update)

    def wheelEvent(self, e) -> None:  # noqa: N802
        e.ignore()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rad = 7 if self.small else theme.R_SM
        p.setPen(QtGui.QPen(LINE_C, 1))
        p.setBrush(QtGui.QColor(WELL))
        p.drawRoundedRect(r, rad, rad)
        span = self.maximum() - self.minimum() or 1
        frac = (self.value() - self.minimum()) / span
        x = r.left() + frac * r.width()
        clip = QtGui.QPainterPath()
        clip.addRoundedRect(r, rad, rad)
        p.save()
        p.setClipPath(clip)
        if self.mono or self.glow is None:
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor(TEXT_2))
            if self.minimum() < 0:       # bipolar: fill from the centre
                cx = r.left() + (-self.minimum() / span) * r.width()
                p.drawRect(QtCore.QRectF(min(cx, x), r.top(), abs(x - cx), r.height()))
            else:
                p.drawRect(QtCore.QRectF(r.left(), r.top(), x - r.left(), r.height()))
        else:
            g = self.glow.color()
            grad = QtGui.QLinearGradient(r.left(), 0, max(r.left() + 1, x), 0)
            a, b = QtGui.QColor(g), QtGui.QColor(g)
            a.setAlphaF(0.85)
            b.setAlphaF(0.55)
            grad.setColorAt(0, a)
            grad.setColorAt(1, b)
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawRect(QtCore.QRectF(r.left(), r.top(), x - r.left(), r.height()))
        # ticks every 10 %
        p.setPen(QtGui.QPen(LINE_2_C, 1))
        for i in range(1, 10):
            tx = round(r.left() + r.width() * i / 10) + 0.5
            p.drawLine(QtCore.QPointF(tx, r.top() + 1), QtCore.QPointF(tx, r.bottom() - 1))
        p.restore()
        # thumb
        th = 14 if self.small else 28
        tr = QtCore.QRectF(min(max(x - 2, r.left() + 3), r.right() - 7), r.center().y() - th / 2, 4, th)
        if not self.mono and self.glow is not None:
            halo = self.glow.color()
            halo.setAlphaF(0.5)
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(halo)
            p.drawRoundedRect(tr.adjusted(-4, -2, 4, 2), 4, 4)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 90), 3))
        p.setBrush(QtGui.QColor("#FFFFFF"))
        p.drawRoundedRect(tr, 2, 2)


class ToggleRow(QtWidgets.QCheckBox):
    """A switch row: bold title, a quiet line under it, an optional keycap,
    the switch on the right. Still a QCheckBox (toggle / toggled / isChecked).
    ``before_on`` may veto a click that would turn it on (a confirmation
    sheet runs it later); programmatic ``toggle`` / ``setChecked`` are not
    vetoed."""

    def __init__(self, title: str, sub: str = "", key: str = "", compact: bool = False, parent=None) -> None:
        super().__init__(title, parent)
        self.setObjectName("toggleRow")
        self._title = title
        self._sub = sub
        self._key = key
        self.compact = compact
        self.before_on = None
        self._f_title = font(13 if compact else 14, _W.DemiBold)
        self._f_sub = font(12 if compact else 12.5)
        press_target(self)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)

    def nextCheckState(self) -> None:  # noqa: N802 (Qt override: clicks only)
        if not self.isChecked() and self.before_on is not None and not self.before_on():
            return
        super().nextCheckState()

    def hitButton(self, _pos) -> bool:  # noqa: N802
        return True

    def _text_width(self, w: int | None = None) -> int:
        return max(80, (self.width() if w is None else w) - 34 - 12 - (32 if self._key else 0))

    def sizeHint(self) -> QtCore.QSize:  # noqa: N802
        return QtCore.QSize(240, self.heightForWidth(240))

    def minimumSizeHint(self) -> QtCore.QSize:  # noqa: N802
        return QtCore.QSize(160, self.heightForWidth(max(160, self.width())))

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, w: int) -> int:  # noqa: N802
        tw = self._text_width(w)
        h = QtGui.QFontMetrics(self._f_title).height()
        if self._sub:
            h += 2 + QtGui.QFontMetrics(self._f_sub).boundingRect(
                QtCore.QRect(0, 0, tw, 1000), int(QtCore.Qt.TextFlag.TextWordWrap), self._sub).height()
        return max(24, h + (4 if self.compact else 6))

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        tw = self._text_width()
        fm = QtGui.QFontMetrics(self._f_title)
        p.setFont(self._f_title)
        p.setPen(QtGui.QColor(TEXT if self.isEnabled() else TEXT_3))
        p.drawText(QtCore.QRectF(0, 1, tw, fm.height()), int(_ALIGN.AlignLeft | _ALIGN.AlignVCenter), self._title)
        if self._sub:
            p.setFont(self._f_sub)
            p.setPen(QtGui.QColor(TEXT_2 if not self.compact else TEXT_3))
            p.drawText(QtCore.QRectF(0, fm.height() + 3, tw, 400),
                       int(_ALIGN.AlignLeft | _ALIGN.AlignTop | QtCore.Qt.TextFlag.TextWordWrap), self._sub)
        cy = 1 + fm.height() / 2 if self._sub else self.height() / 2
        sw = QtCore.QRectF(self.width() - 34, cy - 10, 34, 20)
        draw_switch(p, sw, self.isChecked(), self.isEnabled())
        if self._key:
            draw_keycap(p, sw.left() - 10, cy, self._key)


class NavButton(QtWidgets.QAbstractButton):
    """A 32 px sidebar row. The open page's row is lit (raised step,
    hairline, highlight) and its glyph takes the live light colour; the
    label stays neutral."""

    def __init__(self, text: str, icon_name: str, glow: Glow, parent=None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setObjectName("nav")
        self.setCheckable(True)
        press_target(self)
        self.setFixedHeight(32)
        self.icon_name = icon_name
        self.glow = glow
        self.badge = ""                     # e.g. "On" next to Live during a live show
        self._f = font(13, _W.Medium)
        self._f_on = font(13, _W.DemiBold)
        self._f_badge = font(11, _W.DemiBold)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_Hover)
        glow.changed.connect(self._glow_changed)

    def _glow_changed(self) -> None:
        if self.isChecked():
            self.update()

    def set_badge(self, text: str) -> None:
        if text != self.badge:
            self.badge = text
            self.update()

    def sizeHint(self) -> QtCore.QSize:  # noqa: N802
        return QtCore.QSize(200, 32)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        on = self.isChecked()
        if on:
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor(0, 0, 0, 100))
            p.drawRoundedRect(r.translated(0, 1), 8, 8)
            p.setPen(QtGui.QPen(LINE_C, 1))
            p.setBrush(QtGui.QColor(SURFACE_2))
            p.drawRoundedRect(r, 8, 8)
            p.setPen(QtGui.QPen(HI_C, 1))
            p.drawLine(QtCore.QPointF(r.left() + 6, r.top() + 1), QtCore.QPointF(r.right() - 6, r.top() + 1))
        elif self.underMouse():
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor(255, 255, 255, 10))
            p.drawRoundedRect(r, 8, 8)
        glyph = self.glow.color() if on else QtGui.QColor(TEXT if self.underMouse() else TEXT_2)
        draw_tinted(p, self.icon_name, 11, (self.height() - 17) / 2, 17, glyph)
        p.setFont(self._f_on if on else self._f)
        p.setPen(QtGui.QColor(TEXT if on or self.underMouse() else TEXT_2))
        p.drawText(QtCore.QRectF(38, 0, r.width() - 80, self.height()),
                   int(_ALIGN.AlignLeft | _ALIGN.AlignVCenter), self.text())
        if self.badge:
            p.setFont(self._f_badge)
            fm = QtGui.QFontMetrics(self._f_badge)
            bw = fm.horizontalAdvance(self.badge)
            x = r.right() - 10 - bw
            p.setPen(QtGui.QColor(DANGER_TEXT))
            p.drawText(QtCore.QPointF(x, self.height() / 2 + fm.capHeight() / 2), self.badge)
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor(DANGER))
            p.drawEllipse(QtCore.QPointF(x - 8, self.height() / 2), 3, 3)


class ProSwitch(QtWidgets.QAbstractButton):
    """"Pro controls" and its switch, in the live bar."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setText("Pro controls")
        self.setObjectName("proSwitch")
        self.setCheckable(True)
        press_target(self)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_Hover)
        self._f = font(13, _W.DemiBold)
        self.setFixedHeight(34)
        self.setAccessibleName("Pro controls")

    def sizeHint(self) -> QtCore.QSize:  # noqa: N802
        return QtCore.QSize(12 + 16 + 10 + QtGui.QFontMetrics(self._f).horizontalAdvance(self.text()) + 10 + 34 + 8, 34)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QtGui.QPen(LINE_2_C, 1))
        p.setBrush(QtGui.QColor(SURFACE_2 if self.underMouse() else SURFACE))
        p.drawRoundedRect(r, theme.R_SM, theme.R_SM)
        draw_tinted(p, "sliders", 12, (self.height() - 16) / 2, 16, QtGui.QColor(TEXT))
        p.setFont(self._f)
        p.setPen(QtGui.QColor(TEXT))
        p.drawText(QtCore.QRectF(38, 0, r.width(), self.height()), int(_ALIGN.AlignLeft | _ALIGN.AlignVCenter), self.text())
        draw_switch(p, QtCore.QRectF(r.right() - 8 - 34, r.center().y() - 10, 34, 20), self.isChecked())


class VenueTile(QtWidgets.QWidget):
    """The sidebar's venue tile: a dark well lit from below by the glow."""

    def __init__(self, glow: Glow, parent=None) -> None:
        super().__init__(parent)
        self.glow = glow
        self.setFixedSize(32, 32)
        glow.changed.connect(self.update)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QtGui.QPainterPath()
        path.addRoundedRect(r, 8, 8)
        p.setClipPath(path)
        p.fillRect(r, QtGui.QColor(WELL))
        g = QtGui.QRadialGradient(QtCore.QPointF(r.center().x(), r.bottom() + r.height() * 0.2), r.width() * 0.75)
        c0 = self.glow.color(0.9)
        c1 = self.glow.color(0.0)
        g.setColorAt(0, c0)
        g.setColorAt(1, c1)
        p.fillRect(r, g)
        p.setClipping(False)
        p.setPen(QtGui.QPen(LINE_2_C, 1))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 8, 8)


class Sheet(QtWidgets.QWidget):
    """A confirmation sheet over part of the window (not a modal dialog).

    It covers its parent with a scrim and asks, leaving a hole over
    ``keep_clear`` (the rack with the Blackout key, which stays reachable).
    Every button in it is NoFocus, so B, Space and the other show keys keep
    doing what they do while it is up. "Not now", a click outside it, or Esc (the
    window's ``keyPressEvent``) closes it. The confirm button is
    off until every check is ticked."""

    def __init__(self, parent: QtWidgets.QWidget, keep_clear=None) -> None:
        super().__init__(parent)
        self.setObjectName("sheetScrim")
        self.keep_clear = keep_clear or QtCore.QRect     # parent coords; an empty rect = cover it all
        parent.installEventFilter(self)                 # follow the parent's size
        self.hide()
        self._on_ok = None
        self.card = QtWidgets.QFrame(self)
        self.card.setObjectName("sheet")
        self.card.setFixedWidth(460)
        v = QtWidgets.QVBoxLayout(self.card)
        v.setContentsMargins(24, 24, 24, 24)
        v.setSpacing(14)
        self.tile = QtWidgets.QLabel()
        v.addWidget(self.tile)
        self.title = label("", "sheetTitle")
        v.addWidget(self.title)
        self.body = label("", "sheetBody", wrap=True)
        v.addWidget(self.body)
        self.checks_box = QtWidgets.QVBoxLayout()
        self.checks_box.setSpacing(8)
        v.addLayout(self.checks_box)
        self.checks: list[QtWidgets.QCheckBox] = []
        self.b_no = QtWidgets.QPushButton("Not now")
        self.b_no.setObjectName("ghost")
        self.b_ok = QtWidgets.QPushButton("Continue")
        for b in (self.b_no, self.b_ok):
            press_target(b)
        v.addSpacing(4)
        v.addLayout(hbox(self.b_no, self.b_ok, stretch_at=0))
        self.b_no.clicked.connect(self.close_sheet)
        self.b_ok.clicked.connect(self._confirm)

    def ask(self, title: str, body: str, checks: list[str], ok: str, on_ok, icon_name: str = "alert",
            danger: bool = False) -> None:
        self.title.setText(title)
        self.body.setText(body)
        tile(icon_name, DANGER if danger else WARN, 0.10, 0.30, lbl=self.tile)
        for c in self.checks:
            self.checks_box.removeWidget(c)
            c.deleteLater()
        self.checks = []
        for text in checks:
            c = press_target(QtWidgets.QCheckBox(text))
            c.setObjectName("checkLine")
            c.toggled.connect(self._sync)
            self.checks_box.addWidget(c)
            self.checks.append(c)
        self.b_ok.setText(ok)
        self.b_ok.setObjectName("dangerFill" if danger else "primary")
        self.b_ok.style().unpolish(self.b_ok)
        self.b_ok.style().polish(self.b_ok)
        self._on_ok = on_ok
        self._sync()
        self._cover()
        self.show()
        self.raise_()

    def _sync(self, *_a) -> None:
        self.b_ok.setEnabled(all(c.isChecked() for c in self.checks))

    def _confirm(self) -> None:
        on_ok = self._on_ok
        self.close_sheet()
        if on_ok is not None:
            on_ok()

    def close_sheet(self) -> None:
        self._on_ok = None
        self.hide()

    def _cover(self) -> None:
        self.setGeometry(self.parentWidget().rect())
        hole = self.keep_clear()
        self.setMask(QtGui.QRegion(self.rect()).subtracted(QtGui.QRegion(hole)) if hole.isValid()
                     else QtGui.QRegion(self.rect()))
        self._place_card()

    def _place_card(self) -> None:
        """Centred in the part of the page left of the hole."""
        hole = self.keep_clear()
        right = hole.left() - theme.SP2 if hole.isValid() else self.width()
        self.card.adjustSize()
        self.card.move(max(16, (right - self.card.width()) // 2), max(16, (self.height() - self.card.height()) // 2))

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt override)
        if event.type() == QtCore.QEvent.Type.Resize and not self.isHidden():
            self._cover()
        return False

    def resizeEvent(self, _e) -> None:  # noqa: N802
        self._place_card()


    def mousePressEvent(self, e) -> None:  # noqa: N802
        if not self.card.geometry().contains(e.position().toPoint()):
            self.close_sheet()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 158))


class AppHeader(QtWidgets.QFrame):
    """The top bar of the stand-alone windows (fixture test, virtual rig):
    the mark, the wordmark, what this window is, and a right-hand slot."""

    def __init__(self, subtitle: str = "", mode: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("header")
        self.setFixedHeight(56)
        h = QtWidgets.QHBoxLayout(self)
        h.setContentsMargins(theme.SP5, 0, theme.SP4, 0)
        h.setSpacing(theme.SP2)
        brand = brand_row()
        brand.takeAt(brand.count() - 1)      # no stretch here: the subtitle follows
        h.addLayout(brand)
        if subtitle:
            h.addSpacing(6)
            h.addWidget(label(subtitle, "body2"))
        if mode:
            h.addSpacing(4)
            h.addWidget(label(mode, "modeBadge"), 0, _ALIGN.AlignVCenter)
        h.addStretch(1)
        self._right = QtWidgets.QHBoxLayout()
        self._right.setSpacing(theme.SP2)
        h.addLayout(self._right)

    def add_right(self, w: QtWidgets.QWidget) -> None:
        self._right.addWidget(w)


class Footer(QtWidgets.QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("footer")
        self.setFixedHeight(32)
        self.row = QtWidgets.QHBoxLayout(self)
        self.row.setContentsMargins(theme.SP5, 0, theme.SP5, 0)
        self.row.setSpacing(theme.SP4)


def shell(header: QtWidgets.QWidget, body: QtWidgets.QWidget, footer: QtWidgets.QWidget | None = None) -> QtWidgets.QWidget:
    w = QtWidgets.QWidget()
    v = QtWidgets.QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(0)
    v.addWidget(header)
    v.addWidget(body, 1)
    if footer is not None:
        v.addWidget(footer)
    return w
