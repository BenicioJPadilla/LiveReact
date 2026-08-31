"""Immutable messages that flow from input sources to the metronome.

Input callbacks (real PDL/MIDI listeners, or the demo source) never touch ShowState
directly — they push these onto a ``queue.Queue`` that the metronome drains at the
top of each tick. This is the clean producer/consumer boundary that makes input
handling unit-testable and eliminates input-side locking bugs (docs/05 §4.3).

Every message carries a monotonic ``timestamp`` (from the source's injected clock)
so the metronome can interpolate beat phase and track per-source staleness.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BeatMessage:
    """A beat boundary from Pro DJ Link (or the demo).

    ``beat_in_bar`` is the measured 1-4 counter. Only the *master* deck's beats
    drive the local clock/bar inference; non-master beats are informational.
    """

    timestamp: float
    beat_in_bar: int      # 1..4 (measured)
    bpm: float            # measured tempo (incl. pitch)
    is_master: bool
    player: int


@dataclass(frozen=True)
class StatusMessage:
    """Periodic transport/deck status from PDL (measured)."""

    timestamp: float
    on_air: tuple[int, ...]
    master_deck: int | None
    playing: bool
    loop_active: bool


@dataclass(frozen=True)
class MidiControlMessage:
    """One normalized mixer control. ``control`` is a semantic name (e.g.
    ``"crossfader"``, ``"fader_a"``, ``"eq_low_b"``); ``value`` is 0.0-1.0.

    The raw CC->name/normalization mapping happens in the MIDI listener / demo
    source, so everything downstream is hardware-agnostic.
    """

    timestamp: float
    control: str
    value: float


@dataclass(frozen=True)
class TransitionMessage:
    """A synthetic transition marker from the demo source.

    Real transition *detection* (from crossfader/fader motion) is the Transition
    Engine's job in Phase 6; until then the demo asserts it directly so the rest of
    the pipeline can be exercised.
    """

    timestamp: float
    active: bool
