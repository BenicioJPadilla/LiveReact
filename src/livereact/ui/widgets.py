"""Building blocks of the console look (ui/theme.py's "Blackbox" system).

Everything here runs on the UI thread only and is cheap by construction:
the painted widgets keep their last value and call ``update()`` only when
what they would draw actually changes, so the console's 30 Hz refresh does
not turn into 30 Hz repaints (the show engine and the 40 Hz DMX writer
share the interpreter with this thread).
"""

from __future__ import annotations

from typing import Iterable

from PySide6 import QtCore, QtGui, QtWidgets

from . import icons, theme
from .theme import (
    ACCENT, DANGER, LINE_2, LINE_3, ON_ACCENT, SURFACE, SURFACE_2, SURFACE_4,
    TEXT, TEXT_2, TEXT_3, WARN, font,
)

_W = QtGui.QFont.Weight
_TONE_COLORS = {"ok": ACCENT, "bad": DANGER, "warn": WARN, "idle": TEXT_3}


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


def overline(text: str) -> QtWidgets.QLabel:
    return label(text.upper(), "overline")


class Card(QtWidgets.QFrame):
    """A rounded surface with an optional overline title and a right-hand
    accessory slot (``add_accessory``); content goes in ``body``."""

    def __init__(self, title: str = "", icon_name: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QtWidgets.QVBoxLayout(self)
        self.body.setContentsMargins(theme.SP4, theme.SP4 - 2, theme.SP4, theme.SP4)
        self.body.setSpacing(theme.SP3)
        self._head: QtWidgets.QHBoxLayout | None = None
        if title:
            self._head = QtWidgets.QHBoxLayout()
            self._head.setSpacing(theme.SP2)
            if icon_name:
                ic = QtWidgets.QLabel()
                ic.setPixmap(icons.pixmap(icon_name, TEXT_3, 14))
                self._head.addWidget(ic)
            self.title = label(title.upper(), "cardTitle")
            self.title.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Fixed)
            self._head.addWidget(self.title)
            self._head.addStretch(1)
            self.body.addLayout(self._head)

    def add_accessory(self, w: QtWidgets.QWidget) -> None:
        if self._head is not None:
            w.setSizePolicy(w.sizePolicy().horizontalPolicy(), QtWidgets.QSizePolicy.Policy.Fixed)
            self._head.addWidget(w)

    def cap_height(self) -> None:
        """Never grow past what the content can use: spare height then
        goes to the surrounding layout instead of opening gaps in the card."""
        self.body.setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetMinAndMaxSize)


class StatusPill(QtWidgets.QWidget):
    """A capsule of one or more ``● Label [value]`` segments. ``set`` takes
    the segment index; nothing repaints unless a segment changed."""

    def __init__(self, segments: Iterable[tuple[str, str]], mono_value: bool = False, parent=None) -> None:
        super().__init__(parent)
        # each segment: [label, value, tone, colour override]
        self._segs: list[list] = [[lbl, "", tone, None] for lbl, tone in segments]
        self._mono = mono_value
        self._f_label = font(12, _W.Medium)
        self._f_value = font(12, _W.DemiBold, mono=True) if mono_value else font(12, _W.Bold)
        self._strong = False
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)

    def set(self, i: int = 0, value: str | None = None, tone: str | None = None,
            color: str | None = None, label: str | None = None) -> None:
        seg = self._segs[i]
        new = [seg[0] if label is None else label, seg[1] if value is None else value,
               seg[2] if tone is None else tone, color if color is not None else seg[3]]
        if new != seg:
            resize = (new[0], len(new[1])) != (seg[0], len(seg[1]))
            self._segs[i] = new
            if resize:
                self.updateGeometry()
            self.update()

    def set_strong(self, strong: bool) -> None:
        if strong != self._strong:
            self._strong = strong
            self.update()

    def _seg_width(self, seg) -> int:
        w = 12 + 8 + QtGui.QFontMetrics(self._f_label).horizontalAdvance(seg[0])
        if seg[1]:
            w += 6 + QtGui.QFontMetrics(self._f_value).horizontalAdvance(seg[1])
        return w + 12

    def sizeHint(self) -> QtCore.QSize:  # noqa: N802 (Qt override)
        return QtCore.QSize(sum(self._seg_width(s) for s in self._segs) + 2, 30)

    def minimumSizeHint(self) -> QtCore.QSize:  # noqa: N802
        return self.sizeHint()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        lead = self._segs[0]
        lead_c = QtGui.QColor(lead[3] or _TONE_COLORS.get(lead[2], TEXT_3))
        if self._strong:
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(lead_c)
        else:
            p.setPen(QtGui.QPen(QtGui.QColor(LINE_2), 1))
            p.setBrush(QtGui.QColor(SURFACE_2))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        x = 1.0
        for k, (text, value, tone, override) in enumerate(self._segs):
            c = QtGui.QColor(override or _TONE_COLORS.get(tone, TEXT_3))
            if k:
                p.setPen(QtGui.QPen(QtGui.QColor(LINE_2), 1))
                p.drawLine(QtCore.QPointF(x, 7), QtCore.QPointF(x, r.height() - 6))
            cy = r.center().y()
            dot_x = x + 12 + 3
            if self._strong:
                ink = QtGui.QColor(ON_ACCENT)
                p.setPen(QtCore.Qt.PenStyle.NoPen)
                p.setBrush(ink)
                p.drawEllipse(QtCore.QPointF(dot_x, cy), 3, 3)
            else:
                halo = QtGui.QColor(c)
                halo.setAlpha(60 if tone != "idle" else 0)
                p.setPen(QtCore.Qt.PenStyle.NoPen)
                p.setBrush(halo)
                p.drawEllipse(QtCore.QPointF(dot_x, cy), 6, 6)
                p.setBrush(c)
                p.drawEllipse(QtCore.QPointF(dot_x, cy), 3.2, 3.2)
                ink = QtGui.QColor(TEXT if tone != "idle" else TEXT_2)
            tx = x + 12 + 8 + 4
            p.setFont(self._f_label)
            p.setPen(ink if self._strong else QtGui.QColor(TEXT_2 if value else ink))
            fm = QtGui.QFontMetrics(self._f_label)
            p.drawText(QtCore.QPointF(tx, cy + fm.capHeight() / 2), text)
            tx += fm.horizontalAdvance(text)
            if value:
                p.setFont(self._f_value)
                p.setPen(ink)
                fv = QtGui.QFontMetrics(self._f_value)
                p.drawText(QtCore.QPointF(tx + 6, cy + fv.capHeight() / 2), value)
            x += self._seg_width(self._segs[k])


