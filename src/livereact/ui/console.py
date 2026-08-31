"""Operator console — live readouts + manual controls, around the rig view.

The console embodies "automation is the default; manual is a bias/cap, not an
override" (docs/02 §5): the show always runs itself; the operator only nudges
brightness/strobe-cap/color, arms lasers, or hits the hard switches
(blackout/freeze) and skip/tap-tempo. Readouts make the show legible at a glance.
"""

from __future__ import annotations

import logging

from PySide6 import QtCore, QtGui, QtWidgets

from ..core.messages import BeatMessage
from ..engines.color import band_levels
from ..tap_tempo import TapTempo
from .visualizer import RigView

log = logging.getLogger(__name__)


def _slider(lo: int, hi: int, value: int) -> QtWidgets.QSlider:
    s = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


class ConsoleWindow(QtWidgets.QMainWindow):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self.tap = TapTempo()
        self._tap_beat = 0
        self.setWindowTitle("LiveReact — Operator Console")

        self.rig_view = RigView(app.rig)
        panel = self._build_panel()

        split = QtWidgets.QSplitter()
        split.addWidget(self.rig_view)
        split.addWidget(panel)
        split.setSizes([800, 380])
        self.setCentralWidget(split)
        self.resize(1240, 640)

        self._install_shortcuts()

    # ------------------------------------------------------------------ build
    def _build_panel(self) -> QtWidgets.QWidget:
        m = self.app.manual
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)

        banner = QtWidgets.QLabel("● AUTOMATION RUNNING")
        banner.setStyleSheet("color:#3c6; font-weight:bold;")
        v.addWidget(banner)

        # --- readouts ---
        ro = QtWidgets.QGroupBox("Show")
        form = QtWidgets.QFormLayout(ro)
        self.l_bpm = QtWidgets.QLabel("—")
        self.l_beat = QtWidgets.QLabel("—")
        self.l_deck = QtWidgets.QLabel("—")
        self.l_scene = QtWidgets.QLabel("—")
        self.l_health = QtWidgets.QLabel("—")
        self.pb_energy = QtWidgets.QProgressBar()
        self.pb_energy.setRange(0, 100)
        self.pb_low = QtWidgets.QProgressBar(); self.pb_low.setRange(0, 100)
        self.pb_mid = QtWidgets.QProgressBar(); self.pb_mid.setRange(0, 100)
        self.pb_high = QtWidgets.QProgressBar(); self.pb_high.setRange(0, 100)
        form.addRow("BPM", self.l_bpm)
        form.addRow("Beat / Bar", self.l_beat)
        form.addRow("On-air deck", self.l_deck)
        form.addRow("Scene", self.l_scene)
        form.addRow("Energy", self.pb_energy)
        form.addRow("Low", self.pb_low)
        form.addRow("Mid", self.pb_mid)
        form.addRow("High", self.pb_high)
        form.addRow("Health", self.l_health)
        v.addWidget(ro)

        # --- manual controls (biases/caps) ---
        ctl = QtWidgets.QGroupBox("Manual (bias / cap)")
        cl = QtWidgets.QFormLayout(ctl)
        self.s_bright = _slider(0, 100, int(m.master_brightness * 100))
        self.s_strobe = _slider(0, 100, int(m.strobe_cap * 100))
        self.s_warm = _slider(-100, 100, int(m.warm_cool_bias * 100))
        self.cb_laser = QtWidgets.QCheckBox("Arm lasers")
        self.cb_laser.setChecked(m.laser_enable)
        cl.addRow("Master brightness", self.s_bright)
        cl.addRow("Strobe cap", self.s_strobe)
        cl.addRow("Warm ← → Cool", self.s_warm)
        cl.addRow("Lasers", self.cb_laser)
        v.addWidget(ctl)

        self.s_bright.valueChanged.connect(lambda x: setattr(m, "master_brightness", x / 100))
        self.s_strobe.valueChanged.connect(lambda x: setattr(m, "strobe_cap", x / 100))
        self.s_warm.valueChanged.connect(lambda x: setattr(m, "warm_cool_bias", x / 100))
        self.cb_laser.toggled.connect(lambda on: setattr(m, "laser_enable", on))

        # --- hard switches / actions ---
        btns = QtWidgets.QGroupBox("Actions")
        bl = QtWidgets.QGridLayout(btns)
        self.b_black = QtWidgets.QPushButton("Blackout (B)"); self.b_black.setCheckable(True)
        self.b_freeze = QtWidgets.QPushButton("Freeze (F)"); self.b_freeze.setCheckable(True)
        self.b_skip = QtWidgets.QPushButton("Skip scene (→)")
        self.b_tap = QtWidgets.QPushButton("Tap tempo (T)")
        self.b_burst = QtWidgets.QPushButton("Strobe burst (Space)")
        bl.addWidget(self.b_black, 0, 0); bl.addWidget(self.b_freeze, 0, 1)
        bl.addWidget(self.b_skip, 1, 0); bl.addWidget(self.b_tap, 1, 1)
        bl.addWidget(self.b_burst, 2, 0, 1, 2)
        v.addWidget(btns)
        v.addStretch(1)

        self.b_black.toggled.connect(self._set_blackout)
        self.b_freeze.toggled.connect(lambda on: setattr(m, "freeze", on))
        self.b_skip.clicked.connect(self.app.phrase_engine.skip)
        self.b_tap.clicked.connect(self._do_tap)
        self.b_burst.clicked.connect(self._strobe_burst)
        return w

    def _install_shortcuts(self) -> None:
        def sc(key, fn):
            QtGui.QShortcut(QtGui.QKeySequence(key), self, activated=fn)

        sc("B", self.b_black.toggle)
        sc("F", self.b_freeze.toggle)
        sc(QtCore.Qt.Key.Key_Right, self.app.phrase_engine.skip)
        sc("T", self._do_tap)
        sc(QtCore.Qt.Key.Key_Space, self._strobe_burst)

    # ------------------------------------------------------------------ actions
    def _set_blackout(self, on: bool) -> None:
        self.app.manual.blackout = on
        self.b_black.setStyleSheet("background:#b22; color:white;" if on else "")

    def _do_tap(self) -> None:
        now = self.app.clock.monotonic()
        bpm = self.tap.tap(now)
        if bpm is not None:
            self._tap_beat = self._tap_beat % 4 + 1
            self.app.input_queue.put(BeatMessage(now, self._tap_beat, bpm, is_master=True, player=0))

    def _strobe_burst(self) -> None:
        self.app.manual.strobe_burst = True
        QtCore.QTimer.singleShot(400, lambda: setattr(self.app.manual, "strobe_burst", False))

    # ------------------------------------------------------------------ refresh
    def refresh(self) -> None:
        snap = self.app.show_state.snapshot()
        self.rig_view.update_from_universe(self.app.frame_buffer.latest())

        self.l_bpm.setText(f"{snap.bpm:.1f}")
        self.l_beat.setText(f"beat {snap.beat_in_bar} / bar {snap.bar}")
        self.l_deck.setText(str(snap.master_deck) if snap.master_deck else "—")
        self.l_scene.setText(self.app.phrase_engine.current_scene_name)
        self.pb_energy.setValue(int(snap.energy * 100))
        low, mid, high = band_levels(snap)
        self.pb_low.setValue(int(low * 100))
        self.pb_mid.setValue(int(mid * 100))
        self.pb_high.setValue(int(high * 100))

        clock = "free-run" if snap.free_running else "locked"
        trans = "  TRANSITION" if snap.in_transition else ""
        pdl = "fresh" if snap.pdl_fresh else "STALE"
        midi = "fresh" if snap.midi_fresh else "stale"
        self.l_health.setText(f"clock {clock} · PDL {pdl} · MIDI {midi}{trans}")


def run_console(app, fps: int = 30) -> int:
    """Open the console and refresh it at ``fps`` (blocks until the window closes)."""
    qt = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    win = ConsoleWindow(app)
    win.show()
    timer = QtCore.QTimer()
    timer.timeout.connect(win.refresh)
    timer.start(int(1000 / fps))
    return qt.exec()
