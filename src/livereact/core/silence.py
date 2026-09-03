"""Silence -> auto-blackout detection (docs/14 §2).

VERIFIED BY SIMULATION before this was built: raw audio-RMS silence alone
false-positives on a realistic quiet house/EDM breakdown — 72.7% of a
synthetic breakdown got misflagged "silent" in testing
(tools/simulations/audio_pipeline_sim.py). A deck can be very quiet while
still genuinely playing, and a dramatic quiet breakdown before a drop is a
genre hallmark, not an edge case, for exactly the music this project targets.

So: **"is a deck actually playing" (PDL beat presence, `snap.pdl_fresh`) is
the PRIMARY signal**, not audio silence. Real audio silence is only a
secondary confirmation, and only counts when audio is actually available —
an audio source that isn't connected must not be treated as agreeing it's
silent (that would misfire blackout any time the audio pipeline itself is
unavailable, even with PDL clearly showing a track playing).

A hold time (longer than PDL's own ~1s staleness window) avoids blacking out
on a brief network blip — a track actually ending for a few seconds should
trigger it; a momentary Pro DJ Link hiccup during active play should not.
"""

from __future__ import annotations

from ..clock import Clock
from .show_state import ShowSnapshot

HOLD_S = 3.0             # seconds of confirmed "no music" before auto-blackout engages
AUDIO_SILENCE_RMS = 0.05  # tunable by ear against real material (docs/14's "verify, don't guess")


class SilenceDetector:
    """Stateful: call ``update(snap)`` once per ShowEngine tick."""

    def __init__(self, clock: Clock, hold_s: float = HOLD_S, silence_rms: float = AUDIO_SILENCE_RMS) -> None:
        self.clock = clock
        self.hold_s = hold_s
        self.silence_rms = silence_rms
        self._silent_since: float | None = None
        self.active = False  # exposed for the console (distinguish auto- from manual blackout)

    def update(self, snap: ShowSnapshot) -> bool:
        """Returns whether auto-blackout should be engaged right now."""
        now = self.clock.monotonic()

        if snap.pdl_fresh:
            confirmed_no_music = False  # a deck is actively sending beats — definitely playing
        elif snap.audio_fresh:
            # Secondary confirmation only when audio is actually available.
            confirmed_no_music = snap.audio_energy < self.silence_rms
        else:
            # No beat data AND no audio to check — trust PDL's "not playing" alone,
            # same as before real audio existed.
            confirmed_no_music = True

        if not confirmed_no_music:
            self._silent_since = None
            self.active = False
            return self.active

        if self._silent_since is None:
            self._silent_since = now
        if now - self._silent_since >= self.hold_s:
            self.active = True
        return self.active
