"""Golden DMX frames: every rig's demo-mode show, hashed frame by frame.

The point is one question per pull request: did Josh's default looks change?
Each rig in ``rigs/`` (plus the packaged default rig) runs the real pipeline --
DemoDataSource -> Metronome -> ShowEngine (every engine, merge, finalize) ->
the frame the DMX writer would send -- on a FakeClock, so a run is exactly
repeatable and takes no real time. The demo source alone never leaves BREAK
(the classifier listens to audio), so a scripted song (``song_audio``) and the
DJ's two cues (C at the build, D before the drop) walk every rig through
BREAK, BUILD, DROP, PEAK and back to BREAK / OUTRO. Each rig runs twice: as
the demo boots (lasers armed) and with the lasers disarmed, the state an
accent / trigger / feature rig boots in at a gig until the operator presses L. Every writer-rate frame is fed into a
SHA-256; ``tests/golden/frames.json`` stores the whole-run hash and one per
10-second window, so a mismatch says WHEN the show first differs, not just
that it does.

    python tests/golden_frames.py            # check, print any differences
    python tests/golden_frames.py --update   # re-record (only for a change
                                             # that is MEANT to alter the show)

``tests/test_golden_frames.py`` runs the check inside pytest. A PR that
updates frames.json is changing what the audience sees and must say so.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_PATH = ROOT / "tests" / "golden" / "frames.json"
RIGS_DIR = ROOT / "rigs"

# Simulated time runs on an integer grid so every component's cadence is an
# exact multiple (no float drift between runs or machines): 1200 steps/s is
# the least common multiple of the demo source and metronome (100 Hz), the
# show engine (60 Hz) and the DMX writer (40 Hz).
GRID_HZ = 1200
DEMO_EVERY = GRID_HZ // 100
METRONOME_EVERY = GRID_HZ // 100
SHOW_EVERY = GRID_HZ // 60
WRITER_EVERY = GRID_HZ // 40
DURATION_S = 130
WINDOW_S = 10
# The scripted song, in seconds: a quiet break, a 16 s build (the DJ presses
# C as it starts and D before the drop), a 44 s drop on four-on-the-floor
# kicks (long enough to escalate to PEAK), then a break that ages into OUTRO.
BUILD_AT, DROP_AT, BREAK_AT = 40.0, 56.0, 100.0
CUE_BUILD_AT, ARM_DROP_AT = 40.0, 46.0
SONG_BPM = 124.0  # the demo source's tempo, so the kicks sit on its beats


def song_audio(t: float):
    """One AudioLevelMessage of the scripted song at time ``t`` (the real
    analyzer's units: band_*_abs are absolute band energies, a kick is the
    low band jumping ~12x for the first 30 % of each beat)."""
    from livereact.core.messages import AudioLevelMessage

    kick = (t * SONG_BPM / 60.0) % 1.0 < 0.3
    if BUILD_AT <= t < DROP_AT:
        rise = (t - BUILD_AT) / (DROP_AT - BUILD_AT)
        rms, low, high, onsets = 0.11 + 0.04 * rise, 1.0, 0.4 + 0.5 * rise, 4.0 + 8.0 * rise
    elif DROP_AT <= t < BREAK_AT:
        rms, low, high, onsets = 0.45, (18.0 if kick else 1.5), 0.6, 5.0
    else:
        rms, low, high, onsets = 0.10, 1.2, 0.3, 2.0
    mid = 0.8
    total = low + mid + high
    return AudioLevelMessage(t, rms=rms, band_low=low / total, band_mid=mid / total,
                             band_high=high / total, band_low_abs=low, band_mid_abs=mid,
                             band_high_abs=high, high_flux=high, high_onset_rate=onsets)


def rig_cases() -> list[tuple[str, str | None]]:
    """(name, rig path) for every rig file, plus the packaged default."""
    cases: list[tuple[str, str | None]] = [("default", None)]
    cases += [(p.stem, str(p)) for p in sorted(RIGS_DIR.glob("*.json"))]
    return cases


def run_rig(rig_path: str | None, duration_s: int = DURATION_S, lasers_armed: bool = True) -> dict:
    """Run one rig's demo show; return its frame hashes."""
    from livereact.app import App, AppConfig
    from livereact.clock import FakeClock
    from livereact.output.null_log import NullLogBackend

    clock = FakeClock()
    app = App(AppConfig(demo=True, config_path=None, rig_path=rig_path),
              clock=clock, backend=NullLogBackend())
    app.manual.laser_enable = lasers_armed
    demo = app.sources[0]
    whole = hashlib.sha256()
    window = hashlib.sha256()
    windows: list[str] = []
    frames = 0
    for step in range(duration_s * GRID_HZ):
        t = step / GRID_HZ
        clock._t = t  # absolute time each step: no accumulated float error
        if step == CUE_BUILD_AT * GRID_HZ:
            app.metronome.cue_build()
        if step == ARM_DROP_AT * GRID_HZ:
            app.metronome.arm_drop()
        if step % DEMO_EVERY == 0:
            demo.tick()
            app.input_queue.put(song_audio(t))
        if step % METRONOME_EVERY == 0:
            app.metronome.tick()
        if step % SHOW_EVERY == 0:
            app.show_engine.tick()
        if step % WRITER_EVERY == 0:
            frame = app.frame_buffer.latest()
            whole.update(frame)
            window.update(frame)
            frames += 1
            if frames % (WINDOW_S * 40) == 0:
                windows.append(window.hexdigest()[:16])
                window = hashlib.sha256()
    return {"frames": frames, "sha256": whole.hexdigest(), "windows": windows}


def run_all() -> dict:
    previous = logging.root.manager.disable
    logging.disable(logging.INFO)  # the metronome logs once a simulated second
    try:
        results = {}
        for name, path in rig_cases():
            results[name] = run_rig(path)
            results[f"{name} (lasers disarmed)"] = run_rig(path, lasers_armed=False)
        return results
    finally:
        logging.disable(previous)


def diff(expected: dict, actual: dict) -> list[str]:
    """Human-readable differences; empty means the show is unchanged."""
    problems = []
    for name in sorted(set(expected) | set(actual)):
        if name not in expected:
            problems.append(f"{name}: new rig with no golden frames (run --update)")
            continue
        if name not in actual:
            problems.append(f"{name}: golden frames exist but the rig is gone")
            continue
        exp, act = expected[name], actual[name]
        if exp["sha256"] == act["sha256"]:
            continue
        first = next((i for i, (a, b) in enumerate(zip(exp["windows"], act["windows"])) if a != b), None)
        when = f"first differs in {first * WINDOW_S}-{(first + 1) * WINDOW_S} s" if first is not None else "frame count differs"
        problems.append(f"{name}: frames changed ({when})")
    return problems


def main(argv: list[str] | None = None) -> int:
    sys.path.insert(0, str(ROOT / "src"))
    ap = argparse.ArgumentParser(description="Check or re-record golden demo-mode DMX frames.")
    ap.add_argument("--update", action="store_true", help="re-record tests/golden/frames.json")
    args = ap.parse_args(argv)
    actual = run_all()
    if args.update:
        GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_PATH.write_text(json.dumps(actual, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"recorded {len(actual)} rigs to {GOLDEN_PATH.relative_to(ROOT)}")
        return 0
    expected = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    problems = diff(expected, actual)
    for line in problems:
        print(line)
    print("golden frames: " + ("CHANGED" if problems else f"unchanged ({len(actual)} rigs)"))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
