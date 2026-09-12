"""Transition Engine — the during-mix visual treatment (docs/02 FR-2.3, docs/08 §4).

Detection of ``in_transition`` lives in the metronome (the single state writer), so
both this engine and the Phrase Engine can react to it via the shared snapshot. This
engine handles the *look* during a mix: a gentle white "lift" across the rig so the
moment reads as deliberate. It deliberately does NOT pick scenes — the Phrase Engine
holds the current look during the mix and settles into a new one on the next downbeat.
"""

from __future__ import annotations

from ..core.show_state import ShowSnapshot
from ..fixtures.profiles import Par, WashBar
from ..fixtures.rig import Rig
from ..merge.merge import Contribution

LIFT = 0.22  # white floor added during a mix (max-merges over the held look)


class TransitionEngine:
    # LIGHTING_BIBLE.md §2.3's Titan tiers (Bible-integration Phase 4) --
    # see engines/reactive.py's own priority comment for the full tier list.
    priority = 100

    @property
    def name(self) -> str:
        return "transition"

    def tick(self, snap: ShowSnapshot, rig: Rig) -> Contribution:
        c = Contribution()
        if not snap.in_transition:
            return c  # nothing to add outside a mix
        # A subtle white lift: max-merge raises anything dimmer than LIFT and warms
        # the whole rig toward white, without stopping the underlying look.
        for fx in rig.by_role("wash"):
            if isinstance(fx, (Par, WashBar)):
                # VERIFIED ON HARDWARE: the real Par has a separate dimmer gate,
                # same as WashBar — color alone with dimmer=0 shows nothing, so
                # both channels must be set together (not color-only, as before).
                fx.set_intensity(c, LIFT)
                fx.set_color(c, 1.0, 1.0, 1.0)
        for fx in rig.by_role("spot"):
            fx.set_intensity(c, LIFT)
            fx.set_color(c, 1.0, 1.0, 1.0)
        return c
