"""The Live screen's stage: the real floor plan, lit by the show.

It is ``FloorPlanView`` (the same drawing as the Lights page, nothing
movable) in stage mode, with:

  * a background of the dark room and a pool of the live light colour (the
    glow, ui/glow.py), cached by the view and re-rendered at most 10 times a
    second while the colour moves;
  * a foreground HUD: the status line ("Listening." / "Blackout." ...) over
    a dark fade at the top, quiet chips bottom-left (what the operator has
    started) and bottom-right (the look and the laser switch), and a veil
    over the room while Blackout holds.

All of it is painted from state the console hands over in ``set_hud``;
nothing here reads the engine.
"""

from __future__ import annotations

import time

from PySide6 import QtCore, QtGui, QtWidgets

from . import theme
from .floorplan import FloorPlanView
from .glow import Glow
from .theme import TEXT, TEXT_2, font

_W = QtGui.QFont.Weight
_GLOW_REPAINT_S = 0.1


class StageView(FloorPlanView):
    def __init__(self, rig, glow: Glow) -> None:
        super().__init__(rig, editable=False, stage=True)
        self.glow = glow
        self.setCacheMode(QtWidgets.QGraphicsView.CacheModeFlag.CacheBackground)
        self.setViewportUpdateMode(QtWidgets.QGraphicsView.ViewportUpdateMode.MinimalViewportUpdate)
        self.setInteractive(False)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self._hud = ("", "")
        self._left: tuple[str, ...] = ()
        self._right: tuple[tuple[str, str], ...] = ()
        self._veil = False
        self._glow_t = 0.0
        self._glow_pending = False
        self._f_chip = font(12.5, _W.Medium)
        self._fm_chip = QtGui.QFontMetricsF(self._f_chip)
        self._hud_px: QtGui.QPixmap | None = None     # the HUD, rendered when it changes
        glow.changed.connect(self._glow_changed)

    def sizeHint(self) -> QtCore.QSize:  # noqa: N802 (Qt override)
        # small on purpose: the Live page asks for little and the stage
        # takes whatever height is left (the scene's own size would make
        # the page scroll)
        return QtCore.QSize(640, 220)

    # ------------------------------------------------------------ fit
    def _fit(self) -> None:
        """Fit the room beside or below the status line, so the two never fight."""
        r = self._scene.sceneRect()
        vp = self.viewport().rect()
        if vp.width() > 1.6 * vp.height():
            # wide stage: the room to the right of the status line, full height
            target = QtCore.QRectF(vp).adjusted(max(300, vp.width() * 0.36), 16, -24, -48)
        else:
            top = min(vp.height() * 0.30, 120)
            target = QtCore.QRectF(vp).adjusted(24, top, -24, -48)
        if target.width() < 40 or target.height() < 40:
            self.setSceneRect(QtCore.QRectF())       # track the scene again
            super()._fit()
            return
        k = min(target.width() / r.width(), target.height() / r.height())
        # The view shows exactly this scene rect, so the room's centre lands
        # on the target's centre (centerOn can't move a scene that fits).
        c, tc = r.center(), target.center()
        self.setSceneRect(QtCore.QRectF(c.x() - tc.x() / k, c.y() - tc.y() / k, vp.width() / k, vp.height() / k))
        self.resetTransform()
        self.scale(k, k)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._hud_px = None
        # round the top corners to the stage frame's
        r = QtCore.QRectF(self.rect())
        rad = theme.R_LG - 1
        path = QtGui.QPainterPath()
        path.addRoundedRect(r.adjusted(0, 0, 0, rad), rad, rad)
        self.setMask(QtGui.QRegion(path.toFillPolygon().toPolygon()))

    # ------------------------------------------------------------ state
    def _glow_changed(self) -> None:
        if time.monotonic() - self._glow_t >= _GLOW_REPAINT_S:
            self._repaint_glow()
        elif not self._glow_pending:
            self._glow_pending = True
            QtCore.QTimer.singleShot(int(_GLOW_REPAINT_S * 1000), self._repaint_glow)

    def _repaint_glow(self) -> None:
        self._glow_pending = False
        self._glow_t = time.monotonic()
        self.resetCachedContent()
        self.viewport().update()

    def set_hud(self, title: str, sub: str, left: tuple[str, ...], right: tuple[tuple[str, str], ...],
                veil: bool) -> None:
        """What the HUD says. Repaints only when something changed."""
        state = ((title, sub), left, right, veil)
        if state != (self._hud, self._left, self._right, self._veil):
            self._hud, self._left, self._right, self._veil = state
            self._hud_px = None
            self.viewport().update()

    def hud_text(self) -> tuple[str, str]:
        return self._hud

    # ------------------------------------------------------------ painting
    def drawBackground(self, p: QtGui.QPainter, rect) -> None:  # noqa: N802
        p.save()
        p.resetTransform()
        vp = QtCore.QRectF(self.viewport().rect())
        p.fillRect(vp, QtGui.QColor(theme.ROOM))
        g = QtGui.QRadialGradient(QtCore.QPointF(vp.center().x(), vp.bottom() - vp.height() * 0.28), vp.width() * 0.62)
        g.setColorAt(0.0, self.glow.color(0.20))
        g.setColorAt(1.0, self.glow.color(0.0))
        p.fillRect(vp, g)
        floor = QtGui.QLinearGradient(0, vp.bottom() - vp.height() * 0.30, 0, vp.bottom())
        floor.setColorAt(0.0, self.glow.color(0.0))
        floor.setColorAt(1.0, self.glow.color(0.10))
        p.fillRect(vp, floor)
        vig = QtGui.QRadialGradient(vp.center(), vp.width() * 0.75)
        vig.setColorAt(0.45, QtGui.QColor(0, 0, 0, 0))
        vig.setColorAt(1.0, QtGui.QColor(0, 0, 0, 120))
        p.fillRect(vp, vig)
        p.restore()

    def drawForeground(self, p: QtGui.QPainter, rect) -> None:  # noqa: N802
        # Fixtures repaint every refresh; the HUD only when it changes.
        if self._hud_px is None:
            self._hud_px = self._render_hud()
        p.save()
        p.resetTransform()
        p.drawPixmap(0, 0, self._hud_px)
        p.restore()

    def _render_hud(self) -> QtGui.QPixmap:
        vp = QtCore.QRectF(self.viewport().rect())
        dpr = self.viewport().devicePixelRatioF()
        px = QtGui.QPixmap(max(1, round(vp.width() * dpr)), max(1, round(vp.height() * dpr)))
        px.setDevicePixelRatio(dpr)
        px.fill(QtCore.Qt.GlobalColor.transparent)
        p = QtGui.QPainter(px)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)
        if self._veil:
            p.fillRect(vp, QtGui.QColor(4, 4, 5, 178))
        fade = QtGui.QLinearGradient(0, 0, 0, vp.height() * 0.46)
        fade.setColorAt(0.0, QtGui.QColor(4, 4, 5, 224))
        fade.setColorAt(0.55, QtGui.QColor(4, 4, 5, 128))
        fade.setColorAt(1.0, QtGui.QColor(4, 4, 5, 0))
        p.fillRect(QtCore.QRectF(0, 0, vp.width(), vp.height() * 0.46), fade)
        title, sub = self._hud
        x, y = 28.0, 26.0
        if title:
            f = font(max(34.0, min(64.0, vp.width() * 0.058)), _W.DemiBold, display=True)
            p.setFont(f)
            fm = QtGui.QFontMetricsF(f)
            p.setPen(QtGui.QColor(TEXT))
            p.drawText(QtCore.QPointF(x, y + fm.ascent() * 0.92), title)
            y += fm.ascent() * 0.92 + fm.descent()
        if sub:
            fs = font(max(15.0, min(18.0, vp.width() * 0.0165)), _W.Medium)
            p.setFont(fs)
            fm = QtGui.QFontMetricsF(fs)
            p.setPen(QtGui.QColor(TEXT_2))
            p.drawText(QtCore.QRectF(x, y + 8, vp.width() - 2 * x, fm.height() * 2 + 4),
                       int(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.TextFlag.TextWordWrap), sub)
        cy = vp.height() - 16 - 26
        cx = 16.0
        for text in self._left:
            cx += self._chip(p, cx, cy, text, "") + 6
        rx = vp.width() - 16
        for text, tone in reversed(self._right):
            rx -= self._chip(p, rx, cy, text, tone, right=True) + 6
        p.end()
        return px

    def _chip(self, p: QtGui.QPainter, x: float, y: float, text: str, tone: str, right: bool = False) -> float:
        """A glass chip at ``x`` (its right edge when ``right``); ``tone`` adds
        a status dot. Returns its width."""
        w = self._fm_chip.horizontalAdvance(text) + 20 + (13 if tone else 0)
        r = QtCore.QRectF(x - w if right else x, y, w, 26)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 28), 1))
        p.setBrush(QtGui.QColor(8, 9, 10, 170))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), theme.R_XS, theme.R_XS)
        tx = r.left() + 10
        if tone:
            c = QtGui.QColor(theme.OK if tone == "ok" else theme.TEXT_3)
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawEllipse(QtCore.QPointF(tx + 3.5, r.center().y()), 3.5, 3.5)
            tx += 13
        p.setFont(self._f_chip)
        p.setPen(QtGui.QColor(TEXT))
        p.drawText(QtCore.QPointF(tx, r.center().y() + self._fm_chip.capHeight() / 2), text)
        return w
