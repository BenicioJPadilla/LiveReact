"""Tests for the ShowEngine: publishing, per-engine isolation, freeze, blackout."""

from __future__ import annotations

import threading

from livereact.clock import FakeClock
from livereact.core.frame_buffer import UNIVERSE_SIZE, DmxFrameBuffer
from livereact.core.show_engine import ShowEngine
from livereact.core.show_state import ShowSnapshot, ShowState
from livereact.engines.reactive import ReactiveLayerEngine
from livereact.fixtures.rig import load_rig
from livereact.merge.merge import Contribution, ManualParams


def _engine(engines, manual=None, state=None):
    rig = load_rig()
    show_state = state or ShowState()
    fb = DmxFrameBuffer()
    eng = ShowEngine(show_state, rig, fb, engines, manual or ManualParams(),
                     FakeClock(), threading.Event())
    return eng, fb, show_state


def test_publishes_a_lit_frame_when_energy_present():
    state = ShowState()
    state.publish(ShowSnapshot(energy=0.8, fader_a=1.0, eq_low_a=1.0, beat_phase=0.0))
    eng, fb, _ = _engine([ReactiveLayerEngine(FakeClock())], state=state)
    frame = eng.tick()
    assert frame is not None and len(frame) == UNIVERSE_SIZE
    assert any(frame)  # not a blackout


class FailingEngine:
    name = "boom"

    def tick(self, snapshot, rig):
        raise RuntimeError("engine blew up")


def test_a_failing_engine_does_not_stop_the_show():
    state = ShowState()
    state.publish(ShowSnapshot(energy=0.8, fader_a=1.0, eq_low_a=1.0))
    eng, fb, _ = _engine([FailingEngine(), ReactiveLayerEngine(FakeClock())], state=state)
    frame = eng.tick()  # must not raise
    assert frame is not None
    assert any(frame)  # the reactive layer still produced output


def test_freeze_holds_the_last_frame():
    state = ShowState()
    state.publish(ShowSnapshot(energy=0.8, fader_a=1.0, eq_low_a=1.0))
    manual = ManualParams()
    eng, fb, _ = _engine([ReactiveLayerEngine(FakeClock())], manual=manual, state=state)
    eng.tick()
    held = fb.latest()
    manual.freeze = True
    state.publish(ShowSnapshot(energy=0.1, fader_a=0.1))  # world changed
    assert eng.tick() is None       # nothing published
    assert fb.latest() == held      # writer keeps the old frame


def test_blackout_zeros_the_frame():
    state = ShowState()
    state.publish(ShowSnapshot(energy=1.0, fader_a=1.0, eq_low_a=1.0))
    eng, fb, _ = _engine([ReactiveLayerEngine(FakeClock())], manual=ManualParams(blackout=True), state=state)
    assert eng.tick() == bytes(UNIVERSE_SIZE)


def test_no_music_detected_auto_blackouts_after_the_hold_time():
    """docs/14 §2, end-to-end through the real ShowEngine: no PDL, no audio ->
    auto-blackout engages after SilenceDetector's hold time, same as if the
    operator had hit the manual switch."""
    state = ShowState()
    state.publish(ShowSnapshot(energy=1.0, fader_a=1.0, eq_low_a=1.0, pdl_fresh=False, audio_fresh=False))
    eng, fb, _ = _engine([ReactiveLayerEngine(FakeClock())], state=state)
    eng.silence.hold_s = 0.05  # keep the test fast
    assert any(eng.tick())  # lit at first — hold time hasn't elapsed yet

    eng.clock.advance(0.1)
    frame = eng.tick()
    assert frame == bytes(UNIVERSE_SIZE)
    assert eng.silence.active is True


def test_real_audio_confirms_playing_prevents_auto_blackout():
    """Same as above but with a real, non-silent audio reading -> must NOT
    auto-blackout, even with no PDL beats at all."""
    state = ShowState()
    state.publish(ShowSnapshot(energy=1.0, fader_a=1.0, eq_low_a=1.0,
                                pdl_fresh=False, audio_fresh=True, audio_energy=0.3))
    eng, fb, _ = _engine([ReactiveLayerEngine(FakeClock())], state=state)
    eng.silence.hold_s = 0.05
    eng.tick()
    eng.clock.advance(0.1)
    frame = eng.tick()
    assert any(frame)
    assert eng.silence.active is False
