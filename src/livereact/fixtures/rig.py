"""Rig loader: instantiate fixture profiles from a JSON rig file and expose them
by role/side, so scenes can say "all wash, both sides" instead of raw DMX indices
(docs/04 §3.5). Validates that no two fixtures overlap and all fit in one universe.
"""

from __future__ import annotations

import json
from importlib import resources

from ..core.frame_buffer import UNIVERSE_SIZE
from .profiles import FIXTURE_TYPES, ChannelKind, Fixture


class RigError(Exception):
    """Raised when a rig file is malformed or fixtures overlap / overflow."""


class Rig:
    """A loaded fixture layout: ordered fixtures + a precomputed channel-kind map."""

    def __init__(self, name: str, fixtures: list[Fixture]) -> None:
        self.name = name
        self.fixtures = fixtures
        self._by_slot: dict[str, Fixture] = {}
        self._kinds = bytearray(UNIVERSE_SIZE)  # ChannelKind per channel (default OTHER=0)
        self._validate_and_index()

    def _validate_and_index(self) -> None:
        occupied: dict[int, str] = {}
        for fx in self.fixtures:
            if fx.address < 1 or fx.address + fx.channel_count - 1 > UNIVERSE_SIZE:
                raise RigError(
                    f"{fx.label} at {fx.address} (+{fx.channel_count}) overflows the 512-channel universe"
                )
            kinds = fx.channel_kinds()
            if len(kinds) != fx.channel_count:
                raise RigError(f"{fx.label}: channel_kinds() length != channel_count")
            for local, ch in enumerate(fx.channels()):
                if ch in occupied:
                    raise RigError(
                        f"DMX address overlap at channel {ch}: {occupied[ch]} and {fx.label}"
                    )
                occupied[ch] = fx.label
                self._kinds[ch - 1] = int(kinds[local])
            self._by_slot[getattr(fx, "slot_id", fx.label)] = fx

    # --- lookups ---
    def fixture(self, slot_id: str) -> Fixture:
        return self._by_slot[slot_id]

    def by_role(self, role: str) -> list[Fixture]:
        return [f for f in self.fixtures if f.role == role]

    def by_side(self, side: str) -> list[Fixture]:
        return [f for f in self.fixtures if f.side == side]

    def by_role_side(self, role: str, side: str) -> list[Fixture]:
        return [f for f in self.fixtures if f.role == role and f.side == side]

    def kind_at(self, channel_0based: int) -> ChannelKind:
        return ChannelKind(self._kinds[channel_0based])

    def channel_count(self) -> int:
        return sum(f.channel_count for f in self.fixtures)

    # --- boot ---
    def boot_universe(self) -> bytearray:
        """A 512-byte universe with every fixture in its safe power-on state."""
        from .profiles import Buffer

        class _UniBuffer(Buffer):
            def __init__(self, uni: bytearray) -> None:
                self.uni = uni

            def set(self, channel_1based: int, value: int) -> None:
                self.uni[channel_1based - 1] = 0 if value < 0 else 255 if value > 255 else value

        uni = bytearray(UNIVERSE_SIZE)
        buf = _UniBuffer(uni)
        for fx in self.fixtures:
            fx.boot_defaults(buf)
        return uni


def load_rig(path: str | None = None) -> Rig:
    """Load a rig from ``path``, or the packaged default rig when ``path`` is None."""
    if path is None:
        text = resources.files("livereact.fixtures").joinpath("default_rig.json").read_text()
    else:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    return _rig_from_dict(json.loads(text))


def _rig_from_dict(data: dict) -> Rig:
    try:
        slots = data["slots"]
    except (KeyError, TypeError) as exc:
        raise RigError("rig file must be an object with a 'slots' array") from exc

    fixtures: list[Fixture] = []
    for slot in slots:
        ftype = slot.get("fixture_type")
        cls = FIXTURE_TYPES.get(ftype)
        if cls is None:
            raise RigError(f"unknown fixture_type {ftype!r} (known: {sorted(FIXTURE_TYPES)})")
        fx = cls(
            address=int(slot["dmx_address"]),
            label=slot.get("label", slot.get("slot_id", ftype)),
            role=slot.get("role", "wash"),
            side=slot.get("side", "left"),
        )
        # Stash slot_id for fixture() lookups.
        fx.slot_id = slot.get("slot_id", fx.label)  # type: ignore[attr-defined]
        fixtures.append(fx)
    return Rig(name=data.get("name", "rig"), fixtures=fixtures)
