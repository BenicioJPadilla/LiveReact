"""Operator console — live readouts + manual controls, around the rig view.

The console embodies "automation is the default; manual is a bias/cap, not an
override" (docs/02 §5): the show always runs itself; the operator only nudges
brightness/strobe-cap/color, arms lasers, or hits the hard switches
(blackout/freeze) and skip/tap-tempo. Readouts make the show legible at a glance.

Layout (2026-09-18 redesign, Josh: "easy to see, organized by section and
function so I can track and press buttons while I am DJing"):

    STATUS strip   connections · BPM · beat/bar · deck · scene · BUCKET · health
    left column    live mini-map (read-only) + the status banners + energy bars
    right column   CUES (the big four) · SAFETY / OVERRIDES · FEEL (sliders)

Every control keeps the attribute name and keyboard shortcut it had before
(tests/test_console.py finds them that way); only the grouping, sizing and
theme (ui/theme.py) changed.
"""

from __future__ import annotations

import logging

from PySide6 import QtCore, QtGui, QtWidgets

from ..core.messages import BeatMessage
from ..engines.color import band_levels
from ..tap_tempo import TapTempo
from .floorplan import FloorPlanView
from .rig_config import RigConfigTab
from .theme import MUTED, apply_theme, bucket_color
from .venue_tab import VenueTab

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


def _readout(caption: str, value_label: QtWidgets.QLabel) -> QtWidgets.QWidget:
    """A small caption over a big value, for the status strip."""
    w = QtWidgets.QWidget()
    v = QtWidgets.QVBoxLayout(w)
    v.setContentsMargins(6, 0, 6, 0)
    v.setSpacing(0)
    cap = QtWidgets.QLabel(caption.upper())
    cap.setStyleSheet(f"color:{MUTED}; font-size:11px; font-weight:700;")
    value_label.setObjectName("status")
    v.addWidget(cap)
    v.addWidget(value_label)
    return w


def _button(text: str, role: str | None = None, checkable: bool = False) -> QtWidgets.QPushButton:
    b = QtWidgets.QPushButton(text)
    if role:
        b.setObjectName(role)  # styled by ui/theme.py (#cue / #danger)
    b.setCheckable(checkable)
    b.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
    return b


