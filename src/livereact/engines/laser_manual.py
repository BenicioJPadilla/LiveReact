"""Laser MANUAL profile (2026-10-10, Junior Crib). Josh: "I want to be able to
press buttons on the UI to cue scenes ... just buttons, using the scenes from
Sophia's rig. Same idea we had for Sophia's, just in this rig on the Show tab.
The lasers should be off by default unless I click the button."

Nothing here listens to the music. The engine holds ONE cued scene name (or
None = off): the Show tab's scene buttons (ui/console.py) call ``cue(name)``
and the OFF button calls ``off()``; every tick both heads get that scene's
verbatim 12-channel bytes from MANUAL_SCENES (laser_show.py's LASER_SCENES +
White / Green) via
Laser.set_scene -- lit while a scene is cued, CH1 held at 0 (pattern primed)
while off. ``active`` is True every tick like the SHOW profile so finalize's
gate lets CH1 through; the arm switch (L) and blackout (B) still win exactly
as for every other profile. Only rigs with ``"laser_profile": "manual"`` get
this engine and the buttons.
"""

from __future__ import annotations

from ..clock import Clock
from ..core.show_state import ShowSnapshot
from ..fixtures.profiles import Laser
from ..fixtures.rig import Rig
from ..merge.merge import Contribution, ManualParams
from .laser_show import DEFAULT_SCENE, LASER_SCENES

MOOD_MANUAL = "manual"

# The scenes this profile's buttons offer: Sophia's four verbatim, plus two
# single-colour variants Josh asked for on 2026-10-10 ("add white laser and
# green laser"): the Rainbow pattern with CH12 held on one colour band
# (fixtures/profiles.py Laser.COLOR_* -- the bands set_dotted_line_sweep
# uses) instead of 255's colour cycle. Kept here, not in LASER_SCENES, so
# Sophia's Laser Show tab and its 16-bar rotation are unchanged.
_RAINBOW = LASER_SCENES[DEFAULT_SCENE]
MANUAL_SCENES: dict[str, tuple[int, ...]] = {
    **LASER_SCENES,
    "White": _RAINBOW[:11] + (Laser.COLOR_WHITE,),
    "Green": _RAINBOW[:11] + (Laser.COLOR_GREEN,),
}


def manual_scene_names() -> list[str]:
    return list(MANUAL_SCENES)


class LaserManualEngine:
    """Writes the cued scene to every laser head each tick; no music input."""

    priority = 60

    def __init__(self, clock: Clock, manual: ManualParams | None = None) -> None:
        self.clock = clock
        self.manual = manual if manual is not None else ManualParams()
        self.scene: str | None = None            # None = OFF (the launch state)
        # the shared laser-engine interface (console status line, recorder)
        self.active = False
        self.primed = False
        self.sweep = 0.0
        self.target = 0.0
        self.source = "manual"
        self.stab = 0.0
        self.wub = 0.0
        self.color = self.color_l = self.color_r = 0
        self.mood = MOOD_MANUAL
        self.scene_name = "Off"

    @property
    def manual_cued(self) -> bool:
        return False

    @property
    def name(self) -> str:
        return "Manual"

    # --- operator side (UI thread) ---
    def cue(self, name: str) -> None:
        """Show ``name`` (a LASER_SCENES key) on every head from the next tick."""
        if name not in MANUAL_SCENES:
            raise ValueError(f"unknown laser scene {name!r} (known: {manual_scene_names()})")
        self.scene = name

    def off(self) -> None:
        self.scene = None

    # --- show-engine side ---
    def tick(self, snap: ShowSnapshot, rig: Rig) -> Contribution:
        c = Contribution()
        scene = self.scene
        values = MANUAL_SCENES[scene] if scene is not None else MANUAL_SCENES[DEFAULT_SCENE]
        lit = scene is not None
        for fx in rig.by_role("laser"):
            fx.set_scene(c, values, lit=lit)
        self.active = True                       # the gate never keeps them dark here; lit=False is CH1 0
        self.primed = not lit
        self.scene_name = scene if scene is not None else "Off"
        lo, hi = Laser.SWEEP_SPEED_MIN, Laser.SWEEP_SPEED_MAX
        ch7 = values[6] if lit else 0
        self.sweep = self.target = (ch7 - lo) / float(hi - lo) if ch7 >= lo else 0.0
        self.color = self.color_l = self.color_r = values[11] if lit else 0
        return c
