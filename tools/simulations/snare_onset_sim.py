"""Verification for build_snare_accent Step 1: a snare/hi-hat onset detector
on combined mid+high absolute band energy, before it goes anywhere near
real audio. Same offline-verification-before-hardware discipline as
audio_pipeline_sim_v2.py's kick detector -- don't guess TRIGGER_RATIO/
REFRACTORY_S, derive them against a synthetic track with KNOWN ground
truth, the same way 1.8/0.15 were derived for the kick detector.

Builds on the same groove (kick, hi-hat, sidechained bass, pad) as
audio_pipeline_sim.py's build_track(), adding a real backbeat snare (beats
2 and 4, standard house/techno pattern) with known ground-truth hit times.
The hi-hat is the important adversary here, not a decoration: it already
lives in the SAME high band a snare's own "hiss" does, so this is a real
test of whether the detector can tell "a snare hit" from "a hi-hat doing
its normal job" -- not just "is there high-frequency content."
"""
import sys
sys.path.insert(0, "/Users/joshuaracimora/LiveReact/tools/simulations")
import numpy as np

# audio_pipeline_sim.py has real, hardcoded-path plotting/saving side effects
# at module level (outside any __main__ guard) -- a plain `import` runs them
# and crashes on a stale scratchpad path from a past session.
# audio_pipeline_sim_v2.py already worked around exactly this by execing only
# the source slice BEFORE that section; reusing the same technique here
# rather than inventing a second way to avoid the same problem.
_snippet = open("/Users/joshuaracimora/LiveReact/tools/simulations/audio_pipeline_sim.py").read().split(
    "# ------------------------------------------------------------------ proposed algorithm")[0]
_ns: dict = {}
exec(compile(_snippet, "audio_pipeline_sim_synth_only", "exec"), _ns)
SR, BEAT, BLOCK, hihat, kick, rng, sidechain_envelope = (
    _ns["SR"], _ns["BEAT"], _ns.get("BLOCK", 1024), _ns["hihat"], _ns["kick"], _ns["rng"], _ns["sidechain_envelope"])


# ------------------------------------------------------------------ synth: snare
def snare(t_local, dur=0.15):
    """Snare hit: a short mid-frequency body tone (skin resonance, ~200Hz)
    plus a broadband high-frequency noise burst (the "hiss"/"sizzle") --
    both real components, unlike a hi-hat's noise-only character. Shorter
    and louder overall than the hi-hat synth in audio_pipeline_sim.py."""
    env = np.exp(-t_local / 0.05)
    body = np.sin(2 * np.pi * 200 * t_local) * env * 0.4
    noise = rng.standard_normal(len(t_local)) * env
    out = body + noise * 0.7
    out[t_local > dur] = 0
    return out


def build_track_with_snare():
    sections = [("groove_a", 20.0), ("breakdown", 8.0), ("groove_b", 20.0)]
    total_dur = sum(d for _, d in sections)
    n = int(total_dur * SR)
    t = np.arange(n) / SR
    audio = np.zeros(n)

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

    kick_times, hh_times, snare_times = [], [], []
    for label in ("groove_a", "groove_b"):
        s, e = bounds[label]
        kick_times.extend(np.arange(s, e, BEAT).tolist())
        hh_times.extend(np.arange(s + BEAT / 2, e, BEAT).tolist())
        # backbeat: beats 2 and 4 of every bar -- every OTHER beat, starting
        # one beat in (a real, standard house/techno snare pattern)
        snare_times.extend(np.arange(s + BEAT, e, 2 * BEAT).tolist())
    kick_times, hh_times, snare_times = map(np.array, (kick_times, hh_times, snare_times))

    for kt in kick_times:
        idx0, idx1 = int(kt * SR), min(int(kt * SR) + int(0.25 * SR), n)
        audio[idx0:idx1] += kick(t[idx0:idx1] - kt)
    for ht in hh_times:
        idx0, idx1 = int(ht * SR), min(int(ht * SR) + int(0.06 * SR), n)
        audio[idx0:idx1] += hihat(t[idx0:idx1] - ht)
    for st in snare_times:
        idx0, idx1 = int(st * SR), min(int(st * SR) + int(0.15 * SR), n)
        audio[idx0:idx1] += snare(t[idx0:idx1] - st)

    bass = np.sin(2 * np.pi * 55 * t) * 0.5
    sc_env = sidechain_envelope(t, kick_times)
    audio[groove_mask] += (bass * sc_env)[groove_mask]

    pad = (0.25 * np.sin(2 * np.pi * 440 * t) + 0.2 * np.sin(2 * np.pi * 550 * t)
           + 0.15 * np.sin(2 * np.pi * 660 * t))
    audio[groove_mask] += pad[groove_mask] * 0.4
    audio[breakdown_mask] += pad[breakdown_mask] * 0.12

    audio += rng.standard_normal(n) * 0.0015
    return t, audio, snare_times, hh_times, bounds


