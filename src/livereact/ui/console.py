"""Operator console: live readouts + manual controls, around the rig view.

The console embodies "automation is the default; manual is a bias/cap, not an
override" (docs/02 §5): the show always runs itself; the operator only nudges
brightness/strobe-cap/color, arms lasers, or hits the hard switches
(blackout/freeze) and skip/tap-tempo. Readouts make the show legible at a glance.

Layout (2026-10 "Blackbox" redesign, ui/theme.py; the 2026-09-18 grouping by
function is kept, Josh: "easy to see, organized by section and function so I
can track and press buttons while I am DJing"):

    HEADER    wordmark · navigation · status pills (BPM, energy, audio/link/MIDI/DMX)
    left      HERO (energy state, big BPM, beat pulse, tap, band meters)
              live mini-map (read-only) + the activity banners
    right     CUES (the big six) · laser scenes (manual rigs) · FEEL (faders,
              Synth Sync, laser arm) · SAFETY (Blackout / Freeze, bottom right)
    FOOTER    clock / Pro DJ Link / MIDI health, rig, shortcut legend

Navigation is the header's buttons driving ``self.tabs`` (a QTabWidget whose
own tab bar is hidden), so the page order and labels are unchanged.

Every control keeps the attribute name and keyboard shortcut it had before
(tests/test_console.py finds them that way). Refresh does no more work than
before: it reads the same snapshot once, and every colour change goes through
``theme.set_css`` so a widget is only re-polished when its state changes.
"""

from __future__ import annotations

import logging
import os

from PySide6 import QtCore, QtGui, QtWidgets

from ..core.messages import BeatMessage
from ..engines.color import band_levels
from ..engines.laser_feature import MOOD_OFF, laser_color_name
from ..engines.laser_show import MODE_FOLLOW, MODE_HOLD, MODE_ROTATE, look_names
from ..engines.laser_trigger import DUTY_WINDOW_S
from ..tap_tempo import TapTempo
from . import theme
from .floorplan import FloorPlanView
from .rig_config import RigConfigTab
from .theme import (
    ACCENT, DANGER, DANGER_TEXT, LINE_2, SURFACE_2, TEXT_2, WARN,
    apply_theme, bucket_color, chip_css, rgba, set_css,
)
from .venue_tab import VenueTab
from .widgets import (
    AppHeader, BeatPulse, Card, CueButton, Footer, Meter, StatusPill,
    hbox, label, overline, shell,
)

log = logging.getLogger(__name__)


def _slider(lo: int, hi: int, value: int, role: str = "fader") -> QtWidgets.QSlider:
    s = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
    s.setObjectName(role)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


# Activity-banner tones (the leading ●/○ in each text is the status dot).
_TONES = {
    "ok": f"color:{ACCENT}; background:{rgba(ACCENT, 0.07)}; border:1px solid {rgba(ACCENT, 0.28)};",
    "bad": f"color:{DANGER_TEXT}; background:{rgba(DANGER, 0.08)}; border:1px solid {rgba(DANGER, 0.32)};",
    "muted": f"color:{TEXT_2}; background:{SURFACE_2}; border:1px solid {LINE_2};",
}
# Feature-profile laser moods (engines/laser_feature.py) -> chip colors, calm
# to fan reading cool to hot like the bucket chip does.
_MOOD_COLORS = {
    MOOD_OFF: TEXT_2,
    "calm": theme.BUCKET_COLORS["break"],
    "tension": WARN,
    "groove": "#A98BFF",
    "fan": theme.BUCKET_COLORS["drop"],
}


def _say(lbl: QtWidgets.QLabel, text: str, tone: str = "ok") -> None:
    """Set an activity banner: text, tone, and hidden while empty."""
    lbl.setText(text)
    if text:
        set_css(lbl, _TONES[tone])
    if lbl.isHidden() == bool(text):
        lbl.setVisible(bool(text))


def _set_dot(pill: StatusPill, seg: int, ok: bool) -> None:
    pill.set(seg, tone="ok" if ok else "bad")


def _button(text: str, role: str | None = None, checkable: bool = False) -> QtWidgets.QPushButton:
    b = QtWidgets.QPushButton(text)
    if role:
        b.setObjectName(role)  # styled by ui/theme.py (#look / #danger)
    b.setCheckable(checkable)
    b.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
    return b


