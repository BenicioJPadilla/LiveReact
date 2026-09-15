"""v2: the FIXED audio pipeline, re-stress-tested with all three bugs' fixes
applied together (not just confirmed in isolation like the v1 debugging did).

Fixes applied vs. v1 / the original doc plan:
  1. Band split: average magnitude PER BIN, not summed (fixes the 65x
     bin-count bias that made pure noise read as 64% "high"-dominant).
  2. Laser onset trigger: low-band-weighted energy, not overall RMS (fixes
     3.3% -> 86.9% recall on kicks in a sidechained house track).
  3. Silence -> blackout: gated on "is a deck actually playing" (simulating
     the real PDL beat-presence signal) as the PRIMARY signal, with RMS only
     as a secondary confirmation — not RMS-threshold alone (fixes the 72.7%
     false-positive during a realistically quiet breakdown).

Also uses the QUIET breakdown level (0.03 pad) that originally exposed the
silence-detector bug — the harder, more realistic case, not the easy one.
"""
import sys
sys.path.insert(0, "/Users/joshuaracimora/LiveReact/tools/simulations")
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from audio_pipeline_sim import SR, BLOCK

# ------------------------------------------------------------------ rebuild track at the QUIET (harder) breakdown level
import audio_pipeline_sim as base


def build_track_quiet_breakdown():
    """Same track as v1, but with the QUIET breakdown pad (0.03) that exposed
    the silence-detector bug — the realistic stress case, not the easy one."""
    orig_source = open(base.__file__).read()
    patched = orig_source.replace(
        "audio[breakdown_mask] += pad[breakdown_mask] * 0.12",
        "audio[breakdown_mask] += pad[breakdown_mask] * 0.03",
    )
    ns = {}
    # only need the synth half of the module
    snippet = patched.split("# ------------------------------------------------------------------ proposed algorithm")[0]
    exec(compile(snippet, "audio_pipeline_sim_quiet", "exec"), ns)
    return ns["build_track"]()


t, audio, kick_times, bounds = build_track_quiet_breakdown()

# ground truth: which sections have a deck actually playing (simulates real PDL
# beat-presence — this is NOT derived from the audio signal at all)
DECK_PLAYING_SECTIONS = {"groove_a", "breakdown", "groove_b"}  # NOT "silence"


# ------------------------------------------------------------------ FIX 1: band split by mean-per-bin, not sum
#
# SECOND-ORDER BUG FOUND BY TESTING FIX 1 + FIX 2 TOGETHER (not caught testing
# either in isolation): the mean-per-bin NORMALIZED fraction (band_low) is
# exactly what color needs, but it's a bad signal for onset detection — a
# continuous sidechained bassline stays present (just quieter) even between
# kicks, and with only 5 bins in the low band, its mean-per-bin saturates near
# ~0.9-1.0 pretty much constantly, so a real kick barely moves it (1.06x
# contrast, measured). Onset detection needs ABSOLUTE low-band energy instead
# (2.35x contrast, measured) — normalized-fraction and absolute-energy are
# two different signals for two different jobs, and conflating them was the
# actual mistake. `analyze_fixed` now returns both.
def analyze_fixed(audio):
    n_blocks = len(audio) // BLOCK
    window = np.hanning(BLOCK)
    freqs = np.fft.rfftfreq(BLOCK, d=1 / SR)
    low_band = (freqs >= 20) & (freqs < 250)
    mid_band = (freqs >= 250) & (freqs < 2000)
    high_band = (freqs >= 2000) & (freqs < 16000)

    rms_raw = np.zeros(n_blocks)
    band_low = np.zeros(n_blocks)       # normalized fraction -> for COLOR
    band_mid = np.zeros(n_blocks)
    band_high = np.zeros(n_blocks)
    band_low_abs = np.zeros(n_blocks)   # absolute energy -> for ONSET DETECTION
    times = np.zeros(n_blocks)

    for i in range(n_blocks):
        block = audio[i * BLOCK:(i + 1) * BLOCK]
        times[i] = (i * BLOCK) / SR
        rms_raw[i] = np.sqrt(np.mean(block ** 2))
        spec = np.abs(np.fft.rfft(block * window))
        m_low = spec[low_band].mean()
        m_mid = spec[mid_band].mean()
        m_high = spec[high_band].mean()
        total = m_low + m_mid + m_high + 1e-9
        band_low[i] = m_low / total
        band_mid[i] = m_mid / total
        band_high[i] = m_high / total
        band_low_abs[i] = m_low

    dt_block = BLOCK / SR
    attack = 1 - np.exp(-dt_block / 0.015)
    release = 1 - np.exp(-dt_block / 0.250)
    rms_smooth = np.zeros(n_blocks)
    prev = 0.0
    for i, v in enumerate(rms_raw):
        coeff = attack if v > prev else release
        prev = prev + coeff * (v - prev)
        rms_smooth[i] = prev

    return times, rms_raw, rms_smooth, band_low, band_mid, band_high, band_low_abs


