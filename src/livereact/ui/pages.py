"""The console's quieter pages (design v2): Phone remote, Safety, and the
header the two Lights pages share.

Everything they say is what this build actually does. The numbers come from
the modules that enforce them (engines/reactive.py, core/silence.py,
core/metronome.py), and the laser text follows the rig's laser profile, so
the page can't drift from the engine. These pages only read; the controls
that change the show are on the Live page.
"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from ..core.metronome import PDL_LOST_HOLD_BARS
from ..core.silence import HOLD_S
from ..engines.reactive import STROBE_MAX_BURST_S, STROBE_MIN_SPACING_S, STROBE_TOGGLE_MAX_HZ
from . import icons, theme
from .widgets import StatusLine, heading, hbox, icon_label, label, panel, segmented, tile

_ALIGN = QtCore.Qt.AlignmentFlag


def _n(x: float) -> str:
    return f"{x:g}"


def page_head(title: str, lead: str, eyebrow: str = "") -> QtWidgets.QVBoxLayout:
    v = QtWidgets.QVBoxLayout()
    v.setSpacing(theme.SP2)
    if eyebrow:
        v.addWidget(label(eyebrow, "label"))
    v.addWidget(label(title, "pageTitle"))
    lead_l = label(lead, "lead", wrap=True)
    lead_l.setMaximumWidth(720)
    v.addWidget(lead_l)
    return v


def _rules(lines: list[str]) -> QtWidgets.QVBoxLayout:
    v = QtWidgets.QVBoxLayout()
    v.setSpacing(10)
    for text in lines:
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(10)
        ic = icon_label("check", theme.OK, 16)
        row.addWidget(ic, 0, _ALIGN.AlignTop)
        lbl = label(text, "body", wrap=True)
        row.addWidget(lbl, 1)
        v.addLayout(row)
    return v


def _panel(margins=(22, 22, 22, 22), spacing: int = 16) -> tuple[QtWidgets.QFrame, QtWidgets.QBoxLayout]:
    return panel(margins, spacing)


class LightsHeader(QtWidgets.QWidget):
    """Title, a Room / Addresses switch between the two rig pages, and the
    fixture-test note. ``seg_buttons`` are wired by the console."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        h = QtWidgets.QHBoxLayout(self)
        h.setContentsMargins(theme.SP8, 28, theme.SP8, theme.SP2)
        h.setSpacing(theme.SP5)
        h.addLayout(page_head("Your lights", "Drag a light to where it hangs in the room. "
                                             "LiveReact uses this to aim the moving heads."), 1)
        self.seg, self.seg_group, self.seg_buttons = segmented(["Room", "Addresses"])
        self.seg.setFixedWidth(220)
        self.b_test = QtWidgets.QPushButton("Test lights")
        self.b_test.setIcon(icons.icon("flash", theme.TEXT_2, size=16))
        self.b_test.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.b_test.setToolTip("Raw DMX channel test. Runs as its own mode, with the show stopped.")
        h.addWidget(self.seg, 0, _ALIGN.AlignBottom)
        h.addWidget(self.b_test, 0, _ALIGN.AlignBottom)


