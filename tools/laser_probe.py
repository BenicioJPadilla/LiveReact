"""Hold or sweep raw channels on the Shehds 3W laser to MAP its unverified bytes.

BENCH ONLY. This drives the Enttec directly -- no App, no ShowEngine, no
finalize(): Laser.apply_safety (arm switch, mount-height gate) is NOT in the
loop, exactly like the 2026-09-06 scratchpad scripts (laser_hold.py /
laser_ch2_sweep.py) that mapped CH1/CH2/CH7/CH9/CH11/CH12 in the first place.
No crowd, beam path confirmed safe, operator present -- the tool asks you to
confirm that before it opens the port (``--yes`` skips the prompt).

Why it lives in the repo now (2026-10-01): those scratchpad scripts vanished
with their session, and the bar's feature profile (engines/laser_feature.py)
needs the looks Josh described -- a SOLID line, a CURVY line, a line held
STILL, colors that drift on their own -- none of which has a verified byte
yet. The candidates below come from the QLC+ fixture file's 25-channel
definition (the unit's 12-channel mode is its first 12 channels; the file's
NAMES were wrong before -- "Circle Part Fan" drew a ninja star -- so every
value here is a question, not an answer). Verified constants live in
fixtures/profiles.py's Laser class; docs/laser_findings.md is the evidence
trail this tool appends to.

Usage (from the project root, venv active):

  # the one verified pattern, 10 s, green:
  python tools/laser_probe.py --preset line --seconds 10

  # candidates, each held until you press Enter and type what you saw:
  python tools/laser_probe.py --preset line --set 11=0                 # CH11 < 128: solid outline?
  python tools/laser_probe.py --preset line --sweep 3 --from 0 --to 240 --step 16   # CH3 sub-patterns in the line group
  python tools/laser_probe.py --preset line --sweep 2 --from 0 --to 224 --step 32   # the other 7 CH2 groups (CH3=0)
  python tools/laser_probe.py --preset line --sweep 7 --from 0 --to 120 --step 24   # CH7 static half: a still line, where?
  python tools/laser_probe.py --preset line --sweep 4 --from 0 --to 120 --step 24   # CH4: static rotation angle?
  python tools/laser_probe.py --preset line --sweep 8 --from 0 --to 120 --step 24   # CH8: vertical position (BEAM HEIGHT: watch it)
  python tools/laser_probe.py --preset line --sweep 12 --from 64 --to 127 --step 16  # CH12 64-127: colour auto-change speed?
  python tools/laser_probe.py --preset line --sweep 12 --from 128 --to 191 --step 16 # CH12 128-191: line rainbow?
  python tools/laser_probe.py --preset line --sweep 10 --from 0 --to 255 --step 51   # CH10 "painting" speed?

  --address N     the laser's DMX start address (default 1, josh_rig.json / bar_rig.json's Laser L)
  --port DEV      the Enttec's serial node (default: auto-detect by FTDI VID)
  --dwell S       hold each sweep step S seconds instead of waiting for Enter
  --dry-run       NullLogBackend: print the frames, touch no hardware
  --no-log        don't append to docs/laser_findings.md

Every hold is appended to docs/laser_findings.md as a row (time, the 12
bytes, your note). The output is blacked out (all zeros, a dozen frames) on
every exit path, including Ctrl-C.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from livereact.core.frame_buffer import UNIVERSE_SIZE  # noqa: E402
from livereact.fixtures.profiles import Laser  # noqa: E402

FINDINGS = ROOT / "docs" / "laser_findings.md"
CHANNELS = 12
RATE_HZ = 40.0

# The 2026-09-06 verified combo ("success... this looks really good"), green
# because COLOR_GREEN is the one CH12 band spot-checked on hardware.
PRESETS: dict[str, dict[int, int]] = {
    "off": {},
    "line": {
        1: Laser.MANUAL_PATTERN_MODE, 2: Laser.PATTERN_A1_DOTTED_LINE, 3: Laser.PATTERN_A2_DEFAULT,
        7: Laser.SWEEP_SPEED_MIN, 9: Laser.SCALE_STATIC, 11: Laser.SCAN_DOTS, 12: Laser.COLOR_GREEN,
    },
}


class Frame:
    """The 12 laser bytes, rendered into a 512-byte universe at `address`."""

    def __init__(self, address: int) -> None:
        self.address = address
        self.values = [0] * CHANNELS
        self._lock = threading.Lock()

    def set(self, ch: int, value: int) -> None:
        if not 1 <= ch <= CHANNELS:
            raise SystemExit(f"channel {ch} is not 1-{CHANNELS}")
        with self._lock:
            self.values[ch - 1] = max(0, min(255, int(value)))

    def load(self, values: dict[int, int]) -> None:
        with self._lock:
            self.values = [0] * CHANNELS
        for ch, v in values.items():
            self.set(ch, v)

    def universe(self) -> bytes:
        with self._lock:
            uni = bytearray(UNIVERSE_SIZE)
            start = self.address - 1
            uni[start:start + CHANNELS] = bytes(self.values)
            return bytes(uni)

    def describe(self) -> str:
        with self._lock:
            return " ".join(f"CH{i + 1}={v}" for i, v in enumerate(self.values))

    def bytes_text(self) -> str:
        with self._lock:
            return ",".join(str(v) for v in self.values)


class Sender(threading.Thread):
    def __init__(self, backend, frame: Frame) -> None:
        super().__init__(name="laser-probe-sender", daemon=True)
        self.backend = backend
        self.frame = frame
        self.stop = threading.Event()

    def run(self) -> None:
        period = 1.0 / RATE_HZ
        while not self.stop.is_set():
            self.backend.send(self.frame.universe())
            time.sleep(period)


def blackout(backend) -> None:
    for _ in range(12):
        backend.send(bytes(UNIVERSE_SIZE))
        time.sleep(1.0 / RATE_HZ)


def log_row(frame: Frame, note: str, enabled: bool) -> None:
    if not enabled:
        return
    when = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    FINDINGS.parent.mkdir(parents=True, exist_ok=True)
    if not FINDINGS.exists():
        FINDINGS.write_text("# Laser channel findings\n\n| when | CH1..CH12 | note |\n|---|---|---|\n")
    with FINDINGS.open("a", encoding="utf-8") as fh:
        fh.write(f"| {when} | `{frame.bytes_text()}` | {note.replace('|', '/').strip() or '(no note)'} |\n")


def build_backend(args):
    if args.dry_run:
        from livereact.output.null_log import NullLogBackend
        return NullLogBackend(log_every=int(RATE_HZ))
    from livereact.output.enttec import EnttecSerialBackend
    return EnttecSerialBackend(port=args.port)


def confirm(args) -> None:
    if args.yes or args.dry_run:
        return
    print("BENCH ONLY: this bypasses every safety gate in the app (arm switch, mount-height check).")
    print("No crowd in the room, beam path confirmed safe, you are watching the unit?")
    if input("Type yes to open the Enttec: ").strip().lower() != "yes":
        raise SystemExit("aborted")


def hold(frame: Frame, label: str, args) -> None:
    """Hold the current frame: for --dwell seconds, or until Enter (the note
    typed before Enter goes to the findings log)."""
    print(f"\n{label}\n   {frame.describe()}")
    if args.dwell is not None:
        time.sleep(args.dwell)
        log_row(frame, args.note or f"held {args.dwell:.0f} s (no observation typed)", not args.no_log)
        return
    note = input("   what do you see? (type a note, Enter = next): ")
    log_row(frame, note, not args.no_log)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--address", type=int, default=1)
    ap.add_argument("--port", default=None)
    ap.add_argument("--preset", choices=sorted(PRESETS), default="line")
    ap.add_argument("--set", action="append", default=[], metavar="CH=V",
                    help="override one channel on top of the preset (repeatable)")
    ap.add_argument("--candidate", choices=sorted(Laser.PROBE_CANDIDATES), default=None,
                    help="hold one of Laser.PROBE_CANDIDATES on top of the preset (prints the file's claim)")
    ap.add_argument("--sweep", type=int, default=None, metavar="CH", help="step this channel through a range")
    ap.add_argument("--from", dest="start", type=int, default=0)
    ap.add_argument("--to", dest="end", type=int, default=255)
    ap.add_argument("--step", type=int, default=16)
    ap.add_argument("--seconds", type=float, default=None, help="plain hold length (no sweep); default: until Enter")
    ap.add_argument("--dwell", type=float, default=None, help="seconds per sweep step; default: until Enter")
    ap.add_argument("--note", default="", help="note for every logged row when not prompting")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-log", action="store_true")
    ap.add_argument("--yes", action="store_true", help="skip the bench-only confirmation")
    args = ap.parse_args()

    frame = Frame(args.address)
    frame.load(dict(PRESETS[args.preset]))
    for item in args.set:
        ch, _, v = item.partition("=")
        frame.set(int(ch), int(v))
    if args.candidate:
        ch, v, claim = Laser.PROBE_CANDIDATES[args.candidate]
        frame.set(ch, v)
        print(f"candidate {args.candidate}: CH{ch}={v} -- the file claims: {claim}")

    confirm(args)
    backend = build_backend(args)
    backend.open()
    sender = Sender(backend, frame)
    sender.start()
    try:
        if args.sweep is None:
            if args.seconds is not None:
                args.dwell = args.seconds
            hold(frame, f"HOLD preset={args.preset} address={args.address}", args)
        else:
            values = list(range(args.start, args.end + 1, max(1, args.step)))
            print(f"SWEEP CH{args.sweep} over {values} (everything else held from preset={args.preset})")
            for v in values:
                frame.set(args.sweep, v)
                hold(frame, f"CH{args.sweep} = {v}", args)
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        sender.stop.set()
        sender.join(timeout=1.0)
        blackout(backend)
        backend.close()
        print("blacked out, port closed." + ("" if args.no_log else f" Findings: {FINDINGS}"))


if __name__ == "__main__":
    main()
