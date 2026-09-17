"""Real audio input from the DJ board's USB audio interface (docs/14).

VERIFIED ON HARDWARE (2026-08-31): the XDJ-XZ exposes an "XDJ-XZ" CoreAudio
device over the SAME USB-B cable already carrying MIDI (8 in / 12 out,
44.1kHz) — no new hardware or USB port needed; this was the doc's biggest
unverified assumption and it held up. Of its 8 input channels, only 5-8 carry
a live signal (1-4 measured silent); 5/6 and 7/8 showed matching RMS/peak
(likely Master/Booth, same content) — this listener captures channels 5 & 6.

Real-time safety (docs/14): the sounddevice capture callback does the
absolute minimum — copy the block into a ring buffer, nothing else. A
separate analysis thread does the FFT/band-split/RMS work, so a slow Python
moment can never cause a dropped audio block or stream error. Same
producer/consumer discipline as every other input source in this project.

Algorithm VERIFIED by simulation against synthetic house music before being
wired in here (tools/simulations/audio_pipeline_sim_v2.py):
  - Band split: mean magnitude PER BIN (not summed) -> a normalized fraction,
    for color. Summing is bin-count-biased (the high band has ~65x more FFT
    bins than the low band at this block size) and reads pure noise as ~64%
    "high"-dominant — a real bug, not a style choice.
  - band_low_abs: the SAME low band's un-normalized magnitude, kept as a
    SEPARATE signal for the laser onset trigger (docs/14 §3). The normalized
    fraction saturates near-constant during a sidechained groove (a
    continuous bassline stays present even between kicks) and loses almost
    all its discriminative contrast — verified 1.06x vs 2.35x
    kick-to-quiet-gap. Don't derive one signal from the other.
  - band_mid_abs / band_high_abs (2026-09-14, build_snare_accent): the same
    un-normalized-magnitude idea, extended to the other two bands — the
    snare-roll detector (core/snare_trigger.py, high band) and Synth Sync
    (engines/reactive.py, mid band) need this for the identical reason the laser's kick detector
    needed band_low_abs: the normalized band_mid/band_high fractions
    saturate near-constant during a groove for the same structural reason
    band_low does, so they're unsuitable for onset detection even though
    they're right for the console's band meters. Covered by the existing
    band-split simulation (audio_pipeline_sim_v2.py checks mean-per-bin
    correctness for all three bands, not just low).
"""

from __future__ import annotations

import logging
import os
import queue
import threading

from ..clock import Clock
from ..core.messages import AudioLevelMessage
from .base import InputSource

log = logging.getLogger(__name__)

BLOCK = 1024               # samples/block (~23ms @44.1kHz) — low latency over frequency resolution
                           # MEASURED (2026-09-03): BLOCK size turned out NOT to be the real
                           # latency lever -- sounddevice/PortAudio's own default stream latency
                           # for this device was a fixed ~472ms regardless of blocksize (128 to
                           # 1024 all measured identical). The actual fix was requesting
                           # `latency="low"` on the InputStream below, which dropped real
                           # measured latency to ~31ms with a live callback stream, 0 dropouts
                           # over a 5s check -- a driver-default problem, not a block-size one.
CHANNELS = (5, 6)          # 1-based device channels carrying the live master/booth mix (VERIFIED)
LOW_HZ = (20, 250)
MID_HZ = (250, 2000)
HIGH_HZ = (2000, 16000)
ATTACK_S = 0.015           # VU-meter-style smoothing: fast attack
RELEASE_S = 0.250          #                            slower release
ENERGY_GAIN = 5.0          # RECALIBRATED ON HARDWARE (2026-09-01): the 2026-08-31 calibration
                           # (raw smoothed RMS ~0.009-0.047, p90~0.03, gain=20) was measured
                           # against a quieter setup than tonight's — this session's raw RMS
                           # ran ~0.05-0.13, so gain=20 was clipping the 1.0 ceiling almost
                           # continuously (confirmed live: snap.energy pinned at 1.000 for an
                           # entire playing section instead of tracking the song, which then
                           # cascaded into wrong scene-bucket selection and the wash bar's
                           # hardware strobe firing near-continuously — docs/14 §5). gain=5.0
                           # puts this session's p90 (~0.12) at ~0.6, matching the original
                           # target ratio with headroom for real drops above it. Input level
                           # depends on the mixer's actual gain staging, not just the track, so
                           # this will likely need re-checking again at a different venue/setup
                           # — see tools/simulations or docs/14 §5 for the raw-RMS check script.
                           # LIVEREACT_AUDIO_GAIN env var overrides it for one launch (2026-09-16:
                           # the MacBook mic fallback measured p90 raw RMS 0.43 -> gain 1.4).
