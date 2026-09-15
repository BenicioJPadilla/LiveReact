"""Offline show replay: feed a real MP3 through the REAL pipeline, no hardware.

Built 2026-09-07 because live testing wasn't reproducible enough to make
precise fixes from ("it's hard for me to relay exactly what happened," Josh).
This runs the ACTUAL production code end to end — the same `AudioAnalyzer`
block-analysis math, the same `Metronome`, the same engines
(`ReactiveLayerEngine`/`PhraseEngine`/`TransitionEngine`), the same
`merge`/`finalize` — and only swaps the two genuinely-live-only pieces:
  - the real-time sounddevice stream -> a decoded MP3 file, block by block
  - the real Pro DJ Link beat feed -> synthetic BeatMessages at a BPM you
    supply (a DJ already knows a track's BPM; auto-detection would be one
    more unverified thing to trust)
Everything downstream of those two swaps is 100% the same code path a real
hardware run uses, run against a `FakeClock` so results are exactly
reproducible run to run on the same input.

Usage:
    .venv/bin/python tools/simulations/replay_song.py path/to/song.mp3 --bpm 128
    .venv/bin/python tools/simulations/replay_song.py song.mp3 --bpm 128 --duration 90

Requires `ffmpeg` on PATH (decodes any format to raw PCM; not a new project
dependency, just a subprocess call).

Outputs (next to the input file by default, override with --out):
  <out>.csv   one row per audio block (~23ms) -- every internal signal this
              project has needed to diagnose a live-test complaint so far:
              energy, energy_norm, bucket, wash_level, palette,
              laser/silence active, and per-fixture VisualState (r/g/b,
              brightness, pan, tilt, active) for all 4 real rig fixtures.
  <out>.png   a timeline plot of the same, for eyeballing without a CSV viewer.
Plus a printed summary (bucket distribution, laser fire count + duty %, bucket
flip count) -- the same kind of analysis this project has been doing by hand
on captured hardware sessions, now repeatable on any song with no rig needed.
"""
from __future__ import annotations

import argparse
import csv
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import numpy as np

from livereact.clock import Clock, FakeClock, RealClock
from livereact.core.messages import BeatMessage
from livereact.core.metronome import Metronome
from livereact.core.show_engine import ShowEngine
from livereact.core.show_state import ShowState
from livereact.core.frame_buffer import DmxFrameBuffer
from livereact.engines.laser import LaserEngine
from livereact.engines.phrase import PhraseEngine
from livereact.engines.reactive import ReactiveLayerEngine
from livereact.engines.transition import TransitionEngine
from livereact.fixtures.rig import load_rig
from livereact.inputs.audio import ATTACK_S, BLOCK, RELEASE_S, AudioAnalyzer
from livereact.merge.merge import ManualParams

SR = 44100  # decode target -- matches AudioAnalyzer's live default samplerate

# A commercially-mastered file decoded straight (bit-perfect, no mic/mixer/room
# in between) reads MUCH louder in raw RMS than what the real live mic capture
# ever sees -- FOUND BY TESTING (2026-09-07, first real --hardware replay):
# a bass-heavy track's raw `energy` (rms * ENERGY_GAIN, see inputs/audio.py)
# sat above 0.85 for 96% of the whole song, essentially clipped at the 1.0
# ceiling throughout -- not a reflection of the song's real dynamics, and it
# broke anything still keyed off an ABSOLUTE raw-energy threshold (the strobe
# gate fired almost continuously). inputs/audio.py's own comment documents the
# real captured range this project has actually measured live: "raw smoothed
# RMS ~0.05-0.13" (2026-08-31/09-01 sessions). Auto-scale the decoded file so
# its own overall RMS lands at the middle of that real, hardware-measured
# range, rather than feeding it in unattenuated -- keeps file-replay results
# comparable to a real mic-capture session instead of a saturated one.
TARGET_RAW_RMS = 0.08  # matches the documented real-session range's midpoint


def calibrate_gain(audio: np.ndarray, override: float | None) -> float:
    if override is not None:
        return override
    rms = float(np.sqrt(np.mean(audio ** 2)))
    if rms <= 1e-9:
        return 1.0
    return TARGET_RAW_RMS / rms


