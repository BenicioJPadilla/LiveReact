"""Console design system ("Blackbox"): tokens, fonts and the one stylesheet.

The concept: the console is a piece of stage hardware. Graphite-black
surfaces, monochrome chrome, and exactly ONE signature accent, signal lime,
which always means "live / on / healthy" (a lit cue, a filled fader, a green
link). Every other colour on screen belongs to the show itself: the energy
state, the fixtures and their beams. Red is reserved for the kill switches
(Blackout / Freeze / laser OFF) and for "something is wrong".

Josh operates the console next to the decks while mixing: the booth is dark,
the laptop is at arm's length, and the buttons he reaches for mid-set must be
hittable without looking closely. So the ground is near-black (no glare), the
operator targets are tall, and state is carried by shape and position as well
as colour.

Tokens below are the single source of truth; widgets that paint themselves
(ui/widgets.py, the floor plan) read the same constants. Spacing is on a 4 px
grid. Type: Geist for UI text, Geist Mono for numbers (both SIL OFL 1.1,
bundled under ui/fonts/, loaded by ``load_fonts``); the system sans is the
fallback if they cannot be loaded.

Named roles the views tag with ``setObjectName``:

  ``card`` / ``cardTitle``  a rounded surface and its overline title
  ``cue``                    the show cues: the biggest targets on the screen
  ``look``                   laser look / scene buttons (checked = on air)
  ``danger``                 the hard switches: red while checked
  ``primary``                the one main action of a page (Save)
  ``nav``                    header navigation
  ``bucket``                 an energy-state / laser chip (``chip_css``)
"""

from __future__ import annotations

import os

from PySide6 import QtGui, QtWidgets

# --- colour ------------------------------------------------------------------
BG = "#0A0B0D"          # window ground
SURFACE = "#111316"     # cards
SURFACE_2 = "#171A1E"   # controls / inputs at rest
SURFACE_3 = "#1F2328"   # hover
SURFACE_4 = "#292E34"   # pressed / tracks
LINE = "#1F2328"        # card borders
LINE_2 = "#2B3036"      # control borders
LINE_3 = "#3A4048"      # hover borders, room edges
TEXT = "#EDEFF2"        # 17:1 on SURFACE
TEXT_2 = "#A6ADB7"      # 8.2:1 on SURFACE
TEXT_3 = "#7D8590"      # 5.0:1 on SURFACE (AA for small text)

ACCENT = "#C8F53C"      # signal lime: live / on / healthy
ACCENT_HOVER = "#D7FA6E"
ACCENT_PRESSED = "#AEDB25"
ON_ACCENT = "#0A0B0D"   # text on a lime fill, 16:1
DANGER = "#F0483E"
DANGER_TEXT = "#FF8E86"  # red text on dark, 7.2:1 on SURFACE
WARN = "#FFB224"

# Back-compat names (older modules / user patches import these).
PANEL = SURFACE
BORDER = LINE_2
MUTED = TEXT_3

# Energy-bucket colours (core/show_state.py's `bucket` string values, which are
# scenes/base.py's EnergyBucket values): cool while resting, warm while
# building, hot on the drop. Tuned to stay apart from the lime accent and the
# kill-switch red.
BUCKET_COLORS = {
    "break": "#4D9FFF",   # blue
    "build": "#FFB224",   # amber
    "drop": "#FF6A3D",    # red-orange
    "peak": "#E45CFF",    # magenta
    "outro": "#8A929D",   # slate
}

# --- spacing / radius / type (px) ---------------------------------------------
SP1, SP2, SP3, SP4, SP6 = 4, 8, 12, 16, 24
R_SM, R_MD, R_LG = 6, 10, 14
FONT_UI = "Geist"
FONT_MONO = "Geist Mono"
_FALLBACK_UI = '"Geist", "Inter", "SF Pro Text", "Helvetica Neue", "Segoe UI", sans-serif'
_FALLBACK_MONO = '"Geist Mono", "SF Mono", "Menlo", "Consolas", monospace'

_HERE = os.path.dirname(os.path.abspath(__file__))
_FONT_DIR = os.path.join(_HERE, "fonts")
_ICON_DIR = os.path.join(_HERE, "icons")


def bucket_color(bucket: str) -> str:
    return BUCKET_COLORS.get(bucket, TEXT_3)


def rgba(hex_color: str, alpha: float) -> str:
    c = QtGui.QColor(hex_color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{int(round(alpha * 255))})"


