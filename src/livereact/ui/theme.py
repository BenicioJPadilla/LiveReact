"""Console design system, v2: tokens, fonts and the one stylesheet.

The idea: the booth is dark, and the only colour is the light. The chrome is
graphite; colour comes from the show itself. The live light colour (the
"glow", ui/glow.py) tints the stage, the faders, the beat lights and the open
page's nav glyph. Status colours (ok, amber, red) appear only as small dots,
and red is also the Blackout key.

Tokens come from the approved prototype (lr-design/prototype-v2.html):

  * four graphite steps by role (page, panel, raised, hover) plus a sunk
    "well" for faders and inputs, three alpha hairlines, and a 1 px top
    highlight on raised surfaces only;
  * a radius hierarchy: 20 stage, 14 panels, 10 buttons and inputs,
    6 keycaps and chips;
  * Instrument Sans for UI text and Instrument Sans Condensed (wdth 75) for
    display and readouts, both with tabular figures; Geist Mono only where
    the content is literally technical (keycaps, DMX addresses). All three
    are bundled under ui/fonts/ (SIL OFL 1.1) and loaded by ``load_fonts``.

Widgets that paint themselves (ui/widgets.py, the floor plan) read the same
constants. A stylesheet can't follow a colour that changes every frame, so
nothing in the stylesheet uses the glow; the painted widgets do.
"""

from __future__ import annotations

import os

from PySide6 import QtGui, QtWidgets

# --- colour ------------------------------------------------------------------
BG = "#0C0D0F"          # the booth: window ground
SIDEBAR = "#0A0B0D"     # the sidebar, one step below the page
SURFACE = "#141518"     # panels
SURFACE_2 = "#1B1D21"   # raised: buttons, chips, the lit nav row
SURFACE_3 = "#24272C"   # hover / pressed / tracks
SURFACE_4 = "#2B2E34"   # pad hover top
WELL = "#08090A"        # sunk: fader wells, inputs
DECK = "#0B0C0E"        # the strip under the stage
ROOM = "#040405"        # inside the stage

# Hairlines are white at low alpha, so they read the same on every step.
LINE = "rgba(255,255,255,18)"     # .07
LINE_2 = "rgba(255,255,255,28)"   # .11
LINE_3 = "rgba(255,255,255,46)"   # .18
HIGHLIGHT = "rgba(255,255,255,14)"  # .055, the top edge of a raised surface
# The same hairlines flattened onto a panel, for painters and SVG assets
# that need an opaque colour.
LINE_SOLID = "#232428"
LINE_2_SOLID = "#2D2F33"
LINE_3_SOLID = "#3D3F44"

TEXT = "#EDEEF0"
TEXT_2 = "#A2A6AE"
TEXT_3 = "#6F737B"
ON_TEXT = "#0C0D0F"      # ink on a white (primary / lit) surface

OK = "#4FD89A"
WARN = "#F2B544"
DANGER = "#FF5B4D"
DANGER_TEXT = "#FF9A90"
DANGER_INK = "#1A0503"   # ink on a red fill

# Older names other views still import. There is no static accent any more:
# "primary" is white, and "on / healthy" is the ok dot.
ACCENT = TEXT
ON_ACCENT = ON_TEXT
PANEL = SURFACE
BORDER = LINE_2
MUTED = TEXT_3

# --- spacing / radius / type (px) ---------------------------------------------
SP1, SP2, SP3, SP4, SP5, SP6, SP8 = 4, 8, 12, 16, 20, 24, 32
R_XS, R_SM, R_MD, R_LG = 6, 10, 14, 20
FONT_UI = "Instrument Sans"
FONT_DISPLAY = "Instrument Sans Condensed"
FONT_MONO = "Geist Mono"
_UI_STACK = '"Instrument Sans", "SF Pro Text", "Helvetica Neue", "Segoe UI", sans-serif'
_DISPLAY_STACK = '"Instrument Sans Condensed", "Instrument Sans", "SF Pro Display", "Helvetica Neue", sans-serif'
_MONO_STACK = '"Geist Mono", "SF Mono", "Menlo", "Consolas", monospace'

