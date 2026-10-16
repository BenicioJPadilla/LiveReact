"""Manual fixture-test panel for hardware bring-up (docs/04 §7, docs/12 Phase 7).

Drives individual DMX channels directly, bypassing the engines, so you can verify
each of the 8 fixtures one at a time when wiring the rig. A per-channel slider grid
(grouped by fixture) publishes a manual universe straight to the output backend.
"""

from __future__ import annotations

import logging
import os

from PySide6 import QtCore, QtWidgets

from ..core.frame_buffer import UNIVERSE_SIZE, DmxFrameBuffer
from ..fixtures.profiles import MovingHead, _read16
from ..fixtures.rig import Rig, RigError, save_rig
from ..merge.merge import Contribution
from . import icons, theme
from .widgets import AppHeader, Footer, StatusPill, label, shell

log = logging.getLogger(__name__)


class FixtureTestPanel(QtWidgets.QMainWindow):
    def __init__(self, rig: Rig, frame_buffer: DmxFrameBuffer, rig_path: str | None = None) -> None:
        super().__init__()
        self.rig = rig
        self.frame_buffer = frame_buffer
        self.rig_path = rig_path
        self._uni = bytearray(UNIVERSE_SIZE)
        self._sliders: dict[int, QtWidgets.QSlider] = {}  # channel(1-based) -> slider
        self.setWindowTitle("LiveReact · Fixture test")
        theme.apply_theme()

        header = AppHeader(subtitle="Fixture test", mode="raw dmx")
        warn = StatusPill([("Show bypassed: sliders drive DMX directly", "warn")])
        header.add_right(warn)
        all_off = QtWidgets.QPushButton("All off")
        all_off.setObjectName("ghostDanger")
        all_off.setIcon(icons.icon("power", theme.DANGER_TEXT, size=16))
        all_off.setToolTip("Every channel to 0.")
        all_off.clicked.connect(self.all_off)
        header.add_right(all_off)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(inner)
        grid.setContentsMargins(theme.SP4, theme.SP4, theme.SP4, theme.SP4)
        grid.setSpacing(theme.SP3)
        cols = 2
        for i, fx in enumerate(rig.fixtures):
            grid.addWidget(self._fixture_group(fx), i // cols, i % cols, QtCore.Qt.AlignmentFlag.AlignTop)
        grid.setRowStretch((len(rig.fixtures) + cols - 1) // cols, 1)
        scroll.setWidget(inner)

        footer = Footer()
        self.status = label("", "footerText")
        footer.row.addWidget(self.status, 1)
        n_ch = sum(len(fx.channels()) for fx in rig.fixtures)
        footer.row.addWidget(label(f"{len(rig.fixtures)} fixtures  ·  {n_ch} ch", "footerMono"))

        self.setCentralWidget(shell(header, scroll, footer))
        self.resize(1280, 860)
        self._publish()

    def _fixture_group(self, fx) -> QtWidgets.QWidget:
        box = QtWidgets.QGroupBox(f"{fx.label.upper()}  ·  ADDR {fx.address}  ·  {fx.type_name.upper()}")
        form = QtWidgets.QGridLayout(box)
        form.setHorizontalSpacing(theme.SP3)
        form.setVerticalSpacing(0)
        kinds = fx.channel_kinds()
        for local, ch in enumerate(fx.channels()):
            slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
            slider.setRange(0, 255)
            value = label("0", "value")
            value.setMinimumWidth(32)
            value.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            slider.valueChanged.connect(lambda v, c=ch, lbl=value: self._on_change(c, v, lbl))
            self._sliders[ch] = slider
            form.addWidget(label(f"CH {ch}", "value"), local, 0)
            form.addWidget(label(kinds[local].name.lower(), "hint"), local, 1)
            form.addWidget(slider, local, 2)
            form.addWidget(value, local, 3)
        form.setColumnStretch(2, 1)
        btns = QtWidgets.QHBoxLayout()
        btns.setContentsMargins(0, theme.SP2, 0, 0)
        btns.setSpacing(theme.SP2)
        flash = QtWidgets.QPushButton(f"Flash {fx.label}")
        flash.setIcon(icons.icon("flash", theme.TEXT_2, size=16))
        flash.setToolTip("All off, then this fixture at full white, so you can find it on the truss.")
        flash.clicked.connect(lambda _=False, f=fx: self._flash(f))
        btns.addWidget(flash)
        if isinstance(fx, MovingHead):
            # docs/14 §4: jog pan/tilt above to point the real fixture at the
            # stage, then save that as its calibrated home — all scene
            # movement will oscillate around it within a bounded range
            # afterward, instead of the raw wide sweep.
            home_btn = QtWidgets.QPushButton("Save as home position")
            home_btn.setIcon(icons.icon("home", theme.TEXT_2, size=16))
            home_btn.clicked.connect(lambda _=False, f=fx: self._save_home_position(f))
            btns.addWidget(home_btn)
        btns.addStretch(1)
        form.addLayout(btns, len(fx.channels()), 0, 1, 4)
        return box

    # --- actions ---
    def _on_change(self, channel: int, value: int, label: QtWidgets.QLabel) -> None:
        self._uni[channel - 1] = value
        label.setText(str(value))
        self._publish()

    def all_off(self) -> None:
        for ch, slider in self._sliders.items():
            slider.blockSignals(True)
            slider.setValue(0)
            slider.blockSignals(False)
            self._uni[ch - 1] = 0
        self._publish()

    def _flash(self, fx) -> None:
        """Light one fixture to a recognizable state so you can identify it."""
        self.all_off()
        c = Contribution()
        fx.set_intensity(c, 1.0)
        fx.set_color(c, 1.0, 1.0, 1.0)
        for ch in fx.channels():
            v = c.values[ch - 1]
            if c.touched[ch - 1]:
                self._uni[ch - 1] = v
                self._sliders[ch].blockSignals(True)
                self._sliders[ch].setValue(v)
                self._sliders[ch].blockSignals(False)
        self._publish()

    def _save_home_position(self, fx: MovingHead) -> None:
        # 16-bit (2026-09-18): local ch1/ch2 = pan coarse/fine, ch3/ch4 = tilt.
        pan01 = _read16(self._uni, fx.offset + 0)
        tilt01 = _read16(self._uni, fx.offset + 2)
        fx.home_pan, fx.home_tilt = pan01, tilt01

        default_path = self.rig_path or os.path.join("rigs", "custom_rig.json")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save rig", default_path, "JSON (*.json)")
        if not path:
            return
        try:
            # The shared serializer (fixtures/rig.py) keeps every other
            # field -- mount heights, positions, unknown keys -- intact.
            save_rig(self.rig, path, "Home position saved via the fixture-test panel's Save as Home Position.")
        except RigError as exc:
            self.status.setText(f"Not saved: {exc}")
            theme.set_css(self.status, f"color:{theme.DANGER_TEXT};")
            return
        log.info("Saved %s home position (pan=%.3f tilt=%.3f) to %s", fx.label, pan01, tilt01, path)
        self.status.setText(
            f"Saved {fx.label} home position (pan={pan01:.2f}, tilt={tilt01:.2f}) to {path}. "
            f"Restart with --rig \"{path}\" to apply."
        )
        theme.set_css(self.status, f"color:{theme.ACCENT};")

    def _publish(self) -> None:
        self.frame_buffer.publish(bytes(self._uni))


def run_fixture_test(rig: Rig, backend, clock, dmx_rate_hz: float = 40.0, rig_path: str | None = None) -> int:
    """Open the fixture-test panel, driving ``backend`` via a DMX writer (blocks)."""
    import threading

    from ..output.writer import DmxWriter

    qt = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    frame_buffer = DmxFrameBuffer()
    stop = threading.Event()
    writer = DmxWriter(frame_buffer, backend, clock, stop, hz=dmx_rate_hz)
    writer.start()
    win = FixtureTestPanel(rig, frame_buffer, rig_path=rig_path)
    win.show()
    try:
        return qt.exec()
    finally:
        stop.set()
        writer.join(timeout=3.0)


def show_fixture_test(rig: Rig, backend, clock, dmx_rate_hz: float = 40.0,
                      rig_path: str | None = None) -> None:
    """The panel as a modal window (the launch dialog's "Flash each light"),
    blocking until it is closed. Everything goes dark before the writer
    stops and the port is released: the Enttec repeats its last frame, so a
    flashed light would otherwise stay on until the show starts."""
    import threading

    from ..output.writer import DmxWriter

    frame_buffer = DmxFrameBuffer()
    stop = threading.Event()
    writer = DmxWriter(frame_buffer, backend, clock, stop, hz=dmx_rate_hz)
    writer.start()
    try:
        win = FixtureTestPanel(rig, frame_buffer, rig_path=rig_path)
        win.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        win.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
        loop = QtCore.QEventLoop()
        win.destroyed.connect(loop.quit)
        win.show()
        loop.exec()
    finally:
        frame_buffer.publish(bytes(UNIVERSE_SIZE))
        clock.sleep(3.0 / dmx_rate_hz)            # a few writer ticks of all-zero
        stop.set()
        writer.join(timeout=3.0)
