"""Operator console — live readouts + manual controls, around the rig view.

The console embodies "automation is the default; manual is a bias/cap, not an
override" (docs/02 §5): the show always runs itself; the operator only nudges
brightness/strobe-cap/color, arms lasers, or hits the hard switches
(blackout/freeze) and skip/tap-tempo. Readouts make the show legible at a glance.
"""

from __future__ import annotations

import json
import logging
import os

from PySide6 import QtCore, QtGui, QtWidgets

from ..core.messages import BeatMessage
from ..engines.color import band_levels
from ..fixtures.rig import RigError, _rig_from_dict
from ..tap_tempo import TapTempo
from .rig_config import RigConfigTab
from .visualizer import RigView

log = logging.getLogger(__name__)


def _slider(lo: int, hi: int, value: int) -> QtWidgets.QSlider:
    s = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


_DOT_OK = "color:#3c6; font-weight:bold;"
_DOT_BAD = "color:#c33; font-weight:bold;"


def _status_dot(label: str) -> QtWidgets.QLabel:
    """A glanceable red/green connection indicator (● label)."""
    dot = QtWidgets.QLabel(f"● {label}")
    dot.setStyleSheet(_DOT_BAD)
    return dot


def _set_dot(dot: QtWidgets.QLabel, ok: bool) -> None:
    dot.setStyleSheet(_DOT_OK if ok else _DOT_BAD)


