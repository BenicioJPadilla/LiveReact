"""Inline SVG icon set for the console: one stroke style everywhere.

Every icon is drawn on a 24 px grid with a 1.75 px round-capped stroke in
``currentColor``; ``icon()`` / ``pixmap()`` tint and rasterise them (cached,
so a repaint never re-parses SVG). All paths are original to LiveReact.

The few stylesheet assets Qt can only take as files (toggle switch, radio,
chevrons) are generated from the theme tokens by ``qss_assets()`` and checked
in under ui/icons/; regenerate them with ``python -m livereact.ui.icons``
after changing a colour token.
"""

from __future__ import annotations

import os
from functools import lru_cache

from PySide6 import QtCore, QtGui
from PySide6.QtSvg import QSvgRenderer

from . import theme

_PATHS: dict[str, str] = {
    # brand: a lens with three beams leaving it
    "logo": '<circle cx="7" cy="17" r="3.2" fill="currentColor" stroke="none"/>'
            '<path d="M9.6 14.6 20 4.5M10.2 16 21 11.5M9 13.6 13.5 3"/>',
    # navigation
    "show": '<path d="M3 12h3.5l2.5-7 4 14 3-9 1.5 2H21"/>',
    "laser": '<path d="M12 20 4 7M12 20 9 4M12 20l3-16M12 20l8-13"/><circle cx="12" cy="20" r="1.2" fill="currentColor"/>',
    "venue": '<rect x="3.5" y="3.5" width="17" height="17" rx="2.5"/><path d="M3.5 15.5h17M9.5 15.5v5M14.5 15.5v5"/>'
             '<circle cx="8.5" cy="8.5" r="1.5"/><circle cx="15.5" cy="8.5" r="1.5"/>',
    "rig": '<rect x="3.5" y="4" width="17" height="5" rx="1.5"/><rect x="3.5" y="15" width="17" height="5" rx="1.5"/>'
           '<path d="M7 9v6M17 9v6M7 6.5h.01M7 17.5h.01"/>',
    "fixture_test": '<path d="M4 20V10M4 6V4M10 20v-6M10 10V4M16 20v-3M16 13V4M2 10h4M8 14h4M14 13h4"/>',
    "external": '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    # cues
    "cue_build": '<path d="M3 18 9 12l4 4 8-8"/><path d="M15 8h6v6"/>',
    "arm_drop": '<path d="M12 4v12M6.5 10.5 12 16l5.5-5.5M5 20h14"/>',
    "strobe": '<path d="M13 3 5 13.5h6L10 21l8-10.5h-6L13 3Z"/>',
    "skip": '<path d="M5 5v14l10-7L5 5ZM19 5v14"/>',
    "laser_hit": '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M5.6 18.4l2.8-2.8M15.6 8.4l2.8-2.8"/>',
    "tap": '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="3" fill="currentColor"/>',
    # safety / feel
    "power": '<path d="M12 3v8"/><path d="M6.4 7.2a7.5 7.5 0 1 0 11.2 0"/>',
    "freeze": '<path d="M12 2.5v19M3.8 7.25l16.4 9.5M3.8 16.75l16.4-9.5M9.5 4 12 6.5 14.5 4M9.5 20l2.5-2.5 2.5 2.5"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>',
    "thermo": '<path d="M10 14.5V5a2 2 0 1 1 4 0v9.5a4 4 0 1 1-4 0Z"/><path d="M12 9v7"/>',
    "wave": '<path d="M3 12h2M7 8v8M11 5v14M15 9v6M19 11v2M21 12h0"/>',
    # status
    "audio": '<path d="M3 10v4M7 7v10M11 4v16M15 8v8M19 10v4"/>',
    "link": '<path d="M10 14a4.5 4.5 0 0 0 6.4 0l3-3a4.5 4.5 0 0 0-6.4-6.4l-1 1"/><path d="M14 10a4.5 4.5 0 0 0-6.4 0l-3 3a4.5 4.5 0 0 0 6.4 6.4l1-1"/>',
    "midi": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M8 5v8M12 5v8M16 5v8"/>',
    "dmx": '<circle cx="12" cy="12" r="8.5"/><circle cx="8" cy="10.5" r=".6" fill="currentColor"/><circle cx="16" cy="10.5" r=".6" fill="currentColor"/>'
           '<circle cx="12" cy="8" r=".6" fill="currentColor"/><circle cx="10" cy="14.5" r=".6" fill="currentColor"/><circle cx="14" cy="14.5" r=".6" fill="currentColor"/>',
    # actions
    "save": '<path d="M5 4h11l3 3v12a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4Z"/><path d="M8 4v5h7V4M8 20v-6h8v6"/>',
    "reset": '<path d="M4 12a8 8 0 1 0 2.3-5.6L4 8.5"/><path d="M4 4v4.5h4.5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "trash": '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-12M9 7V4h6v3"/>',
    "target": '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
    "home": '<path d="M4 11 12 4l8 7v8a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1v-8Z"/>',
    "crosshair": '<path d="M12 3v6M12 15v6M3 12h6M15 12h6"/>',
    "flash": '<circle cx="12" cy="12" r="4"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
    "off": '<path d="M5 5l14 14M19 5 5 19"/>',
}


