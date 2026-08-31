"""XDJ-XZ MIDI CC map — translate raw (channel, CC) to semantic control names.

⚠️ The default map is the spec's "verified on Josh's unit" table (docs/04 §6),
reproduced as a HYPOTHESIS. The XDJ-XZ's USB-MIDI mapping is poorly documented,
firmware/mode-dependent, and may use HID for some controls — so this MUST be
re-verified on hardware with the MIDI monitor (`--midi-monitor`) and the discovered
map persisted. Channels here are 0-indexed (as mido reports them); the spec's
"MIDI channel 6" is mido channel 5.
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)

# (mido_channel, cc) -> semantic control name.
DEFAULT_CC_MAP: dict[tuple[int, int], str] = {
    (5, 23): "fader_a", (5, 24): "fader_b", (5, 31): "crossfader",
    (5, 15): "eq_low_a", (5, 16): "eq_mid_a", (5, 17): "eq_high_a",
    (5, 19): "eq_low_b", (5, 20): "eq_mid_b", (5, 21): "eq_high_b",
}


class CcMap:
    """A bidirectional-ish CC map with learn + JSON persistence."""

    def __init__(self, mapping: dict[tuple[int, int], str] | None = None) -> None:
        self.mapping: dict[tuple[int, int], str] = dict(mapping or DEFAULT_CC_MAP)

    def resolve(self, channel: int, cc: int) -> str | None:
        """Semantic control for a raw (channel, cc), or None if unmapped."""
        return self.mapping.get((channel, cc))

    def assign(self, channel: int, cc: int, control: str) -> None:
        """Bind (channel, cc) -> control (MIDI-learn). Removes any prior binding
        for the same control so each control maps to exactly one CC."""
        self.mapping = {k: v for k, v in self.mapping.items() if v != control}
        self.mapping[(channel, cc)] = control

    # --- persistence (keys serialized as "channel:cc") ---
    def to_dict(self) -> dict[str, str]:
        return {f"{ch}:{cc}": name for (ch, cc), name in self.mapping.items()}

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "CcMap":
        mapping = {}
        for key, name in data.items():
            ch, cc = key.split(":")
            mapping[(int(ch), int(cc))] = name
        return cls(mapping)

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)
        log.info("Saved MIDI map to %s", path)

    @classmethod
    def load(cls, path: str) -> "CcMap":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))