def chip_css(color: str, border: bool = True, radius: int = R_SM) -> str:
    """A tinted chip: the colour as text (+ border) on a faint wash of itself."""
    edge = f"1px solid {rgba(color, 0.45)}" if border else "none"
    return (f"background:{rgba(color, 0.14)}; color:{color}; border:{edge};"
            f" border-radius:{radius}px;")


def font(size: int, weight: QtGui.QFont.Weight = QtGui.QFont.Weight.Normal,
         mono: bool = False) -> QtGui.QFont:
    """A QFont on the type scale, for widgets that paint text themselves."""
    f = QtGui.QFont()
    f.setFamilies([FONT_MONO, "SF Mono", "Menlo", "Consolas"] if mono
                  else [FONT_UI, "Inter", "SF Pro Text", "Helvetica Neue", "Segoe UI"])
    f.setPixelSize(size)
    f.setWeight(weight)
    return f


def _icon_url(name: str) -> str:
    return os.path.join(_ICON_DIR, name).replace(os.sep, "/")


def _build_qss() -> str:
    ui, mono = _FALLBACK_UI, _FALLBACK_MONO
    accent_soft = rgba(ACCENT, 0.12)
    accent_line = rgba(ACCENT, 0.55)
    danger_soft = rgba(DANGER, 0.10)
    danger_line = rgba(DANGER, 0.50)
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
    background: {SURFACE_2}; border: 1px solid {LINE_3}; border-radius: 8px; padding: 4px;
}}
QMenu::item {{ padding: 6px 16px; border-radius: 4px; }}
QMenu::item:selected {{ background: {SURFACE_4}; }}
QMenu::item:disabled {{ color: {TEXT_3}; }}
QComboBox QFrame {{ background: {SURFACE_2}; }}
QToolTip {{
    background: {SURFACE_3}; color: {TEXT}; border: 1px solid {LINE_3};
    border-radius: {R_SM}px; padding: 6px 8px; font-size: 12px;
}}

/* ---- shell ---- */
QFrame#header {{ background: {BG}; border-bottom: 1px solid {LINE}; }}
QFrame#footer {{ background: {BG}; border-top: 1px solid {LINE}; }}
QLabel#wordmark {{ font-size: 17px; font-weight: 700; color: {TEXT}; }}
QLabel#modeBadge {{
    font-family: {mono}; font-size: 10px; font-weight: 600; color: {TEXT_2};
    border: 1px solid {LINE_2}; border-radius: 4px; padding: 1px 6px;
}}
QLabel#footerText {{ color: {TEXT_3}; font-size: 12px; }}
QLabel#footerMono {{ color: {TEXT_3}; font-family: {mono}; font-size: 11px; }}
QTabWidget::pane {{ border: none; background: transparent; }}

QPushButton#nav {{
    background: transparent; color: {TEXT_2}; border: 1px solid transparent;
    border-radius: 8px; min-height: 34px; max-height: 34px; padding: 0 14px 0 10px;
    font-size: 13px; font-weight: 500; text-align: left;
}}
QPushButton#nav:hover {{ background: {SURFACE_2}; color: {TEXT}; }}
QPushButton#nav:checked {{ background: {SURFACE_3}; color: {TEXT}; border-color: {LINE_2}; }}

/* ---- cards ---- */
QFrame#card, QGroupBox {{
    background: {SURFACE}; border: 1px solid {LINE}; border-radius: {R_LG}px;
}}
QGroupBox {{
    margin-top: 0; padding: 40px 12px 12px 12px;
    font-size: 11px; font-weight: 600; color: {TEXT_3};
}}
QGroupBox::title {{
    subcontrol-origin: padding; subcontrol-position: top left;
    left: 16px; top: 15px; padding: 0; color: {TEXT_3};
}}
QLabel#cardTitle {{ color: {TEXT_3}; font-size: 11px; font-weight: 600; }}
QLabel#overline {{ color: {TEXT_3}; font-size: 11px; font-weight: 600; }}
QLabel#hint {{ color: {TEXT_3}; font-size: 12px; }}
QLabel#body2 {{ color: {TEXT_2}; font-size: 13px; }}
QLabel#value {{ color: {TEXT}; font-family: {mono}; font-size: 13px; font-weight: 600; }}
QLabel#pageTitle {{ color: {TEXT}; font-size: 20px; font-weight: 600; }}
QLabel#code {{
    font-family: {mono}; font-size: 12px; color: {TEXT};
    background: {SURFACE_2}; border: 1px solid {LINE_2}; border-radius: {R_SM}px; padding: 8px 10px;
}}