_HERE = os.path.dirname(os.path.abspath(__file__))
_FONT_DIR = os.path.join(_HERE, "fonts")
_ICON_DIR = os.path.join(_HERE, "icons")


def rgba(color: str, alpha: float) -> str:
    c = QtGui.QColor(color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{int(round(alpha * 255))})"


def chip_css(color: str = TEXT_2) -> str:
    """A quiet chip: the text in ``color`` on a raised graphite step."""
    return (f"background:{SURFACE_2}; color:{color}; border:1px solid {LINE};"
            f" border-radius:{R_XS}px;")


def font(size: float, weight: QtGui.QFont.Weight = QtGui.QFont.Weight.Normal,
         mono: bool = False, display: bool = False) -> QtGui.QFont:
    """A QFont on the type scale, for widgets that paint text themselves."""
    f = QtGui.QFont()
    if mono:
        f.setFamilies([FONT_MONO, "SF Mono", "Menlo", "Consolas"])
    elif display:
        f.setFamilies([FONT_DISPLAY, FONT_UI, "Helvetica Neue", "Segoe UI"])
    else:
        f.setFamilies([FONT_UI, "SF Pro Text", "Helvetica Neue", "Segoe UI"])
    f.setPixelSize(max(1, round(size)))
    f.setWeight(weight)
    return f


def _icon_url(name: str) -> str:
    return os.path.join(_ICON_DIR, name).replace(os.sep, "/")


