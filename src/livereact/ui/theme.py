"""Console theme: one application-wide stylesheet for a dark DJ booth.

Josh operates the console next to the decks while mixing (2026-09-18 UI
redesign): the booth is dark, the laptop is at arm's length, and the buttons
he reaches for mid-set must be hittable without looking closely. So: a dark
ground so the screen doesn't glare, a larger base font, tall buttons, and a
few named roles the console tags with ``setObjectName``:

  ``cue``     -- the show cues (Cue build / Arm drop / Strobe burst / Skip):
                 the biggest targets on the screen.
  ``danger``  -- the hard switches (Blackout / Freeze): red while checked so
                 a live kill state is impossible to miss.
  ``status``  -- the top status strip's readouts (BPM, bar, scene, bucket).
  ``bucket``  -- the energy-bucket label; its color is set per bucket in
                 ``bucket_color`` below.

Everything is plain QSS, no custom widgets, so every existing test that finds
widgets by attribute name or shortcuts by ``QKeySequence`` still works.
"""

from __future__ import annotations

from PySide6 import QtWidgets

BG = "#101216"
PANEL = "#181b21"
BORDER = "#2a2f38"
TEXT = "#e6e8ec"
MUTED = "#8b919c"
ACCENT = "#3cc06a"      # matches console.py's _DOT_OK green
DANGER = "#c0392b"

# Energy-bucket colors (core/show_state.py's `bucket` string values, which are
# scenes/base.py's EnergyBucket values). One color per state so the strip
# reads at a glance: cool while resting, warm while building, hot on the drop.
BUCKET_COLORS = {
    "break": "#4a90e2",   # blue
    "build": "#f5a623",   # amber
    "drop": "#e0413a",    # red
    "peak": "#d63af9",    # magenta
    "outro": "#8b919c",   # grey
}


def bucket_color(bucket: str) -> str:
    return BUCKET_COLORS.get(bucket, MUTED)


DARK_QSS = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-size: 14px;
}}
QMainWindow, QTabWidget::pane {{
    background: {BG};
    border: 1px solid {BORDER};
}}
QTabBar::tab {{
    background: {PANEL};
    color: {MUTED};
    padding: 8px 18px;
    font-size: 14px;
    font-weight: 600;
    border: 1px solid {BORDER};
    border-bottom: none;
}}
QTabBar::tab:selected {{
    color: {TEXT};
    background: {BG};
}}
QGroupBox {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 6px;
    margin-top: 14px;
    padding: 10px 8px 8px 8px;
    font-weight: 700;
    text-transform: uppercase;
    color: {MUTED};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}}
QLabel {{
    background: transparent;
}}
QLabel#status {{
    font-size: 16px;
    font-weight: 700;
}}
QLabel#bucket {{
    font-size: 20px;
    font-weight: 800;
    padding: 2px 10px;
    border-radius: 4px;
}}
QPushButton {{
    background: #262b34;
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    min-height: 52px;
    padding: 4px 12px;
    font-size: 15px;
    font-weight: 600;
}}
QPushButton:hover {{
    background: #303743;
}}
QPushButton:pressed {{
    background: #3a4250;
}}
QPushButton#cue {{
    min-height: 72px;
    font-size: 18px;
    border: 2px solid #3a4250;
}}
QPushButton#look {{
    min-height: 56px;
    font-size: 17px;
    border: 2px solid #3a4250;
}}
QPushButton#look:checked {{
    background: #2a5db0;
    color: white;
    border: 2px solid #7fb0ff;
}}
QPushButton#danger {{
    border: 2px solid #4a2a2a;
}}
QPushButton#danger:checked {{
    background: {DANGER};
    color: white;
    border: 2px solid #ff6b5b;
}}
QCheckBox {{
    spacing: 10px;
    font-size: 15px;
    min-height: 32px;
}}
QCheckBox::indicator {{
    width: 22px;
    height: 22px;
}}
QSlider::groove:horizontal {{
    height: 8px;
    background: #2a2f38;
    border-radius: 4px;
}}
QSlider::handle:horizontal {{
    width: 26px;
    height: 26px;
    margin: -10px 0;
    background: #b8bec9;
    border-radius: 13px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 4px;
}}
QProgressBar {{
    background: #2a2f38;
    border: none;
    border-radius: 4px;
    height: 14px;
    text-align: center;
    color: {TEXT};
    font-size: 11px;
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 4px;
}}
QProgressBar#low::chunk {{ background: #e0413a; }}
QProgressBar#mid::chunk {{ background: #f5a623; }}
QProgressBar#high::chunk {{ background: #4a90e2; }}
QTableWidget, QTextEdit, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {PANEL};
    border: 1px solid {BORDER};
    selection-background-color: #303743;
}}
QHeaderView::section {{
    background: {PANEL};
    color: {MUTED};
    border: 1px solid {BORDER};
    padding: 4px;
}}
QSplitter::handle {{
    background: {BORDER};
}}
"""


def apply_theme(qapp: QtWidgets.QApplication | None = None) -> None:
    """Install the dark console stylesheet on the running QApplication.

    Safe to call more than once and with no application yet (a no-op then), so
    headless tests that build a ConsoleWindow directly aren't affected."""
    qapp = qapp or QtWidgets.QApplication.instance()
    if qapp is None:
        return
    qapp.setStyleSheet(DARK_QSS)
