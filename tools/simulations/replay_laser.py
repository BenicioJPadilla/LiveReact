"""Replay recorded sessions through the FEATURE laser profile, offline.

The bar's engines/laser_feature.py has never run live. This feeds every
`--record` capture in recordings/ back through the real Metronome
(replay_state.py's replay(), its on_snapshot hook) and ticks a
LaserFeatureEngine on each snapshot, so the mood timeline a set WOULD have
produced can be judged -- and FAN_MIN_HIT / GROOVE_* / TENSION_* tuned --
before it costs Josh a live run (the same before/after discipline every
classifier change since 2026-09-15 has used).

Usage:
    .venv/bin/python tools/simulations/replay_laser.py recordings/session-20260916-114402
    .venv/bin/python tools/simulations/replay_laser.py recordings/session-2026091*
    .venv/bin/python tools/simulations/replay_laser.py <dir> --rig rigs/bar_rig.json   # default
    .venv/bin/python tools/simulations/replay_laser.py <dir> --seed 0.12,0.48          # last session's range
    .venv/bin/python tools/simulations/replay_laser.py <dir> --segments               # every mood segment

What it prints per session: the share of the set in each mood, every FAN
and GROOVE stretch (start, length, bars, the hit that earned it, peak
sweep), the calm colour steps, the accent engine's recorded `laser_on`
seconds for comparison, and a sanity line (fan outside DROP/PEAK must be 0).

Fidelity: replay_state.py's caveats apply (10 Hz rows vs the live 100 Hz
metronome; the wub envelope sees 10 samples/s, so its fast attack is
approximate -- read the sweep numbers as "about").
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from livereact.clock import FakeClock  # noqa: E402
from livereact.engines.laser_feature import (  # noqa: E402
    MOOD_CALM,
    MOOD_FAN,
    MOOD_GROOVE,
    MOOD_OFF,
    MOOD_TENSION,
    MOODS,
    LaserFeatureEngine,
    laser_color_name,
)
from livereact.fixtures.rig import load_rig  # noqa: E402
from replay_state import replay  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def run(session_dir: Path, rig_path: str, seed, show_segments: bool) -> dict:
    rig = load_rig(rig_path)
    clock = FakeClock(0.0)
    eng = LaserFeatureEngine(clock)
    trace: list[tuple[float, int, str, float, int, int, float, bool, str]] = []

    def on_snapshot(row, snap):
        clock._t = row["t"]  # noqa: SLF001 -- the engine's dt comes from the recorded time
        eng.tick(snap, rig)
        trace.append((row["t"], snap.bar, eng.mood, eng.sweep, eng.color_l, eng.color_r,
                      snap.drop_hit_intensity, bool(row.get("laser_on")), snap.bucket))

    result = replay(session_dir, quiet=True, seed=seed, on_snapshot=on_snapshot)
    if not trace:
        print(f"== {session_dir.name}: nothing to replay")
        return {}
    t0 = trace[0][0]
    total = trace[-1][0] - t0
    # --- segments of constant mood ---
    segments = []  # (mood, start, end, bar_a, bar_b, hit, peak_sweep, colors)
    cur = None
    for t, bar, mood, sweep, cl, cr, hit, _, _ in trace:
        if cur is None or cur[0] != mood:
            if cur is not None:
                segments.append(cur)
            cur = [mood, t, t, bar, bar, hit, sweep, (cl, cr)]
        else:
            cur[2], cur[4] = t, bar
            cur[6] = max(cur[6], sweep)
    if cur is not None:
        segments.append(cur)
    time_in = Counter()
    for mood, a, b, *_ in segments:
        time_in[mood] += b - a
    # The accent engine's own recorded decision (one sweep per 8-bar block in PEAK).
    accent_on_s = 0.0
    for i in range(1, len(trace)):
        if trace[i - 1][7]:
            accent_on_s += trace[i][0] - trace[i - 1][0]
    fan_outside = sum(1 for _, _, mood, _, _, _, _, _, bucket in trace
                      if mood == MOOD_FAN and bucket not in ("drop", "peak"))
    colour_steps = sum(1 for i in range(1, len(trace))
                       if trace[i][2] == MOOD_CALM and trace[i - 1][2] == MOOD_CALM
                       and trace[i][4] != trace[i - 1][4])

    print(f"== {session_dir.name}  ({total:.0f} s, {len(trace)} rows)")
    share = "  ".join(f"{m}: {100 * time_in[m] / total:4.1f}%" for m in MOODS if time_in[m] > 0)
    print(f"   mood share   {share}")
    for mood, a, b, bar_a, bar_b, hit, peak, (cl, cr) in segments:
        if mood in (MOOD_FAN, MOOD_GROOVE) and b - a >= 1.0:
            print(f"   {mood:6}  {a - t0:7.1f} s  +{b - a:5.1f} s  bars {bar_a:4d}-{bar_b:<4d} "
                  f"hit={hit:.2f}  peak sweep {peak:.2f}  {laser_color_name(cl)}")
        elif show_segments:
            print(f"   {mood:7}  {a - t0:7.1f} s  +{b - a:5.1f} s  bars {bar_a:4d}-{bar_b:<4d} "
                  f"{laser_color_name(cl)}/{laser_color_name(cr)}")
    tension = [s for s in segments if s[0] == MOOD_TENSION and s[2] - s[1] >= 1.0]
    print(f"   tension stretches >= 1 s: {len(tension)}   calm colour steps: {colour_steps}   "
          f"off: {time_in[MOOD_OFF]:.0f} s")
    print(f"   accent engine (recorded laser_on): {accent_on_s:.1f} s   feature FAN: {time_in[MOOD_FAN]:.1f} s   "
          f"GROOVE: {time_in[MOOD_GROOVE]:.1f} s")
    print(f"   sanity: fan rows outside DROP/PEAK = {fan_outside}  (must be 0)")
    return {"time_in": time_in, "segments": segments, "fan_outside": fan_outside, "total": total,
            "drops": result.get("drops", [])}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("sessions", nargs="+", type=Path)
    ap.add_argument("--rig", default=str(ROOT / "rigs" / "bar_rig.json"))
    ap.add_argument("--seed", default=None, help="floor,ceiling for the energy normalizer (last session's range)")
    ap.add_argument("--segments", action="store_true", help="print every mood segment, not just fan/groove")
    args = ap.parse_args()
    seed = None
    if args.seed:
        a, b = args.seed.split(",")
        seed = (float(a), float(b))
    grand = Counter()
    grand_total = 0.0
    bad = 0
    for s in args.sessions:
        r = run(s, args.rig, seed, args.segments)
        if r:
            grand.update(r["time_in"])
            grand_total += r["total"]
            bad += r["fan_outside"]
    if grand_total > 0 and len(args.sessions) > 1:
        share = "  ".join(f"{m}: {100 * grand[m] / grand_total:4.1f}%" for m in MOODS if grand[m] > 0)
        print(f"\n== all sessions ({grand_total:.0f} s)   {share}   fan outside DROP/PEAK: {bad}")


if __name__ == "__main__":
    main()