# ------------------------------------------------------------------ FIX 2: low-band-weighted onset detector
# Uses ABSOLUTE low-band energy (band_low_abs), not the normalized fraction —
# see the note above analyze_fixed for why the normalized version failed here.
def onset_detector_fixed(times, band_low_abs, ratio=1.8, floor=0.5, refractory_s=0.15):
    energy = band_low_abs
    avg = np.zeros(len(energy))
    a = 0.05
    prev = energy[0]
    fires = []
    last_fire_t = -999
    for i, e in enumerate(energy):
        prev = prev + a * (e - prev)
        avg[i] = prev
        if e > max(avg[i] * ratio, floor) and (times[i] - last_fire_t) > refractory_s:
            fires.append(times[i])
            last_fire_t = times[i]
    return np.array(fires)


# ------------------------------------------------------------------ FIX 3: deck-playing-gated silence detector
def silence_detector_fixed(times, rms_smooth, deck_playing_mask, rms_confirm_threshold=0.02, hold_s=0.5):
    """PRIMARY signal: deck_playing_mask (simulates real PDL beat presence).
    RMS is only a secondary confirmation, and needs a much shorter hold
    (0.5s, not 2s) since the primary signal is already authoritative — this
    just guards against a one-block audio glitch, not the whole detection."""
    hold_blocks = max(1, int(hold_s / (BLOCK / SR)))
    candidate = (~deck_playing_mask) & (rms_smooth < rms_confirm_threshold)
    silent = np.zeros(len(times), dtype=bool)
    run = 0
    for i, c in enumerate(candidate):
        run = run + 1 if c else 0
        silent[i] = run >= hold_blocks
    return silent


# ------------------------------------------------------------------ run
times, rms_raw, rms_smooth, band_low, band_mid, band_high, band_low_abs = analyze_fixed(audio)

# build the deck-playing ground-truth mask at block resolution
deck_playing = np.zeros(len(times), dtype=bool)
for label in DECK_PLAYING_SECTIONS:
    s, e = bounds[label]
    deck_playing |= (times >= s) & (times < e)

GUARD = 0.15
bd_s, bd_e = bounds["breakdown"]
sil_s, sil_e = bounds["silence"]
bd_mask = (times >= bd_s + GUARD) & (times < bd_e - GUARD)
sil_mask = (times >= sil_s + GUARD) & (times < sil_e - GUARD)

