"""PySide6 virtual rig visualizer + raw DMX inspector.

Lets you *see* the universe on screen with no hardware — the substrate for all
visual development (docs/12 Phase 2). The fixture→pixels mapping lives in each
fixture's ``visual_state`` (pure, unit-tested); this module just paints it.

Run the standalone Phase-2 demo (a hand-set, animated scene through the real
merge/safety pipeline):

    python -m livereact.ui.visualizer
"""

from __future__ import annotations

import logging
import math

from PySide6 import QtCore, QtGui, QtWidgets

from ..core.frame_buffer import UNIVERSE_SIZE, DmxFrameBuffer
from ..fixtures.profiles import Laser, MovingHead, Par, WashBar
from ..fixtures.rig import Rig, load_rig
from ..merge.merge import Contribution, ManualParams, render_universe

log = logging.getLogger(__name__)

# Canvas layout (logical scene coordinates).
_SCENE_W, _SCENE_H = 820, 540
_ROW_Y = {"spot": 90, "laser": 210, "par": 350, "bar": 450}
_FIXTURE_R = 34


def _layout(fx) -> tuple[float, float, float, float]:
    """Return (x, y, w, h) for a fixture: a custom dragged/loaded position
    (``fx.layout_x``/``layout_y``, normalized center 0..1) if set, else the
    default role/side schematic layout."""
    is_bar = isinstance(fx, WashBar)
    w, h = (260, 34) if is_bar else (_FIXTURE_R * 2, _FIXTURE_R * 2)
    if fx.layout_x is not None and fx.layout_y is not None:
        cx, cy = fx.layout_x * _SCENE_W, fx.layout_y * _SCENE_H
        return cx - w / 2, cy - h / 2, w, h
    if isinstance(fx, MovingHead):
        row = "spot"
    elif isinstance(fx, Laser):
        row = "laser"
    elif isinstance(fx, WashBar):
        row = "bar"
    else:
        row = "par"
    y = _ROW_Y[row]
    left_x, right_x = _SCENE_W * 0.30, _SCENE_W * 0.70
    x = left_x if fx.side == "left" else right_x
    if row == "bar":
        return x - 130, y, 260, 34  # wide bar
    return x - _FIXTURE_R, y, _FIXTURE_R * 2, _FIXTURE_R * 2


