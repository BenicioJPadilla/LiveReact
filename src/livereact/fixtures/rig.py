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
        # Atmosphere density (LIGHTING_BIBLE.md §4.4, `min_atmosphere_density`
        # gating -- Bible-integration Phase 1). A real, typed field rather than
        # a special-cased "no fog exists" branch scattered through look
        # selection: always 0.0 on this rig (no haze/fogger fixture exists),
        # so `requires{atm: X}` is a single honest comparison everywhere.
        # Revisit only if/when haze hardware is actually added.
        self.atm: float = 0.0
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

    def capabilities(self) -> set[str]:
        """Union of every fixture's `capabilities()` -- what `Scene.requires`
        gets checked against (Bible-integration Phase 1). Plus `role` tokens
        themselves (e.g. "wash", "spot", "laser") so a look can require a
        role directly, matching LIGHTING_BIBLE.md's own `requires{wash,
        atm 0.0}`-style shorthand."""
        caps: set[str] = set()
        for fx in self.fixtures:
            caps |= fx.capabilities()
            caps.add(fx.role)
        return caps

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
        # Optional custom canvas position (normalized 0..1) — see Fixture.layout_x/y.
        if "x" in slot and "y" in slot:
            fx.layout_x = float(slot["x"])
            fx.layout_y = float(slot["y"])
        # Optional calibrated "facing the stage" position — see Fixture.home_pan/tilt.
        if "home_pan" in slot and "home_tilt" in slot:
            fx.home_pan = float(slot["home_pan"])
            fx.home_tilt = float(slot["home_tilt"])
        # Optional laser beam-height safety geometry (LIGHTING_BIBLE.md §8.6,
        # LASER-08/09/10/11 -- Stage 6 audit fix) — see Fixture.mount_height_m.
        if "mount_height_m" in slot:
            fx.mount_height_m = float(slot["mount_height_m"])
        if "safe_projection" in slot and "min_beam_height_m" in slot["safe_projection"]:
            fx.min_beam_height_m = float(slot["safe_projection"]["min_beam_height_m"])
        fixtures.append(fx)
    return Rig(name=data.get("name", "rig"), fixtures=fixtures)