def _build_qss() -> str:
    ui, mono, disp = _UI_STACK, _MONO_STACK, _DISPLAY_STACK
    panel_bg = f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #17181B, stop:0.18 {SURFACE}, stop:1 {SURFACE})"
    return f"""
QWidget {{
    background: transparent;
    color: {TEXT};
    font-family: {ui};
    font-size: 13px;
    font-weight: 400;
}}
QMainWindow, QDialog, QMessageBox {{ background: {BG}; }}
QMainWindow::separator {{ background: transparent; }}
QMenu {{
    background: {SURFACE_2}; border: 1px solid {LINE_3}; border-radius: {R_SM}px; padding: 4px;
}}
QMenu::item {{ padding: 6px 16px; border-radius: 6px; }}
QMenu::item:selected {{ background: {SURFACE_3}; }}
QMenu::item:disabled {{ color: {TEXT_3}; }}
QComboBox QFrame {{ background: {SURFACE_2}; }}
QToolTip {{
    background: {SURFACE_2}; color: {TEXT}; border: 1px solid {LINE_3};
    border-radius: {R_XS}px; padding: 6px 8px; font-size: 12.5px;
}}

/* ---- shell ---- */
QFrame#sidebar {{ background: {SIDEBAR}; border: none; border-right: 1px solid {LINE}; }}
QLabel#wordmark {{ font-family: {disp}; font-size: 17px; font-weight: 600; color: {TEXT}; }}
QLabel#modeBadge {{
    font-size: 11.5px; font-weight: 500; color: {TEXT_3};
    border: 1px solid {LINE_2}; border-radius: {R_XS}px; padding: 1px 7px;
}}
QLabel#group {{ color: {TEXT_3}; font-size: 11.5px; font-weight: 500; padding: 14px 10px 4px 10px; }}
QTabWidget::pane {{ border: none; background: transparent; }}
QStackedWidget {{ background: transparent; }}

/* ---- type ---- */
QLabel#pageTitle {{ font-family: {disp}; font-size: 40px; font-weight: 600; color: {TEXT}; }}
QLabel#lead {{ color: {TEXT_2}; font-size: 15px; }}
QLabel#h2 {{ font-family: {disp}; font-size: 20px; font-weight: 600; color: {TEXT}; }}
QLabel#h3 {{ font-family: {disp}; font-size: 16px; font-weight: 600; color: {TEXT}; }}
QLabel#cardTitle {{ font-family: {disp}; font-size: 16px; font-weight: 600; color: {TEXT}; }}
QLabel#label, QLabel#overline {{ color: {TEXT_2}; font-size: 12.5px; font-weight: 500; }}
QLabel#hint {{ color: {TEXT_3}; font-size: 12.5px; }}
QLabel#body {{ color: {TEXT}; font-size: 13.5px; }}
QLabel#body2 {{ color: {TEXT_2}; font-size: 13px; }}
QLabel#strong {{ color: {TEXT}; font-size: 14px; font-weight: 600; }}
QLabel#value {{ color: {TEXT}; font-size: 13px; font-weight: 500; }}
QLabel#valueMono {{ color: {TEXT}; font-family: {mono}; font-size: 12.5px; font-weight: 500; }}
QLabel#footNote {{ color: {TEXT_3}; font-size: 12.5px; }}
QLabel#readTitle {{ font-family: {disp}; font-size: 22px; font-weight: 600; color: {TEXT}; }}
QLabel#readText {{ color: {TEXT_2}; font-size: 13px; }}
QLabel#bpm {{ font-family: {disp}; font-size: 40px; font-weight: 600; color: {TEXT}; }}
QLabel#bpmUnit {{ color: {TEXT_3}; font-size: 12.5px; }}
QLabel#bucket {{ font-size: 12px; font-weight: 600; padding: 2px 8px; }}
QLabel#code, QLabel#url {{
    font-family: {mono}; font-size: 13px; color: {TEXT};
    background: {WELL}; border: 1px solid {LINE_2}; border-radius: {R_SM}px; padding: 10px 12px;
}}
QLabel#address {{
    font-family: {mono}; font-size: 12.5px; color: {TEXT};
    background: {WELL}; border: 1px solid {LINE_2}; border-radius: 5px; padding: 1px 6px;
}}
QLabel#health, QLabel#footerMono {{ color: {TEXT_3}; font-family: {mono}; font-size: 11px; }}
QLabel#footerText {{ color: {TEXT_3}; font-size: 12px; }}

/* ---- surfaces ---- */
QFrame#card, QFrame#panel, QGroupBox {{
    background: {panel_bg}; border: 1px solid {LINE}; border-radius: {R_MD}px;
}}
QGroupBox {{
    margin-top: 0; padding: 40px 12px 12px 12px;
    font-family: {disp}; font-size: 16px; font-weight: 600; color: {TEXT};
}}
QGroupBox::title {{
    subcontrol-origin: padding; subcontrol-position: top left;
    left: 16px; top: 14px; padding: 0; color: {TEXT};
}}
QFrame#hair {{ background: {LINE}; border: none; min-height: 1px; max-height: 1px; }}
QFrame#vhair {{ background: {LINE}; border: none; min-width: 1px; max-width: 1px; }}
QFrame#notice {{
    background: {rgba(WARN, 0.07)}; border: 1px solid {rgba(WARN, 0.22)}; border-radius: {R_SM}px;
}}
QFrame#callout {{
    background: {panel_bg}; border: 1px solid {LINE}; border-radius: {R_MD}px;
}}

/* ---- activity lines (Under the hood) ---- */
QLabel#banner {{ font-size: 12.5px; font-weight: 500; padding: 6px 10px; border-radius: 8px; }}
QLabel#idle {{ color: {TEXT_3}; font-size: 12.5px; padding: 6px 2px; }}

/* ---- buttons ---- */
QPushButton {{
    background: {SURFACE_2}; color: {TEXT}; border: 1px solid {LINE_2};
    border-top-color: {LINE_3};
    border-radius: {R_SM}px; min-height: 34px; padding: 0 14px;
    font-size: 13.5px; font-weight: 600;
}}
QPushButton:hover {{ background: {SURFACE_3}; }}
QPushButton:pressed {{ background: {SURFACE_3}; padding-top: 1px; }}
QPushButton:focus {{ border-color: {TEXT_3}; }}
QPushButton:disabled {{ background: {SURFACE}; color: {TEXT_3}; border-color: {LINE}; }}

QPushButton#primary {{ background: {TEXT}; color: {ON_TEXT}; border: 1px solid {TEXT}; }}
QPushButton#primary:hover {{ background: #FFFFFF; border-color: #FFFFFF; }}
QPushButton#primary:disabled {{ background: {SURFACE_2}; color: {TEXT_3}; border-color: {LINE}; }}
QPushButton#ghost {{ background: transparent; border-color: transparent; color: {TEXT_2}; }}
QPushButton#ghost:hover {{ background: rgba(255,255,255,13); color: {TEXT}; }}
QPushButton#dangerFill {{ background: {DANGER}; border: 1px solid {DANGER}; color: {DANGER_INK}; }}
QPushButton#dangerFill:hover {{ background: #FF6E61; border-color: #FF6E61; }}
QPushButton#dangerFill:disabled, QPushButton#primary:disabled {{
    background: {SURFACE_2}; color: {TEXT_3}; border-color: {LINE};
}}
QPushButton#ghostDanger {{ background: transparent; color: {DANGER_TEXT}; border-color: {rgba(DANGER, 0.45)}; }}
QPushButton#ghostDanger:hover {{ background: {rgba(DANGER, 0.10)}; }}

/* segmented control: a sunk well, the picked one raised */
QFrame#seg {{ background: {WELL}; border: 1px solid {LINE}; border-radius: {R_SM}px; }}
QPushButton#segItem, QRadioButton#segItem {{
    background: transparent; border: 1px solid transparent; border-radius: 7px;
    min-height: 26px; padding: 0 10px; color: {TEXT_2}; font-size: 12.5px; font-weight: 500;
}}
QRadioButton#segItem::indicator {{ width: 0; height: 0; }}
QPushButton#segItem:hover, QRadioButton#segItem:hover {{ color: {TEXT}; }}
QPushButton#segItem:checked, QRadioButton#segItem:checked {{
    background: {SURFACE_3}; color: {TEXT}; border-color: {LINE}; border-top-color: {LINE_2};
}}

/* laser looks / scenes: small chips, the live one outlined */
QPushButton#look {{
    background: transparent; border: 1px solid {LINE_2}; border-radius: {R_XS}px;
    min-height: 26px; padding: 0 9px; color: {TEXT_2}; font-size: 12px; font-weight: 500;
}}
QPushButton#look:hover {{ color: {TEXT}; border-color: {LINE_3}; }}
QPushButton#look:checked {{ color: {ON_TEXT}; background: {TEXT}; border-color: {TEXT}; }}
QPushButton#lookOff {{
    background: transparent; border: 1px solid {rgba(DANGER, 0.40)}; border-radius: {R_XS}px;
    min-height: 26px; padding: 0 9px; color: {DANGER_TEXT}; font-size: 12px; font-weight: 600;
}}
QPushButton#lookOff:checked {{ background: {rgba(DANGER, 0.16)}; border-color: {DANGER}; }}

/* the painted controls (widgets.py) take only their frame from here */
QPushButton#cue, QPushButton#danger, QPushButton#blackout, QAbstractButton#nav,
QAbstractButton#proSwitch, QCheckBox#toggleRow {{
    background: transparent; border: none; padding: 0;
}}
QPushButton#cue {{ min-height: 64px; max-height: 64px; }}
QPushButton#blackout {{ min-height: 74px; max-height: 74px; }}

/* ---- toggles / radios ---- */
QCheckBox, QRadioButton {{ spacing: 12px; font-size: 14px; color: {TEXT}; min-height: 26px; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: {TEXT_3}; }}
QCheckBox::indicator {{ width: 34px; height: 20px; image: url("{_icon_url('switch-off.svg')}"); }}
QCheckBox::indicator:hover {{ image: url("{_icon_url('switch-off-hover.svg')}"); }}
QCheckBox::indicator:checked {{ image: url("{_icon_url('switch-on.svg')}"); }}
QCheckBox::indicator:checked:hover {{ image: url("{_icon_url('switch-on-hover.svg')}"); }}
QCheckBox::indicator:disabled {{ image: url("{_icon_url('switch-disabled.svg')}"); }}
QCheckBox#checkLine {{
    background: {WELL}; border: 1px solid {LINE}; border-radius: {R_SM}px; padding: 12px; font-size: 14px;
}}
QCheckBox#checkLine::indicator {{ width: 18px; height: 18px; image: url("{_icon_url('check-off.svg')}"); }}
QCheckBox#checkLine::indicator:checked {{ image: url("{_icon_url('check-on.svg')}"); }}
QRadioButton::indicator {{ width: 18px; height: 18px; image: url("{_icon_url('radio-off.svg')}"); }}
QRadioButton::indicator:checked {{ image: url("{_icon_url('radio-on.svg')}"); }}
QRadioButton#option {{
    background: {SURFACE_2}; border: 1px solid {LINE_2}; border-radius: {R_SM}px;
    padding: 12px 14px; min-height: 24px;
}}
QRadioButton#option:hover {{ background: {SURFACE_3}; }}
QRadioButton#option:checked {{ background: {SURFACE_3}; border-color: {TEXT_2}; }}

/* ---- sliders (the live faders paint themselves, widgets.GlowFader) ---- */
QSlider {{ min-height: 24px; }}
QSlider::groove:horizontal {{ height: 6px; background: {WELL}; border: 1px solid {LINE}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {TEXT_2}; border-radius: 3px; }}
QSlider::handle:horizontal {{
    width: 16px; height: 16px; margin: -6px 0; border-radius: 8px;
    background: {TEXT}; border: 3px solid {SURFACE};
}}
QSlider::handle:horizontal:hover {{ background: #FFFFFF; }}
QSlider::sub-page:horizontal:disabled {{ background: {TEXT_3}; }}
QSlider#glowFader {{ min-height: 40px; max-height: 40px; }}
QSlider#glowFaderSm {{ min-height: 24px; max-height: 24px; }}
QSlider#glowFader::groove:horizontal, QSlider#glowFaderSm::groove:horizontal {{
    height: 24px; background: transparent; border: none;
}}
QSlider#glowFader::handle:horizontal, QSlider#glowFaderSm::handle:horizontal {{
    width: 14px; height: 24px; margin: 0; border: none; background: transparent;
}}
QSlider#glowFader::sub-page:horizontal, QSlider#glowFaderSm::sub-page:horizontal {{ background: transparent; }}

/* ---- inputs ---- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {WELL}; border: 1px solid {LINE_2}; border-radius: {R_SM}px;
    min-height: 32px; padding: 0 10px; selection-background-color: {rgba(TEXT, 0.22)};
    font-family: {ui}; font-size: 13px;
}}
QSpinBox, QDoubleSpinBox {{ padding-right: 24px; }}
QAbstractSpinBox[compact="true"] {{ min-height: 28px; }}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {LINE_3}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {TEXT_2}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {TEXT_3}; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border; subcontrol-position: top right; width: 22px; border: none; margin: 2px 2px 0 0;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border; subcontrol-position: bottom right; width: 22px; border: none; margin: 0 2px 2px 0;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: {SURFACE_3}; border-radius: 4px; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{_icon_url('chevron-up.svg')}"); width: 10px; height: 10px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{_icon_url('chevron-down.svg')}"); width: 10px; height: 10px; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{ image: url("{_icon_url('chevron-down.svg')}"); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE_2}; border: 1px solid {LINE_3}; border-radius: {R_SM}px; padding: 4px;
    selection-background-color: {SURFACE_3}; selection-color: {TEXT}; outline: none;
}}

/* ---- tables / text ---- */
QTableWidget, QTableView {{
    background: {SURFACE}; alternate-background-color: #17181B; border: none;
    gridline-color: {LINE_SOLID}; selection-background-color: {SURFACE_3}; selection-color: {TEXT};
    font-size: 13px;
}}
QTableWidget::item, QTableView::item {{ padding: 0 8px; border-bottom: 1px solid {LINE}; }}
QTableWidget QComboBox, QTableWidget QSpinBox {{ border-radius: 6px; min-height: 28px; margin: 3px 4px; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: {SURFACE}; color: {TEXT_3}; border: none; border-bottom: 1px solid {LINE_2};
    padding: 8px 10px; font-size: 12px; font-weight: 500;
}}
QTableCornerButton::section {{ background: {SURFACE}; border: none; }}
QTextEdit, QPlainTextEdit {{
    background: {WELL}; border: 1px solid {LINE_2}; border-radius: {R_SM}px; padding: 8px;
}}
QTextEdit#mono {{ font-family: {mono}; font-size: 12px; color: {TEXT_2}; }}

/* ---- scrolling / splitters ---- */
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QAbstractScrollArea {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {LINE_3}; border-radius: 3px; min-height: 40px; margin: 0 1px; }}
QScrollBar::handle:horizontal {{ background: {LINE_3}; border-radius: 3px; min-width: 40px; margin: 1px 0; }}
QScrollBar::handle:hover {{ background: {TEXT_3}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 12px; }}
QSplitter::handle:vertical {{ height: 12px; }}
QGraphicsView {{ border: none; background: transparent; }}
"""


