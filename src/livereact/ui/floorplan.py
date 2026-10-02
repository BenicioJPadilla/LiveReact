"""Scaled venue floor plan: the rig drawn in real space (feet on screen,
meters underneath -- fixtures/geometry.py's convention).

Two uses (2026-09-18 UI redesign):

  * ``editable=True``  -- the Venue tab: drag fixtures and named targets
    around the room (snapping to half a foot), which writes real positions
    onto the live ``Fixture``/``Venue`` objects and calls ``on_changed``.
  * ``editable=False`` -- the Show tab's live mini-map: same drawing, nothing
    movable, so a stray click mid-set can't move anything.

Drawing: the booth wall (y = 0) is at the BOTTOM of the view, the crowd
extends upward, x runs to the right (the DJ's right). Moving heads draw the
beam where the current pan/tilt actually lands on the floor (via the head's
captured calibration); lasers draw their fan wedge and turn it red when the
fan would pass below the LASER-09 minimum beam height anywhere over the floor.

All geometry math is in fixtures/geometry.py; this module only paints.
"""

from __future__ import annotations

import math
from typing import Callable

from PySide6 import QtCore, QtGui, QtWidgets

from ..fixtures.geometry import (
    Point3,
    Venue,
    beam_floor_hit,
    ft_to_m,
    laser_min_beam_height,
    m_to_ft,
    pan_tilt_to_angles,
    ray_to_rect_edge,
)
from ..fixtures.profiles import Laser, MovingHead, WashBar
from ..fixtures.rig import Rig

PX_PER_M = 40.0                 # scene pixels per meter
SNAP_M = ft_to_m(0.5)           # drag snap: half a foot
DEFAULT_VENUE_FT = (30.0, 40.0, 12.0)   # width, length, ceiling -- when no venue is declared
_MARGIN = 28                    # scene margin around the room for edge labels

# Where an unplaced fixture is drawn, as fractions of the room (x by side, y
# by kind: everything hugs the booth wall until the operator places it).
_ROW_Y_FRAC = {"spot": 0.16, "laser": 0.26, "par": 0.36, "bar": 0.46}
_BODY_R_M = 0.35                # drawn fixture radius (m)
_BAR_W_M, _BAR_H_M = 1.2, 0.25  # wash bar footprint (m)

_GRID_LIGHT = QtGui.QColor(34, 38, 46)
_GRID_BOLD = QtGui.QColor(52, 58, 70)
_ROOM_EDGE = QtGui.QColor(120, 128, 140)
_TEXT = QtGui.QColor(150, 155, 165)
_IDLE = QtGui.QColor(60, 60, 70)
_UNSAFE = QtGui.QColor(224, 65, 58)
_TARGET = QtGui.QColor(245, 166, 35)


def _default_venue() -> Venue:
    w, l, h = (ft_to_m(v) for v in DEFAULT_VENUE_FT)
    return Venue(w, l, h, Venue.default_targets(w, l, h))