class ConsoleWindow(QtWidgets.QMainWindow):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self.tap = TapTempo()
        self._tap_beat = 0
        self._last = {}  # refresh(): last value per readout, to skip no-op updates
        self.setWindowTitle("LiveReact · Console")
        apply_theme()

        # Live floor plan on the Show tab: view only, nothing draggable mid-set.
        self.rig_view = FloorPlanView(app.rig, editable=False)

        rig_path = getattr(app.config, "rig_path", None)
        # Venue tab: the editable floor plan + head calibration. Its jog/probe
        # pins land on app.manual.calibration (read once per show-engine tick)
        # and are cleared the moment the operator leaves the tab.
        self.venue_tab = VenueTab(app.rig, rig_path,
                                  on_pins=lambda pins: setattr(app.manual, "calibration", pins),
                                  is_frozen=lambda: app.manual.freeze)
        tabs = QtWidgets.QTabWidget()
        tabs.tabBar().hide()                 # the header's nav buttons drive it
        tabs.setDocumentMode(True)
        tabs.addTab(self._build_show_page(), "Show")
        # Laser Show tab (2026-10-08): only for rigs on the `show` laser
        # profile (engines/laser_show.py) -- the other profiles have nothing
        # to pick here.
        self.laser_show_tab = None
        if getattr(app.rig, "laser_profile", "") == "show":
            self.laser_show_tab = self._build_laser_show_tab()
            tabs.addTab(self.laser_show_tab, "Laser Show")
        tabs.addTab(self.venue_tab, "Venue")
        tabs.addTab(RigConfigTab(app.rig, rig_path), "Rig Config")
        self.tabs = tabs

        self.header = self._build_header()
        self.footer = self._build_footer(rig_path)
        tabs.currentChanged.connect(self._tab_changed)
        self.setCentralWidget(shell(self.header, tabs, self.footer))
        self.resize(1440, 900)

        self._install_shortcuts()

    def _tab_changed(self, idx: int) -> None:
        if self.tabs.widget(idx) is not self.venue_tab:
            self.venue_tab.deactivate()
            self.venue_tab.plan.select("")
        # the Venue plan is rebuilt on edits; the Show mini-map shares the
        # same rig objects, so re-layout it whenever we come back to Show
        if idx == 0:
            self.rig_view.refresh_layout()
        b = self._nav_buttons.get(idx)
        if b is not None and not b.isChecked():
            b.setChecked(True)

    # ------------------------------------------------------------------ shell
    def _build_header(self) -> AppHeader:
        h = AppHeader(mode="demo" if getattr(self.app.config, "demo", False) else "live")
        nav_icons = {"Show": ("Show", "show"), "Laser Show": ("Lasers", "laser"),
                     "Venue": ("Venue", "venue"), "Rig Config": ("Rig", "rig")}
        self._nav_buttons: dict[int, QtWidgets.QPushButton] = {}
        for i in range(self.tabs.count()):
            text, ic = nav_icons.get(self.tabs.tabText(i), (self.tabs.tabText(i), "show"))
            b = h.add_nav(text, ic)
            b.clicked.connect(lambda _c=False, i=i: self.tabs.setCurrentIndex(i))
            self._nav_buttons[i] = b
        self._nav_buttons[0].setChecked(True)
        ft = h.add_nav("Fixture test", "fixture_test", checkable=False)
        ft.setToolTip("Raw DMX channel test. Runs as its own mode, with the show stopped.")
        ft.clicked.connect(self._explain_fixture_test)

        # Live-state pill: only shown while a kill switch / failsafe holds the rig.
        self.pill_live = StatusPill([("BLACKOUT", "bad")])
        self.pill_live.set_strong(True)
        self.pill_live.hide()
        self.pill_bpm = StatusPill([("BPM", "ok")], mono_value=True)
        self.pill_state = StatusPill([("--", "idle")])
        # Connection dots: one capsule, four segments (kept as dot_* for callers).
        self.pill_conn = StatusPill([("Audio", "bad"), ("Link", "bad"), ("MIDI", "bad"), ("DMX", "bad")])
        self.pill_conn.setToolTip("Audio / Pro DJ Link / MIDI turn green once real data is flowing, "
                                  "DMX once a hardware output (not the log fallback) is open.")
        for w in (self.pill_live, self.pill_bpm, self.pill_state, self.pill_conn):
            h.add_right(w)
        return h

    def _build_footer(self, rig_path: str | None) -> Footer:
        f = Footer()
        self.l_health = label("", "footerMono")
        f.row.addWidget(self.l_health)
        f.row.addStretch(1)
        rig = self.app.rig
        n_ch = sum(len(fx.channels()) for fx in rig.fixtures)
        rig_name = os.path.basename(rig_path) if rig_path else "default rig"
        f.row.addWidget(label(f"{rig_name}  ·  {len(rig.fixtures)} fixtures  ·  {n_ch} ch", "footerMono"))
        f.row.addWidget(label("B blackout  F freeze  Space strobe  C build  D drop  → skip  T tap  K/J laser  L arm  S synth",
                           "footerMono"))
        return f

    def _explain_fixture_test(self) -> None:
        # A tooltip, never a dialog: a modal box opened by a stray click
        # mid-set would swallow B / F / Space until it was dismissed.
        b = self.sender()
        QtWidgets.QToolTip.showText(
            b.mapToGlobal(QtCore.QPoint(0, b.height() + 6)),
            "Fixture test runs on its own: it drives raw DMX channels straight to the output and "
            "bypasses the show, so it never runs alongside a live set.\n"
            "Close the console, then start it with:  python -m livereact --fixture-test", b)

    # ------------------------------------------------------------------ show page
    def _build_show_page(self) -> QtWidgets.QWidget:
        show = QtWidgets.QWidget()
        outer = QtWidgets.QHBoxLayout(show)
        outer.setContentsMargins(theme.SP4, theme.SP4, theme.SP4, theme.SP4)
        outer.setSpacing(0)
        split = QtWidgets.QSplitter()
        split.setChildrenCollapsible(False)
        split.addWidget(self._build_left_column())
        split.addWidget(self._build_right_column())
        split.setStretchFactor(0, 11)
        split.setStretchFactor(1, 9)
        split.setSizes([780, 620])
        outer.addWidget(split)
        return show

    def _build_hero(self) -> Card:
        """Energy state, the big BPM, the beat, and the band meters: the
        "where are we in the music" read, between mixes, from arm's length."""
        hero = Card()
        hero.body.setContentsMargins(0, 0, 0, 0)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(0)
        # a bucket-coloured edge down the card's left side
        self.hero_edge = QtWidgets.QFrame()
        self.hero_edge.setFixedWidth(4)
        row.addWidget(self.hero_edge)
        inner = QtWidgets.QVBoxLayout()
        inner.setContentsMargins(theme.SP6, theme.SP4, theme.SP4, theme.SP4)
        inner.setSpacing(theme.SP4)
        row.addLayout(inner, 1)
        hero.body.addLayout(row)
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(theme.SP6)

        state = QtWidgets.QVBoxLayout()
        state.setSpacing(theme.SP2)
        state.addWidget(overline("Energy state"))
        # Energy bucket (core/show_state.py's debounced `bucket`) -- the single
        # most useful "what does the show think is happening" readout.
        self.l_bucket = label("--", "heroState")
        self.l_bucket.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.l_bucket.setMinimumWidth(170)
        state.addWidget(self.l_bucket, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
        state.addSpacing(theme.SP1)
        self.l_scene = label("--", "heroScene")
        state.addWidget(self.l_scene)
        # Laser profile + mood (2026-10-01): "ACCENT" on the home rig; on the
        # bar's feature rig the lasers are the main light, so what they are
        # doing right now (engines/laser_feature.py's mood) sits beside the
        # bucket that drives it.
        self.l_laser = label("--", "bucket")
        self.l_deck = label("--", "heroMeta")
        state.addLayout(hbox(overline("Laser"), self.l_laser, overline("Deck"), self.l_deck,
                             spacing=theme.SP2, stretch_at=4))
        state.addStretch(1)
        top.addLayout(state, 1)

        bpm = QtWidgets.QVBoxLayout()
        bpm.setSpacing(0)
        bpm.addWidget(overline("Tempo"), 0, QtCore.Qt.AlignmentFlag.AlignRight)
        self.l_bpm = label("--.-", "bpm")
        self.l_bpm.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.l_bpm.setMinimumWidth(QtGui.QFontMetrics(theme.font(76, QtGui.QFont.Weight.Bold, mono=True))
                                   .horizontalAdvance("188.8") + 8)
        bpm.addWidget(self.l_bpm)
        self.beat_pulse = BeatPulse()
        self.l_beat = label("--", "heroMeta")
        bpm.addLayout(hbox(self.l_beat, self.beat_pulse, spacing=theme.SP3, stretch_at=0))
        bpm.addStretch(1)
        top.addLayout(bpm)

        self.b_tap = CueButton("Tap", "T", "tap")
        self.b_tap.setFixedWidth(96)
        self.b_tap.setToolTip("Tap tempo: tap along on the beat to set the BPM when there is no beat grid.")
        top.addWidget(self.b_tap)
        inner.addLayout(top)

        meters = QtWidgets.QGridLayout()
        meters.setContentsMargins(0, 0, 0, 0)
        meters.setHorizontalSpacing(theme.SP4)
        meters.setVerticalSpacing(theme.SP1 + 2)
        self.pb_energy = Meter(ACCENT)
        self.pb_low = Meter(theme.BUCKET_COLORS["drop"])
        self.pb_mid = Meter(theme.BUCKET_COLORS["build"])
        self.pb_high = Meter(theme.BUCKET_COLORS["break"])
        for col, (cap, m) in enumerate((("Energy", self.pb_energy), ("Low", self.pb_low),
                                        ("Mid", self.pb_mid), ("High", self.pb_high))):
            meters.addWidget(overline(cap), 0, col)
            meters.addWidget(m, 1, col)
        inner.addLayout(meters)
        return hero

    def _build_left_column(self) -> QtWidgets.QWidget:
        """Hero + live mini-map + the activity banners."""
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(0, 0, theme.SP1, 0)
        v.setSpacing(theme.SP3)
        # --force-start skipped the gear gate: say so for the whole set.
        note = self.app.config.force_start_note
        self.l_forced = label(f"▲ {note}", "banner", wrap=True)
        set_css(self.l_forced, _TONES["bad"])
        v.addWidget(self.l_forced)
        self.l_forced.setVisible(bool(note))
        v.addWidget(self._build_hero())

        rig = Card("Rig", "venue")
        rig.add_accessory(label("LIVE VIEW", "modeBadge"))
        split = QtWidgets.QHBoxLayout()
        split.setSpacing(theme.SP4)
        split.addWidget(self.rig_view, 1)
        rig.body.addLayout(split, 1)
        # Banner labels: what the automation is doing right now.
        self.l_cue = label("", "banner", wrap=True)
        self.l_arm = label("", "banner", wrap=True)
        self.l_laser_flash = label("", "banner", wrap=True)
        self.l_synth = label("", "banner", wrap=True)
        # docs/14 §2: distinguishes the system's auto-blackout (no music detected)
        # from the operator's manual toggle — they're independent triggers,
        # so the manual button's own checked-state won't reflect the auto one.
        self.l_auto_blackout = label("", "banner", wrap=True)
        self.l_idle = label("○ Automation is running the show. Nothing needs you right now.", "idle", wrap=True)
        acts_w = QtWidgets.QWidget()
        acts_w.setFixedWidth(272)
        acts = QtWidgets.QVBoxLayout(acts_w)
        acts.setContentsMargins(0, 0, 0, 0)
        acts.setSpacing(theme.SP2)
        acts.addWidget(overline("Activity"))
        for lbl in (self.l_auto_blackout, self.l_cue, self.l_arm, self.l_laser_flash, self.l_synth):
            lbl.hide()
            acts.addWidget(lbl)
        acts.addWidget(self.l_idle)
        acts.addStretch(1)
        split.addWidget(acts_w)
        v.addWidget(rig, 1)
        return w

    def _build_right_column(self) -> QtWidgets.QWidget:
        m = self.app.manual
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(theme.SP1, 0, 0, 0)
        v.setSpacing(theme.SP3)

        # --- SAFETY / OVERRIDES: the hard switches ----------------------
        # Kill switches first: the same spot on every rig and every window
        # size, right under the header, never shuffled by profile-specific cards.
        safe = QtWidgets.QHBoxLayout()
        safe.setSpacing(theme.SP2)
        self.b_black = CueButton("Blackout", "B", "power", role="danger", checkable=True, variant="xl")
        self.b_black.setToolTip("One press kills every fixture. Press again to bring the show back.")
        self.b_freeze = CueButton("Freeze", "F", "freeze", role="danger", checkable=True, variant="xl")
        self.b_freeze.setToolTip("Hold the current look. Press again to release.")
        safe.addWidget(self.b_black, 3)
        safe.addWidget(self.b_freeze, 2)
        v.addLayout(safe)

        # --- CUES: what Josh reaches for mid-set --------------------------
        cues = Card("Cues", "show")
        cl = QtWidgets.QGridLayout()
        cl.setSpacing(theme.SP2)
        # DJ build cue (2026-09-16, core/metronome.py's cue_build): BUILD now,
        # held until the drop lands (or 32 bars, or a second press cancels).
        self.b_cue = CueButton("Cue build", "C", "cue_build")
        self.b_cue.setToolTip("BUILD now, held until the drop lands. Press again to cancel.")
        # DJ drop arm (2026-09-17, core/metronome.py's arm_drop): the next
        # drop-level kick commits the drop instantly. Pressed again while
        # armed (2026-09-19): the drop CUTS on the next downbeat regardless.
        self.b_arm = CueButton("Arm drop", "D", "arm_drop")
        self.b_arm.setToolTip("The next drop-level kick commits the drop. Press again to cut on the next downbeat.")
        self.b_burst = CueButton("Strobe burst", "Space", "strobe")
        self.b_skip = CueButton("Skip scene", "→", "skip")
        # Manual laser cue (2026-09-30, engines/laser.py MANUAL CUE): held
        # (checkable), the dotted line shows with its sweep speed following
        # the mids + highs. Also drivable from a MIDI-learned "laser_cue"
        # control (inputs/midi_map.py); refresh() mirrors that back here.
        self.b_laser_cue = CueButton("Cue laser", "K", "laser", checkable=True)
        self.b_laser_cue.setChecked(m.laser_cue)
        # 2026-10-06 (trigger profile): one laser moment NOW -- the operator's
        # "manual scene button" for the lasers. A counter on ManualParams.
        self.b_laser_hit = CueButton("Laser hit", "J", "laser_hit")
        for i, b in enumerate((self.b_cue, self.b_arm, self.b_burst,
                               self.b_skip, self.b_laser_cue, self.b_laser_hit)):
            cl.addWidget(b, i // 3, i % 3)
        cues.body.addLayout(cl)
        cues.cap_height()
        v.addWidget(cues, 3)

        # --- LASER SCENES (laser profile "manual", 2026-10-10, Junior Crib) --
        # Sophia's Laser Show look buttons, on the Show tab: press a scene to
        # cue it on every head, OFF (the launch state) to kill them. Nothing
        # listens to the music (engines/laser_manual.py). Only rigs on that
        # profile get this group -- every other rig's Show tab is unchanged.
        self.laser_scene_buttons: dict[str, QtWidgets.QPushButton] = {}
        if getattr(self.app.rig, "laser_profile", "") == "manual":
            from ..engines.laser_manual import manual_scene_names as scene_names
            eng = self.app.laser_engine
            lasers = Card("Laser scenes", "laser")
            lasers.add_accessory(label("Press a scene to cue it. Off at launch.", "hint"))
            ll = QtWidgets.QGridLayout()
            ll.setSpacing(theme.SP2)
            self._laser_scene_group = QtWidgets.QButtonGroup(w)
            self._laser_scene_group.setExclusive(True)
            names = ["OFF"] + scene_names()
            for i, name in enumerate(names):
                b = _button(name, "danger" if name == "OFF" else "look", checkable=True)
                self.laser_scene_buttons[name] = b
                self._laser_scene_group.addButton(b)
                ll.addWidget(b, i // 4, i % 4)
                if name == "OFF":
                    b.clicked.connect(eng.off)
                else:
                    b.clicked.connect(lambda _c=False, n=name: eng.cue(n))
            self.laser_scene_buttons[eng.scene or "OFF"].setChecked(True)
            lasers.body.addLayout(ll)
            v.addWidget(lasers)

        # --- FEEL: biases/caps, never overrides ---------------------------
        feel = Card("Feel  ·  bias and caps, never overrides", "sun")
        fl = QtWidgets.QGridLayout()
        fl.setHorizontalSpacing(theme.SP4)
        fl.setVerticalSpacing(theme.SP1)
        self.s_bright = _slider(0, 100, int(m.master_brightness * 100))
        self.s_strobe = _slider(0, 100, int(m.strobe_cap * 100))
        self.s_warm = _slider(-100, 100, int(m.warm_cool_bias * 100), role="bipolar")
        self.l_bright_v = label("", "value")
        self.l_strobe_v = label("", "value")
        self.l_warm_v = label("", "value")
        for r, (cap, s, val) in enumerate((("Master brightness", self.s_bright, self.l_bright_v),
                                           ("Strobe cap", self.s_strobe, self.l_strobe_v),
                                           ("Warm  ·  Cool", self.s_warm, self.l_warm_v))):
            val.setMinimumWidth(48)
            val.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            fl.addWidget(label(cap, "body2"), r, 0)
            fl.addWidget(s, r, 1)
            fl.addWidget(val, r, 2)
        fl.setColumnStretch(1, 1)
        feel.body.addLayout(fl)
        # Synth Sync (Josh, 2026-09-15): wash follows the synths/stabs (the mid
        # band) and strobes pause -- see engines/reactive.py's SYNTH_* block.
        self.cb_synth = QtWidgets.QCheckBox("Synth Sync (S)")
        self.cb_synth.setToolTip("The wash follows the synths (the mid band) and strobes pause.")
        self.cb_synth.setChecked(m.synth_sync)
        # Arming is per run, per track (2026-09-16): never persisted, off at
        # every launch -- Josh picks the tunes that get the laser, since the
        # software can't (see engines/laser.py). L toggles it.
        self.cb_laser = QtWidgets.QCheckBox("Arm lasers (L)")
        self.cb_laser.setToolTip("Off at launch. Arm per track.")
        self.cb_laser.setChecked(m.laser_enable)
        toggles = hbox(self.cb_synth, self.cb_laser, spacing=theme.SP6, stretch_at=2)
        toggles.setContentsMargins(0, theme.SP1, 0, 0)
        feel.body.addLayout(toggles)
        v.addWidget(feel)
        v.addStretch(1)
        # wiring
        self.s_bright.valueChanged.connect(lambda x: setattr(m, "master_brightness", x / 100))
        self.s_strobe.valueChanged.connect(lambda x: setattr(m, "strobe_cap", x / 100))
        self.s_warm.valueChanged.connect(lambda x: setattr(m, "warm_cool_bias", x / 100))
        self.s_bright.valueChanged.connect(lambda x: self.l_bright_v.setText(f"{x}%"))
        self.s_strobe.valueChanged.connect(lambda x: self.l_strobe_v.setText(f"{x}%"))
        self.s_warm.valueChanged.connect(self._show_warm)
        self.l_bright_v.setText(f"{self.s_bright.value()}%")
        self.l_strobe_v.setText(f"{self.s_strobe.value()}%")
        self._show_warm(self.s_warm.value())
        self.cb_laser.toggled.connect(lambda on: setattr(m, "laser_enable", on))
        self.b_laser_cue.toggled.connect(lambda on: setattr(m, "laser_cue", on))
        self.b_laser_hit.clicked.connect(lambda: setattr(m, "laser_hit", m.laser_hit + 1))
        self.cb_synth.toggled.connect(lambda on: setattr(m, "synth_sync", on))
        self.b_black.toggled.connect(self._set_blackout)
        self.b_freeze.toggled.connect(lambda on: setattr(m, "freeze", on))
        self.b_skip.clicked.connect(self.app.phrase_engine.skip)
        self.b_tap.clicked.connect(self._do_tap)
        self.b_burst.clicked.connect(self._strobe_burst)
        self.b_cue.clicked.connect(self.app.metronome.cue_build)
        self.b_arm.clicked.connect(self.app.metronome.arm_drop)
        return w

    def _show_warm(self, x: int) -> None:
        self.l_warm_v.setText("0" if x == 0 else (f"W{-x}" if x < 0 else f"C{x}"))

    def _build_laser_show_tab(self) -> QtWidgets.QWidget:
        """Sophia's Thai (2026-10-08): the laser mode (follow the music /
        rotate / hold), the manual override grid (one button per look --
        pressing one holds it), the drop accent, and the light bar's Synth
        Sync. Everything here is a ManualParams field read by
        engines/laser_show.py or the Synth Sync path in engines/reactive.py
        (unchanged)."""
        m = self.app.manual
        w = QtWidgets.QWidget()
        outer = QtWidgets.QHBoxLayout(w)
        outer.setContentsMargins(theme.SP4, theme.SP4, theme.SP4, theme.SP4)
        outer.setSpacing(theme.SP3)
        left = QtWidgets.QVBoxLayout()
        left.setSpacing(theme.SP3)

        modes = Card("Laser mode", "laser")
        self.rb_laser_follow = QtWidgets.QRadioButton(
            "Follow the music\nbreak: Slow Rainbow · build: Tension ramp · armed: chop · "
            "drop: Fan 8 bars then Rainbow · peak: Ping-Pong")
        self.rb_laser_rotate = QtWidgets.QRadioButton("Rotate\nthe static scenes every 16 bars, starting from the picked one")
        self.rb_laser_hold = QtWidgets.QRadioButton("Hold one look\nmanual override: pick it on the right")
        self._laser_mode_buttons = {MODE_FOLLOW: self.rb_laser_follow, MODE_ROTATE: self.rb_laser_rotate,
                                    MODE_HOLD: self.rb_laser_hold}
        self._laser_mode_buttons.get(m.laser_mode, self.rb_laser_follow).setChecked(True)
        for rb in self._laser_mode_buttons.values():
            rb.setObjectName("option")
            modes.body.addWidget(rb)
        self.cb_laser_accent = QtWidgets.QCheckBox("Drop accent in rotate / hold\n"
                                                   "chop the lasers at 8th notes for 2 bars when a drop lands")
        self.cb_laser_accent.setChecked(m.laser_drop_accent)
        modes.body.addWidget(self.cb_laser_accent)
        left.addWidget(modes)

        status = Card("Now playing", "show")
        self.l_laser_show = label("", "banner", wrap=True)
        status.body.addWidget(self.l_laser_show)
        left.addWidget(status)

        bar = Card("Light bar", "rig")
        self.cb_synth_bar = QtWidgets.QCheckBox("SynthSync (light bar)")
        self.cb_synth_bar.setChecked(m.synth_sync)
        bar.body.addWidget(self.cb_synth_bar)
        left.addWidget(bar)
        left.addStretch(1)

        looks = Card("Looks", "laser_hit")
        looks.add_accessory(label("Press one to hold it (manual override)", "hint"))
        gl = QtWidgets.QGridLayout()
        gl.setSpacing(theme.SP2)
        self.laser_look_buttons: dict[str, QtWidgets.QPushButton] = {}
        self._laser_look_group = QtWidgets.QButtonGroup(w)
        self._laser_look_group.setExclusive(True)
        for i, name in enumerate(look_names()):
            b = _button(name, "look", checkable=True)  # #look / #look:checked in ui/theme.py
            b.setProperty("variant", "tall")
            b.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
            b.setMaximumHeight(140)
            self.laser_look_buttons[name] = b
            self._laser_look_group.addButton(b)
            gl.addWidget(b, i // 3, i % 3)
        if m.laser_scene in self.laser_look_buttons:
            self.laser_look_buttons[m.laser_scene].setChecked(True)
        looks.body.addLayout(gl, 4)
        looks.body.addStretch(1)       # once the buttons hit their cap, the rest pools below

        lw = QtWidgets.QWidget()
        lw.setLayout(left)
        outer.addWidget(lw, 5)
        outer.addWidget(looks, 6)

        for mode, rb in self._laser_mode_buttons.items():
            rb.toggled.connect(lambda on, mode=mode: on and setattr(m, "laser_mode", mode))
        for name, b in self.laser_look_buttons.items():
            b.clicked.connect(lambda _=False, name=name: self._hold_laser_look(name))
        self.cb_laser_accent.toggled.connect(lambda on: setattr(m, "laser_drop_accent", on))
        # Same flag as the Show tab's Synth Sync box (S); refresh() keeps both in step.
        self.cb_synth_bar.toggled.connect(lambda on: setattr(m, "synth_sync", on))
        return w

    def _hold_laser_look(self, name: str) -> None:
        """A look button: pick it and switch to the manual hold."""
        self.app.manual.laser_scene = name
        self.rb_laser_hold.setChecked(True)      # its toggled slot writes laser_mode

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
        sc("J", self.b_laser_hit.click)
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
    def _changed(self, key: str, value) -> bool:
        if self._last.get(key) == value:
            return False
        self._last[key] = value
        return True

    def _refresh_status(self, snap) -> None:
        """Header pills + hero: the parts of refresh that are pure display."""
        bpm = f"{snap.bpm:.1f}"
        self.l_bpm.setText(bpm)
        self.pill_bpm.set(0, value=bpm)
        self.l_beat.setText(f"BAR {snap.bar}")
        self.beat_pulse.set_beat(snap.beat_in_bar, self.app.clock.monotonic())
        self.l_deck.setText(str(snap.master_deck) if snap.master_deck else "--")
        self.l_scene.setText(self.app.phrase_engine.current_scene_name)
        self.l_bucket.setText(snap.bucket.upper())
        if self._changed("bucket", snap.bucket):
            color = bucket_color(snap.bucket)
            set_css(self.l_bucket, chip_css(color, border=False, radius=theme.R_MD))
            set_css(self.hero_edge, f"background:{color}; border-top-left-radius:{theme.R_LG}px;"
                                    f" border-bottom-left-radius:{theme.R_LG}px;")
            self.pill_state.set(0, label=snap.bucket.upper(), tone="ok", color=color)
        self.pb_energy.setValue(int(snap.energy * 100))
        low, mid, high = band_levels(snap)
        self.pb_low.setValue(int(low * 100))
        self.pb_mid.setValue(int(mid * 100))
        self.pb_high.setValue(int(high * 100))

        clock = "free-run" if snap.free_running else "locked"
        trans = "  ·  TRANSITION" if snap.in_transition else ""
        pdl = "fresh" if snap.pdl_fresh else "STALE"
        midi = "fresh" if snap.midi_fresh else "stale"
        self.l_health.setText(f"clock {clock}  ·  PDL {pdl}  ·  MIDI {midi}{trans}")

        # connection dots: PDL/MIDI green only once real beat data is flowing (not
        # just a device seen on the wire); DMX green only once a real hardware
        # backend (not the null/log fallback) has successfully opened.
        _set_dot(self.pill_conn, 0, snap.audio_fresh)
        _set_dot(self.pill_conn, 1, snap.pdl_fresh)
        _set_dot(self.pill_conn, 2, snap.midi_fresh)
        writer = self.app.writer
        _set_dot(self.pill_conn, 3, writer.is_open and writer.backend.name != "null-log")

        manual = self.app.manual
        live = ("BLACKOUT" if manual.blackout else "NO MUSIC · AUTO-BLACKOUT"
                if self.app.show_engine.silence.active else "FROZEN" if manual.freeze else "")
        if self._changed("live", live):
            if live:
                self.pill_live.set(0, label=live, tone="warn" if live == "FROZEN" else "bad")
            self.pill_live.setVisible(bool(live))

    def refresh(self) -> None:
        snap = self.app.show_state.snapshot()
        latest = self.app.frame_buffer.latest()
        current = self.tabs.currentWidget()
        if current is self.venue_tab:
            self.venue_tab.plan.update_from_universe(latest)   # see the jogged head move
        elif self.tabs.currentIndex() == 0:
            self.rig_view.update_from_universe(latest)         # only while it is on screen

        self._refresh_status(snap)

        if self.app.show_engine.silence.active:
            _say(self.l_auto_blackout, "● AUTO-BLACKOUT · no music detected", "bad")
        else:
            _say(self.l_auto_blackout, "")

        laser = self.app.laser_engine
        # A MIDI "laser_cue" control writes manual.laser_cue directly; keep
        # the button showing the real state without re-firing its toggled slot.
        if self.b_laser_cue.isChecked() != self.app.manual.laser_cue:
            self.b_laser_cue.blockSignals(True)
            self.b_laser_cue.setChecked(self.app.manual.laser_cue)
            self.b_laser_cue.blockSignals(False)
        mood = getattr(laser, "mood", None)  # engines/laser_feature.py and laser_trigger.py have one
        trigger = getattr(laser, "trigger", None)  # only engines/laser_trigger.py (2026-10-06)
        scene_name = getattr(laser, "scene_name", None)  # only engines/laser_show.py (2026-10-08)
        if scene_name is not None:
            # Show profile: the chip names the scene; the banner says what the
            # rotation / accent are doing. Keep the Laser Show tab's Synth
            # Sync box in step with the Show tab's (one flag, two boxes).
            if self.laser_show_tab is not None and self.cb_synth_bar.isChecked() != self.app.manual.synth_sync:
                self.cb_synth_bar.blockSignals(True)
                self.cb_synth_bar.setChecked(self.app.manual.synth_sync)
                self.cb_synth_bar.blockSignals(False)
            if self.cb_synth.isChecked() != self.app.manual.synth_sync:
                self.cb_synth.blockSignals(True)
                self.cb_synth.setChecked(self.app.manual.synth_sync)
                self.cb_synth.blockSignals(False)
            accent = bool(getattr(laser, "accent", False))
            mode = getattr(laser, "mode", "")
            self.l_laser.setText(f"SHOW · {scene_name.upper()}" + (" · ACCENT" if accent else ""))
            lit = scene_name.lower() not in ("off", "dark")
            set_css(self.l_laser, chip_css(theme.BUCKET_COLORS["drop"] if accent else ACCENT if lit else TEXT_2))
            if self.app.manual.blackout:
                text, tone = "○ LASERS BLACKED OUT (B)", "bad"
            elif not self.app.manual.laser_enable:
                text, tone = "○ LASERS DISARMED · press L (show profile arms at launch)", "bad"
            else:
                reason = getattr(laser, "reason", "")
                nxt = getattr(laser, "bars_to_next", None)
                if getattr(laser, "rotating", False):
                    tail = f"rotating · next in {int(nxt)} bars" if nxt is not None else "rotating on the clock (no beat grid)"
                    if reason:
                        tail = f"{reason} · {tail}"
                else:
                    tail = reason or mode
                tail = tail.replace(" — ", " · ")
                text = f"● LASER SHOW [{mode}] · {scene_name}{' · DROP ACCENT' if accent else ''} · {tail}"
                tone = "ok"
            _say(self.l_laser_flash, text, tone)
            if self.laser_show_tab is not None:
                _say(self.l_laser_show, text, tone)
                # the grid highlights what is showing NOW (follow / rotate
                # move it around; in hold it is the picked look)
                b = self.laser_look_buttons.get(scene_name)
                if b is not None and not b.isChecked():
                    b.setChecked(True)
                rb = self._laser_mode_buttons.get(mode)
                if rb is not None and not rb.isChecked():
                    rb.blockSignals(True); rb.setChecked(True); rb.blockSignals(False)
            mood = None
        elif mood is None:
            self.l_laser.setText("ACCENT")
            set_css(self.l_laser, chip_css(TEXT_2))
        elif trigger is not None:
            lit = bool(laser.active)
            self.l_laser.setText(f"TRIGGER · {mood.upper()} · {laser.budget:.0%} of {int(DUTY_WINDOW_S)} s")
            set_css(self.l_laser, chip_css(ACCENT if lit else TEXT_2))
            if not self.app.manual.laser_enable:
                _say(self.l_laser_flash, "○ LASERS NOT ARMED · press L (trigger profile: 2-bar moments on the drop / PEAK blocks / a big wub; J = hit now, K = hold)", "bad")
            elif mood == MOOD_OFF:
                _say(self.l_laser_flash, "○ LASER OFF · waiting for real audio", "bad")
            elif lit:
                _say(self.l_laser_flash, f"● LASER MOMENT · {trigger.upper()} · {laser_color_name(laser.color)}", "ok")
            else:
                _say(self.l_laser_flash, "○ lasers dark, ready · next moment on the drop hit, a PEAK block, a big wub, J or K", "muted")
            mood = None  # the feature-profile banners below do not apply
        else:
            self.l_laser.setText(f"FEATURE · {mood.upper()}")
            set_css(self.l_laser, chip_css(_MOOD_COLORS.get(mood, TEXT_2)))
        if scene_name is not None:
            pass  # the show-profile banner above is final
        elif mood is not None:
            # Feature profile banners: the lasers ARE the light here, so "not
            # armed" is the loudest thing the console can say.
            colors = f"{laser_color_name(laser.color_l)} / {laser_color_name(laser.color_r)}"
            if not self.app.manual.laser_enable:
                _say(self.l_laser_flash, "○ LASERS NOT ARMED · press L (feature profile: the lasers are the light)", "bad")
            elif mood == MOOD_OFF:
                _say(self.l_laser_flash, "○ LASER OFF · waiting for real audio", "bad")
            else:
                forced = " (K forcing the fan)" if laser.source == "manual" else ""
                _say(self.l_laser_flash,
                     f"● LASER {mood.upper()}{forced} · {colors} · sweep {int(laser.sweep * 100)}%", "ok")
        elif laser.manual_cued and not self.app.manual.laser_enable:
            _say(self.l_laser_flash, "○ LASER CUED but not armed · press L to arm", "bad")
        elif laser.manual_cued and laser.source == "manual":
            _say(self.l_laser_flash, f"● LASER CUED (K) · sweep follows mids+highs · {int(laser.sweep * 100)}%", "ok")
        elif laser.manual_cued:
            _say(self.l_laser_flash, "○ LASER CUED · waiting for real audio", "bad")
        elif laser.active:
            _say(self.l_laser_flash, "● LASER SWEEP", "ok")
        elif laser.primed:
            _say(self.l_laser_flash, "○ laser primed · next 8-bar block", "muted")
        else:
            _say(self.l_laser_flash, "")

        if self.app.metronome.build_cue_active:
            if self.app.metronome.build_cue_source == "auto":
                _say(self.l_cue, "● BUILD (auto: kick back at half the drop's level) · C confirms it", "ok")
            else:
                _say(self.l_cue, "● BUILD CUED · held until the drop lands (C again cancels)", "ok")
        else:
            _say(self.l_cue, "")
        if self.app.metronome.drop_armed:
            src = self.app.metronome.drop_arm_source
            rising = " · RISING" if snap.rising else ""
            if self.app.metronome.drop_cut_pending:
                text = "● DROP CUT · lands on the next downbeat; D again cancels"
            elif src == "roll":
                text = f"● DROP ARMED (snare roll){rising} · the next kick pattern cuts it"
            elif src == "rise":
                text = f"● DROP ARMED (intensity rising){rising} · the next kick pattern cuts it"
            else:
                text = f"● DROP ARMED (D){rising} · strobe runs while the intensity rises; D again CUTS on the next downbeat"
            _say(self.l_arm, text, "ok")
        else:
            _say(self.l_arm, "")

        if self.app.reactive_engine.synth_sync_active:
            _say(self.l_synth, "● SYNTH SYNC · wash follows the mids; strobes cut through", "ok")
        elif self.app.manual.synth_sync:
            _say(self.l_synth, "● SYNTH SYNC armed · waiting for real audio", "bad")
        else:
            _say(self.l_synth, "")

        held = self.app.manual.blackout or self.app.manual.freeze   # the header pill says which
        quiet = not held and all(lbl.isHidden() for lbl in (self.l_auto_blackout, self.l_cue, self.l_arm,
                                                            self.l_laser_flash, self.l_synth))
        if self.l_idle.isHidden() == quiet:
            self.l_idle.setVisible(quiet)


def run_console(app, fps: int = 30) -> int:
    """Open the console and refresh it at ``fps`` (blocks until the window closes)."""
    qt = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    apply_theme(qt)
    win = ConsoleWindow(app)
    win.show()
    timer = QtCore.QTimer()
    timer.timeout.connect(win.refresh)
    timer.start(int(1000 / fps))
    # SIGINT/SIGTERM (and tools/run_show.sh's `touch logs/STOP` + kill) only set
    # app.stop_event; Qt's loop never saw it, so the window had to be force-killed
    # (2026-10-08 demo run). Poll the event and quit the loop when it is set.
    stop_poll = QtCore.QTimer()
    stop_poll.timeout.connect(lambda: qt.quit() if app.stop_event.is_set() else None)
    stop_poll.start(250)
    return qt.exec()