# ------------------------------------------------------------------ analysis: mean-per-bin, same fix as v2
def analyze(audio):
    n_blocks = len(audio) // BLOCK
    window = np.hanning(BLOCK)
    freqs = np.fft.rfftfreq(BLOCK, d=1 / SR)
    mid_band = (freqs >= 250) & (freqs < 2000)
    high_band = (freqs >= 2000) & (freqs < 16000)

    times = np.zeros(n_blocks)
    band_mid_abs = np.zeros(n_blocks)
    band_high_abs = np.zeros(n_blocks)
    for i in range(n_blocks):
        block = audio[i * BLOCK:(i + 1) * BLOCK]
        times[i] = (i * BLOCK) / SR
        spec = np.abs(np.fft.rfft(block * window))
        band_mid_abs[i] = spec[mid_band].mean()
        band_high_abs[i] = spec[high_band].mean()
    return times, band_mid_abs, band_high_abs


# ------------------------------------------------------------------ detector: same shape as the old laser kick-onset detector (retired 2026-09-15)
def snare_onset_detector(times, energy, ratio, floor, refractory_s, alpha):
    avg = np.zeros(len(energy))
    prev = energy[0]
    fires = []
    last_fire_t = -999
    for i, e in enumerate(energy):
        prev = prev + alpha * (e - prev)
        avg[i] = prev
        if e > max(avg[i] * ratio, floor) and (times[i] - last_fire_t) > refractory_s:
            fires.append(times[i])
            last_fire_t = times[i]
    return np.array(fires)


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


def false_positive_rate_on_hihats(fires, hh_times, snare_times, tol=0.08):
    """Of the fires that are NOT a real snare hit, how many land suspiciously
    close to a hi-hat instead -- i.e. is the detector actually confusing
    hi-hats for snares, not just noise."""
    non_snare_fires = [f for f in fires if np.min(np.abs(snare_times - f)) >= tol]
    if not non_snare_fires:
        return 0, 0
    near_hihat = sum(1 for f in non_snare_fires if np.min(np.abs(hh_times - f)) < tol)
    return near_hihat, len(non_snare_fires)


if __name__ == "__main__":
    t, audio, snare_times, hh_times, bounds = build_track_with_snare()
    times, band_mid_abs, band_high_abs = analyze(audio)
    combined = band_mid_abs + band_high_abs

    print(f"Track: {t[-1]:.1f}s, {len(snare_times)} real snare hits, {len(hh_times)} hi-hats")
    print(f"{'ratio':>6} {'floor':>6} {'refrac':>7} {'alpha':>6}   fires  hits  precision  recall  hihat-false-positives")
    # start from the kick detector's own verified numbers (TRIGGER_RATIO=1.8,
    # REFRACTORY_S=0.15, ROLLING_AVG_ALPHA=0.05), then sweep floor and ratio --
    # a snare sits on top of a hi-hat-populated high band, unlike the kick's
    # clean low band, so the same numbers are a starting hypothesis, not an
    # assumed answer.
    best = None
    for ratio in (1.8, 2.2, 2.6, 3.0):
        for floor in (0.5, 1.0, 1.5, 2.0):
            fires = snare_onset_detector(times, combined, ratio=ratio, floor=floor,
                                          refractory_s=0.15, alpha=0.05)
            h, nf, p, r = score(fires, snare_times)
            near_hh, non_snare = false_positive_rate_on_hihats(fires, hh_times, snare_times)
            print(f"{ratio:6.1f} {floor:6.1f} {0.15:7.2f} {0.05:6.2f}   {nf:5d} {h:5d}  {p:8.1%} {r:7.1%}  {near_hh}/{non_snare}")
            if r > 0.8 and p > 0.85 and (best is None or (r, p) > (best[3], best[2])):
                best = (ratio, floor, p, r)

    print()
    if best:
        print(f"BEST meeting target (>80% recall, >85% precision): ratio={best[0]}, floor={best[1]} "
              f"-> precision={best[2]:.1%} recall={best[3]:.1%}")
    else:
        print("NO combination met the >80% recall / >85% precision target -- "
              "the plain onset detector needs more than a ratio/floor retune "
              "(a real, disclosed finding, not a bug in this script).")