class PlanItem(QtWidgets.QGraphicsObject):
    """A fixture body or a target marker: paints itself as one object so it
    moves as one, and reports drops back to the view."""

    def __init__(self, key: str, kind: str, label: str, w_m: float, h_m: float) -> None:
        super().__init__()
        self.key = key
        self.kind = kind            # "fixture" | "target"
        self.label = label
        self.w_px, self.h_px = w_m * PX_PER_M, h_m * PX_PER_M
        self.facing_deg = 0.0
        self.fill = QtGui.QColor(0, 0, 0)
        self.edge = _IDLE
        self.edge_w = 1.0
        self.setZValue(10)

    def boundingRect(self) -> QtCore.QRectF:  # noqa: N802 (Qt override)
        pad = 4
        return QtCore.QRectF(-self.w_px / 2 - pad, -self.h_px / 2 - pad,
                             self.w_px + 2 * pad, self.h_px + 2 * pad + 16)

    def paint(self, painter: QtGui.QPainter, option, widget=None) -> None:  # noqa: ARG002
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = QtCore.QRectF(-self.w_px / 2, -self.h_px / 2, self.w_px, self.h_px)
        painter.setPen(QtGui.QPen(self.edge, self.edge_w))
        painter.setBrush(QtGui.QBrush(self.fill))
        if self.kind == "target":
            path = QtGui.QPainterPath()
            r = self.w_px / 2
            path.moveTo(0, -r); path.lineTo(r, 0); path.lineTo(0, r); path.lineTo(-r, 0); path.closeSubpath()
            painter.drawPath(path)
        elif self.w_px > self.h_px * 1.5:
            painter.drawRect(rect)
        else:
            painter.drawEllipse(rect)
            # facing tick: which way the body's pan=0.5 points (screen y is
            # flipped, so "into the crowd" (az 0) is straight UP).
            a = math.radians(self.facing_deg)
            r = self.w_px / 2
            painter.setPen(QtGui.QPen(_TEXT, 2))
            painter.drawLine(QtCore.QPointF(0, 0), QtCore.QPointF(math.sin(a) * r * 1.4, -math.cos(a) * r * 1.4))
        if self.isSelected():
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255), 1, QtCore.Qt.PenStyle.DashLine))
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(-3, -3, 3, 3))
        painter.setPen(_TEXT)
        painter.setFont(QtGui.QFont("Arial", 8))
        painter.drawText(QtCore.QRectF(-60, self.h_px / 2 + 1, 120, 14),
                         QtCore.Qt.AlignmentFlag.AlignHCenter, self.label)