def decode_mp3(path: str, duration: float | None) -> np.ndarray:
    """ffmpeg -> mono float32 PCM at SR Hz. Not a new dependency: shells out to
    the `ffmpeg` binary rather than adding a Python audio-decoding library."""
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR),
           "-f", "f32le", "-acodec", "pcm_f32le"]
    if duration is not None:
        cmd += ["-t", str(duration)]
    cmd += ["pipe:1"]
    try:
        raw = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
    except FileNotFoundError as exc:
        raise SystemExit("ffmpeg not found on PATH -- required to decode audio files.") from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"ffmpeg failed decoding {path!r}:\n{exc.stderr.decode(errors='replace')}") from exc
    return np.frombuffer(raw, dtype=np.float32)


FIXTURE_SLOTS = ["laser", "par", "mh", "bar"]  # josh_rig.json's slot_ids


def run(mp3_path: str, bpm: float, duration: float | None, rig_path: str, out_prefix: str,
        hardware: bool = False, gain: float | None = None) -> dict:
    audio = decode_mp3(mp3_path, duration)
    n_blocks = len(audio) // BLOCK
    audio = audio[: n_blocks * BLOCK]
    applied_gain = calibrate_gain(audio, gain)
    audio = audio * applied_gain
    print(f"Input gain: {applied_gain:.3f}x "
          f"({'manual override' if gain is not None else f'auto, targeting raw RMS {TARGET_RAW_RMS}'})")
    dt_block = BLOCK / SR
    attack = 1 - np.exp(-dt_block / ATTACK_S)
    release = 1 - np.exp(-dt_block / RELEASE_S)

    # --hardware: real-time pacing + a real Enttec output + actual speaker
    # playback, so the SAME offline-replay decisions (still 100% the real
    # engine code, just fed this file instead of live audio/PDL) drive the
    # actual rig while you listen and watch -- not just a CSV/plot after the
    # fact. Without --hardware this runs as fast as possible (pure analysis).
    clock: Clock = RealClock() if hardware else FakeClock()
    enttec = None
    player_proc = None
    if hardware:
        from livereact.output.enttec import EnttecSerialBackend
        enttec = EnttecSerialBackend()
        enttec.open()
        play_cmd = ["afplay", mp3_path]
        if duration is not None:
            play_cmd += ["-t", str(duration)]
        player_proc = subprocess.Popen(play_cmd)

    shared_queue: "queue.Queue" = queue.Queue()
    stop_event = threading.Event()
    show_state = ShowState()

    metronome = Metronome(shared_queue, show_state, clock, stop_event)

    # AudioAnalyzer, analysis-only -- never call .start() (that opens a real
    # sounddevice stream). Manually do the one-time setup start() would have
    # done, then feed it decoded blocks directly instead of live callback data.
    analyzer = AudioAnalyzer(shared_queue, clock, stop_event)
    analyzer._sr = SR
    analyzer._setup_bands(np)

    rig = load_rig(rig_path)
    reactive = ReactiveLayerEngine(clock)
    phrase = PhraseEngine()
    laser_engine = LaserEngine(clock)
    transition = TransitionEngine()
    frame_buffer = DmxFrameBuffer()
    manual = ManualParams(laser_enable=True)  # so the laser isn't suppressed for this analysis
    for fx in rig.by_role("laser"):
        fx.safety_test_mode = True  # offline analysis: same bypass as `--testing`
    show_engine = ShowEngine(show_state, rig, frame_buffer, [reactive, phrase, laser_engine, transition],
                              manual, clock, stop_event, laser_engine=laser_engine)

    fixtures = {slot: rig.fixture(slot) for slot in FIXTURE_SLOTS}

    beat_dur = 60.0 / bpm
    next_beat_time = 0.0
    beat_in_bar = 1

    rows = []
    prev_bucket = None
    bucket_flips = 0
    bucket_counts: dict[str, int] = {}
    laser_ticks = 0
    over_strobe_threshold = 0

    wall_start = clock.monotonic() if hardware else None

    for i in range(n_blocks):
        if hardware:
            # Pace to real wall-clock time so DMX output tracks the actual
            # audio playing over the speakers, instead of running flat-out.
            target = wall_start + (i + 1) * dt_block
            sleep_for = target - clock.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)
        else:
            clock.advance(dt_block)
        now = clock.monotonic()
        while next_beat_time <= now:
            shared_queue.put(BeatMessage(timestamp=next_beat_time, beat_in_bar=beat_in_bar,
                                          bpm=bpm, is_master=True, player=1))
            beat_in_bar = beat_in_bar % 4 + 1
            next_beat_time += beat_dur

        block = audio[i * BLOCK:(i + 1) * BLOCK]
        analyzer._analyze_block(block, attack, release, np)

        snap = metronome.tick()
        frame = show_engine.tick()
        if frame is None:  # frozen (shouldn't happen, manual.freeze defaults False)
            frame = frame_buffer.latest()
        if enttec is not None:
            enttec.send(frame)

        # snap.bucket -- the ALREADY-DEBOUNCED bucket from metronome.py
        # (BUCKET_MIN_DWELL_S), not a fresh undebounced bucket_for_energy call
        # -- this trace should show what the real engines actually see.
        bucket = snap.bucket.upper()
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        if prev_bucket is not None and bucket != prev_bucket:
            bucket_flips += 1
        prev_bucket = bucket

        laser_on = laser_engine.active
        if laser_on:
            laser_ticks += 1
        if snap.energy > 0.85:
            over_strobe_threshold += 1

        row = {
            "t": round(now, 3),
            "bar": snap.bar,
            "beat": snap.beat_in_bar,
            "beat_phase": round(snap.beat_phase, 3),
            "energy": round(snap.energy, 4),
            "energy_norm": round(snap.energy_norm, 4),
            "bucket": bucket,
            "wash_level": round(reactive.wash_level, 4),
            "palette": snap.palette,
            "scene": phrase._current.name,
            "scene_uses_lasers": phrase._current.uses_lasers,
            "bar_strobe": frame[fixtures["bar"].offset + 1],  # raw CH2 (strobe) byte, 0-255
            # NOTE: named laser_on, not laser_active -- a fixture slot is
            # also named "laser", and the per-fixture loop below writes
            # f"{slot}_active" for each slot, which for slot="laser" produces the
            # key "laser_active" -- that used to silently clobber THIS field with
            # a different signal (Laser.visual_state()'s "is CH1 in manual mode,"
            # not "is the onset-detector flash window open right now"). FOUND BY
            # TESTING (2026-09-07): this made the laser panel/laser_active_pct
            # summary silently wrong -- confirmed the onset detector really was
            # firing (direct instrumentation) while every CSV row still read
            # False, because the fixture loop ran after and overwrote it.
            "laser_on": laser_on,
            "silence_active": show_engine.silence.active,
        }
        for slot, fx in fixtures.items():
            vs = fx.visual_state(frame)
            row[f"{slot}_r"] = vs.r
            row[f"{slot}_g"] = vs.g
            row[f"{slot}_b"] = vs.b
            row[f"{slot}_brightness"] = round(vs.brightness, 3)
            row[f"{slot}_pan"] = round(vs.pan, 3)
            row[f"{slot}_tilt"] = round(vs.tilt, 3)
            row[f"{slot}_active"] = vs.active
        rows.append(row)

    if enttec is not None:
        enttec.send(bytes(len(frame)))  # blackout on exit -- same convention as every
        enttec.close()                   # other hands-on hardware-probing tool here
    if player_proc is not None:
        player_proc.wait()

    total_s = n_blocks * dt_block
    summary = {
        "total_seconds": round(total_s, 1),
        "bucket_distribution_pct": {k: round(100 * v / n_blocks, 1) for k, v in bucket_counts.items()},
        "bucket_flips": bucket_flips,
        "bucket_flips_per_min": round(bucket_flips / (total_s / 60.0), 2) if total_s > 0 else 0.0,
        "laser_active_pct": round(100 * laser_ticks / n_blocks, 2),
        "raw_energy_over_0.85_pct": round(100 * over_strobe_threshold / n_blocks, 1),
        "applied_gain": round(applied_gain, 3),
    }

    write_csv(rows, f"{out_prefix}.csv")
    write_plot(rows, f"{out_prefix}.png", bpm)
    return summary