print("=== RE-TEST 1 (fixed): band split, mean-per-bin ===")
mid_sil_idx = np.where(sil_mask)[0][len(np.where(sil_mask)[0]) // 2]
print(f"  true-silence block band split: low={band_low[mid_sil_idx]:.2f} "
      f"mid={band_mid[mid_sil_idx]:.2f} high={band_high[mid_sil_idx]:.2f} "
      f"(v1 bug showed high=0.64 here; should be roughly balanced now)")
balanced = max(band_low[mid_sil_idx], band_mid[mid_sil_idx], band_high[mid_sil_idx]) < 0.5
print(f"  no single band > 50% during pure noise: {'PASS' if balanced else 'FAIL'}")

print("\n=== RE-TEST 2 (fixed): low-band-weighted onset detector (absolute energy, not normalized fraction) ===")
fires = onset_detector_fixed(times, band_low_abs)


def score(fires, ground_truth, tol=0.08):
    hits = 0
    used = np.zeros(len(ground_truth), dtype=bool)
    for f in fires:
        d = np.abs(ground_truth - f)
        j = np.argmin(d)
        if d[j] < tol and not used[j]:
            used[j] = True
            hits += 1
    precision = hits / len(fires) if len(fires) else 0.0
    recall = hits / len(ground_truth) if len(ground_truth) else 0.0
    return hits, len(fires), precision, recall


h, nf, p, r = score(fires, kick_times)
print(f"  {nf} fires, {h} matched kicks -> precision={p:.1%} recall={r:.1%}")
print(f"  {'PASS' if r > 0.8 and p > 0.85 else 'FAIL'} (target: >80% recall, >85% precision)")

print("\n=== RE-TEST 3 (fixed): deck-playing-gated silence detector, QUIET breakdown ===")
fixed_silence = silence_detector_fixed(times, rms_smooth, deck_playing)
false_trigger = fixed_silence[bd_mask].mean()
true_detect = fixed_silence[sil_mask].mean()
print(f"  Fraction of QUIET BREAKDOWN incorrectly flagged silent: {false_trigger:.1%} (v1 bug: 72.7%)")
print(f"  Fraction of TRUE SILENCE correctly flagged silent: {true_detect:.1%}")
print(f"  {'PASS' if false_trigger < 0.01 and true_detect > 0.8 else 'FAIL'}")

# ------------------------------------------------------------------ report plot
plt.figure(figsize=(14, 9))

plt.subplot(4, 1, 1)
plt.plot(times, band_low, label="low", color="red", alpha=0.8)
plt.plot(times, band_mid, label="mid", color="purple", alpha=0.8)
plt.plot(times, band_high, label="high", color="cyan", alpha=0.8)
for label, (s, e) in bounds.items():
    plt.axvspan(s, e, alpha=0.06)
plt.legend(loc="upper right", fontsize=8)
plt.title("FIX 1: band fractions (mean-per-bin) — silence should NOT spike any single band")

plt.subplot(4, 1, 2)
plt.plot(times, rms_raw, alpha=0.4, label="raw RMS", color="gray")
plt.scatter(fires, np.full(len(fires), rms_raw.max() * 1.05), marker="v", color="green", s=30, label="onset fires (fixed)")
plt.scatter(kick_times, np.full(len(kick_times), rms_raw.max() * 1.1), marker="|", color="orange", s=100, label="true kicks")
plt.legend(loc="upper right", fontsize=8)
plt.title(f"FIX 2: low-band-weighted onset detector — {h}/{len(kick_times)} kicks matched")

plt.subplot(4, 1, 3)
plt.plot(times, deck_playing.astype(float) * 0.9, label="deck playing (ground truth / simulated PDL)", color="blue")
plt.plot(times, rms_smooth / rms_smooth.max(), label="RMS (normalized)", color="gray", alpha=0.5)
plt.legend(loc="upper right", fontsize=8)
plt.title("Ground truth: deck-playing signal vs. audio loudness (note: playing thru the quiet breakdown)")

plt.subplot(4, 1, 4)
plt.plot(times, fixed_silence.astype(float), label="fixed silence flag", color="black")
plt.axvspan(*bounds["breakdown"], alpha=0.15, color="orange", label="breakdown (should stay OFF)")
plt.axvspan(*bounds["silence"], alpha=0.15, color="red", label="true silence (should go ON)")
plt.legend(loc="upper right", fontsize=8)
plt.title("FIX 3: deck-playing-gated silence detector vs. section ground truth")

plt.tight_layout()
plt.savefig("/Users/joshuaracimora/LiveReact/tools/simulations/audio_sim_v2_report.png", dpi=110)
print("\nSaved plot to tools/simulations/audio_sim_v2_report.png")