class PhonePage(QtWidgets.QScrollArea):
    """The phone console (--phone): its address while it is on, what it can
    do, and how to turn it on when it is off. ``phone_row`` / ``l_phone``
    are filled by the console's refresh."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        inner = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(inner)
        v.setContentsMargins(theme.SP8, 28, theme.SP8, 48)
        v.setSpacing(theme.SP5)
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setWidget(inner)
        cols = QtWidgets.QHBoxLayout()
        cols.setSpacing(48)
        left = QtWidgets.QVBoxLayout()
        left.setSpacing(theme.SP5)
        cols.addLayout(left, 1)
        cols.addWidget(self._phone_controls(), 0, _ALIGN.AlignTop)
        left.addLayout(page_head("Run the room from your pocket.",
                              "Walk the floor, talk to the owner, grab a drink. Your phone shows what the "
                              "lights are doing and gives you the controls that make the room calmer. "
                              "Nothing to install.", eyebrow="Phone remote"))

        # on: the address
        self.phone_row, pv = _panel((20, 18, 20, 20), 10)
        pv.addWidget(label("Open this on your phone", "strong"))
        pv.addWidget(label("Use a phone on the same Wi-Fi as this computer. The code at the end is new "
                           "every time LiveReact starts.", "body2", wrap=True))
        self.l_phone = label("", "url")
        self.l_phone.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.l_phone.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)   # never steals B / F / Space
        self.l_phone.setToolTip("Select the text to copy it.")
        pv.addWidget(self.l_phone)
        self.phone_row.hide()
        left.addWidget(self.phone_row)

        # off: how to turn it on
        self.off_row, ov = _panel((20, 18, 20, 20), 6)
        ov.addLayout(hbox(StatusLine("Phone remote is off", "off", role="strong"), stretch_at=1))
        ov.addWidget(label("Turn on Phone console in the launch window, or start LiveReact with --phone.",
                           "body2", wrap=True))
        left.addWidget(self.off_row)

        call, cv = _panel((18, 18, 18, 18), 0)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(14)
        row.addWidget(tile("shieldok", theme.OK), 0, _ALIGN.AlignTop)
        txt = QtWidgets.QVBoxLayout()
        txt.setSpacing(4)
        txt.addWidget(label("Your phone can only make things calmer.", "strong"))
        txt.addWidget(label("It can black out, dim, lower the strobe limit and switch lasers off. Releasing a "
                            "blackout, turning lasers on or raising anything needs this computer, so a lost "
                            "phone can't make the room less safe.", "body2", wrap=True))
        row.addLayout(txt, 1)
        cv.addLayout(row)
        left.addWidget(call)
        for w in (self.phone_row, self.off_row, call):
            w.setMaximumWidth(760)
        left.addStretch(1)
        v.addLayout(cols)
        v.addStretch(1)

    @staticmethod
    def _phone_controls() -> QtWidgets.QFrame:
        """What the phone page (remote/page.py) actually offers."""
        f, pv = _panel((20, 18, 20, 20), 14)
        f.setFixedWidth(360)
        pv.addWidget(label("On your phone", "h3"))
        for icon_name, title, text in (
                ("power", "Blackout", "Turns every light off. Only this computer brings them back."),
                ("sun", "Dim", "Down 10 %, or to 50 % or 25 %. Never brighter."),
                ("flash", "Strobe limit", "Lower it to 50 % or 0 %. This caps the lights' own strobe channel; "
                                          "the automatic strobe keeps its own limit."),
                ("laser", "Lasers off", "Switches the lasers off. Never on."),
        ):
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(12)
            row.addWidget(tile(icon_name, theme.TEXT_2), 0, _ALIGN.AlignTop)
            t = QtWidgets.QVBoxLayout()
            t.setSpacing(2)
            t.addWidget(label(title, "strong"))
            t.addWidget(label(text, "body2", wrap=True))
            row.addLayout(t, 1)
            pv.addLayout(row)
        pv.addWidget(label("It also shows the brightness, strobe limit and laser switch, and what was used "
                           "from the phone.", "hint", wrap=True))
        return f


    def set_url(self, url: str | None) -> None:
        self.l_phone.setText(url or "")
        self.phone_row.setVisible(bool(url))
        self.off_row.setVisible(not url)


class _StrobeZones(QtWidgets.QWidget):
    """The flash-speed bar: where the automatic strobe lives (green), the
    band to stay out of (red hatch). Drawn once."""

    def __init__(self, max_hz: float, parent=None) -> None:
        super().__init__(parent)
        self.max_hz = max_hz
        self.setMinimumHeight(30)
        self.setAccessibleName(f"Flash speed: the automatic strobe stays at or under {_n(max_hz)} a second; "
                               "10 to 25 a second is the range to avoid")

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        w = float(self.width())
        x = lambda hz: hz / 25.0 * w  # noqa: E731
        bar = QtCore.QRectF(0, 0, w, 12)
        clip = QtGui.QPainterPath()
        clip.addRoundedRect(bar, 4, 4)
        p.setClipPath(clip)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.fillRect(QtCore.QRectF(0, 0, x(self.max_hz) - 1, 12), QtGui.QColor(theme.OK))
        p.fillRect(QtCore.QRectF(x(self.max_hz) + 1, 0, x(10) - x(self.max_hz) - 2, 12), QtGui.QColor(theme.SURFACE_3))
        p.fillRect(QtCore.QRectF(x(10) + 1, 0, w - x(10), 12), theme.qcolor(theme.DANGER, 0.55))
        hatch = QtGui.QPen(QtGui.QColor(theme.DANGER), 4)
        p.setPen(hatch)
        xx = x(10) - 12
        while xx < w + 12:
            p.drawLine(QtCore.QPointF(xx, 14), QtCore.QPointF(xx + 12, -2))
            xx += 8
        p.setClipping(False)
        p.setFont(theme.font(11))
        p.setPen(QtGui.QColor(theme.TEXT_3))
        fm = QtGui.QFontMetricsF(p.font())
        for hz, text in ((0, "0"), (self.max_hz, _n(self.max_hz)), (10, "10"), (25, "25 a second")):
            tw = fm.horizontalAdvance(text)
            tx = 0 if hz == 0 else w - tw if hz == 25 else x(hz) - tw / 2
            p.drawText(QtCore.QPointF(tx, 28), text)


def _key(color: str, text: str) -> QtWidgets.QWidget:
    w = QtWidgets.QWidget()
    h = QtWidgets.QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(6)
    sw = QtWidgets.QLabel()
    sw.setFixedSize(8, 8)
    theme.set_css(sw, f"background: {color}; border-radius: 2px;")
    h.addWidget(sw)
    h.addWidget(label(text, "body2"))
    return w


# What each laser profile does at launch and when the signal drops
# (app.py arms "show" and "manual" at launch; engines/laser*.py).
_OFF_AT_LAUNCH = ("Lasers start off, every time",
                  ["They are off when the app opens. Only this computer can turn them on (L).",
                   "They go dark if the music signal drops."])
_LASER_COPY = {
    "accent": (_OFF_AT_LAUNCH[0], [_OFF_AT_LAUNCH[1][0], "They go dark if the music or DJ Link signal drops."]),
    "feature": _OFF_AT_LAUNCH,
    "trigger": _OFF_AT_LAUNCH,
    "show": ("This rig's laser show starts on",
             ["The laser switch is on when the app opens. Press L to switch it off.",
              "If the signal drops, the laser show keeps running on its own clock."]),
    "manual": ("Lasers wait for your scene",
               ["The laser switch is on when the app opens, but nothing lights until you press a scene.",
                "They don't follow the music, so a lost signal doesn't change them."]),
}


class SafetyPage(QtWidgets.QScrollArea):
    def __init__(self, laser_profile: str, demo: bool, failsafe_glow: bool, parent=None) -> None:
        super().__init__(parent)
        inner = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(inner)
        v.setContentsMargins(theme.SP8, 28, theme.SP8, 48)
        v.setSpacing(theme.SP6)
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setWidget(inner)
        v.addLayout(page_head("Safety", "LiveReact keeps your room safe by default. Here is what it does, "
                                        "in plain words."))
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        hz = STROBE_TOGGLE_MAX_HZ

        strobe, sv = _panel()
        sv.addWidget(_section_label("flash", "Strobe"))
        sv.addWidget(label(f"The automatic strobe stays at {_n(hz)} flashes a second or less", "h2", wrap=True))
        sv.addWidget(_StrobeZones(hz))
        keys = QtWidgets.QHBoxLayout()
        keys.setSpacing(14)
        keys.addWidget(_key(theme.OK, f"Up to {_n(hz)} a second"))
        keys.addWidget(_key(theme.DANGER, "Avoid 10 to 25 a second"))
        keys.addStretch(1)
        sv.addLayout(keys)
        sv.addLayout(_rules([
            f"Drop and peak flashes come in bursts of {_n(STROBE_MAX_BURST_S)} seconds at most, "
            f"at least {_n(STROBE_MIN_SPACING_S)} seconds apart.",
            "The strobe limit fader caps the Space burst and each light's own strobe channel.",
            "Put a strobe warning sign at the door.",
        ]))
        note = QtWidgets.QFrame()
        note.setObjectName("notice")
        nh = QtWidgets.QHBoxLayout(note)
        nh.setContentsMargins(14, 12, 14, 12)
        nh.setSpacing(10)
        nh.addWidget(icon_label("alert", theme.WARN, 16), 0, _ALIGN.AlignTop)
        nh.addWidget(label("The Space burst uses each light's own strobe, and its real speed hasn't been "
                           "measured on your lights. Measure it with --strobe-calibrate before a show.",
                           "body", wrap=True), 1)
        sv.addWidget(note)
        sv.addStretch(1)

        title, lines = _LASER_COPY.get(laser_profile, _LASER_COPY["accent"])
        lasers, lv = _panel()
        lv.addWidget(_section_label("laser", "Lasers"))
        lv.addWidget(label(title, "h2", wrap=True))
        lv.addLayout(_rules(lines + [
            "Blackout turns them off with everything else.",
            "Your phone can switch them off, never on.",
            "LiveReact can't see where the beams go. Mount lasers above head height (at least 3 m, "
            "10 ft) and aim them over the crowd.",
        ] + (["In demo mode nothing is sent to the lights."] if demo else [])))
        lv.addStretch(1)

        steady, wv = _panel()
        wv.addWidget(_section_label("shield", "When things go wrong"))
        wv.addWidget(label("The show keeps itself steady", "h2", wrap=True))
        silence = ("the wash fades to a soft white glow" if failsafe_glow else "the lights go dark")
        wv.addLayout(_rules([
            "No internet needed. The show runs on this computer.",
            "If the light adapter is unplugged, the lights come back by themselves about a second "
            "after you plug it back in.",
            f"If DJ Link goes quiet, the look holds for up to {PDL_LOST_HOLD_BARS} bars, then follows the audio.",
            f"When the music stops for {_n(HOLD_S)} seconds, {silence}. "
            "They come back the moment the music does.",
            "If LiveReact stops during a live show, it restarts by itself and keeps your blackout, "
            "brightness and strobe limit. Lasers stay off if they were off.",
            "Your phone can only make things calmer.",
        ]))
        wv.addStretch(1)

        for i, w in enumerate((strobe, lasers, steady)):
            grid.addWidget(w, 0, i, _ALIGN.AlignTop)
            grid.setColumnStretch(i, 1)
        v.addLayout(grid)
        v.addStretch(1)


def _section_label(icon_name: str, text: str) -> QtWidgets.QWidget:
    w = QtWidgets.QWidget()
    h = heading(text, icon_name, role="label", color=theme.TEXT_2, size=18, spacing=10)
    h.setContentsMargins(0, 0, 0, 0)
    w.setLayout(h)
    return w