_fonts_loaded = False


def load_fonts() -> bool:
    """Register the bundled Instrument Sans / Geist Mono cuts (once).
    Absolute paths: Qt's offscreen/cocoa platforms reject relative ones.
    Returns True when they are available; the stylesheet's fallback stack
    covers a failure."""
    global _fonts_loaded
    if _fonts_loaded:
        return True
    if QtWidgets.QApplication.instance() is None or not os.path.isdir(_FONT_DIR):
        return False
    ok = False
    for name in sorted(os.listdir(_FONT_DIR)):
        if name.endswith(".ttf"):
            ok |= QtGui.QFontDatabase.addApplicationFont(os.path.join(_FONT_DIR, name)) >= 0
    _fonts_loaded = ok
    return ok


DARK_QSS = _build_qss()


def apply_theme(qapp: QtWidgets.QApplication | None = None) -> None:
    """Install the fonts and stylesheet on the running QApplication.

    Safe to call more than once and with no application yet (a no-op then), so
    headless tests that build a ConsoleWindow directly aren't affected. The
    stylesheet is only (re)set when it differs: re-polishing every widget is
    the most expensive thing a stylesheet can do."""
    qapp = qapp or QtWidgets.QApplication.instance()
    if qapp is None:
        return
    load_fonts()
    if qapp.styleSheet() != DARK_QSS:
        qapp.setStyleSheet(DARK_QSS)


def pad_spinbox(box: QtWidgets.QAbstractSpinBox) -> QtWidgets.QAbstractSpinBox:
    """Inset a spin box's text: stylesheet padding does not reach its inner
    line edit, so set the editor's text margins directly."""
    edit = box.findChild(QtWidgets.QLineEdit)
    if edit is not None:
        edit.setTextMargins(SP2, 0, 0, 0)
    return box


def set_css(widget: QtWidgets.QWidget, css: str) -> None:
    """``setStyleSheet`` only when it changes. A per-widget stylesheet forces
    a re-polish; the console refreshes at 30 Hz and most of its colours
    change a few times a minute, so this keeps the UI thread idle."""
    if widget.property("_css") != css:
        widget.setProperty("_css", css)
        widget.setStyleSheet(css)
