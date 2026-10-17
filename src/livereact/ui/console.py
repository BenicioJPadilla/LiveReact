"""Operator console: the live show at a glance, and the controls around it.

The console embodies "automation is the default; manual is a bias/cap, not an
override" (docs/02 §5): the show always runs itself; the operator only nudges
brightness/strobe-cap/color, arms lasers, or hits the hard switches
(blackout/freeze) and skip/tap-tempo.

Layout (design v2, ui/theme.py; lr-design/prototype-v2.html):

    SIDEBAR   the rig (venue) with its glow tile · Live · Lights ·
              Room: Phone remote · Safety
    LIVE      status bar: on-air clock, music, light output, phone, Pro switch
              stage: the real floor plan lit by the show, the status line
              ("Listening.", "Blackout."), and under it the deck: beat
              lights, a plain-language read of the music, the last two
              minutes as sections
              rack (right): Brightness, the look now showing, Blackout (B)
              Pro controls (hidden until switched on): Moments (cues),
              Lasers, Feel, Under the hood (the technical readouts)
    LIGHTS    the Venue floor plan + calibration, or the Rig Config table
    PHONE / SAFETY   what the phone console and the safety rules do

Pro controls hide Josh-level controls from everyone else. Every keyboard
shortcut works whether they are shown or not (Josh's muscle memory), and
anything latched by a key (Freeze, the laser hold, a held build or an armed
drop) shows on the stage either way. The switch is remembered between
launches (QSettings) when the console is opened by ``run_console``.

Every control keeps the attribute name it had before (tests/test_console.py
finds them that way). Refresh does no more work than before: it reads the
same snapshot once, and painted widgets repaint only when what they draw
changes. The live light colour ("glow") is read from the published DMX frame
by ui/glow.py's own UI-thread timer (30 fps at most), never on the show thread.
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
from ..merge.merge import strobe_allowed
from ..tap_tempo import TapTempo
from . import theme
from .glow import Glow, GlowSource
from .pages import LightsHeader, PhonePage, SafetyPage
from .rig_config import RigConfigTab
from .stage import StageView
from .theme import DANGER, OK, TEXT, TEXT_2, TEXT_3, WARN, apply_theme, chip_css, set_css
from .venue_tab import VenueTab
from .widgets import (
    BeatLeds, BlackoutKey, CueButton, GlowFader, Meter, NavButton, OnAirChip, ProSwitch,
    SECTION_NAMES, SectionStrip, Sheet, StatusLine, StatusPill, ToggleRow, VenueTile,
    brand_row, hair, hbox, heading, icon_label, label, press_target, segmented,
)

log = logging.getLogger(__name__)

_ALIGN = QtCore.Qt.AlignmentFlag

# Activity lines (Under the hood): a tone bar down the left edge carries the
# status; the text itself stays readable graphite / white.
_TONES = {tone: f"color:{ink}; background:{theme.SURFACE_2}; border:none; border-left:2px solid {bar};"
          for tone, ink, bar in (("ok", TEXT, OK), ("bad", TEXT, DANGER), ("muted", TEXT_2, TEXT_3),
                                 ("warn", TEXT, WARN))}
# the chips in Under the hood: bright when something is on, quiet otherwise
_CHIP = {c: chip_css(c) for c in (TEXT, TEXT_2, TEXT_3)}

# The plain-language read of the music, per ShowSnapshot.bucket.
_READ = {
    "break": ("Taking a breather", "The beat is resting. The lights ease off."),
    "build": ("Building up", "Energy is rising."),
    "drop": ("The drop hit", "The lights hit with it."),
    "peak": ("Peak energy", "The floor is at full energy."),
    "outro": ("Winding down", "Energy is falling off."),
}
_SILENT = ("Waiting for music", "No music coming in. The lights stay dark until it comes back.")

_LASER_HINT = {
    "show": "On at launch for this rig. Only this computer can turn them on.",
    "manual": "Armed at launch for this rig; dark until you press a scene.",
}
_LASER_HINT_DEFAULT = "Off every time you open the app. Only this computer can turn them on."


def _say(lbl: QtWidgets.QLabel, text: str, tone: str = "ok") -> None:
    """Set an activity line: text, tone, and hidden while empty."""
    lbl.setText(text)
    if text:
        set_css(lbl, _TONES[tone])
    if lbl.isHidden() == bool(text):
        lbl.setVisible(bool(text))


def _set_dot(pill: StatusPill, seg: int, ok: bool) -> None:
    pill.set(seg, tone="ok" if ok else "bad")


def _mirror_check(w: QtWidgets.QAbstractButton, on: bool) -> None:
    """Show ``on`` without firing the control's slot: the mirror never writes
    ManualParams back, so an outside writer (phone, relaunch, MIDI) wins."""
    if w.isChecked() != on:
        w.blockSignals(True)
        w.setChecked(on)
        w.blockSignals(False)


def _mirror_slider(s: QtWidgets.QSlider, val: QtWidgets.QLabel, value: float) -> None:
    """Move a 0..100 fader to an outside write of ``value`` (0..1), signals
    blocked. Only when it is more than one step away, so a value between two
    steps never makes the handle hunt."""
    if abs(value * 100 - s.value()) > 1:
        s.blockSignals(True)
        s.setValue(round(value * 100))
        s.blockSignals(False)
        val.setText(f"{s.value()}%")


def _look_button(text: str, role: str = "look") -> QtWidgets.QPushButton:
    b = press_target(QtWidgets.QPushButton(text))
    b.setObjectName(role)            # #look / #lookOff in ui/theme.py
    b.setCheckable(True)
    return b


def _lights(n: int) -> str:
    return f"{n} light{'s' if n != 1 else ''}"


def _look_grid(names: list[str], buttons: dict, parent) -> tuple[QtWidgets.QButtonGroup, QtWidgets.QGridLayout]:
    """Exclusive look / scene chips, three to a row, into ``buttons`` by name."""
    grid = QtWidgets.QGridLayout()
    grid.setSpacing(4)
    group = QtWidgets.QButtonGroup(parent)
    group.setExclusive(True)
    for i, name in enumerate(names):
        b = _look_button("Off" if name == "OFF" else name, "lookOff" if name == "OFF" else "look")
        buttons[name] = b
        group.addButton(b)
        grid.addWidget(b, i // 3, i % 3)
    return group, grid


def _clock(seconds: float) -> str:
    s = int(max(0.0, seconds))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}"


class ConsoleWindow(QtWidgets.QMainWindow):
    def __init__(self, app, remember: bool = False) -> None:
        super().__init__()
        self.app = app
        self.tap = TapTempo()
        self._tap_beat = 0
        self._last = {}  # refresh(): last value per readout, to skip no-op updates
        self._t0 = app.clock.monotonic()
        self._demo = bool(getattr(app.config, "demo", False))
        self._settings = QtCore.QSettings("LiveReact", "Console") if remember else None
        # Arming lasers asks once per run, unless they were already armed
        # when the window opened (demo, or a rig profile that arms at launch).
        self._lasers_confirmed = app.manual.laser_enable
        self.setWindowTitle("LiveReact")
        apply_theme()

        self.glow = Glow(self)
        self.glow_source = GlowSource(self.glow, app.rig, app.frame_buffer, self)
        # The Live stage: the floor plan, view only, nothing draggable mid-set.
        self.rig_view = StageView(app.rig, self.glow)

        rig_path = getattr(app.config, "rig_path", None)
        self.rig_path = rig_path
        # Venue page: the editable floor plan + head calibration. Its jog/probe
        # pins land on app.manual.calibration (read once per show-engine tick)
        # and are cleared the moment the operator leaves the page.
        self.venue_tab = VenueTab(app.rig, rig_path,
                                  on_pins=lambda pins: setattr(app.manual, "calibration", pins),
                                  is_frozen=lambda: app.manual.freeze)
        self.rig_tab = RigConfigTab(app.rig, rig_path)
        self.phone_page = PhonePage()
        self.safety_page = SafetyPage(getattr(app.rig, "laser_profile", "accent") or "accent", self._demo,
                                      bool(getattr(app.config, "bible_failsafe_enabled", False)))
        tabs = QtWidgets.QTabWidget()
        tabs.tabBar().hide()                 # the sidebar drives it
        tabs.setDocumentMode(True)
        self.tabs = tabs
        tabs.addTab(self._build_live_page(), "Show")
        tabs.addTab(self.venue_tab, "Venue")
        tabs.addTab(self.rig_tab, "Rig Config")
        tabs.addTab(self.phone_page, "Phone remote")
        tabs.addTab(self.safety_page, "Safety")
        # the phone page owns the address row; the names stay on the window
        self.phone_row, self.l_phone = self.phone_page.phone_row, self.phone_page.l_phone

        self.lights_header = LightsHeader()
        self.lights_header.seg_buttons[0].clicked.connect(lambda: self.tabs.setCurrentWidget(self.venue_tab))
        self.lights_header.seg_buttons[1].clicked.connect(lambda: self.tabs.setCurrentWidget(self.rig_tab))
        self.lights_header.b_test.clicked.connect(self._explain_fixture_test)
        self.lights_header.hide()

        main = QtWidgets.QWidget()
        mv = QtWidgets.QVBoxLayout(main)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(0)
        mv.addWidget(self.lights_header)
        mv.addWidget(tabs, 1)
        central = QtWidgets.QWidget()
        ch = QtWidgets.QHBoxLayout(central)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(0)
        ch.addWidget(self._build_sidebar(rig_path))
        ch.addWidget(main, 1)
        self.setCentralWidget(central)
        tabs.currentChanged.connect(self._tab_changed)
        self.setMinimumSize(1200, 760)
        self.resize(1440, 900)

        self._install_shortcuts()
        pro = bool(self._settings is not None and self._settings.value("pro", False, type=bool))
        self.pro_switch.setChecked(pro)
        self._set_pro(pro)
        self.pro_switch.toggled.connect(self._set_pro)
        self.glow_source.start()

    # ------------------------------------------------------------------ shell
    def _build_sidebar(self, rig_path: str | None) -> QtWidgets.QFrame:
        side = QtWidgets.QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(240)
        v = QtWidgets.QVBoxLayout(side)
        v.setContentsMargins(10, 12, 10, 12)
        v.setSpacing(2)

        rig = self.app.rig
        name = (getattr(rig, "name", "") or "").strip() or (
            os.path.splitext(os.path.basename(rig_path))[0] if rig_path else "Default rig")
        n = len(rig.fixtures)
        venue = QtWidgets.QWidget()
        vh = QtWidgets.QHBoxLayout(venue)
        vh.setContentsMargins(8, 8, 8, 8)
        vh.setSpacing(10)
        vh.addWidget(VenueTile(self.glow))
        txt = QtWidgets.QVBoxLayout()
        txt.setSpacing(0)
        self.l_venue = label(name, "venueName")
        txt.addWidget(self.l_venue)
        txt.addWidget(label(_lights(n), "hint"))
        vh.addLayout(txt, 1)
        venue.setToolTip(rig_path or "The built-in default rig")
        v.addWidget(venue)
        v.addSpacing(12)

        self.nav_group = QtWidgets.QButtonGroup(side)
        self.nav_group.setExclusive(True)
        self.nav_live = NavButton("Live", "live", self.glow)
        self.nav_lights = NavButton("Lights", "lights", self.glow)
        self.nav_phone = NavButton("Phone remote", "phone", self.glow)
        self.nav_safety = NavButton("Safety", "shield", self.glow)
        if not self._demo:
            self.nav_live.set_badge("On")
        targets = ((self.nav_live, 0), (self.nav_lights, self.venue_tab), (self.nav_phone, self.phone_page),
                   (self.nav_safety, self.safety_page))
        for b, target in targets:
            self.nav_group.addButton(b)
            if isinstance(target, int):
                b.clicked.connect(lambda _c=False, i=target: self.tabs.setCurrentIndex(i))
            else:
                b.clicked.connect(lambda _c=False, w=target: self.tabs.setCurrentWidget(w))
        v.addWidget(self.nav_live)
        v.addWidget(self.nav_lights)
        v.addWidget(label("Room", "group"))
        v.addWidget(self.nav_phone)
        v.addWidget(self.nav_safety)
        self.nav_live.setChecked(True)
        v.addStretch(1)

        brand = brand_row("Demo" if self._demo else "Live show", size=20)
        brand.setContentsMargins(8, 10, 8, 2)
        v.addWidget(hair())
        v.addLayout(brand)
        return side

    def _tab_changed(self, idx: int) -> None:
        w = self.tabs.widget(idx)
        if w is not self.venue_tab:
            self.venue_tab.deactivate()
            self.venue_tab.plan.select("")
        if idx != 0:
            self.sheet.close_sheet()
        # the Venue plan is rebuilt on edits; the Live stage shares the
        # same rig objects, so re-layout it whenever we come back to Live
        if idx == 0:
            self.rig_view.refresh_layout()
        lights = w in (self.venue_tab, self.rig_tab)
        self.lights_header.setVisible(lights)
        if lights:
            self.lights_header.seg_buttons[0 if w is self.venue_tab else 1].setChecked(True)
        nav = {0: self.nav_live}.get(idx) or (self.nav_lights if lights else
                                             self.nav_phone if w is self.phone_page else self.nav_safety)
        if not nav.isChecked():
            nav.setChecked(True)

    def _explain_fixture_test(self) -> None:
        # A tooltip, never a dialog: a modal box opened by a stray click
        # mid-set would swallow B / F / Space until it was dismissed.
        b = self.sender()
        QtWidgets.QToolTip.showText(
            b.mapToGlobal(QtCore.QPoint(0, b.height() + 6)),
            "Light test runs on its own: it drives raw DMX channels straight to the output and "
            "bypasses the show, so it never runs alongside a live set.\n"
            "Close LiveReact, then start it with:  python -m livereact --fixture-test\n"
            "(The launch window's \"Flash each light\" does the same before a show.)", b)

    # ------------------------------------------------------------------ live page
    def _build_live_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        page.setObjectName("live")
        v = QtWidgets.QVBoxLayout(page)
        v.setContentsMargins(theme.SP8, theme.SP5, theme.SP8, theme.SP5)
        v.setSpacing(theme.SP5)

        # --force-start skipped the gear gate: say so for the whole set.
        note = self.app.config.force_start_note
        self.l_forced = label(note or "", "dangerNote", wrap=True)
        v.addWidget(self.l_forced)
        self.l_forced.setVisible(bool(note))

        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(18)
        self.chip_onair = OnAirChip(live=not self._demo)
        self.st_music = StatusLine("Listening for music", "off")
        self.st_lights = StatusLine("", "off")
        self.st_phone = StatusLine("Phone remote off", "off")
        self.st_strobe = StatusLine("Strobe allowed", "ok")
        self.pro_switch = ProSwitch()
        for w in (self.chip_onair, self.st_music, self.st_lights, self.st_strobe, self.st_phone):
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addWidget(self.pro_switch)
        v.addLayout(bar)

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(theme.SP5)
        grid.setVerticalSpacing(theme.SP5)
        self.stage_frame = self._build_stage()
        grid.addWidget(self.stage_frame, 0, 0)
        self._rack = self._build_rack()
        grid.addWidget(self._rack, 0, 1, _ALIGN.AlignTop)
        grid.setColumnStretch(0, 1)
        grid.setRowStretch(0, 1)
        self.pro_rack = self._build_pro()
        grid.addWidget(self.pro_rack, 1, 0, 1, 2)
        v.addLayout(grid, 1)
        # The confirmation sheet covers the page but not the rack column: the
        # Blackout key stays reachable while it is up.
        self.sheet = Sheet(page, keep_clear=lambda: self._rack.geometry())

        area = QtWidgets.QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        area.setWidget(page)
        return area

    def _build_stage(self) -> QtWidgets.QFrame:
        frame = QtWidgets.QFrame()
        frame.setObjectName("stage")
        v = QtWidgets.QVBoxLayout(frame)
        v.setContentsMargins(1, 1, 1, 1)
        v.setSpacing(0)
        self.rig_view.setMinimumHeight(200)
        v.addWidget(self.rig_view, 1)

        deck = QtWidgets.QFrame()
        deck.setObjectName("deck")
        dh = QtWidgets.QHBoxLayout(deck)
        dh.setContentsMargins(20, 16, 20, 18)
        dh.setSpacing(24)
        now = QtWidgets.QVBoxLayout()
        now.setSpacing(3)
        self.beat_leds = BeatLeds(self.glow)
        self.l_deck_bpm = label("", "hint")
        now.addLayout(hbox(self.beat_leds, self.l_deck_bpm, spacing=10, stretch_at=2))
        now.addSpacing(6)
        self.l_read_title = label("", "readTitle")
        self.l_read_text = label("", "readText", wrap=True)
        now.addWidget(self.l_read_title)
        now.addWidget(self.l_read_text)
        now.addStretch(1)
        now_w = QtWidgets.QWidget()
        now_w.setLayout(now)
        now_w.setFixedWidth(250)
        dh.addWidget(now_w)
        track = QtWidgets.QVBoxLayout()
        track.setSpacing(4)
        self.section_strip = SectionStrip(self.glow)
        track.addWidget(self.section_strip)
        self.l_track_cap = label("", "hint")
        track.addLayout(hbox(label("Last 2 minutes", "hint"), self.l_track_cap, stretch_at=1))
        dh.addLayout(track, 1)
        v.addWidget(deck)
        return frame

    def _build_rack(self) -> QtWidgets.QWidget:
        m = self.app.manual
        col = QtWidgets.QWidget()
        col.setFixedWidth(320)
        v = QtWidgets.QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(theme.SP3)

        rack = QtWidgets.QFrame()
        rack.setObjectName("panel")
        rv = QtWidgets.QVBoxLayout(rack)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        ch = QtWidgets.QVBoxLayout()
        ch.setContentsMargins(18, 16, 18, 18)
        ch.setSpacing(10)
        self.l_bright_v = label("", "value")
        self.l_bright_v.setAlignment(_ALIGN.AlignRight | _ALIGN.AlignVCenter)
        ch.addLayout(hbox(icon_label("sun"), label("Brightness", "strong"), self.l_bright_v, stretch_at=2))
        self.s_bright = GlowFader(0, 100, round(m.master_brightness * 100), self.glow)
        self.s_bright.setAccessibleName("Brightness")
        ch.addWidget(self.s_bright)
        rv.addLayout(ch)
        rv.addWidget(hair())
        look = QtWidgets.QHBoxLayout()
        look.setContentsMargins(18, 14, 18, 16)
        look.setSpacing(12)
        look.addWidget(VenueTile(self.glow))
        lt = QtWidgets.QVBoxLayout()
        lt.setSpacing(0)
        self.l_look = label("", "strong")
        lt.addWidget(self.l_look)
        lt.addWidget(label("Look now showing", "hint"))
        look.addLayout(lt, 1)
        rv.addLayout(look)
        v.addWidget(rack)

        # Strobe allowed (2026-10-17, photosensitivity safety): off is a hard
        # stop for every strobe, the automatic one included (merge.py
        # strobe_allowed). Always on screen, Pro controls or not, like
        # Blackout. The phone can switch it off at any time and a relaunch
        # restores it: start from the model, refresh() keeps it in step.
        strobe = QtWidgets.QFrame()
        strobe.setObjectName("panel")
        sv = QtWidgets.QVBoxLayout(strobe)
        sv.setContentsMargins(18, 12, 18, 12)
        sv.setSpacing(6)
        self.cb_strobe = ToggleRow("Strobe allowed", "Off stops every strobe, automatic included, "
                                   "until you switch it back on.", key="X", compact=True)
        self.cb_strobe.setAccessibleName("Strobe allowed")
        self.cb_strobe.setChecked(m.strobe_enabled)
        sv.addWidget(self.cb_strobe)
        self.l_strobe_state = label("", "banner", wrap=True)
        self.l_strobe_state.hide()
        sv.addWidget(self.l_strobe_state)
        v.addWidget(strobe)

        # Blackout: one press kills every fixture; again brings the show back.
        # A crash relaunch restores blackout before the window exists, and the
        # phone console writes it at any time: start from the model, and
        # refresh() keeps it in step.
        self.b_black = BlackoutKey()
        self.b_black.setToolTip("One press kills every fixture. Press again to bring the show back.")
        self.b_black.setChecked(m.blackout)
        v.addWidget(self.b_black)
        foot = label("Everything else is automatic. You can leave this screen alone all night.", "footNote", wrap=True)
        foot.setAlignment(_ALIGN.AlignHCenter)
        v.addWidget(foot)
        v.addStretch(1)

        self.s_bright.valueChanged.connect(lambda x: setattr(m, "master_brightness", x / 100))
        self.s_bright.valueChanged.connect(lambda x: self.l_bright_v.setText(f"{x}%"))
        self.l_bright_v.setText(f"{self.s_bright.value()}%")
        self.b_black.toggled.connect(self._set_blackout)
        self.cb_strobe.toggled.connect(lambda on: setattr(m, "strobe_enabled", on))
        return col

    # ------------------------------------------------------------------ pro rack
    def _section(self, title: str, icon_name: str, hint: str = "") -> tuple[QtWidgets.QWidget, QtWidgets.QVBoxLayout]:
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(8)
        v.addLayout(heading(title, icon_name))
        if hint:
            h = label(hint, "hint", wrap=True)
            v.addWidget(h)
        return w, v

    def _build_pro(self) -> QtWidgets.QFrame:
        m = self.app.manual
        rack = QtWidgets.QFrame()
        rack.setObjectName("panel")
        row = QtWidgets.QHBoxLayout(rack)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        # --- Moments: what Josh reaches for mid-set ------------------------
        moments, mv = self._section("Moments", "bolt", "Push the show yourself. It goes back to automatic after.")
        pads = QtWidgets.QGridLayout()
        pads.setSpacing(6)
        g = self.glow
        # DJ build cue (2026-09-16, core/metronome.py's cue_build): BUILD now,
        # held until the drop lands (or 32 bars, or a second press cancels).
        self.b_cue = CueButton("Build up now", "C", "trend", glow=g)
        self.b_cue.setToolTip("BUILD now, held until the drop lands. Press again to cancel.")
        # DJ drop arm (2026-09-17, core/metronome.py's arm_drop): the next
        # drop-level kick commits the drop instantly. Pressed again while
        # armed (2026-09-19): the drop CUTS on the next downbeat regardless.
        self.b_arm = CueButton("Drop on the next kick", "D", "drop", glow=g)
        self.b_arm.setToolTip("The next drop-level kick commits the drop. Press again to cut on the next downbeat.")
        self.b_burst = CueButton("Strobe burst", "Space", "flash", glow=g)
        self.b_burst.setToolTip("A short strobe on every light with a strobe channel, up to the strobe limit.")
        self.b_skip = CueButton("Next look", "→", "skip", glow=g)
        self.b_freeze = CueButton("Freeze the look", "F", "freeze", checkable=True, glow=g)
        self.b_freeze.setToolTip("Hold the current look. Press again to release.")
        self.b_freeze.setChecked(m.freeze)
        self.b_tap = CueButton("Tap tempo", "T", "tap", glow=g)
        self.b_tap.setToolTip("Tap along on the beat to set the BPM when there is no beat grid.")
        for i, b in enumerate((self.b_cue, self.b_arm, self.b_burst, self.b_skip, self.b_freeze, self.b_tap)):
            pads.addWidget(b, i // 2, i % 2)
        mv.addLayout(pads)
        mv.addStretch(1)

        # --- Lasers ----------------------------------------------------------
        profile = getattr(self.app.rig, "laser_profile", "") or ""
        hint = ("On for the demo, so its drops can show them. Only this computer can turn them on."
                if self._demo else _LASER_HINT.get(profile, _LASER_HINT_DEFAULT))
        lasers, lv = self._section("Lasers", "laser", hint)
        # Arming is per run, per track (2026-09-16): never persisted, off at
        # every launch on the accent rigs. L toggles it; the first arming of a
        # run that started disarmed asks first (the laser sheet).
        self.cb_laser = ToggleRow("Lasers on", "Arm per song", key="L", compact=True)
        self.cb_laser.setChecked(m.laser_enable)
        self.cb_laser.before_on = self._laser_gate
        lv.addWidget(self.cb_laser)
        lpads = QtWidgets.QGridLayout()
        lpads.setSpacing(6)
        # 2026-10-06 (trigger profile): one laser moment NOW. A counter on ManualParams.
        self.b_laser_hit = CueButton("Laser hit", "J", "flash", glow=g)
        # Manual laser cue (2026-09-30, engines/laser.py MANUAL CUE): held
        # (checkable), the lasers show while it is on. Also drivable from a
        # MIDI-learned "laser_cue" control; refresh() mirrors that back here.
        self.b_laser_cue = CueButton("Hold lasers", "K", "pause", checkable=True, glow=g)
        self.b_laser_cue.setChecked(m.laser_cue)
        lpads.addWidget(self.b_laser_hit, 0, 0)
        lpads.addWidget(self.b_laser_cue, 0, 1)
        lv.addLayout(lpads)
        self._build_laser_profile_controls(lasers, lv, profile)
        lv.addStretch(1)

        # --- Feel: biases/caps, never overrides --------------------------------
        feel, fv = self._section("Feel", "sliders", "These bias the show. They never take it over.")
        self.s_strobe = GlowFader(0, 100, round(m.strobe_cap * 100), g, small=True)
        self.s_strobe.setAccessibleName("Strobe limit")
        self.s_warm = GlowFader(-100, 100, int(m.warm_cool_bias * 100), small=True, mono=True)
        self.s_warm.setAccessibleName("Warm to cool")
        self.l_strobe_v = label("", "value")
        self.l_warm_v = label("", "value")
        fv.addLayout(hbox(label("Strobe limit", "body2"), self.l_strobe_v, stretch_at=1))
        fv.addWidget(self.s_strobe)
        fv.addSpacing(4)
        warm = hbox(label("Warm", "body2"))
        warm.addStretch(1)
        warm.addWidget(self.l_warm_v)
        warm.addStretch(1)
        warm.addWidget(label("Cool", "body2"))
        fv.addLayout(warm)
        fv.addWidget(self.s_warm)
        fv.addSpacing(4)
        # Synth Sync (Josh, 2026-09-15): wash follows the synths/stabs (the mid
        # band); the automated strobes still cut through (engines/reactive.py).
        self.cb_synth = ToggleRow("Follow the synths", "The wash rides the synths. Strobes still cut through.",
                                  key="S", compact=True)
        self.cb_synth.setChecked(m.synth_sync)
        fv.addWidget(self.cb_synth)
        fv.addStretch(1)

        # --- Under the hood -----------------------------------------------------
        hood, hv = self._section("Under the hood", "gauge")
        self.l_bpm = label("--.-", "bpm")
        bpm = QtWidgets.QHBoxLayout()
        bpm.setSpacing(6)
        bpm.addWidget(self.l_bpm, 0, _ALIGN.AlignBottom)
        bpm.addWidget(label("BPM", "bpmUnit"), 0, _ALIGN.AlignBottom)
        bpm.addStretch(1)
        self.beat_leds_hood = BeatLeds(g)
        bpm.addWidget(self.beat_leds_hood, 0, _ALIGN.AlignBottom)
        hv.addLayout(bpm)
        read = QtWidgets.QGridLayout()
        read.setHorizontalSpacing(12)
        read.setVerticalSpacing(2)
        self.l_beat = label("--", "value")
        # Energy bucket (core/show_state.py's debounced `bucket`): the single
        # most useful "what does the show think is happening" readout.
        self.l_bucket = label("--", "bucket")
        set_css(self.l_bucket, _CHIP[TEXT])
        self.l_scene = label("--", "value")
        # Laser profile + mood (2026-10-01): on the bar's feature rig the
        # lasers are the main light, so what they are doing sits here too.
        self.l_laser = label("--", "bucket")
        self.l_deck = label("--", "value")
        self.l_output = label("", "value")
        self.l_grid = label("", "value")
        for r, (cap, w) in enumerate((("Bar", self.l_beat), ("Section", self.l_bucket), ("Look", self.l_scene),
                                      ("Laser", self.l_laser), ("Deck", self.l_deck),
                                      ("Light output", self.l_output), ("Beat grid", self.l_grid))):
            read.addWidget(label(cap, "hint"), r, 0)
            read.addWidget(w, r, 1, _ALIGN.AlignRight)
        read.setColumnStretch(1, 1)
        hv.addLayout(read)
        meters = QtWidgets.QGridLayout()
        meters.setHorizontalSpacing(8)
        meters.setVerticalSpacing(4)
        self.pb_low = Meter(g)
        self.pb_mid = Meter(g)
        self.pb_high = Meter(g)
        for r, (cap, mtr) in enumerate((("Low", self.pb_low), ("Mid", self.pb_mid), ("High", self.pb_high))):
            c = label(cap, "hint")
            c.setFixedWidth(44)
            meters.addWidget(c, r, 0)
            meters.addWidget(mtr, r, 1)
        hv.addLayout(meters)
        # Connection dots: Audio / Pro DJ Link / MIDI / DMX.
        self.pill_conn = StatusPill([("Audio", "bad"), ("Link", "bad"), ("MIDI", "bad"), ("DMX", "bad")])
        self.pill_conn.setToolTip("Audio / Pro DJ Link / MIDI turn green once real data is flowing, "
                                  "DMX once a hardware output (not the log fallback) is open.")
        hv.addWidget(self.pill_conn)
        self.l_health = label("", "health")
        hv.addWidget(self.l_health)
        # Activity: what the automation is doing right now.
        self.l_cue = label("", "banner", wrap=True)
        self.l_arm = label("", "banner", wrap=True)
        self.l_laser_flash = label("", "banner", wrap=True)
        self.l_synth = label("", "banner", wrap=True)
        # docs/14 §2: the system's auto-blackout (no music detected) is
        # independent of the operator's manual toggle.
        self.l_auto_blackout = label("", "banner", wrap=True)
        # FAIL-01: Pro DJ Link went quiet mid-set; the show holds its look.
        self.l_pdl_lost = label("", "banner", wrap=True)
        self.l_idle = label("○ Automation is running the show. Nothing needs you right now.", "idle", wrap=True)
        # each line sits under the column it is about: the link and silence
        # lines here, the rest above their column's closing stretch
        for lbl in (self.l_pdl_lost, self.l_auto_blackout):
            lbl.hide()
            hv.addWidget(lbl)
        for lbl, col in ((self.l_cue, mv), (self.l_arm, mv), (self.l_laser_flash, lv), (self.l_synth, fv)):
            lbl.hide()
            col.insertWidget(col.count() - 1, lbl)
        hv.addWidget(self.l_idle)
        hv.addStretch(1)

        for i, sec in enumerate((moments, lasers, feel, hood)):
            if i:
                row.addWidget(hair(vertical=True))
            row.addWidget(sec, 1)

        # wiring
        self.s_strobe.valueChanged.connect(lambda x: setattr(m, "strobe_cap", x / 100))
        self.s_warm.valueChanged.connect(lambda x: setattr(m, "warm_cool_bias", x / 100))
        self.s_strobe.valueChanged.connect(lambda x: self.l_strobe_v.setText(f"{x}%"))
        self.s_warm.valueChanged.connect(self._show_warm)
        self.l_strobe_v.setText(f"{self.s_strobe.value()}%")
        self._show_warm(self.s_warm.value())
        self.cb_laser.toggled.connect(lambda on: setattr(m, "laser_enable", on))
        self.b_laser_cue.toggled.connect(lambda on: setattr(m, "laser_cue", on))
        self.b_laser_hit.clicked.connect(lambda: setattr(m, "laser_hit", m.laser_hit + 1))
        self.cb_synth.toggled.connect(lambda on: setattr(m, "synth_sync", on))
        self.b_freeze.toggled.connect(lambda on: setattr(m, "freeze", on))
        self.b_skip.clicked.connect(self.app.phrase_engine.skip)
        self.b_tap.clicked.connect(self._do_tap)
        self.b_burst.clicked.connect(self._strobe_burst)
        self.b_cue.clicked.connect(self.app.metronome.cue_build)
        self.b_arm.clicked.connect(self.app.metronome.arm_drop)
        return rack

    def _build_laser_profile_controls(self, parent: QtWidgets.QWidget, lv: QtWidgets.QVBoxLayout,
                                      profile: str) -> None:
        """The profile-specific laser controls, in the Lasers section."""
        m = self.app.manual
        self.laser_scene_buttons: dict[str, QtWidgets.QPushButton] = {}
        self.laser_look_buttons: dict[str, QtWidgets.QPushButton] = {}
        self._laser_mode_buttons: dict[str, QtWidgets.QRadioButton] = {}
        if profile == "manual":
            # Laser profile "manual" (2026-10-10, Junior Crib): press a scene to
            # cue it on every head, Off (the launch state) to kill them.
            # Nothing listens to the music (engines/laser_manual.py).
            from ..engines.laser_manual import manual_scene_names as scene_names
            eng = self.app.laser_engine
            lv.addWidget(label("Scenes", "label"))
            self._laser_scene_group, grid = _look_grid(["OFF"] + scene_names(), self.laser_scene_buttons, parent)
            for name, b in self.laser_scene_buttons.items():
                if name == "OFF":
                    b.clicked.connect(eng.off)
                else:
                    b.clicked.connect(lambda _c=False, n=name: eng.cue(n))
            self.laser_scene_buttons[eng.scene or "OFF"].setChecked(True)
            lv.addLayout(grid)
        elif profile == "show":
            # Laser SHOW profile (2026-10-08, engines/laser_show.py): the mode
            # (follow the music / rotate / hold one look), the looks (pressing
            # one holds it) and the drop accent. ManualParams fields only.
            seg, _group, (self.rb_laser_follow, self.rb_laser_rotate, self.rb_laser_hold) = segmented(
                ["Follow music", "Rotate", "Hold one"], parent, cls=QtWidgets.QRadioButton)
            self.rb_laser_follow.setToolTip("break: Slow Rainbow, build: Tension ramp, armed: chop, "
                                            "drop: Fan 8 bars then Rainbow, peak: Ping-Pong")
            self.rb_laser_rotate.setToolTip("The static scenes in turn every 16 bars, from the picked one.")
            self.rb_laser_hold.setToolTip("Manual override: show the picked look and nothing else.")
            self._laser_mode_buttons = {MODE_FOLLOW: self.rb_laser_follow, MODE_ROTATE: self.rb_laser_rotate,
                                        MODE_HOLD: self.rb_laser_hold}
            self._laser_mode_buttons.get(m.laser_mode, self.rb_laser_follow).setChecked(True)
            lv.addWidget(seg)
            self._laser_look_group, grid = _look_grid(look_names(), self.laser_look_buttons, parent)
            if m.laser_scene in self.laser_look_buttons:
                self.laser_look_buttons[m.laser_scene].setChecked(True)
            lv.addLayout(grid)
            self.cb_laser_accent = ToggleRow("Drop accent", "Chop the lasers for 2 bars when a drop lands "
                                                            "(rotate and hold)", compact=True)
            self.cb_laser_accent.setChecked(m.laser_drop_accent)
            lv.addWidget(self.cb_laser_accent)
            for mode, rb in self._laser_mode_buttons.items():
                rb.toggled.connect(lambda on, mode=mode: on and setattr(m, "laser_mode", mode))
            for name, b in self.laser_look_buttons.items():
                b.clicked.connect(lambda _=False, name=name: self._hold_laser_look(name))
            self.cb_laser_accent.toggled.connect(lambda on: setattr(m, "laser_drop_accent", on))

    def _show_warm(self, x: int) -> None:
        self.l_warm_v.setText("0" if x == 0 else (f"W{-x}" if x < 0 else f"C{x}"))

    def _hold_laser_look(self, name: str) -> None:
        """A look button: pick it and switch to the manual hold."""
        self.app.manual.laser_scene = name
        self.rb_laser_hold.setChecked(True)      # its toggled slot writes laser_mode

    # ------------------------------------------------------------------ pro / keys
    def _install_shortcuts(self) -> None:
        def sc(key, fn):
            return QtGui.QShortcut(QtGui.QKeySequence(key), self, activated=fn)

        # Every shortcut works with the Pro controls shown or hidden.
        sc("B", self.b_black.toggle)
        sc("X", self.cb_strobe.toggle)  # Strobe allowed: on / off
        for key, fn in (
            ("F", self.b_freeze.toggle),
            (QtCore.Qt.Key.Key_Right, self.app.phrase_engine.skip),
            ("T", self._do_tap),
            ("S", self.cb_synth.toggle),
            ("L", self._laser_key),
            ("K", self.b_laser_cue.toggle),
            ("J", self.b_laser_hit.click),
            ("C", self.app.metronome.cue_build),
            ("D", self.app.metronome.arm_drop),
            (QtCore.Qt.Key.Key_Space, self._strobe_burst),
        ):
            sc(key, fn)

    def _set_pro(self, on: bool) -> None:
        self.pro_rack.setVisible(on)
        if not on:
            self.sheet.close_sheet()
        if self._settings is not None:
            self._settings.setValue("pro", on)

    def _laser_gate(self) -> bool:
        """May the lasers be armed right now? Asks first (the sheet) the
        first time in a run that started with them off."""
        if self._lasers_confirmed:
            return True
        self.tabs.setCurrentIndex(0)
        self.sheet.ask(
            "Turn lasers on?",
            "Lasers can damage eyes. LiveReact can't see where the beams go, so check the room first. "
            "Blackout (B) turns them off with everything else.",
            ["The lasers are mounted above head height\nand aimed over the crowd",
             "Nobody is standing on a stage or balcony\nin the beam path"],
            "Turn lasers on", self._lasers_ok, icon_name="laser", danger=True)
        return False

    def _lasers_ok(self) -> None:
        self._lasers_confirmed = True
        self.cb_laser.setChecked(True)

    def _laser_key(self) -> None:
        if self.cb_laser.isChecked():
            self.cb_laser.setChecked(False)
        elif self._laser_gate():
            self.cb_laser.setChecked(True)

    def keyPressEvent(self, e) -> None:  # noqa: N802 (Qt override)
        if e.key() == QtCore.Qt.Key.Key_Escape and self.sheet.isVisible():
            self.sheet.close_sheet()
            return
        super().keyPressEvent(e)

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
        if not strobe_allowed(self.app.manual):
            return  # strobe off: finalize would drop it anyway; don't leave a burst pending
        self.app.manual.strobe_burst = True
        QtCore.QTimer.singleShot(400, lambda: setattr(self.app.manual, "strobe_burst", False))

    # ------------------------------------------------------------------ refresh
    def _changed(self, key: str, value) -> bool:
        if self._last.get(key) == value:
            return False
        self._last[key] = value
        return True

    def _refresh_status(self, snap) -> None:
        """The status bar and Under the hood: the parts of refresh that are pure display."""
        bpm = f"{snap.bpm:.1f}"
        self.l_bpm.setText(bpm)
        self.l_deck_bpm.setText(f"{bpm} BPM")
        self.l_beat.setText(str(snap.bar))
        self.l_deck.setText(str(snap.master_deck) if snap.master_deck else "--")
        scene = self.app.phrase_engine.current_scene_name.replace(" -> ", " → ")
        self.l_scene.setText(scene)
        if self._changed("look", scene):
            self.l_look.setText(self.l_look.fontMetrics().elidedText(scene, QtCore.Qt.TextElideMode.ElideRight, 220))
            self.l_look.setToolTip(scene)
        self.l_bucket.setText(snap.bucket.upper())
        low, mid, high = band_levels(snap)
        self.pb_low.setValue(int(low * 100))
        self.pb_mid.setValue(int(mid * 100))
        self.pb_high.setValue(int(high * 100))

        clock = "free-run" if snap.free_running else "locked"
        trans = "  ·  TRANSITION" if snap.in_transition else ""
        # FAIL-01: DJ Link beats were heard, then stopped; the look is held on purpose.
        pdl_lost = getattr(snap, "pdl_lost", False)
        pdl = "fresh" if snap.pdl_fresh else "LOST, look held" if pdl_lost else "STALE"
        midi = "fresh" if snap.midi_fresh else "stale"
        self.l_health.setText(f"clock {clock}  ·  PDL {pdl}  ·  MIDI {midi}{trans}")
        self.l_grid.setText("Pro DJ Link" if snap.pdl_fresh else "Held (DJ Link lost)" if pdl_lost
                            else "Free-running" if snap.free_running else "Locked")

        # connection dots: PDL/MIDI green only once real beat data is flowing (not
        # just a device seen on the wire); DMX green only once a real hardware
        # backend (not the null/log fallback) has successfully opened.
        _set_dot(self.pill_conn, 0, snap.audio_fresh)
        lost = pdl_lost and not snap.pdl_fresh
        if lost:
            self.pill_conn.set(1, tone="warn")
        else:
            _set_dot(self.pill_conn, 1, snap.pdl_fresh)
        _set_dot(self.pill_conn, 2, snap.midi_fresh)
        # DMX: a real backend that is open and (when the writer reports it)
        # actually getting frames out; a wedged interface can reopen yet fail
        # every write.
        writer = self.app.writer
        hardware = writer.backend.name != "null-log"
        dmx_ok = hardware and bool(getattr(writer, "output_ok", writer.is_open))
        _set_dot(self.pill_conn, 3, dmx_ok)
        _say(self.l_pdl_lost, "○ DJ LINK LOST, look held" if lost else "", "warn")

        # the plain-language status bar
        if lost:
            music = ("DJ Link lost, look held", "warn")
        elif self._demo and (snap.audio_fresh or snap.pdl_fresh):
            music = ("Hearing the demo music", "ok")
        elif snap.audio_fresh:
            music = ("Hearing the DJ board" if snap.pdl_fresh else "Hearing the music", "ok")
        elif snap.pdl_fresh:
            music = ("DJ Link beats, no audio", "warn")
        else:
            music = ("No music coming in", "warn")
        self.st_music.set(*music)
        n = len(self.app.rig.fixtures)
        if not hardware:
            lights = ("Demo, nothing sent to the lights" if self._demo else "No light adapter", "off" if self._demo else "bad")
        elif dmx_ok:
            lights = (f"Sending to {_lights(n)}", "ok")
        else:
            lights = ("Light adapter not sending", "bad")
        self.st_lights.set(*lights)
        self.l_output.setText(f"{writer.backend.name}, {'open' if dmx_ok else 'not sending'}"
                              if hardware else "None (demo)" if self._demo else "None")
        self.chip_onair.set_clock(_clock(self.app.clock.monotonic() - self._t0))

    def _refresh_live(self, snap) -> None:
        """The stage HUD and the deck: plain language only."""
        m = self.app.manual
        silent = self.app.show_engine.silence.active
        lost = getattr(snap, "pdl_lost", False) and not snap.pdl_fresh
        if m.blackout:
            title, sub = "Blackout.", "The lights are off. Press B or the Blackout key to bring them back."
        elif silent:
            title, sub = "Waiting for music.", "Play something and the lights will pick it up."
        elif m.freeze:
            title, sub = "Frozen.", "The look is held. Press F to follow the music again."
        elif lost:
            title, sub = "Holding the look.", "DJ Link went quiet. The lights keep this look until it comes back."
        else:
            title, sub = "Listening.", "Your lights are following the music."
        met = self.app.metronome
        left = []
        if met.build_cue_active:
            left.append("Build held" if met.build_cue_source != "auto" else "Building (auto)")
        if met.drop_armed:
            left.append("Drop on the next downbeat" if met.drop_cut_pending else "Drop armed")
        if self.app.reactive_engine.synth_sync_active:
            left.append("Following the synths")
        if m.freeze and title != "Frozen.":
            left.append("Frozen (F)")
        if m.laser_cue:
            left.append("Lasers held (K)")
        if not strobe_allowed(m):
            left.append("Strobe off (X)")
        lasers = (("Lasers armed, blacked out", "off") if m.laser_enable and m.blackout else
                  ("Lasers on", "ok") if m.laser_enable else ("Lasers off", "off"))
        right = ((self._last["look"], ""), lasers)
        self.rig_view.set_hud(title, sub, tuple(left), right, m.blackout)
        self.b_cue.set_lit(met.build_cue_active)
        self.b_arm.set_lit(met.drop_armed)

        read = _SILENT if silent else _READ.get(snap.bucket, _READ["break"])
        if not silent and snap.bucket == "build":
            read = (read[0], "The drop is armed for the next kick." if met.drop_armed
                    else "Energy is rising. A drop may be close." if snap.rising else read[1])
        if self._changed("read", read):
            self.l_read_title.setText(read[0])
            self.l_read_text.setText(read[1])
        beat = 0 if (silent or m.blackout) else int(snap.beat_in_bar)
        self.beat_leds.set_beat(beat)
        self.beat_leds_hood.set_beat(beat)
        if self.section_strip.add(self.app.clock.monotonic(), snap.bucket, snap.energy_norm):
            sec, secs = self.section_strip.current_run()
            cap = f"{SECTION_NAMES.get(sec, sec.title())} for {int(secs) // 60}:{int(secs) % 60:02d}"
            if self._changed("track_cap", cap):
                self.l_track_cap.setText(cap)
        url = getattr(self.app, "phone_url", None)
        self.st_phone.set("Phone remote on" if url else "Phone remote off", "ok" if url else "off")

    def _mirror_manual(self) -> None:
        """Show what ManualParams holds right now. The phone console and the
        relaunch supervisor write blackout / freeze / laser arm / faders
        directly, so a stale widget would make the next B or L press a no-op
        (or worse, re-assert the old state). Display only: never writes the model."""
        m = self.app.manual
        _mirror_check(self.b_black, m.blackout)
        _mirror_check(self.b_freeze, m.freeze)
        _mirror_check(self.cb_laser, m.laser_enable)
        _mirror_check(self.cb_synth, m.synth_sync)
        _mirror_check(self.cb_strobe, m.strobe_enabled)
        allowed = strobe_allowed(m)
        if not m.strobe_enabled:
            _say(self.l_strobe_state, "● STROBE OFF · no strobe at all, automatic included", "warn")
        elif not allowed:
            _say(self.l_strobe_state, "● STROBE OFF · the strobe limit is at 0 %", "warn")
        else:
            _say(self.l_strobe_state, "")
        self.st_strobe.set("Strobe allowed" if allowed else "Strobe OFF", "ok" if allowed else "warn")
        if self.b_burst.isEnabled() != allowed:
            self.b_burst.setEnabled(allowed)
        # A MIDI "laser_cue" control writes manual.laser_cue directly.
        _mirror_check(self.b_laser_cue, m.laser_cue)
        _mirror_slider(self.s_bright, self.l_bright_v, m.master_brightness)
        _mirror_slider(self.s_strobe, self.l_strobe_v, m.strobe_cap)
        url = getattr(self.app, "phone_url", None)
        if self._changed("phone_url", url):
            self.phone_page.set_url(url)

    def refresh(self) -> None:
        snap = self.app.show_state.snapshot()
        latest = self.app.frame_buffer.latest()
        current = self.tabs.currentWidget()
        if current is self.venue_tab:
            self.venue_tab.plan.update_from_universe(latest)   # see the jogged head move
        elif self.tabs.currentIndex() == 0:
            self.rig_view.update_from_universe(latest)         # only while it is on screen

        self._mirror_manual()
        self._refresh_status(snap)
        self._refresh_live(snap)

        if self.app.show_engine.silence.active:
            _say(self.l_auto_blackout, "● AUTO-BLACKOUT · no music detected", "bad")
        else:
            _say(self.l_auto_blackout, "")
        self._refresh_laser()

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

        held = self.app.manual.blackout or self.app.manual.freeze   # the stage says which
        quiet = not held and all(lbl.isHidden() for lbl in (self.l_pdl_lost, self.l_auto_blackout, self.l_cue,
                                                            self.l_arm, self.l_laser_flash, self.l_synth))
        if self.l_idle.isHidden() == quiet:
            self.l_idle.setVisible(quiet)

    def _refresh_laser(self) -> None:
        """The laser chip and activity line, per laser profile."""
        laser = self.app.laser_engine
        manual = self.app.manual
        mood = getattr(laser, "mood", None)  # engines/laser_feature.py and laser_trigger.py have one
        trigger = getattr(laser, "trigger", None)  # only engines/laser_trigger.py (2026-10-06)
        scene_name = getattr(laser, "scene_name", None)  # only engines/laser_show.py (2026-10-08)
        if scene_name is not None:
            # Show profile: the chip names the scene; the line says what the
            # rotation / accent are doing.
            accent = bool(getattr(laser, "accent", False))
            mode = getattr(laser, "mode", "")
            self.l_laser.setText(f"SHOW · {scene_name.upper()}" + (" · ACCENT" if accent else ""))
            lit = scene_name.lower() not in ("off", "dark")
            set_css(self.l_laser, _CHIP[TEXT if lit else TEXT_3])
            if manual.blackout:
                text, tone = "○ LASERS BLACKED OUT (B)", "bad"
            elif not manual.laser_enable:
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
            # the looks highlight what is showing NOW (follow / rotate move it
            # around; in hold it is the picked look)
            b = self.laser_look_buttons.get(scene_name)
            if b is not None and not b.isChecked():
                b.setChecked(True)
            rb = self._laser_mode_buttons.get(mode)
            if rb is not None and not rb.isChecked():
                _mirror_check(rb, True)
        elif mood is None:
            self.l_laser.setText("ACCENT")
            set_css(self.l_laser, _CHIP[TEXT_2])
            if laser.manual_cued and not manual.laser_enable:
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
        elif trigger is not None:
            lit = bool(laser.active)
            self.l_laser.setText(f"TRIGGER · {mood.upper()} · {laser.budget:.0%} of {int(DUTY_WINDOW_S)} s")
            set_css(self.l_laser, _CHIP[TEXT if lit else TEXT_2])
            if not manual.laser_enable:
                _say(self.l_laser_flash, "○ LASERS NOT ARMED · press L (trigger profile: 2-bar moments on the drop / "
                                         "PEAK blocks / a big wub; J = hit now, K = hold)", "bad")
            elif mood == MOOD_OFF:
                _say(self.l_laser_flash, "○ LASER OFF · waiting for real audio", "bad")
            elif lit:
                _say(self.l_laser_flash, f"● LASER MOMENT · {trigger.upper()} · {laser_color_name(laser.color)}", "ok")
            else:
                _say(self.l_laser_flash, "○ lasers dark, ready · next moment on the drop hit, a PEAK block, "
                                         "a big wub, J or K", "muted")
        else:
            # Feature profile: the lasers ARE the light here, so "not armed"
            # is the loudest thing the console can say.
            self.l_laser.setText(f"FEATURE · {mood.upper()}")
            set_css(self.l_laser, _CHIP[TEXT_3 if mood == MOOD_OFF else TEXT])
            colors = f"{laser_color_name(laser.color_l)} / {laser_color_name(laser.color_r)}"
            if not manual.laser_enable:
                _say(self.l_laser_flash, "○ LASERS NOT ARMED · press L (feature profile: the lasers are the light)", "bad")
            elif mood == MOOD_OFF:
                _say(self.l_laser_flash, "○ LASER OFF · waiting for real audio", "bad")
            else:
                forced = " (K forcing the fan)" if laser.source == "manual" else ""
                _say(self.l_laser_flash,
                     f"● LASER {mood.upper()}{forced} · {colors} · sweep {int(laser.sweep * 100)}%", "ok")


def run_console(app, fps: int = 30) -> int:
    """Open the console and refresh it at ``fps`` (blocks until the window closes)."""
    qt = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    apply_theme(qt)
    win = ConsoleWindow(app, remember=True)
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