class Meter(QtWidgets.QWidget):
    """A thin segmented level meter (0..100), QProgressBar-compatible
    ``setValue``/``value``; repaints only when the integer level changes."""

    def __init__(self, color: str = ACCENT, height: int = 8, parent=None) -> None:
        super().__init__(parent)
        self._v = 0
        self._color = QtGui.QColor(color)
        self.setFixedHeight(height)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)

    def setValue(self, v: int) -> None:  # noqa: N802 (QProgressBar API)
        v = max(0, min(100, int(v)))
        if v != self._v:
            self._v = v
            self.update()

    def value(self) -> int:
        return self._v

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        r = QtCore.QRectF(self.rect())
        rad = r.height() / 2
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor(SURFACE_4))
        p.drawRoundedRect(r, rad, rad)
        if self._v:
            fill = QtCore.QRectF(r.x(), r.y(), max(r.height(), r.width() * self._v / 100), r.height())
            p.setBrush(self._color)
            p.drawRoundedRect(fill, rad, rad)
        # LED segment gaps, drawn over both track and fill
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, False)
        p.setPen(QtGui.QPen(QtGui.QColor(SURFACE), 2))
        x = 6
        w = int(r.width())
        while x < w:
            p.drawLine(x, 0, x, int(r.height()))
            x += 6


class BeatPulse(QtWidgets.QWidget):
    """Four step cells, the current beat lit and fading over ~350 ms. The
    fade is sampled by the console's refresh (no timer of its own) and
    quantised to a few levels, so it costs a handful of tiny repaints a beat."""

    _FADE_S = 0.35
    _LEVELS = 5

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._beat = 0
        self._t = 0.0
        self._level = 0
        self.setFixedSize(4 * 30 + 3 * 6, 10)

    def set_beat(self, beat: int, now: float) -> None:
        if beat != self._beat:
            self._beat, self._t, self._level = beat, now, self._LEVELS
            self.update()
            return
        level = max(0, round(self._LEVELS * (1 - (now - self._t) / self._FADE_S)))
        if level != self._level:
            self._level = level
            self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        for i in range(4):
            r = QtCore.QRectF(i * 36, 0, 30, 10)
            if i + 1 == self._beat:
                c = QtGui.QColor(ACCENT)
                c.setAlphaF(0.45 + 0.55 * self._level / self._LEVELS)
            elif i == 0:
                c = QtGui.QColor(LINE_3)       # the downbeat cell reads as "one"
            else:
                c = QtGui.QColor(SURFACE_4)
            p.setBrush(c)
            p.drawRoundedRect(r, 3, 3)