class FloorPlanView(QtWidgets.QGraphicsView):
    fixture_selected = QtCore.Signal(str)   # slot_id, or "" when nothing is selected

    def __init__(self, rig: Rig, editable: bool = False,
                 on_changed: Callable[[], None] | None = None) -> None:
        super().__init__()
        self.rig = rig
        self.editable = editable
        self.on_changed = on_changed
        self._scene = QtWidgets.QGraphicsScene()
        self.setScene(self._scene)
        self.setBackgroundBrush(QtGui.QColor(12, 12, 16))
        self.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._grid: list[QtWidgets.QGraphicsItem] = []
        self._bodies: dict[str, PlanItem] = {}
        self._targets: dict[str, PlanItem] = {}
        self._beams: dict[str, QtWidgets.QGraphicsLineItem] = {}
        self._wedges: dict[str, QtWidgets.QGraphicsPolygonItem] = {}
        self._warnings: dict[str, QtWidgets.QGraphicsSimpleTextItem] = {}
        self._dragging: set[str] = set()
        self._scene.selectionChanged.connect(self._on_selection)
        self.refresh_layout()

    # ------------------------------------------------------------ geometry
    def venue(self) -> Venue:
        return self.rig.venue if self.rig.venue is not None else _default_venue()

    def to_scene(self, x_m: float, y_m: float) -> QtCore.QPointF:
        """Meters -> scene px; the booth wall (y=0) sits at the bottom."""
        return QtCore.QPointF(x_m * PX_PER_M, (self.venue().length_m - y_m) * PX_PER_M)

    def from_scene(self, p: QtCore.QPointF) -> tuple[float, float]:
        return p.x() / PX_PER_M, self.venue().length_m - p.y() / PX_PER_M

    def _fallback_xy(self, fx) -> tuple[float, float]:
        """Where to draw a fixture that has no real position yet."""
        v = self.venue()
        if fx.layout_x is not None and fx.layout_y is not None:
            return fx.layout_x * v.width_m, (1.0 - fx.layout_y) * v.length_m
        if isinstance(fx, MovingHead):
            row = "spot"
        elif isinstance(fx, Laser):
            row = "laser"
        elif isinstance(fx, WashBar):
            row = "bar"
        else:
            row = "par"
        x = v.width_m * (0.3 if fx.side == "left" else 0.7)
        return x, v.length_m * _ROW_Y_FRAC[row]

    def fixture_origin(self, fx) -> Point3:
        """The fixture's emitter point in meters (drawn position + height)."""
        if fx.position is not None:
            return fx.position
        x, y = self._fallback_xy(fx)
        z = fx.mount_height_m if fx.mount_height_m is not None else 1.0
        return Point3(x, y, z)

    # ------------------------------------------------------------ build
    def refresh_layout(self) -> None:
        """(Re)build every static item from the rig + venue. Call after any
        venue/position edit; cheap enough for that (a few dozen items)."""
        self._scene.blockSignals(True)
        self._scene.clear()
        self._grid.clear(); self._bodies.clear(); self._targets.clear()
        self._beams.clear(); self._wedges.clear(); self._warnings.clear()
        v = self.venue()
        w_px, l_px = v.width_m * PX_PER_M, v.length_m * PX_PER_M
        self._scene.setSceneRect(-_MARGIN, -_MARGIN, w_px + 2 * _MARGIN, l_px + 2 * _MARGIN)

        # grid: every foot light, every 5 ft bold
        step = ft_to_m(1.0) * PX_PER_M
        n_x, n_y = int(v.width_m / ft_to_m(1.0)) + 1, int(v.length_m / ft_to_m(1.0)) + 1
        for i in range(n_x + 1):
            x = i * step
            if x > w_px + 0.5:
                break
            pen = QtGui.QPen(_GRID_BOLD if i % 5 == 0 else _GRID_LIGHT, 1)
            self._grid.append(self._scene.addLine(x, 0, x, l_px, pen))
            if i % 5 == 0:
                t = self._scene.addSimpleText(f"{i}′"); t.setBrush(_TEXT); t.setPos(x - 6, l_px + 4)
        for j in range(n_y + 1):
            y = l_px - j * step
            if y < -0.5:
                break
            pen = QtGui.QPen(_GRID_BOLD if j % 5 == 0 else _GRID_LIGHT, 1)
            self._grid.append(self._scene.addLine(0, y, w_px, y, pen))
            if j % 5 == 0:
                t = self._scene.addSimpleText(f"{j}′"); t.setBrush(_TEXT); t.setPos(-_MARGIN + 2, y - 7)
        self._scene.addRect(0, 0, w_px, l_px, QtGui.QPen(_ROOM_EDGE, 2))
        booth = self._scene.addSimpleText("DJ BOOTH WALL")
        booth.setBrush(_ROOM_EDGE); booth.setPos(w_px / 2 - 44, l_px + 14)

        movable = (QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                   | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)

        # named targets
        for name, p in v.targets.items():
            item = PlanItem(name, "target", f"{name} · {m_to_ft(p.z):.0f}′", 0.45, 0.45)
            item.fill = QtGui.QColor(0, 0, 0); item.edge = _TARGET; item.edge_w = 2
            item.setPos(self.to_scene(p.x, p.y))
            item.setZValue(5)
            if self.editable:
                item.setFlags(movable)
                item.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
            self._scene.addItem(item)
            self._targets[name] = item

        # fixtures
        for fx in self.rig.fixtures:
            key = self._key(fx)
            is_bar = isinstance(fx, WashBar)
            item = PlanItem(key, "fixture", fx.label,
                            _BAR_W_M if is_bar else _BODY_R_M * 2, _BAR_H_M if is_bar else _BODY_R_M * 2)
            item.facing_deg = fx.facing_deg
            o = self.fixture_origin(fx)
            item.setPos(self.to_scene(o.x, o.y))
            if self.editable:
                item.setFlags(movable | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
                item.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
            self._scene.addItem(item)
            self._bodies[key] = item
            if isinstance(fx, MovingHead):
                beam = self._scene.addLine(0, 0, 0, 0, QtGui.QPen(QtGui.QColor(80, 80, 90), 2))
                beam.setZValue(3)
                self._beams[key] = beam
            elif isinstance(fx, Laser):
                wedge = self._scene.addPolygon(QtGui.QPolygonF(), QtGui.QPen(_IDLE, 1),
                                               QtGui.QBrush(QtGui.QColor(60, 60, 70, 40)))
                wedge.setZValue(2)
                self._wedges[key] = wedge
                warn = self._scene.addSimpleText("")
                warn.setBrush(_UNSAFE); warn.setZValue(12)
                self._warnings[key] = warn
        self._scene.blockSignals(False)
        self._fit()
        self.update_from_universe(self.rig.boot_universe())

    @staticmethod
    def _key(fx) -> str:
        return getattr(fx, "slot_id", fx.label)

    def _fit(self) -> None:
        self.fitInView(self._scene.sceneRect(), QtCore.Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._fit()

    # ------------------------------------------------------------ selection / drag
    def _on_selection(self) -> None:
        for key, item in self._bodies.items():
            if item.isSelected():
                self.fixture_selected.emit(key)
                return
        self.fixture_selected.emit("")

    def select(self, slot_id: str) -> None:
        self._scene.blockSignals(True)
        for key, item in self._bodies.items():
            item.setSelected(key == slot_id)
        self._scene.blockSignals(False)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().mouseReleaseEvent(event)
        if not self.editable:
            return
        changed = False
        for key, item in self._bodies.items():
            if item.isSelected():
                changed |= self._commit_fixture_drop(key, item)
        for name, item in self._targets.items():
            if item.isSelected():
                changed |= self._commit_target_drop(name, item)
        if changed:
            self.rig.refresh_geometry()
            if self.on_changed is not None:
                self.on_changed()

    def _snap(self, x_m: float, y_m: float) -> tuple[float, float]:
        v = self.venue()
        x_m = min(v.width_m, max(0.0, round(x_m / SNAP_M) * SNAP_M))
        y_m = min(v.length_m, max(0.0, round(y_m / SNAP_M) * SNAP_M))
        return x_m, y_m

    def _commit_fixture_drop(self, key: str, item: PlanItem) -> bool:
        fx = self.rig.fixture(key)
        x_m, y_m = self._snap(*self.from_scene(item.pos()))
        old = fx.position
        z = old.z if old is not None else (fx.mount_height_m if fx.mount_height_m is not None else 1.0)
        fx.position = Point3(x_m, y_m, z)
        if isinstance(fx, Laser) and fx.mount_height_m is None:
            fx.mount_height_m = z
        item.setPos(self.to_scene(x_m, y_m))
        return old != fx.position

    def _commit_target_drop(self, name: str, item: PlanItem) -> bool:
        v = self.rig.venue
        if v is None:
            return False
        x_m, y_m = self._snap(*self.from_scene(item.pos()))
        old = v.targets.get(name)
        z = old.z if old is not None else 1.0
        v.targets[name] = Point3(x_m, y_m, z)
        item.setPos(self.to_scene(x_m, y_m))
        return old != v.targets[name]

    def set_fixture_position(self, slot_id: str, p: Point3) -> None:
        """Move a body to a position set from the property panel (no snap)."""
        item = self._bodies.get(slot_id)
        if item is not None:
            item.setPos(self.to_scene(p.x, p.y))

    # ------------------------------------------------------------ live frame
    def update_from_universe(self, uni: bytes) -> None:
        v = self.venue()
        for fx in self.rig.fixtures:
            key = self._key(fx)
            item = self._bodies.get(key)
            if item is None:
                continue
            vs = fx.visual_state(uni)
            b = vs.brightness
            color = QtGui.QColor(int(vs.r * b), int(vs.g * b), int(vs.b * b))
            item.fill = color
            item.edge = QtGui.QColor(vs.r, vs.g, vs.b) if vs.active else _IDLE
            item.edge_w = 2 if vs.active else 1
            item.facing_deg = fx.facing_deg
            item.update()
            origin = self.fixture_origin(fx)
            center = item.pos()

            beam = self._beams.get(key)
            if beam is not None and isinstance(fx, MovingHead):
                az, el = pan_tilt_to_angles(vs.pan, vs.tilt, fx.facing_deg, fx.calibration,
                                            fx.PAN_RANGE_DEG, fx.TILT_RANGE_DEG)
                hit = beam_floor_hit(origin, az, el)
                edge = ray_to_rect_edge((origin.x, origin.y), az, v.width_m, v.length_m)
                if hit is not None and math.hypot(hit.x - origin.x, hit.y - origin.y) <= edge:
                    end = self.to_scene(hit.x, hit.y)
                    pen = QtGui.QPen(color if vs.active else QtGui.QColor(50, 50, 60), 2)
                else:  # aimed up or past the wall: draw to the wall, faded
                    dx, dy = math.sin(math.radians(az)), math.cos(math.radians(az))
                    end = self.to_scene(origin.x + dx * edge, origin.y + dy * edge)
                    faded = QtGui.QColor(color); faded.setAlpha(90)
                    pen = QtGui.QPen(faded if vs.active else QtGui.QColor(40, 40, 50), 1, QtCore.Qt.PenStyle.DashLine)
                beam.setLine(center.x(), center.y(), end.x(), end.y())
                beam.setPen(pen)

            wedge = self._wedges.get(key)
            if wedge is not None and isinstance(fx, Laser):
                # display assumption (UNVERIFIED CH7 0-127): the static offset
                # shifts the fan's centre within its own half-angle.
                centre_az = fx.facing_deg + (fx.h_offset01 - 0.5) * 2 * fx.fan_half_angle_deg
                pts = [center]
                for k in (-1.0, -0.5, 0.0, 0.5, 1.0):
                    az = centre_az + k * fx.fan_half_angle_deg
                    throw = ray_to_rect_edge((origin.x, origin.y), az, v.width_m, v.length_m)
                    dx, dy = math.sin(math.radians(az)), math.cos(math.radians(az))
                    pts.append(self.to_scene(origin.x + dx * throw, origin.y + dy * throw))
                wedge.setPolygon(QtGui.QPolygonF(pts))
                lowest = laser_min_beam_height(origin, centre_az, fx.beam_tilt_deg, fx.fan_half_angle_deg,
                                               v.width_m, v.length_m)
                unsafe = fx.mount_height_m is None or lowest < fx.min_beam_height_m
                if unsafe:
                    wedge.setPen(QtGui.QPen(_UNSAFE, 1))
                    wedge.setBrush(QtGui.QBrush(QtGui.QColor(224, 65, 58, 70), QtCore.Qt.BrushStyle.BDiagPattern))
                else:
                    fill = QtGui.QColor(color) if vs.active else QtGui.QColor(60, 60, 70)
                    fill.setAlpha(70 if vs.active else 40)
                    wedge.setPen(QtGui.QPen(QtGui.QColor(vs.r, vs.g, vs.b) if vs.active else _IDLE, 1))
                    wedge.setBrush(QtGui.QBrush(fill))
                warn = self._warnings.get(key)
                if warn is not None:
                    if fx.mount_height_m is None:
                        warn.setText("NO MOUNT HEIGHT")
                    elif unsafe:
                        warn.setText(f"BELOW {fx.min_beam_height_m:.1f} m")
                    else:
                        warn.setText("")
                    warn.setPos(center.x() - 40, center.y() - self._bodies[key].h_px / 2 - 16)

    # ------------------------------------------------------------ queries (tests / panel)
    def item_position_m(self, slot_id: str) -> tuple[float, float]:
        return self.from_scene(self._bodies[slot_id].pos())

    def laser_unsafe(self, slot_id: str) -> bool:
        warn = self._warnings.get(slot_id)
        return bool(warn is not None and warn.text())