def write_csv(rows: list[dict], path: str) -> None:
    if not rows:
        return
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_plot(rows: list[dict], path: str, bpm: float) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t = [r["t"] for r in rows]
    bucket_color = {"BREAKDOWN": "#2b3a55", "BUILD": "#c98a2c", "HOLD": "#3c8a4a", "DROP": "#c0392b"}

    fig, axes = plt.subplots(5, 1, figsize=(16, 11), sharex=True,
                              gridspec_kw={"height_ratios": [2, 1.4, 1.4, 1, 1]})

    ax = axes[0]
    for b, color in bucket_color.items():
        mask = [r["bucket"] == b for r in rows]
        ax.fill_between(t, 0, 1, where=mask, color=color, alpha=0.15, step="post")
    ax.plot(t, [r["energy"] for r in rows], color="#888", lw=0.6, label="raw energy")
    ax.plot(t, [r["energy_norm"] for r in rows], color="black", lw=1.0, label="energy_norm")
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("energy")
    ax.legend(loc="upper right", fontsize=8)
    ax.set_title(f"LiveReact offline replay -- {bpm:.1f} BPM")

    ax = axes[1]
    ax.plot(t, [r["wash_level"] for r in rows], color="#c98a2c", lw=1.0, label="wash_level (par/bar)")
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("wash/par")
    ax.legend(loc="upper right", fontsize=8)

    ax = axes[2]
    ax.plot(t, [r["mh_pan"] for r in rows], color="#2b3a55", lw=0.8, label="MH pan")
    ax.plot(t, [r["mh_tilt"] for r in rows], color="#8e44ad", lw=0.8, label="MH tilt")
    ax.plot(t, [r["mh_brightness"] for r in rows], color="#999", lw=0.6, label="MH brightness")
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("moving head")
    ax.legend(loc="upper right", fontsize=8)

    ax = axes[3]
    ax.fill_between(t, 0, [1 if r["laser_on"] else 0 for r in rows], color="#c0392b", step="post")
    ax.set_ylim(0, 1.2)
    ax.set_ylabel("laser")
    ax.set_yticks([])

    ax = axes[4]
    ax.fill_between(t, 0, [1 if r["silence_active"] else 0 for r in rows], color="#555", step="post")
    ax.set_ylim(0, 1.2)
    ax.set_ylabel("blackout")
    ax.set_yticks([])
    ax.set_xlabel("seconds")

    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mp3", help="Path to an MP3 (or any ffmpeg-decodable audio file)")
    p.add_argument("--bpm", type=float, required=True, help="Track BPM (you already know it -- no auto-detection)")
    p.add_argument("--duration", type=float, default=None, help="Only replay the first N seconds")
    p.add_argument("--rig", default="rigs/josh_rig.json", help="Rig JSON (default: rigs/josh_rig.json)")
    p.add_argument("--out", default=None, help="Output file prefix (default: alongside the input, same basename)")
    p.add_argument("--hardware", action="store_true",
                    help="Also drive the real Enttec rig in real time and play the file aloud "
                         "(afplay) -- watch the actual lights, not just the CSV/plot after the fact.")
    p.add_argument("--gain", type=float, default=None,
                    help="Manual input-level multiplier (default: auto-calibrated so the file's "
                         "overall RMS matches this project's real captured mic-input range -- see "
                         "TARGET_RAW_RMS). Override only to deliberately test a different level.")
    args = p.parse_args()

    out_prefix = args.out or str(Path(args.mp3).with_suffix(""))
    summary = run(args.mp3, args.bpm, args.duration, args.rig, out_prefix,
                  hardware=args.hardware, gain=args.gain)

    print(f"Replayed {summary['total_seconds']}s @ {args.bpm} BPM")
    print(f"Bucket distribution: {summary['bucket_distribution_pct']}")
    print(f"Bucket flips: {summary['bucket_flips']} ({summary['bucket_flips_per_min']}/min)")
    print(f"Laser active: {summary['laser_active_pct']}% of the time")
    print(f"Raw energy > 0.85 (strobe threshold): {summary['raw_energy_over_0.85_pct']}% of the time "
          f"-- if this is very high, the input may still be too hot (try a lower --gain)")
    print(f"Wrote {out_prefix}.csv and {out_prefix}.png")


if __name__ == "__main__":
    main()
