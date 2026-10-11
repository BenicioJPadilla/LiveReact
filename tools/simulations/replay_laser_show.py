"""Replay recorded sessions through the SHOW laser profile's follow mode, offline.

engines/laser_show.py's "follow the music" mapping (2026-10-08, Sophia's
Thai) has never run live. This feeds `--record` captures back through the
real Metronome (replay_state.py's replay(), its on_snapshot hook) and ticks
a LaserShowEngine in follow mode on each snapshot, so the look timeline a
set WOULD have produced can be judged before it costs Josh a live run.

Usage:
    .venv/bin/python tools/simulations/replay_laser_show.py recordings/session-20261005-151343
    .venv/bin/python tools/simulations/replay_laser_show.py recordings/session-202610* --segments

Per session: share of the set per look, every drop (fan bars actually
shown vs FAN_BARS), builds (length, how far the Tension ramp got, armed
chop length), Dark stretches, Ping-Pong stretches, and FLAGS -- things
that would read badly on the night (fan cut short, look flapping, long
chops, long darks, fallback mid-track). Same fidelity caveats as
replay_laser.py (10 Hz rows; the wub envelope is approximate).
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from livereact.clock import FakeClock  # noqa: E402
from livereact.engines.laser_show import (  # noqa: E402
    FAN_BARS, LOOK_ARMED, LOOK_DARK, LOOK_FAN, LOOK_PINGPONG, LOOK_TENSION, LaserShowEngine,
)
from livereact.fixtures.rig import load_rig  # noqa: E402
from livereact.merge.merge import ManualParams  # noqa: E402
from replay_state import replay  # noqa: E402


def run(session_dir: Path, rig_path: str, seed, show_segments: bool) -> list[str]:
    rig = load_rig(rig_path)
    clock = FakeClock(0.0)
    manual = ManualParams(laser_mode="follow")
    eng = LaserShowEngine(clock, manual)
    trace = []   # (t, bar, look, reason, sweep, lit_l, lit_r, bucket, drop_start_bar, pdl, audio, armed, src, silence)

    def on_snapshot(row, snap):
        clock._t = row["t"]  # noqa: SLF001
        c = eng.tick(snap, rig)
        lasers = rig.by_role("laser")
        lit = [c.values[fx.offset] > 41 for fx in lasers]
        trace.append((row["t"], snap.bar, eng.scene_name, eng.reason, eng.sweep, lit[0], lit[-1],
                      snap.bucket, snap.drop_start_bar, snap.pdl_fresh, snap.audio_fresh,
                      snap.drop_armed, snap.drop_arm_source, bool(row.get("silence_active")), eng.rotating))

    replay(session_dir, quiet=True, seed=seed, on_snapshot=on_snapshot)
    flags: list[str] = []
    if not trace:
        print(f"== {session_dir.name}: nothing to replay")
        return flags
    t0 = trace[0][0]
    total = trace[-1][0] - t0
    music = [r for r in trace if r[9] and r[10]]
    music_s = len(music) * 0.1
    print(f"\n== {session_dir.name}: {total/60:.1f} min, grid+audio fresh {music_s/60:.1f} min")
    if music_s < 30:
        print("   (no real music; skipping)")
        return flags

    # --- look segments (over music rows only) ---
    segs = []  # [look, t_start, t_end, bar_a, bar_b, max_sweep, reason, lit_any_count, rows]
    cur = None
    for r in music:
        t, bar, look, reason, sweep, ll, lr = r[:7]
        if cur is None or cur[0] != look:
            if cur is not None:
                segs.append(cur)
            cur = [look, t, t, bar, bar, sweep, reason, 0, 0]
        cur[2] = t; cur[4] = bar; cur[5] = max(cur[5], sweep); cur[8] += 1
        cur[7] += 1 if (ll or lr) else 0
    if cur is not None:
        segs.append(cur)

    share = Counter()
    for s in segs:
        share[s[0]] += s[8]
    n = sum(share.values())
    print("   look share: " + "  ".join(f"{k} {v/n:.0%}" for k, v in share.most_common()))
    lit_rows = sum(1 for r in music if r[5] or r[6])
    print(f"   lasers lit (either side): {lit_rows/len(music):.0%} of music time")

    def bars(s):
        return s[4] - s[3] + 1

    # --- drops: fan bars actually shown ---
    for i, s in enumerate(segs):
        if s[0] == LOOK_FAN:
            b = bars(s)
            nxt = segs[i + 1][0] if i + 1 < len(segs) else "-"
            print(f"   DROP @{s[1]-t0:7.1f}s bar {s[3]}: fan {b} bars ({s[2]-s[1]:.1f}s) -> {nxt}   peak sweep {s[5]:.2f}")
            if b < FAN_BARS - 1:
                flags.append(f"{session_dir.name}: fan at {s[1]-t0:.0f}s lasted {b} bars, not {FAN_BARS} (-> {nxt})")
    # drop entries that never showed the fan (origin earlier than the entry)
    prev_bucket = None
    for r in music:
        if r[7] == "drop" and prev_bucket not in ("drop", "peak") and prev_bucket is not None:
            if r[2] != LOOK_FAN:
                origin = r[8]
                flags.append(f"{session_dir.name}: DROP entry at {r[0]-t0:.0f}s bar {r[1]} showed {r[2]} not Fan "
                             f"(drop_start_bar={origin}, {r[1]-(origin or r[1])} bars before entry)")
        prev_bucket = r[7]
    # --- builds ---
    for i, s in enumerate(segs):
        if s[0] == LOOK_TENSION:
            print(f"   BUILD @{s[1]-t0:7.1f}s: tension {bars(s)} bars, ramp reached {s[5]:.2f}")
            if bars(s) >= 8 and s[5] < 0.3:
                flags.append(f"{session_dir.name}: build at {s[1]-t0:.0f}s ran {bars(s)} bars but the ramp only reached {s[5]:.2f}")
        if s[0] == LOOK_ARMED:
            src = next((r[12] for r in music if s[1] <= r[0] <= s[2] and r[11]), "")
            print(f"   ARMED @{s[1]-t0:7.1f}s: chop {bars(s)} bars ({s[2]-s[1]:.1f}s, {src or 'D'})")
            if s[2] - s[1] > 30:
                flags.append(f"{session_dir.name}: armed chop at {s[1]-t0:.0f}s lasted {s[2]-s[1]:.0f}s ({bars(s)} bars)")
        if s[0] == LOOK_DARK:
            print(f"   DARK  @{s[1]-t0:7.1f}s: {s[2]-s[1]:.1f}s ({bars(s)} bars)")
            if s[2] - s[1] > 2.5:
                flags.append(f"{session_dir.name}: dark (drop_pending) at {s[1]-t0:.0f}s lasted {s[2]-s[1]:.1f}s")
        if s[0] == LOOK_PINGPONG:
            both = sum(1 for r in music if s[1] <= r[0] <= s[2] and r[5] and r[6])
            print(f"   PEAK  @{s[1]-t0:7.1f}s: ping-pong {bars(s)} bars ({s[2]-s[1]:.0f}s), both lit {both/max(1,s[8]):.0%}")
            if s[8] and both / s[8] > 0.6:
                flags.append(f"{session_dir.name}: ping-pong at {s[1]-t0:.0f}s had both sides lit {both/s[8]:.0%} (drop_start_bar stuck?)")
    # --- flapping: short segments (not Dark) ---
    short = [s for s in segs if s[0] != LOOK_DARK and (s[2] - s[1]) < 2.0]
    if len(short) > 2:
        flags.append(f"{session_dir.name}: {len(short)} look changes shorter than 2 s (flapping): "
                     + ", ".join(f"{s[0]}@{s[1]-t0:.0f}s" for s in short[:8]))
    # --- fallback mid music: pdl/audio stale gaps inside the music window ---
    fb = [r for r in trace if r[0] >= music[0][0] and r[0] <= music[-1][0] and r[14] and not r[13]]
    if len(fb) * 0.1 > 2:
        flags.append(f"{session_dir.name}: fell back to rotation for {len(fb)*0.1:.0f}s inside the music window (grid/audio stale, no silence)")
    gaps = [r for r in trace if r[0] >= music[0][0] and r[0] <= music[-1][0] and not (r[9] and r[10]) and not r[13]]
    if gaps:
        print(f"   grid/audio stale {len(gaps)*0.1:.0f}s inside the music window; rotation fallback used {len(fb)*0.1:.0f}s")
    sil = sum(1 for r in trace if r[13]) * 0.1
    if sil:
        print(f"   silence auto-blackout active {sil:.0f}s (lasers dark with the rig then)")
    if show_segments:
        for s in segs:
            print(f"      {s[1]-t0:7.1f}s  bar {s[3]:4d}-{s[4]:4d}  {s[0]:12s} {s[2]-s[1]:6.1f}s  {s[6]}")
    return flags


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("sessions", nargs="+")
    ap.add_argument("--rig", default="rigs/sophias_thai.json")
    ap.add_argument("--seed")
    ap.add_argument("--segments", action="store_true")
    args = ap.parse_args()
    seed = tuple(float(x) for x in args.seed.split(",")) if args.seed else None
    flags: list[str] = []
    for s in args.sessions:
        flags += run(Path(s), args.rig, seed, args.segments)
    print("\n== FLAGS ==")
    for f in flags or ["none"]:
        print(" - " + f)


if __name__ == "__main__":
    main()