class ConsoleWindow(QtWidgets.QMainWindow):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self.tap = TapTempo()
        self._tap_beat = 0
        self.setWindowTitle("LiveReact — Operator Console")
        apply_theme()

        # Live floor plan on the Show tab: view only, nothing draggable mid-set.
        self.rig_view = FloorPlanView(app.rig, editable=False)

        show = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(show)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)
        outer.addWidget(self._build_status_strip())

        split = QtWidgets.QSplitter()
        split.addWidget(self._build_left_column())
        split.addWidget(self._build_right_column())
        split.setSizes([720, 520])
        outer.addWidget(split, 1)

        rig_path = getattr(app.config, "rig_path", None)
        # Venue tab: the editable floor plan + head calibration. Its jog/probe
        # pins land on app.manual.calibration (read once per show-engine tick)
        # and are cleared the moment the operator leaves the tab.
        self.venue_tab = VenueTab(app.rig, rig_path,
                                  on_pins=lambda pins: setattr(app.manual, "calibration", pins),
                                  is_frozen=lambda: app.manual.freeze)
        tabs = QtWidgets.QTabWidget()
        tabs.addTab(show, "Show")
        tabs.addTab(self.venue_tab, "Venue")
        tabs.addTab(RigConfigTab(app.rig, rig_path), "Rig Config")
        tabs.currentChanged.connect(self._tab_changed)
        self.tabs = tabs
        self.setCentralWidget(tabs)
        self.resize(1280, 800)

        self._install_shortcuts()

    def _tab_changed(self, idx: int) -> None:
        if self.tabs.widget(idx) is not self.venue_tab:
            self.venue_tab.deactivate()
            self.venue_tab.plan.select("")
        # the Venue plan is rebuilt on edits; the Show mini-map shares the
        # same rig objects, so re-layout it whenever we come back to Show
        if idx == 0:
            self.rig_view.refresh_layout()

    # ------------------------------------------------------------------ build
    def _build_status_strip(self) -> QtWidgets.QWidget:
        """One row across the top: is everything connected, and where in the
        music are we. Read at a glance between mixes."""
        w = QtWidgets.QGroupBox("Status")
        h = QtWidgets.QHBoxLayout(w)
        h.setSpacing(12)

        self.dot_pdl = _status_dot("LINK")
        self.dot_midi = _status_dot("MIDI")
        self.dot_audio = _status_dot("AUDIO")
        self.dot_dmx = _status_dot("DMX")
        conn = QtWidgets.QWidget()
        cv = QtWidgets.QVBoxLayout(conn)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        row1 = QtWidgets.QHBoxLayout(); row1.addWidget(self.dot_pdl); row1.addWidget(self.dot_midi)
        row2 = QtWidgets.QHBoxLayout(); row2.addWidget(self.dot_audio); row2.addWidget(self.dot_dmx)
        cv.addLayout(row1)
        cv.addLayout(row2)
        h.addWidget(conn)

        self.l_bpm = QtWidgets.QLabel("—")
        self.l_beat = QtWidgets.QLabel("—")
        self.l_deck = QtWidgets.QLabel("—")
        self.l_scene = QtWidgets.QLabel("—")
        self.l_health = QtWidgets.QLabel("—")
        # Energy bucket (core/show_state.py's debounced `bucket`) -- the single
        # most useful "what does the show think is happening" readout, never
        # shown before 2026-09-18.
        self.l_bucket = QtWidgets.QLabel("—")
        self.l_bucket.setObjectName("bucket")
        self.l_bucket.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.l_bucket.setMinimumWidth(110)

        h.addWidget(_readout("BPM", self.l_bpm))
        h.addWidget(_readout("Beat / Bar", self.l_beat))
        h.addWidget(_readout("Deck", self.l_deck))
        h.addWidget(_readout("Scene", self.l_scene), 1)
        h.addWidget(_readout("Bucket", self.l_bucket))
        self.l_health.setStyleSheet(f"color:{MUTED};")
        h.addWidget(self.l_health)
        return w

    def _build_left_column(self) -> QtWidgets.QWidget:
        """Live mini-map + the status banners + the energy bars."""
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        rig = QtWidgets.QGroupBox("Rig (live)")
        rv = QtWidgets.QVBoxLayout(rig)
        rv.addWidget(self.rig_view, 1)
        # Banner labels: what the automation is doing right now.
        self.l_cue = QtWidgets.QLabel("")
        self.l_arm = QtWidgets.QLabel("")
        self.l_laser_flash = QtWidgets.QLabel("")
        self.l_synth = QtWidgets.QLabel("")
        # docs/14 §2: distinguishes the system's auto-blackout (no music detected)
        # from the operator's manual toggle — they're independent triggers,
        # so the manual button's own checked-state won't reflect the auto one.
        self.l_auto_blackout = QtWidgets.QLabel("")
        for lbl in (self.l_cue, self.l_arm, self.l_laser_flash, self.l_synth, self.l_auto_blackout):
            lbl.setWordWrap(True)
            rv.addWidget(lbl)
        v.addWidget(rig, 1)

        energy = QtWidgets.QGroupBox("Energy")
        form = QtWidgets.QFormLayout(energy)
        self.pb_energy = QtWidgets.QProgressBar(); self.pb_energy.setRange(0, 100)
        self.pb_low = QtWidgets.QProgressBar(); self.pb_low.setRange(0, 100); self.pb_low.setObjectName("low")
        self.pb_mid = QtWidgets.QProgressBar(); self.pb_mid.setRange(0, 100); self.pb_mid.setObjectName("mid")
        self.pb_high = QtWidgets.QProgressBar(); self.pb_high.setRange(0, 100); self.pb_high.setObjectName("high")
        for pb in (self.pb_energy, self.pb_low, self.pb_mid, self.pb_high):
            pb.setTextVisible(False)
        form.addRow("Energy", self.pb_energy)
        form.addRow("Low", self.pb_low)
        form.addRow("Mid", self.pb_mid)
        form.addRow("High", self.pb_high)
        v.addWidget(energy)
        return w

    def _build_right_column(self) -> QtWidgets.QWidget:
        m = self.app.manual
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        # --- CUES: what Josh reaches for mid-set --------------------------
        cues = QtWidgets.QGroupBox("Cues")
        cl = QtWidgets.QGridLayout(cues)
        cl.setSpacing(8)
        # DJ build cue (2026-09-16, core/metronome.py's cue_build): BUILD now,
        # held until the drop lands (or 32 bars, or a second press cancels).
        self.b_cue = _button("CUE BUILD\n(C)", "cue")
        # DJ drop arm (2026-09-17, core/metronome.py's arm_drop): the next
        # drop-level kick commits the drop instantly. Pressed again while
        # armed (2026-09-19): the drop CUTS on the next downbeat regardless.
        self.b_arm = _button("ARM DROP\n(D)", "cue")
        self.b_burst = _button("STROBE BURST\n(Space)", "cue")
        self.b_skip = _button("SKIP SCENE\n(→)", "cue")
        # Manual laser cue (2026-09-30, engines/laser.py MANUAL CUE): held
        # (checkable), the dotted line shows with its sweep speed following
        # the mids + highs. Also drivable from a MIDI-learned "laser_cue"
        # control (inputs/midi_map.py); refresh() mirrors that back here.
        self.b_laser_cue = _button("CUE LASER\n(K)", "cue", checkable=True)
        self.b_laser_cue.setChecked(m.laser_cue)
        self.b_tap = _button("Tap tempo (T)")
        cl.addWidget(self.b_cue, 0, 0); cl.addWidget(self.b_arm, 0, 1)
        cl.addWidget(self.b_burst, 1, 0); cl.addWidget(self.b_skip, 1, 1)
        cl.addWidget(self.b_laser_cue, 2, 0); cl.addWidget(self.b_tap, 2, 1)
        v.addWidget(cues)

        # --- SAFETY / OVERRIDES: the hard switches ------------------------
        safe = QtWidgets.QGroupBox("Safety / Overrides")
        sl = QtWidgets.QGridLayout(safe)
        sl.setSpacing(8)
        self.b_black = _button("BLACKOUT (B)", "danger", checkable=True)
        self.b_freeze = _button("FREEZE (F)", "danger", checkable=True)
        # Arming is per run, per track (2026-09-16): never persisted, off at
        # every launch -- Josh picks the tunes that get the laser, since the
        # software can't (see engines/laser.py). L toggles it.
        self.cb_laser = QtWidgets.QCheckBox("Arm lasers (L) — off at launch, arm per track")
        self.cb_laser.setChecked(m.laser_enable)
        sl.addWidget(self.b_black, 0, 0); sl.addWidget(self.b_freeze, 0, 1)
        sl.addWidget(self.cb_laser, 1, 0, 1, 2)
        v.addWidget(safe)

        # --- FEEL: biases/caps, never overrides ---------------------------
        feel = QtWidgets.QGroupBox("Feel (bias / cap)")
        fl = QtWidgets.QFormLayout(feel)
        self.s_bright = _slider(0, 100, int(m.master_brightness * 100))
        self.s_strobe = _slider(0, 100, int(m.strobe_cap * 100))
        self.s_warm = _slider(-100, 100, int(m.warm_cool_bias * 100))
        # Synth Sync (Josh, 2026-09-15): wash follows the synths/stabs (the mid
        # band) and strobes pause -- see engines/reactive.py's SYNTH_* block.
        self.cb_synth = QtWidgets.QCheckBox("Synth Sync (S) — wash follows the synths")
        self.cb_synth.setChecked(m.synth_sync)
        fl.addRow("Master brightness", self.s_bright)
        fl.addRow("Strobe cap", self.s_strobe)
        fl.addRow("Warm ← → Cool", self.s_warm)
        fl.addRow("", self.cb_synth)
        v.addWidget(feel)
        v.addStretch(1)

        # wiring
        self.s_bright.valueChanged.connect(lambda x: setattr(m, "master_brightness", x / 100))
        self.s_strobe.valueChanged.connect(lambda x: setattr(m, "strobe_cap", x / 100))
        self.s_warm.valueChanged.connect(lambda x: setattr(m, "warm_cool_bias", x / 100))
        self.cb_laser.toggled.connect(lambda on: setattr(m, "laser_enable", on))
        self.b_laser_cue.toggled.connect(lambda on: setattr(m, "laser_cue", on))
        self.cb_synth.toggled.connect(lambda on: setattr(m, "synth_sync", on))
        self.b_black.toggled.connect(self._set_blackout)
        self.b_freeze.toggled.connect(lambda on: setattr(m, "freeze", on))
        self.b_skip.clicked.connect(self.app.phrase_engine.skip)
        self.b_tap.clicked.connect(self._do_tap)
        self.b_burst.clicked.connect(self._strobe_burst)
        self.b_cue.clicked.connect(self.app.metronome.cue_build)
        self.b_arm.clicked.connect(self.app.metronome.arm_drop)
        return w

    def _install_shortcuts(self) -> None:
        def sc(key, fn):
            QtGui.QShortcut(QtGui.QKeySequence(key), self, activated=fn)

        sc("B", self.b_black.toggle)
        sc("F", self.b_freeze.toggle)
        sc(QtCore.Qt.Key.Key_Right, self.app.phrase_engine.skip)
        sc("T", self._do_tap)
        sc("S", self.cb_synth.toggle)
        sc("L", self.cb_laser.toggle)
        sc("K", self.b_laser_cue.toggle)
        sc("C", self.app.metronome.cue_build)
        sc("D", self.app.metronome.arm_drop)
        sc(QtCore.Qt.Key.Key_Space, self._strobe_burst)

    # ------------------------------------------------------------------ actions
    def _set_blackout(self, on: bool) -> None:
        self.app.manual.blackout = on

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
        latest = self.app.frame_buffer.latest()
        if self.tabs.currentWidget() is self.venue_tab:
            self.venue_tab.plan.update_from_universe(latest)   # see the jogged head move
        else:
            self.rig_view.update_from_universe(latest)

        self.l_bpm.setText(f"{snap.bpm:.1f}")
        self.l_beat.setText(f"{snap.beat_in_bar} / {snap.bar}")
        self.l_deck.setText(str(snap.master_deck) if snap.master_deck else "—")
        self.l_scene.setText(self.app.phrase_engine.current_scene_name)
        self.l_bucket.setText(snap.bucket.upper())
        self.l_bucket.setStyleSheet(f"background:{bucket_color(snap.bucket)}; color:white;")
        self.pb_energy.setValue(int(snap.energy * 100))
        low, mid, high = band_levels(snap)
        self.pb_low.setValue(int(low * 100))
        self.pb_mid.setValue(int(mid * 100))
        self.pb_high.setValue(int(high * 100))

        clock = "free-run" if snap.free_running else "locked"
        trans = "  TRANSITION" if snap.in_transition else ""
        pdl = "fresh" if snap.pdl_fresh else "STALE"
        midi = "fresh" if snap.midi_fresh else "stale"
        self.l_health.setText(f"clock {clock}\nPDL {pdl} · MIDI {midi}{trans}")

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

        laser = self.app.laser_engine
        # A MIDI "laser_cue" control writes manual.laser_cue directly; keep
        # the button showing the real state without re-firing its toggled slot.
        if self.b_laser_cue.isChecked() != self.app.manual.laser_cue:
            self.b_laser_cue.blockSignals(True)
            self.b_laser_cue.setChecked(self.app.manual.laser_cue)
            self.b_laser_cue.blockSignals(False)
        if laser.manual_cued and not self.app.manual.laser_enable:
            self.l_laser_flash.setText("○ LASER CUED but not armed — press L to arm")
            self.l_laser_flash.setStyleSheet(_DOT_BAD)
        elif laser.manual_cued and laser.source == "manual":
            self.l_laser_flash.setText(f"● LASER CUED (K) — sweep follows mids+highs · {int(laser.sweep * 100)}%")
            self.l_laser_flash.setStyleSheet(_DOT_OK)
        elif laser.manual_cued:
            self.l_laser_flash.setText("○ LASER CUED — waiting for real audio")
            self.l_laser_flash.setStyleSheet(_DOT_BAD)
        elif laser.active:
            self.l_laser_flash.setText("● LASER SWEEP")
            self.l_laser_flash.setStyleSheet(_DOT_OK)
        elif laser.primed:
            self.l_laser_flash.setText("○ laser primed — next 8-bar block")
            self.l_laser_flash.setStyleSheet("")
        else:
            self.l_laser_flash.setText("")

        if self.app.metronome.build_cue_active:
            if self.app.metronome.build_cue_source == "auto":
                self.l_cue.setText("● BUILD (auto: kick back at half the drop's level) — C confirms it")
            else:
                self.l_cue.setText("● BUILD CUED — held until the drop lands (C again cancels)")
            self.l_cue.setStyleSheet(_DOT_OK)
        else:
            self.l_cue.setText("")
        if self.app.metronome.drop_armed:
            src = self.app.metronome.drop_arm_source
            rising = " · RISING" if snap.rising else ""
            if self.app.metronome.drop_cut_pending:
                self.l_arm.setText("● DROP CUT — lands on the next downbeat; D again cancels")
            elif src == "roll":
                self.l_arm.setText(f"● DROP ARMED (snare roll){rising} — the next kick pattern cuts it")
            elif src == "rise":
                self.l_arm.setText(f"● DROP ARMED (intensity rising){rising} — the next kick pattern cuts it")
            else:
                self.l_arm.setText(f"● DROP ARMED (D){rising} — strobe runs while the intensity rises; D again CUTS on the next downbeat")
            self.l_arm.setStyleSheet(_DOT_OK)
        else:
            self.l_arm.setText("")

        if self.app.reactive_engine.synth_sync_active:
            self.l_synth.setText("● SYNTH SYNC — wash follows the mids; strobes cut through")
            self.l_synth.setStyleSheet(_DOT_OK)
        elif self.app.manual.synth_sync:
            self.l_synth.setText("● SYNTH SYNC armed — waiting for real audio")
            self.l_synth.setStyleSheet(_DOT_BAD)
        else:
            self.l_synth.setText("")


def run_console(app, fps: int = 30) -> int:
    """Open the console and refresh it at ``fps`` (blocks until the window closes)."""
    qt = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    apply_theme(qt)
    win = ConsoleWindow(app)
    win.show()
    timer = QtCore.QTimer()
    timer.timeout.connect(win.refresh)
    timer.start(int(1000 / fps))
    return qt.exec()
