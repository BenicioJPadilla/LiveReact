"""Verification for build_snare_accent Step 2: distinguishing a genuine
ACCELERATING snare roll from an ordinary steady backbeat pattern, given
only a sequence of onset times (Step 1's SnareOnsetDetector output) --
same offline-before-hardware discipline as every other detector in this
project. This is pure timing-pattern classification, not an audio signal,
so unlike snare_onset_sim.py this doesn't synthesize audio at all -- just
scripted onset-time sequences with known ground truth (steady vs.
accelerating).
"""
import sys
sys.path.insert(0, "/Users/joshuaracimora/LiveReact/src")

from livereact.clock import FakeClock
from livereact.core.snare_trigger import SnareRollDetector

BPM = 128.0
BEAT = 60.0 / BPM


def steady_backbeat_times(n_bars: int) -> list[float]:
    """A real, ordinary house/techno backbeat -- constant 2-beat spacing,
    beats 2 and 4 of every bar. Must NEVER be classified as a roll."""
    times = []
    t = BEAT  # beat 2 of bar 0
    for _ in range(n_bars * 2):
        times.append(t)
        t += 2 * BEAT
    return times


def accelerating_roll_times(start_t: float) -> list[float]:
    """A real snare-roll shape: quarter notes, then eighths, then
    sixteenths, tightening into the drop -- the actual thing this detector
    exists to catch."""
    times = []
    t = start_t
    for interval in (BEAT, BEAT, BEAT / 2, BEAT / 2, BEAT / 4, BEAT / 4, BEAT / 4, BEAT / 4):
        t += interval
        times.append(t)
    return times


def run(onset_times: list[float], bucket_at: callable, max_age_s=0.5, history=4, tighten_ratio=0.85):
    """Replays a sequence of KNOWN onset times through the real detector on
    a FakeClock, ticking at a fine enough resolution (10ms) to catch the
    max_age_s expiry window, and returns the (time, active) trace."""
    clock = FakeClock()
    d = SnareRollDetector(clock, history=history, tighten_ratio=tighten_ratio)
    trace = []
    t = 0.0
    end = onset_times[-1] + 2.0
    step = 0.01
    remaining = sorted(onset_times)
    while t <= end:
        # an onset "fires" on the first tick that reaches or passes it --
        # the real system ticks at a fixed rate and never lands exactly on
        # an arbitrary float time either, so nearest-following-tick is the
        # realistic match, not exact equality.
        fired = bool(remaining) and t >= remaining[0]
        if fired:
            remaining.pop(0)
        active = d.update(fired, bucket_at(t), max_age_s=max_age_s)
        trace.append((t, active))
        clock.advance(step)
        t = round(t + step, 3)
    return trace


if __name__ == "__main__":
    # Ground truth 1: steady backbeat, 8 bars, BUILD bucket the whole time --
    # must NEVER read as a roll despite being multiple onsets in a row.
    backbeat = steady_backbeat_times(8)
    trace = run(backbeat, bucket_at=lambda t: "build")
    false_positives = sum(1 for _, active in trace if active)
    print(f"Steady backbeat ({len(backbeat)} hits, 8 bars): {false_positives} ticks incorrectly read as a roll")
    print(f"  {'PASS' if false_positives == 0 else 'FAIL'} (target: 0)")

    # Ground truth 2: a real accelerating roll starting at t=10s, BUILD bucket.
    roll = accelerating_roll_times(10.0)
    trace = run(roll, bucket_at=lambda t: "build")
    active_ticks = [t for t, active in trace if active]
    print(f"\nAccelerating roll ({len(roll)} hits, {roll[0]:.2f}s-{roll[-1]:.2f}s):")
    if active_ticks:
        print(f"  first correctly flagged as a roll at t={active_ticks[0]:.2f}s "
              f"(roll started at {roll[0]:.2f}s, {len(roll)} hits ending {roll[-1]:.2f}s)")
        print(f"  last flagged at t={active_ticks[-1]:.2f}s -- correctly turns back off: "
              f"{'PASS' if active_ticks[-1] < roll[-1] + 1.0 else 'FAIL'}")
    else:
        print("  NEVER flagged as a roll -- FAIL")

    # Ground truth 3: the same accelerating pattern, but bucket is NOT build
    # (e.g. still BREAK) -- must stay off regardless of the timing pattern,
    # since this is explicitly gated to BUILD only.
    trace = run(roll, bucket_at=lambda t: "break")
    off_bucket_false_positives = sum(1 for _, active in trace if active)
    print(f"\nSame accelerating pattern, bucket=break (not build): "
          f"{off_bucket_false_positives} ticks incorrectly active")
    print(f"  {'PASS' if off_bucket_false_positives == 0 else 'FAIL'} (target: 0 -- BUILD-gated)")
