"""Replay a recorded session's `state.jsonl` through the REAL `Metronome`.

The complement to `replay_song.py`: that one is for audio CONTENT (it
re-runs the FFT math on a file, with a synthetic beat grid), this one is
for CLASSIFIER behaviour on a real set -- it feeds the 100%-real inputs a
`--record` session captured (real audio levels, real Pro DJ Link beats,
the DJ's real C presses) back through the current working tree's
`Metronome`, so a change to the energy/bucket logic can be judged against
every capture in `recordings/` before it costs Josh a live run. Run it
once on the working tree and once under `git stash` (or against another
commit) and diff the two printouts -- that's the before/after every
classifier change since 2026-09-15 has been checked with.

Usage:
    .venv/bin/python tools/simulations/replay_state.py recordings/session-20260916-114402
    .venv/bin/python tools/simulations/replay_state.py recordings/session-2026091{5,6}-*   # several
    CUE=220,310 .venv/bin/python tools/simulations/replay_state.py <dir>   # inject C presses (s)
    .venv/bin/python tools/simulations/replay_state.py <dir> --csv out.csv  # per-row trace
    .venv/bin/python tools/simulations/replay_state.py <dir> --seed 0.12,0.48  # last session's range
    .venv/bin/python tools/simulations/replay_state.py <dir> --no-cue        # ignore the recorded C presses

What it prints per session: the normalizer's warm-up end, every bucket
transition (time, bar, from -> to, the smoothed/instantaneous energy at
the commit), every drop commit with its hit intensity, the C presses it
replayed, and a one-line count summary.

Fidelity, stated plainly: the recorder samples at 10 Hz, the live
metronome derives at 100 Hz off ~43 audio blocks/s. Every EMA here is
dt-based so the taus (0.4 s attack, 3 s release, 2 s hit-lead level) hold
up, but anything shorter than ~0.2 s (the 0.3 s low-band peak-hold sees 3
samples, not 13) is approximate. Transition TIMES have matched the live
log within a tick on every capture checked so far; treat sub-0.3 s claims
as "about". The recorder logs `band_low/mid/high` as the *_abs values and
does not log the normalized fractions, so those are fed as flat thirds --
they only feed the palette, never the classifier. `bpm`/`beat` are the
real PDL values, so bars count exactly as they did live.

Ground truth in the recording is the OLD code's decisions (`bucket`,
`build_cue`); the C presses are re-issued at their recorded rising edges
(or from `CUE=` seconds, offset from the session's first row) so a rule
under test sees the same operator input the live run had.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import queue
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from livereact.clock import FakeClock
from livereact.core.messages import AudioLevelMessage, BeatMessage, StatusMessage
from livereact.core.metronome import Metronome
from livereact.core.show_state import ShowState
from livereact.core.snare_trigger import RollRiseDetector

TRACE_FIELDS = (
    "t", "rel", "bar", "beat", "energy", "energy_smooth", "energy_norm", "energy_norm_inst",
    "bucket", "base", "candidate", "build_cue", "drop_hit_intensity", "band_low", "band_mid",
    "band_high", "onset_rate",
)


def load_rows(session_dir: Path) -> list[dict]:
    rows = []
    with (session_dir / "state.jsonl").open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def cue_times_from_env(first_t: float) -> list[float]:
    raw = os.environ.get("CUE", "").strip()
    if not raw:
        return []
    return [first_t + float(x) for x in raw.split(",") if x.strip()]


def replay(session_dir: Path, *, csv_path: Path | None = None, quiet: bool = False,
           seed: tuple[float, float] | None = None, replay_cues: bool = True) -> dict:
    rows = load_rows(session_dir)
    if not rows:
        print(f"{session_dir}: empty")
        return {}
    t0 = rows[0]["t"]
    clock = FakeClock(t0)
    state = ShowState()
    q: queue.Queue = queue.Queue()
    m = Metronome(q, state, clock, threading.Event(), log_interval=1e9, seed_range=seed)
    roll = RollRiseDetector(clock)  # the accent lives in the reactive engine live; here it arms the drop
    prev_roll = False
    rolls: list[tuple[float, float]] = []
    roll_since: float | None = None

    env_cues = cue_times_from_env(t0)
    transitions: list[tuple[float, int, str, str, float, float]] = []
    drops: list[tuple[float, int, float]] = []
    cues: list[float] = []
    auto_cues: list[tuple[float, int, str]] = []  # (t, bar, "fired"/"released")
    prev_src = ""
    warm_at: float | None = None        # the live window reached ENERGY_NORM_MIN_SAMPLES
    first_norm_at: float | None = None  # first nonzero energy_norm (earlier than warm_at when seeded)
    prev_bucket = None
    prev_beat = None
    prev_cue = False
    writer = None
    fh = None
    if csv_path is not None:
        fh = csv_path.open("w", newline="")
        writer = csv.DictWriter(fh, fieldnames=TRACE_FIELDS)
        writer.writeheader()

    try:
        for row in rows:
            t = row["t"]
            if t < clock.monotonic():
                continue  # the recorder never goes backwards, but be safe
            clock._t = t  # noqa: SLF001 - drive the fake clock to the recorded instant
            if row.get("audio_fresh"):
                q.put(AudioLevelMessage(
                    timestamp=t, rms=row["energy"],
                    band_low=1 / 3, band_mid=1 / 3, band_high=1 / 3,
                    band_low_abs=row.get("band_low", 0.0),
                    band_mid_abs=row.get("band_mid", 0.0),
                    band_high_abs=row.get("band_high", 0.0),
                    high_onset_rate=row.get("onset_rate", 0.0),  # only in captures from 2026-09-17 on
                    high_flux=row.get("high_flux", 0.0),
                ))
            beat = row.get("beat")
            if row.get("pdl_fresh") and beat != prev_beat:
                q.put(BeatMessage(timestamp=t, beat_in_bar=int(beat), bpm=float(row["bpm"]),
                                  is_master=True, player=1))
            prev_beat = beat
            if row.get("on_air") is not None:
                q.put(StatusMessage(timestamp=t, on_air=tuple(row.get("on_air") or ()),
                                    master_deck=row.get("master_deck"), playing=True, loop_active=False))
            # The DJ's C presses: recorded rising edges, plus any injected ones.
            cue_now = bool(row.get("build_cue"))
            pressed = replay_cues and cue_now and not prev_cue
            prev_cue = cue_now
            while env_cues and env_cues[0] <= t:
                env_cues.pop(0)
                pressed = True
            if pressed:
                m.cue_build()
                cues.append(t)
            snap = m.tick()
            # The roll detector reads the snapshot the engines would see and
            # feeds the metronome like engines/reactive.py does live.
            roll_on = roll.update(snap)
            m.note_roll(roll_on)
            if roll_on and not prev_roll:
                roll_since = t
            if not roll_on and prev_roll and roll_since is not None:
                rolls.append((roll_since, t))
            prev_roll = roll_on
            if snap.build_cue_source != prev_src and "auto" in (snap.build_cue_source, prev_src):
                auto_cues.append((t, snap.bar, "fired" if snap.build_cue_source == "auto" else "released"))
            prev_src = snap.build_cue_source
            if warm_at is None and m.norm_warm:
                warm_at = t
            if first_norm_at is None and snap.energy_norm > 0.0 and row.get("audio_fresh"):
                first_norm_at = t
            if snap.bucket != prev_bucket:
                transitions.append((t, snap.bar, prev_bucket or "-", snap.bucket,
                                    snap.energy_norm, m._energy_norm_inst or 0.0))  # noqa: SLF001
                if snap.bucket == "drop" and prev_bucket not in ("drop", "peak"):
                    drops.append((t, snap.bar, snap.drop_hit_intensity))
                prev_bucket = snap.bucket
            if writer is not None:
                writer.writerow({
                    "t": round(t, 3), "rel": round(t - t0, 2), "bar": snap.bar, "beat": snap.beat_in_bar,
                    "energy": row.get("energy"), "energy_smooth": round(m._energy_smooth, 4),  # noqa: SLF001
                    "energy_norm": round(snap.energy_norm, 4),
                    "energy_norm_inst": round(m._energy_norm_inst or 0.0, 4),  # noqa: SLF001
                    "bucket": snap.bucket, "base": m._base_committed.value,  # noqa: SLF001
                    "candidate": m._bucket_candidate.value if m._bucket_candidate else "",  # noqa: SLF001
                    "build_cue": snap.build_cue, "drop_hit_intensity": snap.drop_hit_intensity,
                    "band_low": row.get("band_low"), "band_mid": row.get("band_mid"),
                    "band_high": row.get("band_high"), "onset_rate": row.get("onset_rate", ""),
                })
    finally:
        if fh is not None:
            fh.close()

    if not quiet:
        print(f"== {session_dir.name}  ({len(rows)} rows, {rows[-1]['t'] - t0:.0f} s)")
        print(f"   warm-up done: {'never' if warm_at is None else f'{warm_at - t0:.1f} s'}"
              f"   first energy_norm>0: {'never' if first_norm_at is None else f'{first_norm_at - t0:.1f} s'}"
              f"{'   (seeded)' if seed else ''}")
        for t in cues:
            print(f"   C press     {t - t0:8.1f} s")
        for t, bar, what in auto_cues:
            print(f"   auto cue {what:8} {t - t0:8.1f} s  bar {bar:4d}")
        for a, b in rolls:
            if b - a >= 1.0:
                print(f"   roll        {a - t0:8.1f}-{b - t0:.1f} s")
        for t, bar, a, b, en, inst in transitions:
            print(f"   {t - t0:8.1f} s  bar {bar:4d}  {a:>5} -> {b:<5}  en={en:.2f} inst={inst:.2f}")
        for t, bar, hit in drops:
            print(f"   DROP commit {t - t0:8.1f} s  bar {bar:4d}  hit={hit:.2f}")
        print(f"   {len(transitions)} transitions, {len(drops)} drops, {len(cues)} cues, "
              f"{sum(1 for a in auto_cues if a[2] == 'fired')} auto cues")
        floor, ceiling = m.energy_norm_range
        print(f"   final range: floor={floor:.3f} ceiling={ceiling:.3f}"
              f"{'' if m.norm_warm else '  (never warmed up)'}  -> --seed {floor:.3f},{ceiling:.3f}")
    return {"transitions": transitions, "drops": drops, "cues": cues, "warm_at": warm_at, "t0": t0,
            "range": m.energy_norm_range}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sessions", nargs="+", type=Path, help="recordings/session-* directories")
    ap.add_argument("--csv", type=Path, help="write a per-row trace (single session only)")
    ap.add_argument("--no-cue", action="store_true",
                    help="don't re-issue the recorded C presses (what the classifier does unaided)")
    ap.add_argument("--seed", help="floor,ceiling to seed the normalizer with (what config.py would "
                                   "have persisted from the previous session; see 'final range')")
    args = ap.parse_args()
    seed = None
    if args.seed:
        floor, ceiling = (float(x) for x in args.seed.split(","))
        seed = (floor, ceiling)
    if args.csv is not None and len(args.sessions) != 1:
        ap.error("--csv takes exactly one session")
    for s in args.sessions:
        if not (s / "state.jsonl").exists():
            print(f"{s}: no state.jsonl, skipping")
            continue
        replay(s, csv_path=args.csv, seed=seed, replay_cues=not args.no_cue)


if __name__ == "__main__":
    main()