class ConsoleWindow(QtWidgets.QMainWindow):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self.tap = TapTempo()
        self._tap_beat = 0
        self.setWindowTitle("LiveReact — Operator Console")

        self.rig_view = RigView(app.rig)
        rig_view_container = self._build_rig_view_container()
        panel = self._build_panel()

        split = QtWidgets.QSplitter()
        split.addWidget(rig_view_container)
        split.addWidget(panel)
        split.setSizes([800, 380])

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(split, "Show")
        tabs.addTab(RigConfigTab(app.rig, getattr(app.config, "rig_path", None)), "Rig Config")
        self.setCentralWidget(tabs)
        self.resize(1240, 640)

        self._install_shortcuts()

    # ------------------------------------------------------------------ build
    def _build_rig_view_container(self) -> QtWidgets.QWidget:
        """The rig view plus a small toolbar for arranging the virtual rig to
        match a real venue's physical layout — drag fixtures around, then
        Save Layout persists positions to the rig file (Reset Layout clears
        back to the default role/side schematic)."""
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)

        bar = QtWidgets.QHBoxLayout()
        bar.addWidget(QtWidgets.QLabel("Drag fixtures to match your venue's layout:"))
        bar.addStretch(1)
        reset_btn = QtWidgets.QPushButton("Reset Layout")
        reset_btn.clicked.connect(self._reset_layout)
        save_btn = QtWidgets.QPushButton("Save Layout…")
        save_btn.clicked.connect(self._save_layout)
        bar.addWidget(reset_btn)
        bar.addWidget(save_btn)
        v.addLayout(bar)
        v.addWidget(self.rig_view)

        self.l_layout_status = QtWidgets.QLabel("")
        v.addWidget(self.l_layout_status)
        return w

    def _reset_layout(self) -> None:
        self.rig_view.reset_layout()
        self.l_layout_status.setText("")

    def _save_layout(self) -> None:
        positions = self.rig_view.fixture_positions()
        slots = []
        for fx in self.app.rig.fixtures:
            key = getattr(fx, "slot_id", fx.label)
            x, y = positions.get(key, (0.5, 0.5))
            slots.append({
                "slot_id": key,
                "label": fx.label,
                "fixture_type": fx.type_name,
                "dmx_address": fx.address,
                "role": fx.role,
                "side": fx.side,
                "x": round(x, 4),
                "y": round(y, 4),
            })
        data = {
            "name": self.app.rig.name,
            "description": "Positions edited via the LiveReact console's Show tab (drag layout).",
            "slots": slots,
        }
        try:
            _rig_from_dict(data)  # same overlap/overflow/unknown-type validation the loader uses
        except RigError as exc:
            self.l_layout_status.setText(f"Not saved — {exc}")
            self.l_layout_status.setStyleSheet(_DOT_BAD)
            return

        default_path = getattr(self.app.config, "rig_path", None) or os.path.join("rigs", "custom_rig.json")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save rig layout", default_path, "JSON (*.json)")
        if not path:
            return
        dirname = os.path.dirname(path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        log.info("Saved rig layout to %s", path)
        self.l_layout_status.setText(f"Saved to {path} — restart with --rig \"{path}\" to apply.")
        self.l_layout_status.setStyleSheet(_DOT_OK)

    def _build_panel(self) -> QtWidgets.QWidget:
        m = self.app.manual
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)

        banner = QtWidgets.QLabel("● AUTOMATION RUNNING")
        banner.setStyleSheet("color:#3c6; font-weight:bold;")
        v.addWidget(banner)

        # --- connection status (red/green — is the rig actually hooked up?) ---
        conn = QtWidgets.QGroupBox("Connections")
        cf = QtWidgets.QHBoxLayout(conn)
        self.dot_pdl = _status_dot("DJ BOARD (Link)")
        self.dot_midi = _status_dot("DJ BOARD (MIDI)")
        self.dot_audio = _status_dot("DJ BOARD (Audio)")
        self.dot_dmx = _status_dot("LIGHTS (DMX)")
        cf.addWidget(self.dot_pdl)
        cf.addWidget(self.dot_midi)
        cf.addWidget(self.dot_audio)
        cf.addWidget(self.dot_dmx)
        v.addWidget(conn)

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
        # engines/laser.py: lit while the laser layer's DROP/PEAK gate is open --
        # armed alone isn't enough to see the laser, and it needs real audio +
        # PDL connected at all.
        self.l_laser_flash = QtWidgets.QLabel("")
        cl.addRow("Master brightness", self.s_bright)
        cl.addRow("Strobe cap", self.s_strobe)
        cl.addRow("Warm ← → Cool", self.s_warm)
        cl.addRow("Lasers", self.cb_laser)
        cl.addRow("", self.l_laser_flash)
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
        # docs/14 §2: distinguishes the system's auto-blackout (no music detected)
        # from the operator's manual toggle above — they're independent triggers,
        # so the manual button's own checked-state won't reflect the auto one.
        self.l_auto_blackout = QtWidgets.QLabel("")
        bl.addWidget(self.b_black, 0, 0); bl.addWidget(self.b_freeze, 0, 1)
        bl.addWidget(self.b_skip, 1, 0); bl.addWidget(self.b_tap, 1, 1)
        bl.addWidget(self.b_burst, 2, 0, 1, 2)
        bl.addWidget(self.l_auto_blackout, 3, 0, 1, 2)
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

        # connection dots: PDL/MIDI green only once real beat data is flowing (not
        # just a device seen on the wire); DMX green only once a real hardware
        # backend (not the null/log fallback) has successfully opened.
        _set_dot(self.dot_pdl, snap.pdl_fresh)
        _set_dot(self.dot_midi, snap.midi_fresh)
        _set_dot(self.dot_audio, snap.audio_fresh)
        writer = self.app.writer
        dmx_ok = writer.is_open and writer.backend.name != "null-log"
        _set_dot(self.dot_dmx, dmx_ok)

        if self.app.show_engine.silence.active:
            self.l_auto_blackout.setText("● AUTO-BLACKOUT — no music detected")
            self.l_auto_blackout.setStyleSheet(_DOT_BAD)
        else:
            self.l_auto_blackout.setText("")

        if self.app.laser_engine.active:
            self.l_laser_flash.setText("● LASER ON")
            self.l_laser_flash.setStyleSheet(_DOT_OK)
        else:
            self.l_laser_flash.setText("")


def run_console(app, fps: int = 30) -> int:
    """Open the console and refresh it at ``fps`` (blocks until the window closes)."""
    qt = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    win = ConsoleWindow(app)
    win.show()
    timer = QtCore.QTimer()
    timer.timeout.connect(win.refresh)
    timer.start(int(1000 / fps))
    return qt.exec()
