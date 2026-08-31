"""Tests for the real audio analyzer (docs/14).

The capture side (sounddevice callback -> ring buffer -> analysis thread) needs
real hardware and isn't unit-tested here (matches how prodj.py's raw-socket
receive loop isn't unit-tested either) — this covers the pure, hardware-free
parts: block analysis math and the clear-error device-not-found path, plus a
regression test pinning down the verified-by-simulation band-math bug so it
can never silently come back (docs/14 §1, tools/simulations/audio_pipeline_sim_v2.py).
"""

from __future__ import annotations

import queue
import threading

import numpy as np
import pytest

from livereact.clock import FakeClock
from livereact.core.messages import AudioLevelMessage
from livereact.inputs.audio import AudioAnalyzer, AudioInputError, BLOCK


def _analyzer() -> AudioAnalyzer:
    a = AudioAnalyzer(queue.Queue(), FakeClock(), threading.Event())
    a._sr = 44100
    a._setup_bands(np)
    return a


def test_find_device_raises_clear_error_without_a_matching_device():
    class _FakeSd:
        @staticmethod
        def query_devices():
            return [{"name": "Built-in Microphone", "max_input_channels": 1}]

    with pytest.raises(AudioInputError, match="No XDJ audio input device"):
        AudioAnalyzer._find_device(_FakeSd())


def test_find_device_matches_by_name_case_insensitively():
    class _FakeSd:
        @staticmethod
        def query_devices():
            return [
                {"name": "Built-in Microphone", "max_input_channels": 1},
                {"name": "XDJ-XZ", "max_input_channels": 8},
            ]

    assert AudioAnalyzer._find_device(_FakeSd()) == 1


def test_analyze_block_emits_higher_rms_for_a_louder_block():
    a = _analyzer()
    quiet = (np.random.default_rng(1).standard_normal(BLOCK) * 0.001).astype(np.float32)
    loud = (np.random.default_rng(1).standard_normal(BLOCK) * 0.5).astype(np.float32)

    a._analyze_block(quiet, attack=1.0, release=1.0, np=np)
    quiet_msg = a.queue.get_nowait()
    a._rms_smooth = 0.0  # reset smoothing between the two probes
    a._analyze_block(loud, attack=1.0, release=1.0, np=np)
    loud_msg = a.queue.get_nowait()

    assert isinstance(quiet_msg, AudioLevelMessage)
    assert loud_msg.rms > quiet_msg.rms


def test_analyze_block_reads_a_pure_low_tone_as_low_dominant():
    t = np.arange(BLOCK) / 44100
    tone = (np.sin(2 * np.pi * 80 * t) * 0.8).astype(np.float32)  # 80Hz, well inside the low band
    a = _analyzer()
    a._analyze_block(tone, attack=1.0, release=1.0, np=np)
    msg = a.queue.get_nowait()
    assert msg.band_low > msg.band_mid
    assert msg.band_low > msg.band_high


def test_normalized_band_fraction_is_not_biased_toward_the_wider_high_band():
    """Regression test for the bug found by simulation (docs/14): summing raw
    FFT magnitude per band (instead of averaging per bin) reads pure noise as
    ~64% "high"-dominant purely because the high band has ~65x more FFT bins
    than the low band at this block size — not because of real content."""
    noise = (np.random.default_rng(7).standard_normal(BLOCK) * 0.01).astype(np.float32)
    a = _analyzer()
    a._analyze_block(noise, attack=1.0, release=1.0, np=np)
    msg = a.queue.get_nowait()
    assert max(msg.band_low, msg.band_mid, msg.band_high) < 0.6  # no single band dominates pure noise


def test_band_low_abs_is_not_normalized_like_band_low():
    """docs/14: band_low_abs must stay a separate, un-normalized signal — the
    normalized fraction saturates near-constant under continuous bass and is a
    bad signal for onset detection (verified: 1.06x vs 2.35x contrast)."""
    t = np.arange(BLOCK) / 44100
    quiet_bass = (np.sin(2 * np.pi * 60 * t) * 0.1).astype(np.float32)
    loud_bass = (np.sin(2 * np.pi * 60 * t) * 0.9).astype(np.float32)
    a = _analyzer()
    a._analyze_block(quiet_bass, attack=1.0, release=1.0, np=np)
    quiet_msg = a.queue.get_nowait()
    a._analyze_block(loud_bass, attack=1.0, release=1.0, np=np)
    loud_msg = a.queue.get_nowait()
    # the normalized fraction is near-saturated for any pure low tone either way...
    assert quiet_msg.band_low > 0.9 and loud_msg.band_low > 0.9
    # ...but the absolute signal still shows the real loudness difference.
    assert loud_msg.band_low_abs > quiet_msg.band_low_abs * 5
