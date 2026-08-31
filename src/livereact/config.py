"""Tiny optional persistence (docs/10 C1).

Saves a handful of operator settings between runs so scene/brightness tuning isn't
lost on every restart. Deliberately minimal — no cloud, no accounts, no presets,
just a local ``config.json``. Missing/corrupt files are ignored (fall back to
defaults), so this can never block startup.
"""

from __future__ import annotations

import json
import logging
import os

log = logging.getLogger(__name__)

DEFAULT_PATH = "config.json"

# ManualParams fields that persist between runs (momentary states do not).
_PERSIST = ("master_brightness", "strobe_cap", "warm_cool_bias", "laser_enable")


def load_into(manual, path: str = DEFAULT_PATH) -> bool:
    """Apply saved settings onto ``manual``. Returns True if a file was loaded."""
    if not os.path.exists(path):
        return False
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        log.warning("Ignoring unreadable config %s: %s", path, exc)
        return False
    for field in _PERSIST:
        if field in data:
            setattr(manual, field, data[field])
    log.info("Loaded settings from %s", path)
    return True


def save_from(manual, path: str = DEFAULT_PATH) -> None:
    """Write the persistable settings from ``manual`` to ``path``."""
    data = {field: getattr(manual, field) for field in _PERSIST}
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except OSError as exc:
        log.warning("Could not save config %s: %s", path, exc)