/* ---- hero ---- */
QLabel#bpm {{ font-family: {mono}; font-size: 76px; font-weight: 700; color: {TEXT}; }}
QLabel#bpmUnit {{ font-family: {mono}; font-size: 13px; font-weight: 600; color: {TEXT_3}; }}
QLabel#heroState {{ font-size: 34px; font-weight: 700; padding: 4px 16px; }}
QLabel#heroScene {{ font-size: 17px; font-weight: 600; color: {TEXT}; }}
QLabel#heroMeta {{ font-family: {mono}; font-size: 13px; font-weight: 500; color: {TEXT_2}; }}
QLabel#bucket {{ font-size: 12px; font-weight: 700; padding: 4px 10px; }}

/* ---- activity banners (tone set per state by the console) ---- */
QLabel#banner {{ font-size: 13px; font-weight: 500; padding: 7px 12px; border-radius: 8px; }}
QLabel#idle {{ color: {TEXT_3}; font-size: 13px; padding: 7px 2px; }}

/* ---- buttons ---- */
QPushButton {{
    background: {SURFACE_2}; color: {TEXT}; border: 1px solid {LINE_2};
    border-radius: {R_MD}px; min-height: 38px; padding: 0 16px;
    font-size: 13px; font-weight: 600;
}}
QPushButton:hover {{ background: {SURFACE_3}; border-color: {LINE_3}; }}
QPushButton:pressed {{ background: {SURFACE_4}; }}
QPushButton:focus {{ border-color: {TEXT_3}; }}
QPushButton:disabled {{ background: {SURFACE}; color: {TEXT_3}; border-color: {LINE}; }}

QPushButton#primary {{ background: {ACCENT}; color: {ON_ACCENT}; border-color: {ACCENT}; }}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton#primary:pressed {{ background: {ACCENT_PRESSED}; border-color: {ACCENT_PRESSED}; }}

QPushButton#ghostDanger {{ background: transparent; color: {DANGER_TEXT}; border-color: {danger_line}; }}
QPushButton#ghostDanger:hover {{ background: {danger_soft}; }}

QPushButton#cue {{
    background: {SURFACE_2}; border: 1px solid {LINE_2}; border-radius: 12px;
    min-height: 76px; padding: 0;
}}
QPushButton#cue:hover {{ background: {SURFACE_3}; border-color: {LINE_3}; }}
QPushButton#cue:pressed {{ background: {accent_soft}; border-color: {accent_line}; }}
QPushButton#cue:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QPushButton#cue:checked:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton#cue:focus {{ border-color: {LINE_3}; }}
QPushButton#cue:checked:focus {{ border-color: {ACCENT}; }}

QPushButton#look {{
    min-height: 52px; border-radius: 12px; font-size: 16px; font-weight: 600; color: {TEXT_2};
}}
QPushButton#look:hover {{ color: {TEXT}; }}
QPushButton#look:checked {{ background: {accent_soft}; color: {ACCENT}; border: 2px solid {ACCENT}; }}
QPushButton#look[variant="tall"] {{ min-height: 88px; font-size: 17px; }}

QPushButton#danger {{
    background: {rgba(DANGER, 0.08)}; color: {DANGER_TEXT}; border: 1px solid {danger_line};
    border-radius: 12px; min-height: 52px; font-size: 14px; font-weight: 700;
}}
QPushButton#danger:hover {{ background: {rgba(DANGER, 0.16)}; border-color: {DANGER}; }}
QPushButton#danger:pressed {{ background: {rgba(DANGER, 0.26)}; }}
QPushButton#danger:checked {{ background: {DANGER}; color: {ON_ACCENT}; border: 2px solid #FF8A82; }}
QPushButton#danger:checked:hover {{ background: #F65A51; }}
QPushButton#danger[variant="xl"] {{ min-height: 84px; max-height: 84px; border-width: 2px; }}
QPushButton#danger[variant="xl"]:checked {{ border-width: 2px; }}