class CueButton(QtWidgets.QPushButton):
    """A big operator target: icon top-left, keycap top-right, title
    bottom-left. The surface (rest / hover / pressed / checked) comes from
    the stylesheet role (``cue`` or ``danger``); only the content is painted
    here. The plain ``text()`` stays set for accessibility and tests."""

    def __init__(self, title: str, key: str = "", icon_name: str | None = None,
                 role: str = "cue", checkable: bool = False, variant: str = "", parent=None) -> None:
        super().__init__(title, parent)
        self.setObjectName(role)
        if variant:
            self.setProperty("variant", variant)   # not "size": that is QWidget's own QSize property
        self.setCheckable(checkable)
        self._title = title.upper()
        self._key = key
        self._icon_name = icon_name
        self._role = role
        self._f_title = font(17, _W.Bold)
        self._f_key = font(11, _W.DemiBold, mono=True)
        # grows into spare height (bigger targets) up to a sane cap
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        self.setMaximumHeight(132)
        self.setAccessibleName(f"{title} ({key})" if key else title)

    def sizeHint(self) -> QtCore.QSize:  # noqa: N802
        return QtCore.QSize(160, 76)

    def _ink(self) -> str:
        if not self.isEnabled():
            return TEXT_3
        if self.isChecked():
            return ON_ACCENT                    # dark ink on lime and on red: 16:1 / 5.4:1
        return theme.DANGER_TEXT if self._role == "danger" else TEXT

    def paintEvent(self, _e) -> None:  # noqa: N802
        opt = QtWidgets.QStyleOptionButton()
        self.initStyleOption(opt)
        opt.text = ""
        opt.icon = QtGui.QIcon()
        sp = QtWidgets.QStylePainter(self)
        sp.drawControl(QtWidgets.QStyle.ControlElement.CE_PushButton, opt)
        sp.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        ink = self._ink()
        r = QtCore.QRectF(self.rect()).adjusted(14, 12, -14, -12)
        compact = self.height() < 64
        if self._icon_name and not compact:
            sp.drawPixmap(QtCore.QPointF(r.left(), r.top()), icons.pixmap(self._icon_name, ink, 20))
        if self._key:
            fm = QtGui.QFontMetrics(self._f_key)
            kw = max(22, fm.horizontalAdvance(self._key) + 12)
            kr = QtCore.QRectF(r.right() - kw, r.top() if not compact else r.center().y() - 11, kw, 22)
            edge = QtGui.QColor(ink)
            edge.setAlphaF(0.35)
            sp.setPen(QtGui.QPen(edge, 1))
            sp.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            sp.drawRoundedRect(kr, 5, 5)
            sp.setFont(self._f_key)
            key_ink = QtGui.QColor(ink)
            key_ink.setAlphaF(0.8)
            sp.setPen(key_ink)
            sp.drawText(kr, QtCore.Qt.AlignmentFlag.AlignCenter, self._key)
        sp.setFont(self._f_title)
        sp.setPen(QtGui.QColor(ink))
        fm = QtGui.QFontMetrics(self._f_title)
        if compact:
            y = r.center().y() + fm.capHeight() / 2
        else:
            y = r.bottom()
        sp.drawText(QtCore.QPointF(r.left(), y), fm.elidedText(self._title, QtCore.Qt.TextElideMode.ElideRight, int(r.width() - (60 if compact else 0))))


class AppHeader(QtWidgets.QFrame):
    """Wordmark + navigation + live status. ``add_nav`` returns the button;
    the owner wires what it does."""

    def __init__(self, subtitle: str = "", mode: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("header")
        self.setFixedHeight(60)
        h = QtWidgets.QHBoxLayout(self)
        h.setContentsMargins(theme.SP4 + 4, 0, theme.SP4, 0)
        h.setSpacing(theme.SP2)
        logo = QtWidgets.QLabel()
        logo.setPixmap(icons.pixmap("logo", ACCENT, 22))
        h.addWidget(logo)
        h.addSpacing(2)
        h.addWidget(label("LiveReact", "wordmark"))
        if subtitle:
            h.addSpacing(4)
            h.addWidget(label(subtitle, "body2"))
        if mode:
            h.addSpacing(4)
            h.addWidget(label(mode.upper(), "modeBadge"), 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
        h.addSpacing(theme.SP6)
        self._nav = QtWidgets.QHBoxLayout()
        self._nav.setSpacing(theme.SP1)
        h.addLayout(self._nav)
        h.addStretch(1)
        self._right = QtWidgets.QHBoxLayout()
        self._right.setSpacing(theme.SP2)
        h.addLayout(self._right)
        self.nav_group = QtWidgets.QButtonGroup(self)
        self.nav_group.setExclusive(True)

    def add_nav(self, text: str, icon_name: str, checkable: bool = True) -> QtWidgets.QPushButton:
        b = QtWidgets.QPushButton(text)
        b.setObjectName("nav")
        b.setIcon(icons.icon(icon_name, TEXT_3, on_color=ACCENT, size=16))
        b.setIconSize(QtCore.QSize(16, 16))
        b.setCheckable(checkable)
        b.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)   # never steals Space from the strobe shortcut
        b.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        if checkable:
            self.nav_group.addButton(b)
        self._nav.addWidget(b)
        return b

    def add_right(self, w: QtWidgets.QWidget) -> None:
        self._right.addWidget(w)


class Footer(QtWidgets.QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("footer")
        self.setFixedHeight(30)
        self.row = QtWidgets.QHBoxLayout(self)
        self.row.setContentsMargins(theme.SP4 + 4, 0, theme.SP4 + 4, 0)
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


__all__ = [
    "AppHeader", "BeatPulse", "Card", "CueButton", "Footer", "Meter", "StatusPill",
    "hbox", "label", "overline", "shell",
]
