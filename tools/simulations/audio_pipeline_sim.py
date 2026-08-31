"""Stress test for the proposed audio-reactive pipeline (docs/14).

Builds a synthetic house-music signal with KNOWN ground truth (exact kick
times, a real breakdown section, a true-silence section) and runs the
proposed algorithm design against it: block FFT -> low/mid/high bands ->
smoothed RMS -> naive RMS-silence detector -> onset/transient detector for
laser triggering. Reports discrepancies against ground truth, not just
"does it run."
"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SR = 44100
BPM = 128.0
BEAT = 60.0 / BPM  # seconds per beat

rng = np.random.default_rng(42)


# ------------------------------------------------------------------ synth
def kick(t_local, dur=0.25):
    """Percussive thump: pitch-dropping sine + short click, fast attack/decay."""
    env = np.exp(-t_local / 0.09)
    pitch = 90 * np.exp(-t_local / 0.04) + 45  # pitch drop 135Hz -> 45Hz
    phase = 2 * np.pi * np.cumsum(pitch) / SR
    tone = np.sin(phase) * env
    click = (rng.standard_normal(len(t_local)) * np.exp(-t_local / 0.004)) * 0.5
    out = tone + click
    out[t_local > dur] = 0
    return out


def hihat(t_local, dur=0.06):
    env = np.exp(-t_local / 0.02)
    noise = rng.standard_normal(len(t_local))
    # crude high-pass: difference noise to push energy up-spectrum
    hp = np.diff(noise, prepend=0)
    out = hp * env * 0.35
    out[t_local > dur] = 0
    return out


def sidechain_envelope(t, kick_times, depth=0.85, recover=0.30):
    """Ducking envelope: dips hard right at each kick, recovers over `recover`s."""
    env = np.ones_like(t)
    for kt in kick_times:
        dt = t - kt
        mask = (dt >= 0) & (dt < recover)
        duck = 1 - depth * np.exp(-dt[mask] / (recover * 0.35))
        env[mask] = np.minimum(env[mask], duck)
    return env


def build_track():
    sections = []  # (label, duration_s)
    sections.append(("groove_a", 16.0))
    sections.append(("breakdown", 10.0))   # pad only, no kick/bass — still "playing"
    sections.append(("silence", 5.0))      # track actually stopped
    sections.append(("groove_b", 12.0))
    total_dur = sum(d for _, d in sections)
    n = int(total_dur * SR)
    t = np.arange(n) / SR
    audio = np.zeros(n)

    # section boundaries
    bounds = {}
    cursor = 0.0
    for label, dur in sections:
        bounds[label] = (cursor, cursor + dur)
        cursor += dur

    def in_section(label):
        s, e = bounds[label]
        return (t >= s) & (t < e)

    groove_mask = in_section("groove_a") | in_section("groove_b")
    breakdown_mask = in_section("breakdown")
    silence_mask = in_section("silence")

    # kick times: every beat, during groove sections only
    kick_times = []
    for label in ("groove_a", "groove_b"):
        s, e = bounds[label]
        kt = np.arange(s, e, BEAT)
        kick_times.extend(kt.tolist())
    kick_times = np.array(kick_times)

    for kt in kick_times:
        idx0 = int(kt * SR)
        seg_n = int(0.25 * SR)
        idx1 = min(idx0 + seg_n, n)
        local_t = t[idx0:idx1] - kt
        audio[idx0:idx1] += kick(local_t)

    # hihats on the off-beat 8th (between kicks), groove sections only
    hh_times = []
    for label in ("groove_a", "groove_b"):
        s, e = bounds[label]
        hh = np.arange(s + BEAT / 2, e, BEAT)
        hh_times.extend(hh.tolist())
    for ht in hh_times:
        idx0 = int(ht * SR)
        seg_n = int(0.06 * SR)
        idx1 = min(idx0 + seg_n, n)
        local_t = t[idx0:idx1] - ht
        audio[idx0:idx1] += hihat(local_t)

    # sidechained sub-bassline under the groove (55Hz, continuous)
    bass = np.sin(2 * np.pi * 55 * t) * 0.5
    sc_env = sidechain_envelope(t, kick_times)
    audio[groove_mask] += (bass * sc_env)[groove_mask]

    # mid pad: present in groove AND breakdown (quiet in breakdown), absent in true silence
    pad = (
        0.25 * np.sin(2 * np.pi * 440 * t)
        + 0.2 * np.sin(2 * np.pi * 550 * t)
        + 0.15 * np.sin(2 * np.pi * 660 * t)
    )
    audio[groove_mask] += pad[groove_mask] * 0.4
    audio[breakdown_mask] += pad[breakdown_mask] * 0.12  # quiet, but NOT silent — track is playing

    # realistic noise floor everywhere (real interfaces are never numerically silent)
    audio += rng.standard_normal(n) * 0.0015
    # true silence section: nothing but noise floor
    # (already zero from all the above masks; noise floor already added)

    return t, audio, kick_times, bounds


# ------------------------------------------------------------------ proposed algorithm
BLOCK = 1024  # samples, ~23ms @44.1kHz — per doc's "small block for low latency"


def analyze(audio):
    n_blocks = len(audio) // BLOCK
    window = np.hanning(BLOCK)
    freqs = np.fft.rfftfreq(BLOCK, d=1 / SR)
    low_band = (freqs >= 20) & (freqs < 250)
    mid_band = (freqs >= 250) & (freqs < 2000)
    high_band = (freqs >= 2000) & (freqs < 16000)

    rms_raw = np.zeros(n_blocks)
    band_low = np.zeros(n_blocks)
    band_mid = np.zeros(n_blocks)
    band_high = np.zeros(n_blocks)
    times = np.zeros(n_blocks)

    for i in range(n_blocks):
        block = audio[i * BLOCK:(i + 1) * BLOCK]
        times[i] = (i * BLOCK) / SR
        rms_raw[i] = np.sqrt(np.mean(block ** 2))
        spec = np.abs(np.fft.rfft(block * window))
        total = spec.sum() + 1e-9
        band_low[i] = spec[low_band].sum() / total
        band_mid[i] = spec[mid_band].sum() / total
        band_high[i] = spec[high_band].sum() / total

    # VU-meter smoothing: fast attack (~15ms), slow release (~250ms)
    dt_block = BLOCK / SR
    attack = 1 - np.exp(-dt_block / 0.015)
    release = 1 - np.exp(-dt_block / 0.250)
    rms_smooth = np.zeros(n_blocks)
    prev = 0.0
    for i, v in enumerate(rms_raw):
        coeff = attack if v > prev else release
        prev = prev + coeff * (v - prev)
        rms_smooth[i] = prev

    return times, rms_raw, rms_smooth, band_low, band_mid, band_high


def naive_silence_detector(times, rms_smooth, threshold, hold_s):
    """The ORIGINAL (pre-stress-test) design: pure RMS threshold + hold time."""
    hold_blocks = max(1, int(hold_s / (BLOCK / SR)))
    below = rms_smooth < threshold
    silent = np.zeros(len(times), dtype=bool)
    run = 0
    for i, b in enumerate(below):
        run = run + 1 if b else 0
        silent[i] = run >= hold_blocks
    return silent


def onset_detector(times, energy, ratio=1.8, floor=0.02, refractory_s=0.15):
    """Fires when current energy exceeds a rolling average by `ratio`."""
    avg = np.zeros(len(energy))
    a = 0.05  # rolling-average smoothing
    prev = energy[0]
    fires = []
    last_fire_t = -999
    for i, e in enumerate(energy):
        prev = prev + a * (e - prev)
        avg[i] = prev
        if e > max(avg[i] * ratio, floor) and (times[i] - last_fire_t) > refractory_s:
            fires.append(times[i])
            last_fire_t = times[i]
    return np.array(fires), avg


# ------------------------------------------------------------------ run + report
t, audio, kick_times, bounds = build_track()
times, rms_raw, rms_smooth, band_low, band_mid, band_high = analyze(audio)

print(f"=== Track: {t[-1]:.1f}s, {len(kick_times)} kicks, {len(times)} analysis blocks ===")
for label, (s, e) in bounds.items():
    print(f"  section {label:12s}: {s:6.1f}s - {e:6.1f}s")

# --- Test 1: naive RMS-only silence detector — does it false-trigger on breakdown? ---
naive = naive_silence_detector(times, rms_smooth, threshold=0.03, hold_s=2.0)
bd_s, bd_e = bounds["breakdown"]
sil_s, sil_e = bounds["silence"]
GUARD = 0.15  # seconds — trim near section boundaries so a block straddling two
               # sections (e.g. silence's last 23ms block catching the next
               # section's first kick) doesn't contaminate "clean" stats.
bd_mask = (times >= bd_s + GUARD) & (times < bd_e - GUARD)
sil_mask = (times >= sil_s + GUARD) & (times < sil_e - GUARD)
print("\n=== TEST 1: naive RMS-threshold silence detector (the ORIGINAL plan) ===")
print(f"  RMS during breakdown: mean={rms_smooth[bd_mask].mean():.4f} min={rms_smooth[bd_mask].min():.4f}")
print(f"  RMS during true silence: mean={rms_smooth[sil_mask].mean():.4f} max={rms_smooth[sil_mask].max():.4f}")
false_trigger_frac = naive[bd_mask].mean()
print(f"  Fraction of BREAKDOWN incorrectly flagged 'silent': {false_trigger_frac:.1%}")
true_detect_frac = naive[sil_mask].mean()
print(f"  Fraction of TRUE SILENCE correctly flagged 'silent': {true_detect_frac:.1%}")
if false_trigger_frac > 0.05:
    print("  >>> DISCREPANCY CONFIRMED: naive RMS silence detector WOULD blackout during the breakdown.")
else:
    print("  >>> No false trigger at this threshold — but see margin analysis below.")

margin = rms_smooth[sil_mask].max() < rms_smooth[bd_mask].min()
print(f"  Is there ANY threshold that cleanly separates breakdown from silence? {margin}")
print(f"  (breakdown min={rms_smooth[bd_mask].min():.4f} vs silence max={rms_smooth[sil_mask].max():.4f} "
      f"-> gap={rms_smooth[bd_mask].min() - rms_smooth[sil_mask].max():.4f})")

# --- Test 2: onset detector for laser triggering — precision/recall vs known kicks ---
print("\n=== TEST 2: onset/transient detector (laser trigger candidate) ===")
overall_energy = band_low + 0.3  # placeholder; try both overall RMS and low-band-weighted
fires_rms, _ = onset_detector(times, rms_raw, ratio=1.8, floor=0.02)
fires_low, _ = onset_detector(times, rms_raw * band_low, ratio=1.8, floor=0.001)

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

h, nf, p, r = score(fires_rms, kick_times)
print(f"  Overall-RMS onset detector: {nf} fires, {h} matched kicks -> precision={p:.1%} recall={r:.1%}")
h2, nf2, p2, r2 = score(fires_low, kick_times)
print(f"  RMS*low-band-weighted onset detector: {nf2} fires, {h2} matched kicks -> precision={p2:.1%} recall={r2:.1%}")

# --- Test 3: band correctness — does low band actually spike on kicks, high on hats? ---
print("\n=== TEST 3: band-splitting sanity ===")
kick_block_idx = np.searchsorted(times, kick_times[5:8])  # sample a few
for i in kick_block_idx:
    print(f"  at kick t={times[i]:.2f}s: low={band_low[i]:.2f} mid={band_mid[i]:.2f} high={band_high[i]:.2f}")

plt.figure(figsize=(14, 8))
plt.subplot(4, 1, 1)
plt.plot(times, rms_smooth, label="RMS (smoothed)")
plt.axhline(0.03, color="red", linestyle="--", label="naive silence threshold")
for label, (s, e) in bounds.items():
    plt.axvspan(s, e, alpha=0.08)
    plt.text(s + 0.2, plt.ylim()[1] * 0.9, label, fontsize=8)
plt.legend(loc="upper right", fontsize=8)
plt.title("RMS loudness vs section ground truth")

plt.subplot(4, 1, 2)
plt.plot(times, band_low, label="low", color="red", alpha=0.8)
plt.plot(times, band_mid, label="mid", color="purple", alpha=0.8)
plt.plot(times, band_high, label="high", color="cyan", alpha=0.8)
plt.legend(loc="upper right", fontsize=8)
plt.title("Band fractions over time")

plt.subplot(4, 1, 3)
plt.plot(times, naive.astype(float), label="naive silence flag", color="black")
plt.scatter(kick_times, np.zeros_like(kick_times) + 0.02, marker="|", color="orange", label="true kicks", s=100)
plt.legend(loc="upper right", fontsize=8)
plt.title("Naive silence detector vs ground truth (does it trip during breakdown?)")

plt.subplot(4, 1, 4)
plt.plot(times, rms_raw, alpha=0.4, label="raw RMS")
plt.scatter(fires_rms, np.full(len(fires_rms), rms_raw.max() * 1.05), marker="v", color="green", s=30, label="onset fires")
plt.scatter(kick_times, np.full(len(kick_times), rms_raw.max() * 1.1), marker="|", color="orange", s=100, label="true kicks")
plt.legend(loc="upper right", fontsize=8)
plt.title("Onset detector fires vs true kick times")

plt.tight_layout()
plt.savefig("/private/tmp/claude-501/-Users-joshuaracimora/551a4356-08fb-4159-931d-5050bdcb5fd5/scratchpad/audio_sim_report.png", dpi=110)
print("\nSaved plot to audio_sim_report.png")