/* ---- toggles / radios ---- */
QCheckBox, QRadioButton {{ spacing: 12px; font-size: 15px; color: {TEXT}; min-height: 28px; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: {TEXT_3}; }}
QCheckBox::indicator {{ width: 36px; height: 20px; image: url("{_icon_url('switch-off.svg')}"); }}
QCheckBox::indicator:hover {{ image: url("{_icon_url('switch-off-hover.svg')}"); }}
QCheckBox::indicator:checked {{ image: url("{_icon_url('switch-on.svg')}"); }}
QCheckBox::indicator:checked:hover {{ image: url("{_icon_url('switch-on-hover.svg')}"); }}
QCheckBox::indicator:disabled {{ image: url("{_icon_url('switch-disabled.svg')}"); }}
QRadioButton::indicator {{ width: 18px; height: 18px; image: url("{_icon_url('radio-off.svg')}"); }}
QRadioButton::indicator:checked {{ image: url("{_icon_url('radio-on.svg')}"); }}
QRadioButton#option {{
    background: {SURFACE_2}; border: 1px solid {LINE_2}; border-radius: {R_MD}px;
    padding: 12px 14px; min-height: 24px;
}}
QRadioButton#option:hover {{ background: {SURFACE_3}; border-color: {LINE_3}; }}
QRadioButton#option:checked {{ background: {accent_soft}; border-color: {accent_line}; }}

/* ---- sliders ---- */
QSlider {{ min-height: 28px; }}
QSlider::groove:horizontal {{ height: 6px; background: {SURFACE_4}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::handle:horizontal {{
    width: 20px; height: 20px; margin: -7px 0; border-radius: 10px;
    background: {TEXT}; border: 3px solid {SURFACE};
}}
QSlider::handle:horizontal:hover {{ background: #FFFFFF; }}
QSlider::sub-page:horizontal:disabled {{ background: {TEXT_3}; }}
QSlider#fader {{ min-height: 36px; }}
QSlider#fader::groove:horizontal {{ height: 8px; border-radius: 4px; }}
QSlider#fader::sub-page:horizontal {{ border-radius: 4px; }}
QSlider#fader::handle:horizontal {{ width: 26px; height: 26px; margin: -9px 0; border-radius: 13px; }}
QSlider#bipolar::sub-page:horizontal {{ background: {SURFACE_4}; }}

/* ---- inputs ---- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {SURFACE_2}; border: 1px solid {LINE_2}; border-radius: 8px;
    min-height: 32px; padding: 0 10px; selection-background-color: {rgba(ACCENT, 0.30)};
    font-family: {ui}; font-size: 13px;
}}
QSpinBox, QDoubleSpinBox {{ font-family: {mono}; padding-right: 24px; }}
QAbstractSpinBox[compact="true"] {{ min-height: 28px; }}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {LINE_3}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {accent_line}; }}
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
    background: {SURFACE_2}; border: 1px solid {LINE_3}; border-radius: 8px; padding: 4px;
    selection-background-color: {SURFACE_4}; selection-color: {TEXT}; outline: none;
}}

/* ---- tables / text ---- */
QTableWidget, QTableView {{
    background: {SURFACE}; alternate-background-color: {SURFACE_2}; border: none;
    gridline-color: {LINE}; selection-background-color: {rgba(ACCENT, 0.14)}; selection-color: {TEXT};
    font-size: 13px;
}}
QTableWidget::item, QTableView::item {{ padding: 0 8px; border-bottom: 1px solid {LINE}; }}
QTableWidget QComboBox, QTableWidget QSpinBox {{ border-radius: 6px; min-height: 28px; margin: 3px 4px; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: {SURFACE}; color: {TEXT_3}; border: none; border-bottom: 1px solid {LINE_2};
    padding: 8px 10px; font-size: 11px; font-weight: 600;
}}
QTableCornerButton::section {{ background: {SURFACE}; border: none; }}
QTextEdit, QPlainTextEdit {{
    background: {SURFACE_2}; border: 1px solid {LINE_2}; border-radius: {R_MD}px; padding: 8px;
}}
QTextEdit#mono {{ font-family: {mono}; font-size: 12px; color: {TEXT_2}; }}

/* ---- scrolling / splitters ---- */
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QAbstractScrollArea {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {LINE_3}; border-radius: 4px; min-height: 40px; margin: 0 2px; }}
QScrollBar::handle:horizontal {{ background: {LINE_3}; border-radius: 4px; min-width: 40px; margin: 2px 0; }}
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
    """Register the bundled Geist / Geist Mono faces (once). Absolute paths:
    Qt's offscreen/cocoa platforms reject relative ones. Returns True when
    Geist is available; the stylesheet's fallback stack covers a failure."""
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
