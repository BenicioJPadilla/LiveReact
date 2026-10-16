"""Inline SVG icon set for the console: one stroke style everywhere.

Every icon is drawn on a 24 px grid with a 1.75 px round-capped stroke in
``currentColor``; ``icon()`` / ``pixmap()`` tint and rasterise them (cached,
so a repaint never re-parses SVG). The set is the one drawn for the v2
design (lr-design/prototype-v2.html), plus a few setup glyphs in the same
grammar.

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
    # brand: a lit key with a wave through it (the rect takes the colour,
    # the wave is cut out in the page colour)
    "logo": '<rect x="1" y="1" width="22" height="22" rx="6" fill="currentColor" stroke="none"/>'
            '<path d="M6 15.5c1.6-5 3.4-5 5 0s3.4 5 5 0" stroke="#0C0D0F" stroke-width="2.2"/>'
            '<circle cx="18" cy="7" r="1.6" fill="#0C0D0F" stroke="none"/>',
    # navigation
    "live": '<path d="M3 12h3.5L9 5l5 14 2.5-7H21"/>',
    "lights": '<path d="M8.5 3.5h7l-1.2 6h-4.6z"/><path d="M10 9.5 6.5 20.5M14 9.5l3.5 11M5 20.5h14"/>',
    "phone": '<rect x="7" y="2.5" width="10" height="19" rx="2.5"/><path d="M11 18.5h2"/>',
    "shield": '<path d="M12 3l7.5 3v5.5c0 4.6-3.2 8.2-7.5 9.5-4.3-1.3-7.5-4.9-7.5-9.5V6z"/>',
    "shieldok": '<path d="M12 3l7.5 3v5.5c0 4.6-3.2 8.2-7.5 9.5-4.3-1.3-7.5-4.9-7.5-9.5V6z"/><path d="m9 12 2.2 2.2L15.5 10"/>',
    "home": '<path d="M3.5 10.5 12 3.5l8.5 7V20a1 1 0 0 1-1 1H15v-6H9v6H4.5a1 1 0 0 1-1-1z"/>',
    "venue": '<rect x="3.5" y="3.5" width="17" height="17" rx="2.5"/><path d="M3.5 15.5h17M9.5 15.5v5M14.5 15.5v5"/>'
             '<circle cx="8.5" cy="8.5" r="1.5"/><circle cx="15.5" cy="8.5" r="1.5"/>',
    "rig": '<rect x="3.5" y="4" width="17" height="5" rx="1.5"/><rect x="3.5" y="15" width="17" height="5" rx="1.5"/>'
           '<path d="M7 9v6M17 9v6"/>',
    "fixture_test": '<path d="M4 20V10M4 6V4M10 20v-6M10 10V4M16 20v-3M16 13V4M2 10h4M8 14h4M14 13h4"/>',
    "external": '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    # moments (cues)
    "trend": '<path d="m3 17 6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    "drop": '<path d="M12 3v12"/><path d="m7 10.5 5 5 5-5"/><path d="M4 20.5h16"/>',
    "flash": '<path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/>'
             '<circle cx="12" cy="12" r="2.5"/>',
    "skip": '<path d="m6 5 7 7-7 7"/><path d="M17 5v14"/>',
    "freeze": '<path d="M12 2.5v19M3.8 7.2l16.4 9.6M20.2 7.2 3.8 16.8"/><path d="m9.5 4 2.5 2 2.5-2M9.5 20l2.5-2 2.5 2"/>',
    "tap": '<path d="M9 3.5h6l3.5 17h-13z"/><path d="m12 16 4-8.5"/>',
    "bolt": '<path d="M13 3 5 13.5h6L10 21l8-10.5h-6z"/>',
    "laser": '<path d="M12 16 4 4M12 16 9 4M12 16l3-12M12 16l8-12"/><rect x="7" y="16" width="10" height="5" rx="1.5"/>',
    "pause": '<path d="M9 5v14M15 5v14"/>',
    # rack / safety
    "power": '<path d="M12 3v8"/><path d="M6.3 6.8a8 8 0 1 0 11.4 0"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>',
    "wave": '<path d="M2.5 12c2-5 4-5 6 0s4 5 6 0 4-5 6 0"/>',
    "sliders": '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
    "gauge": '<path d="M4.5 18a8.5 8.5 0 1 1 15 0"/><path d="m12 13 3.5-4"/>',
    "thermo": '<path d="M10 14.5V5a2 2 0 1 1 4 0v9.5a4 4 0 1 1-4 0Z"/><path d="M12 9v7"/>',
    "lock": '<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7"/>',
    "alert": '<path d="M12 4 2.8 20h18.4z"/><path d="M12 10v4.5M12 17.4v.1"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.9v.1"/>',
    "plug": '<path d="M9 2.5v5M15 2.5v5M6.5 7.5h11V11a5.5 5.5 0 0 1-11 0z"/><path d="M12 16.5v5"/>',
    "disc": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2.5"/><path d="M12 3a9 9 0 0 1 9 9"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    # status
    "audio": '<path d="M3 10v4M7 7v10M11 4v16M15 8v8M19 10v4"/>',
    "link": '<path d="M10 14a4.5 4.5 0 0 0 6.4 0l3-3a4.5 4.5 0 0 0-6.4-6.4l-1 1"/><path d="M14 10a4.5 4.5 0 0 0-6.4 0l-3 3a4.5 4.5 0 0 0 6.4 6.4l1-1"/>',
    "midi": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M8 5v8M12 5v8M16 5v8"/>',
    "dmx": '<path d="M9 2.5v5M15 2.5v5M6.5 7.5h11V11a5.5 5.5 0 0 1-11 0z"/><path d="M12 16.5v5"/>',
    # fixtures, same grammar
    "wash": '<rect x="2.5" y="9" width="19" height="6" rx="1.5"/><path d="M6 15v3M18 15v3"/>',
    "head": '<rect x="6" y="18.5" width="12" height="3" rx="1"/><path d="M7.5 18.5V9M16.5 18.5V9"/>'
            '<rect x="9" y="4.5" width="6" height="10" rx="3"/><circle cx="12" cy="8.5" r="1.4"/>',
    "par": '<path d="M7.5 4h9l-1.6 15H9.1z"/><path d="M5 10.5h2.8M16.2 10.5H19M10 21.5h4"/>',
    "strobe": '<rect x="3" y="6.5" width="18" height="10" rx="2"/><rect x="6" y="9.5" width="12" height="4" rx="1"/>'
              '<path d="M12 16.5v4M8.5 20.5h7"/>',
    # actions
    "save": '<path d="M5 4h11l3 3v12a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4Z"/><path d="M8 4v5h7V4M8 20v-6h8v6"/>',
    "reset": '<path d="M4 12a8 8 0 1 0 2.3-5.6L4 8.5"/><path d="M4 4v4.5h4.5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "trash": '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-12M9 7V4h6v3"/>',
    "target": '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
    "crosshair": '<path d="M12 3v6M12 15v6M3 12h6M15 12h6"/>',
    "off": '<path d="M5 5l14 14M19 5 5 19"/>',
}
# Older names some views still use.
_PATHS["show"] = _PATHS["live"]
_PATHS["cue_build"] = _PATHS["trend"]
_PATHS["arm_drop"] = _PATHS["drop"]
_PATHS["laser_hit"] = _PATHS["flash"]


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
    cx = 24 if on else 10
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="34" height="20" viewBox="0 0 34 20">'
            f'<rect x="0.5" y="0.5" width="33" height="19" rx="9.5" fill="{track}" stroke="{border}"/>'
            f'<circle cx="{cx}" cy="10" r="7" fill="{knob}"/></svg>')


def _chevron(up: bool) -> str:
    d = "M3 7.5 6 4.5l3 3" if up else "M3 4.5 6 7.5l3-3"
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">'
            f'<path d="{d}" fill="none" stroke="{theme.TEXT_2}" stroke-width="1.6" '
            'stroke-linecap="round" stroke-linejoin="round"/></svg>')


def _radio(on: bool) -> str:
    ring = theme.TEXT if on else theme.LINE_3_SOLID
    dot = f'<circle cx="9" cy="9" r="4" fill="{theme.TEXT}"/>' if on else ""
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 18 18">'
            f'<circle cx="9" cy="9" r="8" fill="{theme.WELL}" stroke="{ring}" stroke-width="1.5"/>{dot}</svg>')


def _check(on: bool) -> str:
    if not on:
        return ('<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 18 18">'
                f'<rect x="0.75" y="0.75" width="16.5" height="16.5" rx="4.5" fill="none" '
                f'stroke="{theme.TEXT_3}" stroke-width="1.5"/></svg>')
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 18 18">'
            f'<rect width="18" height="18" rx="5" fill="{theme.TEXT}"/>'
            f'<path d="M5 9.2 7.8 12 13 6.5" fill="none" stroke="{theme.ON_TEXT}" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round"/></svg>')


def qss_assets() -> dict[str, str]:
    t = theme
    return {
        "switch-off.svg": _switch(t.SURFACE_3, t.TEXT_2, False, t.LINE_2_SOLID),
        "switch-off-hover.svg": _switch(t.SURFACE_3, t.TEXT, False, t.LINE_3_SOLID),
        "switch-on.svg": _switch(t.TEXT, t.ON_TEXT, True, t.TEXT),
        "switch-on-hover.svg": _switch("#FFFFFF", t.ON_TEXT, True, "#FFFFFF"),
        "switch-disabled.svg": _switch(t.SURFACE_2, t.LINE_3_SOLID, False, t.LINE_SOLID),
        "radio-off.svg": _radio(False),
        "radio-on.svg": _radio(True),
        "check-off.svg": _check(False),
        "check-on.svg": _check(True),
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
