"""XDJ-XZ MIDI CC map — translate raw (channel, CC) to semantic control names.

VERIFIED ON HARDWARE (real XDJ-XZ, 2026-08-31) — full map, every control
below confirmed by isolated capture (moving exactly one control at a time;
crossfader/fader_a/fader_b retested twice for consistency). Replaces the old
written-spec guess entirely, which assumed a different channel (5) and
different CC numbers (23/24/31/etc.) that never matched this unit at all.

Everything lands on the **same mido channel (4)** — MIDI channel does NOT
encode which deck you're on here; deck identity comes from the CC number
instead. The two decks' CCs follow a clean, consistent sequential pattern
(high/mid/low ascending by CC within each deck, deck B offset from deck A),
which is good independent evidence the numbers are real and not noise:

    deck A: fader=17, eq_high=2, eq_mid=3, eq_low=4
    deck B: fader=18, eq_high=7, eq_mid=8, eq_low=9

Channels are 0-indexed (as mido reports them).

Operator CUE controls (2026-09-30) -- not in the default map because the
XDJ control to use is Josh's pick: run `--midi-monitor`, turn/press the
knob or switch, and add its "channel:cc" to midi_map.json with one of these
names. Value >= 50% reads as ON (app.py's MIDI_CUE_THRESHOLD):

    "laser_cue"   hold the laser's dotted line, sweep speed from mids + highs
    "laser_hit"   one laser moment now (trigger profile): fires on the control's rising edge
                  (engines/laser.py MANUAL CUE; same as the console's K key)
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)

# (mido_channel, cc) -> semantic control name.
DEFAULT_CC_MAP: dict[tuple[int, int], str] = {
    (4, 11): "crossfader",
    (4, 17): "fader_a", (4, 18): "fader_b",
    (4, 2): "eq_high_a", (4, 3): "eq_mid_a", (4, 4): "eq_low_a",
    (4, 7): "eq_high_b", (4, 8): "eq_mid_b", (4, 9): "eq_low_b",
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