ENERGY_GAIN = float(os.environ.get("LIVEREACT_AUDIO_GAIN", ENERGY_GAIN))
AGC_CEILING = 0.9          # Automatic gain control (2026-09-16 house party, mic fallback): when
AGC_ATTACK_S = 0.5         # the DJ turns the room up, a fixed gain pins `energy` at 1.0 and the
AGC_RELEASE_S = 20.0       # strobe/drop logic loses the song. A peak tracker on the smoothed RMS
                           # (0.5 s attack so one transient can't grab it, 20 s release so it
                           # recovers after the volume comes back down) trims the effective gain
                           # so the running peak lands at AGC_CEILING. It only ever REDUCES the
                           # gain below ENERGY_GAIN -- never boosts -- so silence detection and
                           # quiet-venue behaviour are exactly as before, and at the XDJ's normal
                           # line level it's a no-op.


class AudioInputError(RuntimeError):
    pass


class AudioAnalyzer(InputSource):
    def __init__(
        self,
        output_queue: "queue.Queue",
        clock: Clock,
        stop_event: threading.Event,
        device: str | int | None = None,
    ) -> None:
        self.queue = output_queue
        self.clock = clock
        self.stop_event = stop_event
        self.device = device  # explicit device name/index override (--audio-device); None = auto-detect
        self._stream = None
        self._thread: threading.Thread | None = None
        self._ring: "queue.SimpleQueue | None" = None
        self._sr = 44100

        # analysis state (owned solely by the analysis thread)
        self._low_mask = None
        self._mid_mask = None
        self._high_mask = None
        self._window = None
        self._rms_smooth = 0.0
        self._peak_hold = 0.0      # AGC: slow peak of _rms_smooth
        self._gain_eff = ENERGY_GAIN
        self._agc_last_log = 0.0
        self._agc_attack, self._agc_release = self._agc_coeffs()

    @property
    def name(self) -> str:
        return "audio"

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        try:
            import sounddevice as sd  # lazy: only needed in hardware mode
        except ImportError as exc:  # pragma: no cover - lib not installed in dev
            raise AudioInputError(
                "sounddevice is not installed. Install it before using audio "
                "analysis; see this module's docstring."
            ) from exc
        import numpy as np  # lazy, same reasoning

        device = self.device if self.device is not None else self._find_device(sd)
        info = sd.query_devices(device)
        self._sr = int(info["default_samplerate"])
        self._setup_bands(np)

        self._ring = queue.SimpleQueue()
        # An explicit --audio-device with fewer inputs than the XDJ's (5, 6) --
        # e.g. the laptop mic as a fallback when the XDJ drops off USB
        # (2026-09-16 house party) -- uses every channel it has instead.
        n_in = int(info["max_input_channels"])
        channels = CHANNELS if n_in >= max(CHANNELS) else tuple(range(1, n_in + 1))
        channel_idx = [c - 1 for c in channels]  # 0-based, for indexing captured frames

        def _callback(indata, frames, time_info, status):
            # REAL-TIME SAFETY: do the absolute minimum here — see module docstring.
            # No FFT, no analysis, nothing that can stall the audio thread.
            if status:
                log.debug("Audio stream status: %s", status)
            self._ring.put_nowait(indata[:, channel_idx].mean(axis=1).copy())

        self._stream = sd.InputStream(
            device=device,
            channels=max(channels),
            samplerate=self._sr,
            blocksize=BLOCK,
            dtype="float32",
            latency="low",
            callback=_callback,
        )
        self._stream.start()
        log.info(
            "Audio analyzer listening on device %r (%d Hz, channels %s, stream latency %.0fms)",
            device, self._sr, channels, self._stream.latency * 1000,
        )

        self._thread = threading.Thread(target=self._run, name="audio-analyzer", daemon=False)
        self._thread.start()

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # noqa: BLE001
                log.exception("Error closing audio stream")
            self._stream = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    # ------------------------------------------------------------------ device selection
    @staticmethod
    def _find_device(sd) -> int:
        for i, info in enumerate(sd.query_devices()):
            if "xdj" in info["name"].lower() and info["max_input_channels"] >= max(CHANNELS):
                return i
        raise AudioInputError(
            "No XDJ audio input device found. Connect the XDJ-XZ via USB and "
            "confirm it shows up as an audio device (not just MIDI), or pass "
            "an explicit --audio-device."
        )

    def _setup_bands(self, np) -> None:
        freqs = np.fft.rfftfreq(BLOCK, d=1 / self._sr)
        self._low_mask = (freqs >= LOW_HZ[0]) & (freqs < LOW_HZ[1])
        self._mid_mask = (freqs >= MID_HZ[0]) & (freqs < MID_HZ[1])
        self._high_mask = (freqs >= HIGH_HZ[0]) & (freqs < HIGH_HZ[1])
        self._window = np.hanning(BLOCK)

    # ------------------------------------------------------------------ analysis thread
    def _run(self) -> None:
        import numpy as np

        dt_block = BLOCK / self._sr
        # Plain Python floats, deliberately: a numpy float64 here turned
        # `_rms_smooth`, hence snap.energy and everything derived from it,
        # into numpy scalars, and a comparison on one of those produced a
        # numpy bool that the recorder's json.dumps rejected (162 samples
        # lost in recordings/session-20260915-211607).
        attack = float(1 - np.exp(-dt_block / ATTACK_S))
        release = float(1 - np.exp(-dt_block / RELEASE_S))
        self._agc_attack, self._agc_release = self._agc_coeffs()  # real sample rate now known
        while not self.stop_event.is_set():
            try:
                block = self._ring.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._analyze_block(block, attack, release, np)
            except Exception:  # noqa: BLE001 - never let the analysis thread die on one bad block
                log.exception("Audio analysis failed on one block")

    def _agc_coeffs(self) -> tuple[float, float]:
        import math
        dt_block = BLOCK / self._sr
        return (float(1 - math.exp(-dt_block / AGC_ATTACK_S)),
                float(1 - math.exp(-dt_block / AGC_RELEASE_S)))

    def _analyze_block(self, block, attack: float, release: float, np) -> None:
        if len(block) != BLOCK:
            return  # a partial block at stream start/stop; skip rather than crash
        now = self.clock.monotonic()
        rms_raw = float(np.sqrt(np.mean(block ** 2)))
        coeff = attack if rms_raw > self._rms_smooth else release
        self._rms_smooth += coeff * (rms_raw - self._rms_smooth)

        # AGC: trim the gain so the running peak sits at the ceiling (see AGC_* above).
        pk = self._agc_attack if self._rms_smooth > self._peak_hold else self._agc_release
        self._peak_hold += pk * (self._rms_smooth - self._peak_hold)
        if self._peak_hold * ENERGY_GAIN > AGC_CEILING:
            self._gain_eff = AGC_CEILING / self._peak_hold
        else:
            self._gain_eff = ENERGY_GAIN
        if self._gain_eff < ENERGY_GAIN * 0.8 and now - self._agc_last_log > 10.0:
            log.info("AGC trimming audio gain %.2f -> %.2f (raw peak %.3f)",
                     ENERGY_GAIN, self._gain_eff, self._peak_hold)
            self._agc_last_log = now

        spec = np.abs(np.fft.rfft(block * self._window))
        m_low = float(spec[self._low_mask].mean())
        m_mid = float(spec[self._mid_mask].mean())
        m_high = float(spec[self._high_mask].mean())
        total = m_low + m_mid + m_high + 1e-9

        self.queue.put(AudioLevelMessage(
            timestamp=now,
            rms=float(min(1.0, self._rms_smooth * self._gain_eff)),
            band_low=m_low / total,
            band_mid=m_mid / total,
            band_high=m_high / total,
            band_low_abs=m_low,
            band_mid_abs=m_mid,
            band_high_abs=m_high,
        ))
