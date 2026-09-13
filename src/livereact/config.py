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
    """Apply saved settings onto ``manual``. Returns True if a file was loaded.

    Warns loudly (2026-09-13, found via a real hardware session) about any
    loaded value that differs from ``ManualParams``' own dataclass default --
    a stale `warm_cool_bias` left over from a previous console session
    silently biased every fixture's color (R x0.5/B x1.5 at the value found,
    +1.0 "max cool") for a full ~7-minute real test with zero visibility
    into why, since the only prior log line was "Loaded settings from
    config.json" with no indication anything non-default had loaded. This
    doesn't refuse to load a non-default value (that's a legitimate, saved
    operator choice for master_brightness/strobe_cap) -- it just makes sure
    it's never silent again.
    """
    if not os.path.exists(path):
        return False
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        log.warning("Ignoring unreadable config %s: %s", path, exc)
        return False
    defaults = {field: getattr(manual, field) for field in _PERSIST}
    non_default = []
    for field in _PERSIST:
        if field in data:
            setattr(manual, field, data[field])
            if data[field] != defaults[field]:
                non_default.append(f"{field}={data[field]!r} (default {defaults[field]!r})")
    log.info("Loaded settings from %s", path)
    if non_default:
        log.warning(
            "%s has NON-DEFAULT operator settings active: %s -- these affect every fixture "
            "every frame; confirm this is intentional before trusting tonight's colors/caps.",
            path, "; ".join(non_default),
        )
    return True


def save_from(manual, path: str = DEFAULT_PATH) -> None:
    """Write the persistable settings from ``manual`` to ``path``."""
    data = {field: getattr(manual, field) for field in _PERSIST}
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except OSError as exc:
        log.warning("Could not save config %s: %s", path, exc)