class RigView(QtWidgets.QGraphicsView):
    """Draws the 8 fixtures, colored/brightness/positioned from the live universe."""

    def __init__(self, rig: Rig) -> None:
        super().__init__()
        self.rig = rig
        self._scene = QtWidgets.QGraphicsScene(0, 0, _SCENE_W, _SCENE_H)
        self.setScene(self._scene)
        self.setBackgroundBrush(QtGui.QColor(12, 12, 16))
        self.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        self._bodies: dict[str, QtWidgets.QAbstractGraphicsShapeItem] = {}
        self._beams: dict[str, QtWidgets.QGraphicsLineItem] = {}
        self._labels: dict[str, QtWidgets.QGraphicsTextItem] = {}  # keep a Python ref — see _build_items
        self._build_items()

    def _build_items(self) -> None:
        pen = QtGui.QPen(QtGui.QColor(60, 60, 70))
        movable = (
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
        )
        for fx in self.rig.fixtures:
            x, y, w, h = _layout(fx)
            is_bar = isinstance(fx, WashBar)
            item: QtWidgets.QAbstractGraphicsShapeItem = (
                self._scene.addRect(x, y, w, h, pen) if is_bar else self._scene.addEllipse(x, y, w, h, pen)
            )
            # Draggable, so the operator can arrange the virtual rig to match a
            # real venue's physical layout (Save Layout persists it to the rig
            # file). Beam/label positions are derived live from wherever the
            # body actually is on screen, not recomputed from the original
            # layout, so they track a drag automatically.
            item.setFlag(movable, True)
            item.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
            self._bodies[self._key(fx)] = item
            # Beam line for moving heads (shows pan/tilt).
            if isinstance(fx, MovingHead):
                cx, cy = x + w / 2, y + h / 2
                beam = self._scene.addLine(cx, cy, cx, cy + 60, QtGui.QPen(QtGui.QColor(80, 80, 90), 2))
                self._beams[self._key(fx)] = beam
            # Parented to the body -> moves with it automatically when dragged
            # (child position is in the parent's own local coordinate frame,
            # which starts at the body's un-dragged origin, so this places it
            # in the same spot as before and keeps tracking on every drag).
            label = QtWidgets.QGraphicsTextItem(fx.label, item)
            label.setFont(QtGui.QFont("Arial", 8))
            label.setDefaultTextColor(QtGui.QColor(150, 150, 160))
            label.setPos(x, y + h + 2)
            self._labels[self._key(fx)] = label  # keep a Python ref (parent alone isn't enough — PySide6 GC gotcha)

    @staticmethod
    def _key(fx) -> str:
        return getattr(fx, "slot_id", fx.label)

    def fixture_positions(self) -> dict[str, tuple[float, float]]:
        """Each fixture's current on-screen center, normalized 0..1 — reflects
        drags, so this is what "Save Layout" persists to the rig file."""
        out = {}
        for fx in self.rig.fixtures:
            item = self._bodies.get(self._key(fx))
            if item is None:
                continue
            center = item.sceneBoundingRect().center()
            out[self._key(fx)] = (center.x() / _SCENE_W, center.y() / _SCENE_H)
        return out

    def reset_layout(self) -> None:
        """Clear custom positions and snap every fixture back to the default
        role/side schematic layout."""
        for fx in self.rig.fixtures:
            fx.layout_x = None
            fx.layout_y = None
            item = self._bodies.get(self._key(fx))
            if item is None:
                continue
            x, y, w, h = _layout(fx)
            item.setPos(0, 0)
            item.setRect(x, y, w, h)
            label = self._labels.get(self._key(fx))
            if label is not None:
                label.setPos(x, y + h + 2)

    def update_from_universe(self, uni: bytes) -> None:
        for fx in self.rig.fixtures:
            vs = fx.visual_state(uni)
            b = vs.brightness
            color = QtGui.QColor(int(vs.r * b), int(vs.g * b), int(vs.b * b))
            item = self._bodies[self._key(fx)]
            item.setBrush(QtGui.QBrush(color))
            glow = QtGui.QColor(vs.r, vs.g, vs.b) if vs.active else QtGui.QColor(60, 60, 70)
            item.setPen(QtGui.QPen(glow, 2 if vs.active else 1))
            beam = self._beams.get(self._key(fx))
            if beam is not None:
                center = item.sceneBoundingRect().center()  # live position, tracks drags
                cx, cy = center.x(), center.y()
                # pan 0..1 -> -60..60 px horizontally; tilt 0..1 -> 30..90 px down.
                dx = (vs.pan - 0.5) * 120
                dy = 30 + vs.tilt * 60
                beam.setLine(cx, cy, cx + dx, cy + dy)
                beam.setPen(QtGui.QPen(color if vs.active else QtGui.QColor(50, 50, 60), 2))


class DmxInspector(QtWidgets.QTableWidget):
    """Live per-channel values for the channels the rig actually uses."""

    def __init__(self, rig: Rig) -> None:
        # Map each used channel -> (fixture label, kind name).
        self._rows: list[tuple[int, str, str]] = []
        for fx in rig.fixtures:
            kinds = fx.channel_kinds()
            for local, ch in enumerate(fx.channels()):
                self._rows.append((ch, fx.label, kinds[local].name))
        super().__init__(len(self._rows), 4)
        self.setHorizontalHeaderLabels(["Ch", "Value", "Fixture", "Kind"])
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        for r, (ch, label, kind) in enumerate(self._rows):
            self.setItem(r, 0, QtWidgets.QTableWidgetItem(str(ch)))
            self.setItem(r, 1, QtWidgets.QTableWidgetItem("0"))
            self.setItem(r, 2, QtWidgets.QTableWidgetItem(label))
            self.setItem(r, 3, QtWidgets.QTableWidgetItem(kind))
        self.resizeColumnsToContents()

    def update_from_universe(self, uni: bytes) -> None:
        for r, (ch, _label, _kind) in enumerate(self._rows):
            self.item(r, 1).setText(str(uni[ch - 1]))


