"""Tests for SilenceDetector (docs/14 §2) — driven deterministically with a
FakeClock, same pattern as the Metronome tests."""

from __future__ import annotations

from livereact.clock import FakeClock
from livereact.core.show_state import ShowSnapshot
from livereact.core.silence import SilenceDetector


def _snap(**kw) -> ShowSnapshot:
    base = dict(pdl_fresh=False, audio_fresh=False, audio_energy=0.0)
    base.update(kw)
    return ShowSnapshot(**base)


def test_stays_off_while_a_deck_is_sending_beats():
    clock = FakeClock()
    d = SilenceDetector(clock, hold_s=3.0)
    for _ in range(10):
        assert d.update(_snap(pdl_fresh=True)) is False
        clock.advance(1.0)


def test_engages_after_the_hold_time_with_no_pdl_and_no_audio():
    """No beat data and no audio source at all -> trust PDL alone, same as
    before real audio existed."""
    clock = FakeClock()
    d = SilenceDetector(clock, hold_s=3.0)
    assert d.update(_snap()) is False        # not yet — hold time hasn't elapsed
    clock.advance(2.9)
    assert d.update(_snap()) is False
    clock.advance(0.2)
    assert d.update(_snap()) is True         # now past the 3.0s hold


def test_a_realistic_quiet_breakdown_does_not_false_trigger():
    """The exact scenario the stress test proved dangerous: no PDL beats (say,
    a brief PDL hiccup) but real audio confirms the room is NOT actually
    silent -> must not blackout, even past the hold time."""
    clock = FakeClock()
    d = SilenceDetector(clock, hold_s=3.0, silence_rms=0.05)
    for _ in range(10):
        result = d.update(_snap(pdl_fresh=False, audio_fresh=True, audio_energy=0.15))
        clock.advance(1.0)
    assert result is False


def test_audio_confirms_true_silence_after_the_hold():
    clock = FakeClock()
    d = SilenceDetector(clock, hold_s=3.0, silence_rms=0.05)
    result = False
    for _ in range(5):
        result = d.update(_snap(pdl_fresh=False, audio_fresh=True, audio_energy=0.01))
        clock.advance(1.0)
    assert result is True


def test_resets_immediately_once_a_deck_resumes():
    clock = FakeClock()
    d = SilenceDetector(clock, hold_s=3.0)
    for _ in range(5):
        d.update(_snap())
        clock.advance(1.0)
    assert d.active is True
    assert d.update(_snap(pdl_fresh=True)) is False
    assert d.active is False


def test_brief_pdl_hiccup_shorter_than_hold_does_not_trigger():
    """A momentary network blip during active play should not blackout —
    only a sustained absence past hold_s should."""
    clock = FakeClock()
    d = SilenceDetector(clock, hold_s=3.0)
    assert d.update(_snap(pdl_fresh=True)) is False
    clock.advance(1.5)  # brief gap in beat data, well under the hold time
    assert d.update(_snap(pdl_fresh=False)) is False
    clock.advance(0.1)
    assert d.update(_snap(pdl_fresh=True)) is False  # beats resume before the hold elapsed