def svg(name: str, color: str = "currentColor", stroke: float = 1.75) -> str:
    body = _PATHS[name].replace("currentColor", color)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">'
            f'{body}</svg>')


@lru_cache(maxsize=256)
def pixmap(name: str, color: str = theme.TEXT, size: int = 18, dpr: float = 2.0) -> QtGui.QPixmap:
    px = QtGui.QPixmap(int(size * dpr), int(size * dpr))
    px.fill(QtCore.Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QtCore.QByteArray(svg(name, color).encode()))
    p = QtGui.QPainter(px)
    renderer.render(p)
    p.end()
    px.setDevicePixelRatio(dpr)
    return px


@lru_cache(maxsize=128)
def icon(name: str, color: str = theme.TEXT_2, on_color: str | None = None, size: int = 18) -> QtGui.QIcon:
    """A tinted icon; ``on_color`` is used for the checked (On) state."""
    ic = QtGui.QIcon()
    ic.addPixmap(pixmap(name, color, size), QtGui.QIcon.Mode.Normal, QtGui.QIcon.State.Off)
    ic.addPixmap(pixmap(name, on_color or color, size), QtGui.QIcon.Mode.Normal, QtGui.QIcon.State.On)
    ic.addPixmap(pixmap(name, theme.TEXT_3, size), QtGui.QIcon.Mode.Disabled, QtGui.QIcon.State.Off)
    return ic


# --- stylesheet assets ---------------------------------------------------------

def _switch(track: str, knob: str, on: bool, border: str) -> str:
    cx = 26 if on else 10
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="36" height="20" viewBox="0 0 36 20">'
            f'<rect x="0.5" y="0.5" width="35" height="19" rx="9.5" fill="{track}" stroke="{border}"/>'
            f'<circle cx="{cx}" cy="10" r="7" fill="{knob}"/></svg>')


def _chevron(up: bool) -> str:
    d = "M3 7.5 6 4.5l3 3" if up else "M3 4.5 6 7.5l3-3"
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">'
            f'<path d="{d}" fill="none" stroke="{theme.TEXT_2}" stroke-width="1.6" '
            'stroke-linecap="round" stroke-linejoin="round"/></svg>')


def _radio(on: bool) -> str:
    ring = theme.ACCENT if on else theme.LINE_3
    dot = f'<circle cx="9" cy="9" r="4" fill="{theme.ACCENT}"/>' if on else ""
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 18 18">'
            f'<circle cx="9" cy="9" r="8" fill="{theme.SURFACE_2}" stroke="{ring}" stroke-width="1.5"/>{dot}</svg>')


def qss_assets() -> dict[str, str]:
    t = theme
    return {
        "switch-off.svg": _switch(t.SURFACE_4, t.TEXT_2, False, t.LINE_3),
        "switch-off-hover.svg": _switch(t.SURFACE_4, t.TEXT, False, t.TEXT_3),
        "switch-on.svg": _switch(t.ACCENT, t.ON_ACCENT, True, t.ACCENT),
        "switch-on-hover.svg": _switch(t.ACCENT_HOVER, t.ON_ACCENT, True, t.ACCENT_HOVER),
        "switch-disabled.svg": _switch(t.SURFACE_2, t.LINE_3, False, t.LINE_2),
        "radio-off.svg": _radio(False),
        "radio-on.svg": _radio(True),
        "chevron-up.svg": _chevron(True),
        "chevron-down.svg": _chevron(False),
    }


def write_qss_assets(directory: str | None = None) -> list[str]:
    directory = directory or os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
    os.makedirs(directory, exist_ok=True)
    written = []
    for name, data in qss_assets().items():
        path = os.path.join(directory, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(data + "\n")
        written.append(path)
    return written


if __name__ == "__main__":
    for p in write_qss_assets():
        print("wrote", p)