class VisualizerWindow(QtWidgets.QMainWindow):
    """Rig view + DMX inspector side by side."""

    def __init__(self, rig: Rig) -> None:
        super().__init__()
        self.setWindowTitle("LiveReact — Virtual Rig")
        self.rig_view = RigView(rig)
        self.inspector = DmxInspector(rig)
        split = QtWidgets.QSplitter()
        split.addWidget(self.rig_view)
        split.addWidget(self.inspector)
        split.setSizes([820, 360])
        self.setCentralWidget(split)
        self.resize(1180, 600)

    def update_from_universe(self, uni: bytes) -> None:
        self.rig_view.update_from_universe(uni)
        self.inspector.update_from_universe(uni)


def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[float, float, float]:
    i = int(h * 6) % 6
    f = h * 6 - int(h * 6)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    return [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i]


def build_demo_universe(rig: Rig, t: float) -> bytes:
    """A hand-set, animated scene driven only by time (no engines yet).

    Demonstrates the full Phase-2 pipeline: fixture setters -> merge -> finalize,
    including a periodic 'drop' window that enables the lasers to prove the
    safety gate works (lasers are off the rest of the time).
    """
    c = Contribution()
    hue = (t * 0.05) % 1.0
    energy = 0.5 + 0.4 * math.sin(t * 0.25)
    pulse = 0.55 + 0.45 * max(0.0, math.sin(t * math.tau * (124 / 60)))  # ~124 BPM
    level = energy * pulse
    r, g, b = _hsv_to_rgb(hue, 0.85, 1.0)

    for fx in rig.by_role("wash"):
        if isinstance(fx, (Par, WashBar)):
            fx.set_intensity(c, level)
            fx.set_color(c, r, g, b)

    for fx in rig.by_role("spot"):
        fx.set_intensity(c, energy)
        pan = 0.5 + 0.4 * math.sin(t * 0.7) * (1 if fx.side == "left" else -1)  # mirror
        tilt = 0.4 + 0.2 * math.sin(t * 0.5)
        fx.set_position(c, pan, tilt)
        fx.set_color(c, r, g, b)

    in_drop = (t % 16.0) < 4.0  # a 4-second "drop" every 16 seconds
    if in_drop:
        for fx in rig.by_role("laser"):
            fx.set_pattern(c, pattern=40, color=200, scale=0.8)

    manual = ManualParams(master_brightness=1.0, laser_enable=in_drop)
    return render_universe([c], rig, manual)


def run(frame_buffer: DmxFrameBuffer, rig: Rig, fps: int = 30, status=None) -> int:
    """Open the window and refresh it from a frame buffer at ``fps`` (blocks).

    ``status`` is an optional zero-arg callable returning a string (e.g. the active
    scene name) shown in the window title.
    """
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    win = VisualizerWindow(rig)
    win.show()

    def refresh() -> None:
        win.update_from_universe(frame_buffer.latest())
        if status is not None:
            win.setWindowTitle(f"LiveReact — Virtual Rig  |  Scene: {status()}")

    timer = QtCore.QTimer()
    timer.timeout.connect(refresh)
    timer.start(int(1000 / fps))
    return app.exec()


def demo_main() -> int:
    logging.basicConfig(level=logging.INFO)
    rig = load_rig()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    win = VisualizerWindow(rig)
    win.show()
    state = {"t": 0.0}

    def tick() -> None:
        state["t"] += 1 / 30
        win.update_from_universe(build_demo_universe(rig, state["t"]))

    timer = QtCore.QTimer()
    timer.timeout.connect(tick)
    timer.start(int(1000 / 30))
    log.info("Visualizer demo running — close the window to exit.")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(demo_main())
