"""Strobe calibration: measure a fixture's native strobe-byte -> Hz curve with
a phone's slow-motion video, and record the highest byte that stays at or
under 4 Hz.

``python -m livereact --strobe-calibrate [--hardware] [--rig R]
[--strobe-fixture SLOT] [--strobe-seconds S]`` runs this and exits, like
--fixture-test. Without --hardware it is a dry run on NullLogBackend (every
prompt, no light), so the procedure can be rehearsed with no rig attached.

Why it exists (2026-10-16): every AUTOMATED strobe in LiveReact is a
software dimmer toggle at a known Hz, capped at SAFETY_STROBE_SUSTAINED_MAX_HZ
(engines/reactive.py, the shared _StrobeClock). The one path whose Hz nobody
knows is the fixture's own strobe-rate byte (wash bar ch2, moving head ch7),
which the operator's manual STROBE BURST writes at ``ManualParams.strobe_cap``
(merge.py, ``apply_strobe_burst``). The fixture's oscillator has never been
measured, so SAFE-01/02/03 (sustained <= 4 Hz, never 10-25 Hz, absolute <=
8 Hz; spec/LIGHTING_BIBLE.md section 13) cannot be enforced on that path:
spec/conformance.md keeps them PARTIAL for exactly this reason. Section 11's
own method is "photodiode or high-speed camera at the fixture"; a phone's
240 fps slow-mo is the high-speed camera everybody has.

Search strategy (limits exposure to fast strobing): ascend through coarse
bytes 8, 16, 24, ... and stop at the FIRST byte measured above 4.0 Hz; then
bisect between the last byte <= 4 Hz and that one down to a 2-byte bracket.
No byte above the first > 4 Hz byte is ever commanded again. Any reading at
or above 8 Hz (SAFE-03's absolute ceiling) ends the search for that fixture
on the spot, no bisection. Every one of those decisions assumes the count
is one flash short ((flashes + 1) / seconds, see hz_upper_from_count): a
miscount of a slow-mo clip reads low, never high. The bytes come only from the search state
machine, never from typed input, so a typo can mis-record a reading but
cannot command a byte.

BENCH ONLY, like tools/laser_probe.py: this drives the Enttec directly, with
no App, no finalize() and no strobe cap in the loop. Every frame it builds
holds every channel outside the fixture under test at 0 (lasers included,
and laser channels are re-zeroed by kind as a second check). The output is
blacked out (all zeros, a dozen frames) on every exit path, including
exceptions and Ctrl-C.

Results go to ``strobe_calibration.json`` in the current working directory
(next to config.json), keyed by fixture type then rig slot, merged with
whatever earlier runs measured, and saved after every reading so a crash
loses nothing.

Follow-up, deliberately NOT in this change: applying the measured
``max_dmx_at_or_below_4hz`` as a hard clamp on the manual burst
(``strobe_cap`` in merge.py's finalize). Until that lands, the measurement
only informs a human choosing ``strobe_cap``; the live show is unchanged.
"""

from __future__ import annotations

import copy
import datetime as _dt
import json
import math
import os
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from .core.frame_buffer import UNIVERSE_SIZE
from .engines.reactive import SAFETY_STROBE_ABSOLUTE_MAX_HZ, SAFETY_STROBE_SUSTAINED_MAX_HZ
from .fixtures.profiles import Buffer, ChannelKind, Fixture, MovingHead, WashBar
from .fixtures.rig import Rig, load_rig
from .output.enttec import EnttecSerialBackend

OUTPUT_FILE = "strobe_calibration.json"
RATE_HZ = 40.0              # same cadence as the show's DMX writer
BLACKOUT_FRAMES = 12        # same as tools/laser_probe.py
LEAD_IN_S = 1.0             # dark before each strobe window, so the clip has a clear start
FLUSH_TIMEOUT_S = 1.0       # a frame not on the wire within this is a stalled sender: abort
# Serial write timeout for this tool's Enttec (review, 2026-10-16). The show's
# EnttecSerialBackend opens with no write_timeout, so a wedged USB write
# blocks forever; here that would freeze the sender with a strobe frame as
# the Enttec's last one (it keeps repeating it). One 518-byte frame takes
# well under a millisecond on USB, so 0.5 s only ever trips on a real fault.
WRITE_TIMEOUT_S = 0.5

# Coarse ascent. 8 is the first step: the manuals we have only say "1-255
# slow -> fast (up to 25 Hz)", so if the curve were linear one coarse step is
# roughly 0.8 Hz, small enough not to jump from under 4 Hz straight past 8 Hz.
COARSE_START = 8
COARSE_STEP = 8
# Bisection stops when the last byte <= 4 Hz and the first byte > 4 Hz are
# this close. 2, not 1: with a 3 s window one miscounted flash is +-0.33 Hz,
# so the last byte of precision would be noise bought with extra exposure.
BISECT_BRACKET = 2

SECONDS_MIN = 1.0           # shorter windows make one miscounted flash a large Hz error
SECONDS_MAX = 10.0          # longer windows only add exposure

# Moving-head dimmer during the strobe window: 0.85 maps to DMX ~178 on the
# gamma curve (profiles._intensity_to8), just under the wash bar's 180 strobe
# brightness cap (WashBar.STROBE_BRIGHTNESS_CAP_DMX, Josh's 2026-09-15 call),
# so both fixtures are filmed at about the same strobe brightness. The head
# has no cap_brightness_while_strobing of its own.
HEAD_DIMMER_LEVEL = 0.85


# --------------------------------------------------------------------------
# Pure logic: Hz math, the search state machine, the JSON merge. No I/O.
# --------------------------------------------------------------------------

def hz_from_count(flashes: int, seconds: float) -> float:
    """Flashes counted in the clip over the strobe window length."""
    if flashes < 0:
        raise ValueError("flash count cannot be negative")
    if seconds <= 0:
        raise ValueError("seconds must be positive")
    return flashes / seconds


def hz_upper_from_count(flashes: int, seconds: float) -> float:
    """The rate if the count is one flash short: (flashes + 1) / seconds.
    Every safe/unsafe decision uses this, not the raw rate (review,
    2026-10-16): a flash cut off at either edge of the window, or simply
    missed while counting a slow-mo clip, is the expected error, and it
    always reads LOW. With a 3 s window, 12 flashes (4.0 Hz raw) is
    therefore treated as over 4 Hz."""
    return hz_from_count(flashes, seconds) + 1.0 / seconds


class StrobeSearch:
    """Ascend-then-bisect search for the highest strobe byte at or under
    ``sustained_max_hz``. Call ``next_byte()`` for the byte to command, then
    ``record(byte, hz, hz_upper)`` with what was measured; ``None`` from
    next_byte means the search is over (``stop_reason`` says why). Bytes are
    classified by ``hz_upper`` (the one-missed-flash bound, see
    hz_upper_from_count) when it is given, else by ``hz``.

    Invariant (the safety point of the whole tool): once a byte has measured
    above ``sustained_max_hz``, ``next_byte()`` never returns that byte or
    anything above it. ``ceiling`` is that limit (255 until it is known)."""

    def __init__(self, *, start: int = COARSE_START, step: int = COARSE_STEP,
                 bracket: int = BISECT_BRACKET,
                 sustained_max_hz: float = SAFETY_STROBE_SUSTAINED_MAX_HZ,
                 absolute_max_hz: float = SAFETY_STROBE_ABSOLUTE_MAX_HZ) -> None:
        if not 1 <= start <= 255:
            raise ValueError("start must be a strobing byte, 1-255")
        if step < 1 or bracket < 1:
            raise ValueError("step and bracket must be >= 1")
        self.step = step
        self.bracket = bracket
        self.sustained_max_hz = sustained_max_hz
        self.absolute_max_hz = absolute_max_hz
        self.phase = "ascend"          # "ascend" -> "bisect" -> "done"
        self.lo = 0                    # highest byte measured <= sustained (0 = strobe off)
        self.hi: int | None = None     # lowest byte measured > sustained
        self.over_absolute = False     # a reading hit the absolute ceiling
        self.stop_reason = ""
        self.history: list[tuple[int, float]] = []
        self._pending: int | None = start

    @property
    def done(self) -> bool:
        return self.phase == "done"

    @property
    def ceiling(self) -> int:
        """Highest byte this search may still command."""
        return 255 if self.hi is None else self.hi - 1

    def next_byte(self) -> int | None:
        return None if self.done else self._pending

    def quit(self, reason: str = "operator finished early (q)") -> None:
        self._finish(reason)

    def record(self, byte: int, hz: float, hz_upper: float | None = None) -> None:
        if self.done:
            raise RuntimeError("search is already finished")
        if byte != self._pending:
            raise ValueError(f"recorded byte {byte}, but the search asked for {self._pending}")
        if hz < 0:
            raise ValueError("hz cannot be negative")
        bound = hz if hz_upper is None else hz_upper
        if bound < hz:
            raise ValueError("hz_upper cannot be below hz")
        self.history.append((byte, bound))
        if bound > self.sustained_max_hz:
            self.hi = byte if self.hi is None else min(self.hi, byte)
            if bound >= self.absolute_max_hz:
                self.over_absolute = True
                self._finish(f"up to {bound:.1f} Hz at byte {byte} is at or above the "
                             f"{self.absolute_max_hz:.0f} Hz absolute ceiling (SAFE-03): "
                             f"stopped here, no bisection")
                return
            self.phase = "bisect"
        else:
            self.lo = max(self.lo, byte)

        if self.phase == "ascend":
            if byte >= 255:
                self._finish("reached byte 255 without passing "
                             f"{self.sustained_max_hz:.1f} Hz")
                return
            self._pending = min(255, byte + self.step)
            return
        assert self.hi is not None
        if self.hi - self.lo <= self.bracket:
            self._finish(f"bracketed: byte {self.lo} <= {self.sustained_max_hz:.1f} Hz, "
                         f"byte {self.hi} > {self.sustained_max_hz:.1f} Hz")
            return
        self._pending = (self.lo + self.hi) // 2

    def _finish(self, reason: str) -> None:
        self.phase = "done"
        self._pending = None
        self.stop_reason = reason


@dataclass(frozen=True)
class Reading:
    dmx: int
    flashes: int
    seconds: float
    hz: float           # raw: flashes / seconds
    hz_upper: float     # (flashes + 1) / seconds, what every decision uses
    measured_at: str


def _upper(r: dict) -> float:
    """A stored reading's one-missed-flash bound (computed if the row
    predates the hz_upper field)."""
    if "hz_upper" in r:
        return r["hz_upper"]
    if "flashes" in r and r.get("seconds"):
        return hz_upper_from_count(r["flashes"], r["seconds"])
    return r["hz"]


def derive(readings: list[dict], sustained_max_hz: float = SAFETY_STROBE_SUSTAINED_MAX_HZ) -> dict:
    """The derived fields for one slot, over every reading it has (all runs).

    Classified by each reading's one-missed-flash upper bound, never the raw
    rate. ``max_dmx_at_or_below_4hz`` is also conservative against noisy or
    contradictory data: the highest byte whose upper bound is <= 4 Hz that
    is ALSO below the lowest byte whose upper bound was ever > 4 Hz. None
    when no such byte was measured."""
    over = [r["dmx"] for r in readings if _upper(r) > sustained_max_hz]
    limit = min(over) if over else 256
    safe = [r for r in readings if _upper(r) <= sustained_max_hz and r["dmx"] < limit]
    best = max(safe, key=lambda r: r["dmx"]) if safe else None
    # The same byte can be measured twice (across runs); report its worst.
    at_best = [r for r in safe if best and r["dmx"] == best["dmx"]]
    return {
        "max_dmx_at_or_below_4hz": best["dmx"] if best else None,
        "hz_at_max_dmx": round(max(r["hz"] for r in at_best), 3) if at_best else None,
        "hz_upper_at_max_dmx": round(max(_upper(r) for r in at_best), 3) if at_best else None,
        "max_hz_observed": round(max(r["hz"] for r in readings), 3) if readings else None,
        "max_hz_upper_observed": round(max(_upper(r) for r in readings), 3) if readings else None,
    }


def merge_reading(data: dict, *, fixture_type: str, slot: str, label: str, address: int,
                  strobe_channel: int, rig: str, reading: Reading) -> dict:
    """Return a copy of ``data`` (the whole strobe_calibration.json) with
    ``reading`` appended under fixture_type -> slot and the derived fields
    recomputed. Other fixture types and slots are left exactly as they were."""
    out = copy.deepcopy(data)
    entry = out.setdefault(fixture_type, {}).setdefault(slot, {})
    entry["label"] = label
    entry["dmx_address"] = address
    entry["strobe_channel_local"] = strobe_channel
    entry["rig"] = rig
    readings = entry.setdefault("readings", [])
    readings.append(asdict(reading))
    entry.update(derive(readings))
    return out


def load_results(path: Path) -> dict:
    """Read an existing results file. Refuses (ValueError) anything that isn't
    a JSON object, so a damaged file is never silently overwritten."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def save_results(path: Path, data: dict) -> None:
    """Atomic write (temp file + replace): a crash mid-write can't truncate
    earlier measurements."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# --------------------------------------------------------------------------
# Frames: built through the fixture profiles' own setters.
# --------------------------------------------------------------------------

class _UniBuffer(Buffer):
    def __init__(self, uni: bytearray) -> None:
        self.uni = uni

    def set(self, channel_1based: int, value: int) -> None:
        self.uni[channel_1based - 1] = 0 if value < 0 else 255 if value > 255 else int(value)


def strobe_fixtures(rig: Rig) -> list[Fixture]:
    """Every fixture with a native strobe channel, in rig order."""
    return [fx for fx in rig.fixtures if ChannelKind.STROBE in fx.channel_kinds()]


def strobe_channel(fx: Fixture) -> int:
    """The fixture's strobe channel, 1-based local (wash bar 2, head 7), read
    from the profile's channel_kinds() rather than hard-coded here."""
    return fx.channel_kinds().index(ChannelKind.STROBE) + 1


def build_frame(rig: Rig, fx: Fixture, strobe_byte: int | None) -> bytes:
    """One 512-byte universe for calibrating ``fx``.

    ``strobe_byte=None`` is the DARK frame: dimmer and strobe 0 (a moving
    head keeps the same aim so it never moves between steps).
    Otherwise the fixture is lit in a fixed, known way with its strobe
    channel at exactly ``strobe_byte`` (1-255):
      - wash bar: white full, RGB 0, dimmer at WashBar.STROBE_BRIGHTNESS_CAP_DMX
        (set full, then the profile's own cap_brightness_while_strobing);
      - moving head: open/white wheel, HEAD_DIMMER_LEVEL, aimed at its own
        boot_defaults pose (pan centre, tilt angled down). Not a raw 0.5/0.5
        set_position (review, 2026-10-16): raw centre tilt is wherever 128
        lands on this unit, possibly level into the room; boot_defaults'
        tilt is the pose the show itself powers up in.
    Every channel outside ``fx`` is 0, and every LASER channel in the rig is
    forced to 0 again by kind, whatever happened above."""
    if strobe_byte is not None and not 1 <= strobe_byte <= 255:
        raise ValueError(f"strobe byte {strobe_byte} is not 1-255")
    uni = bytearray(UNIVERSE_SIZE)
    buf = _UniBuffer(uni)
    if isinstance(fx, WashBar):
        fx.boot_defaults(buf)   # all six channels 0
        if strobe_byte is not None:
            fx.set_color(buf, 0.0, 0.0, 0.0, w=1.0)
            fx.set_intensity(buf, 1.0)
            fx.set_strobe(buf, strobe_byte / 255)
            fx.cap_brightness_while_strobing(uni)
    elif isinstance(fx, MovingHead):
        fx.boot_defaults(buf)   # pan centre, tilt angled down, dimmer 0, macro 0, speed mid
        if strobe_byte is not None:
            fx.set_color(buf, 1.0, 1.0, 1.0)   # wheel slot 0: open / white
            fx.set_intensity(buf, HEAD_DIMMER_LEVEL)
            fx.set_strobe(buf, strobe_byte / 255)
    else:
        raise ValueError(f"{fx.label}: no calibration lighting recipe for {fx.type_name}")

    # Only the fixture under test may be nonzero.
    out = bytearray(UNIVERSE_SIZE)
    out[fx.offset:fx.offset + fx.channel_count] = uni[fx.offset:fx.offset + fx.channel_count]
    for i in range(UNIVERSE_SIZE):
        if rig.kind_at(i) == ChannelKind.LASER:
            out[i] = 0
    # The profile's own float mapping must land on exactly the byte asked for.
    want = strobe_byte or 0
    got = out[fx.offset + strobe_channel(fx) - 1]
    if got != want:
        raise RuntimeError(f"{fx.label}: strobe channel is {got}, expected {want}")
    return bytes(out)


def describe_frame(frame: bytes) -> str:
    on = [f"ch{i + 1}={v}" for i, v in enumerate(frame) if v]
    return " ".join(on) if on else "(all zero)"


# --------------------------------------------------------------------------
# I/O: the DMX sender thread and the interactive session.
# --------------------------------------------------------------------------

def _sleep(seconds: float) -> None:
    """Indirection so tests can run the session without real waits."""
    time.sleep(seconds)


def build_backend(hardware: bool):
    """Enttec when --hardware, else NullLogBackend. No silent fallback to the
    null backend in hardware mode (unlike --fixture-test): an operator
    filming a fixture that never lights would record nonsense."""
    if hardware:
        return _BoundedEnttec()
    from .output.null_log import NullLogBackend
    # One log line a minute, not a second: the per-step frame printout is the
    # dry run's real output, and the log chatter would bury the prompts.
    return NullLogBackend(log_every=int(RATE_HZ * 60))


class _BoundedEnttec(EnttecSerialBackend):
    """The show's Enttec backend, opened with WRITE_TIMEOUT_S so a wedged
    write raises (and the sender reports it) instead of blocking forever.
    A subclass here, not a change to output/enttec.py: the show's DMX
    output path is untouched by this tool."""

    def open(self) -> None:
        super().open()
        try:
            self._serial.write_timeout = WRITE_TIMEOUT_S
        except Exception:
            self.close()
            raise


class _Sender(threading.Thread):
    """Resends the current universe at RATE_HZ, and immediately on a change.
    ``flush()`` blocks until the latest ``set()`` frame is really on the
    wire, so the strobe window is timed from when the fixture got the byte
    (and tests see every frame the session set). A send failure is kept in
    ``error`` and stops the thread; flush()/check() raise it (an Enttec
    keeps repeating its last frame, so a dead sender must not go
    unnoticed). On exit, for any reason, it tries one all-zero frame."""

    def __init__(self, backend) -> None:
        super().__init__(name="strobe-cal-sender", daemon=True)
        self.backend = backend
        self.stop = threading.Event()
        self.error: BaseException | None = None
        self._changed = threading.Event()
        self._cond = threading.Condition()
        self._frame = bytes(UNIVERSE_SIZE)
        self._gen = 0           # bumped by every set()
        self._sent_gen = 0      # the generation of the last frame actually sent

    def set(self, frame: bytes) -> None:
        with self._cond:
            self._frame = bytes(frame)
            self._gen += 1
        self._changed.set()

    def check(self) -> None:
        if self.error is not None:
            raise RuntimeError(f"DMX output failed: {self.error!r}") from self.error

    def flush(self, timeout: float = FLUSH_TIMEOUT_S) -> None:
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._sent_gen < self._gen and self.error is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self.is_alive():
                    raise RuntimeError("DMX sender stalled: frame not sent")
                self._cond.wait(min(remaining, 0.05))
        self.check()

    def wake(self) -> None:
        self._changed.set()

    def run(self) -> None:
        period = 1.0 / RATE_HZ
        try:
            while not self.stop.is_set():
                with self._cond:
                    frame, gen = self._frame, self._gen
                try:
                    self.backend.send(frame)
                except BaseException as exc:  # noqa: BLE001 - reported via flush()/check()
                    with self._cond:
                        self.error = exc
                        self._cond.notify_all()
                    return
                with self._cond:
                    self._sent_gen = gen
                    self._cond.notify_all()
                self._changed.wait(period)
                self._changed.clear()
        finally:
            try:
                self.backend.send(bytes(UNIVERSE_SIZE))
            except BaseException:  # noqa: BLE001 - blackout() reports output failures
                pass


def _stop_sender(sender: _Sender) -> None:
    """Zero the frame, stop and join the sender. Retried if a second Ctrl-C
    lands mid-way, so the caller always reaches blackout()."""
    for _ in range(5):
        try:
            sender.set(bytes(UNIVERSE_SIZE))
            sender.stop.set()
            sender.wake()
            sender.join(timeout=1.0)
            return
        except KeyboardInterrupt:
            continue


def blackout(backend, print_fn: Callable[[str], None] = print) -> bool:
    """All zeros for BLACKOUT_FRAMES frames. Returns False (and says so
    loudly) if the port would not take them. A second Ctrl-C (an operator
    hammering it while something strobes) must not cut the blackout short,
    so KeyboardInterrupt is swallowed here: we are exiting anyway."""
    try:
        for _ in range(BLACKOUT_FRAMES):
            try:
                backend.send(bytes(UNIVERSE_SIZE))
                time.sleep(1.0 / RATE_HZ)
            except KeyboardInterrupt:
                continue
        return True
    except Exception as exc:  # noqa: BLE001
        print_fn(f"\n!!! COULD NOT BLACK OUT ({exc!r}). The fixture may still be strobing:\n"
                 f"!!! power it off or pull its DMX cable NOW.")
        return False


WARNING = """\
==========================================================================
 PHOTOSENSITIVITY WARNING: STROBE CALIBRATION
==========================================================================
 This tool makes a fixture strobe, a few seconds at a time, at rates up to
 about 4-8 flashes per second, to film it in slow motion.

  - BENCH ONLY. No audience, no show running.
  - Nobody in the room who could be affected by flashing light
    (photosensitive epilepsy, migraine). Film it, don't stare at it.
  - It drives the Enttec directly: no show safety layer in the loop.
    Lasers and every other fixture are held at 0 the whole time.
  - Stop at any time: type q at any prompt, or press Ctrl-C.
    Every exit blacks the universe out.
=========================================================================="""

HOW_TO = """\
How it works: for each step the tool names a strobe byte. Start the phone's
slow-mo video (240 fps, phone on a stand, fixture in frame), press Enter,
it goes dark for {lead:.0f} s, strobes for {secs:g} s, then dark again. Stop the
video, count the flashes in the clip, and type the number.
  0  = it did not flash (steady or off)
  s  = redo this step (missed the clip, lost count)
  q  = finish now (everything measured so far is already saved)"""


@dataclass
class _FixtureResult:
    label: str
    search: StrobeSearch
    readings: list[Reading]
    quit: bool = False
    skipped: bool = False


class _Session:
    def __init__(self, rig: Rig, rig_label: str, sender: _Sender, seconds: float,
                 out_path: Path, input_fn: Callable[[str], str],
                 print_fn: Callable[[str], None]) -> None:
        self.rig = rig
        self.rig_label = rig_label
        self.sender = sender
        self.seconds = seconds
        self.out_path = out_path
        self.input_fn = input_fn
        self.print = print_fn

    def ask(self, prompt: str) -> str:
        try:
            return self.input_fn(prompt).strip().lower()
        except EOFError:
            return "q"

    def ask_choice(self, prompt: str, choices: tuple[str, ...]) -> str:
        """Re-prompt until the answer is one of ``choices`` ("" = Enter). Strict
        on purpose: a stray key at a "press Enter to strobe" prompt must not
        start a strobe."""
        while True:
            ans = self.ask(prompt)
            if ans in choices:
                return ans
            shown = ", ".join("Enter" if c == "" else c for c in choices)
            self.print(f"   please answer {shown}")

    def ask_count(self) -> int | str:
        while True:
            ans = self.ask("   flashes counted in the clip (number, s = redo, q = finish): ")
            if ans in ("s", "q"):
                return ans
            if ans.isdigit():
                return int(ans)
            self.print("   please type a whole number (0 if it did not flash), s or q")

    def confirm_odd_reading(self, byte: int, count: int, hz: float, history: list[Reading]) -> bool:
        """A count well below what a LOWER byte measured is most likely a
        typo, and a too-low typo is the one that lets the ascent climb, so it
        has to be typed twice. Returns False to redo the step."""
        slower = [r for r in history if r.dmx < byte and r.hz > hz + 1.0]
        if not slower:
            return True
        worst = max(slower, key=lambda r: r.hz)
        self.print(f"   that is {hz:.2f} Hz, slower than byte {worst.dmx} ({worst.hz:.2f} Hz).")
        again = self.ask("   type the same count again to keep it, or s to redo: ")
        if again.isdigit() and int(again) == count:
            return True
        self.print("   not confirmed: redoing this step.")
        return False

    def table(self, readings: list[Reading]) -> None:
        self.print("   byte  flashes  seconds     Hz  up to Hz")
        for r in sorted(readings, key=lambda r: r.dmx):
            mark = "  > 4 Hz" if r.hz_upper > SAFETY_STROBE_SUSTAINED_MAX_HZ else ""
            self.print(f"   {r.dmx:4d}  {r.flashes:7d}  {r.seconds:7.2f}  {r.hz:5.2f}  {r.hz_upper:8.2f}{mark}")

    def calibrate(self, fx: Fixture) -> _FixtureResult:
        slot = getattr(fx, "slot_id", fx.label)
        ch = strobe_channel(fx)
        search = StrobeSearch()
        result = _FixtureResult(fx.label, search, [])
        dark = build_frame(self.rig, fx, None)
        self.sender.set(dark)
        self.print(f"\n=== {fx.label} (slot {slot}, {fx.type_name}, address {fx.address}, "
                   f"strobe = channel {fx.address + ch - 1}) ===")
        ans = self.ask_choice("Press Enter to start this fixture, n = skip it, q = finish: ", ("", "n", "q"))
        if ans == "q":
            search.quit()
            result.quit = True
            return result
        if ans == "n":
            search.quit("skipped by operator (n)")
            result.skipped = True
            return result

        step = 0
        while (byte := search.next_byte()) is not None:
            # Belt and braces: the state machine already guarantees this.
            if byte > search.ceiling:
                raise RuntimeError(f"refusing byte {byte}: above the measured ceiling {search.ceiling}")
            step += 1
            lit = build_frame(self.rig, fx, byte)
            self.print(f"\nStep {step} ({search.phase}): {fx.label}, strobe byte {byte}")
            self.print(f"   frame while strobing: {describe_frame(lit)}")
            ans = self.ask_choice("   start the slow-mo video, then press Enter (q = finish): ", ("", "q"))
            if ans == "q":
                search.quit()
                result.quit = True
                return result

            self.sender.set(dark)
            self.sender.flush()
            _sleep(LEAD_IN_S)
            self.sender.set(lit)
            try:
                self.sender.flush()
                self.print(f"   STROBING byte {byte} for {self.seconds:g} s ...")
                _sleep(self.seconds)
            finally:
                self.sender.set(dark)
            self.sender.flush()
            self.print("   dark. Stop the video and count the flashes.")

            count = self.ask_count()
            if count == "s":
                continue
            if count == "q":
                search.quit()
                result.quit = True
                return result
            assert isinstance(count, int)
            hz = hz_from_count(count, self.seconds)
            hz_up = hz_upper_from_count(count, self.seconds)
            if not self.confirm_odd_reading(byte, count, hz, result.readings):
                continue
            reading = Reading(dmx=byte, flashes=count, seconds=self.seconds, hz=round(hz, 3),
                              hz_upper=round(hz_up, 3),
                              measured_at=_dt.datetime.now().isoformat(timespec="seconds"))
            result.readings.append(reading)
            search.record(byte, hz, hz_up)
            data = load_results(self.out_path)
            save_results(self.out_path, merge_reading(
                data, fixture_type=fx.type_name, slot=slot, label=fx.label, address=fx.address,
                strobe_channel=ch, rig=self.rig_label, reading=reading))
            self.print(f"   {count} flashes / {self.seconds:g} s = {hz:.2f} Hz, "
                       f"up to {hz_up:.2f} Hz if one flash was missed (saved)")
            self.table(result.readings)
            if search.over_absolute:
                self.print(f"\n!!! up to {hz_up:.1f} Hz is at or above {SAFETY_STROBE_ABSOLUTE_MAX_HZ:.0f} Hz. "
                           f"Stopping this fixture now; nothing higher will be tested.")
        self.print(f"   search finished: {search.stop_reason}")
        return result


def _cap01(byte: int) -> float:
    """``strobe_cap`` (0..1) for a byte, rounded DOWN to 3 decimals so it
    can never map back above the byte."""
    return math.floor(byte / 255 * 1000) / 1000


def summarize(data: dict, fixtures: list[Fixture]) -> list[str]:
    """Summary lines from the MERGED results file (every run so far), one
    per strobe fixture, then the single strobe_cap they imply. ManualParams
    has ONE strobe_cap for every fixture, so it must be the minimum of the
    per-fixture safe bytes, and none can be given while any fixture lacks one."""
    lines: list[str] = []
    safe: dict[str, int | None] = {}
    for fx in fixtures:
        entry = data.get(fx.type_name, {}).get(getattr(fx, "slot_id", fx.label))
        n = entry.get("max_dmx_at_or_below_4hz") if entry else None
        safe[fx.label] = n
        if n is None:
            lines.append(f"highest safe byte for {fx.label}: none measured yet")
        else:
            lines.append(f"highest safe byte for {fx.label}: {n} ({entry['hz_at_max_dmx']:.1f} Hz, "
                         f"at most {entry['hz_upper_at_max_dmx']:.1f} Hz allowing one missed flash)")
    missing = [label for label, n in safe.items() if n is None]
    if missing:
        lines.append("strobe_cap: one cap covers every strobe fixture, so it must be the minimum "
                     f"across them; not possible yet, no safe byte for: {', '.join(missing)}")
    elif safe:
        low = min(v for v in safe.values() if v is not None)
        lines.append(f"strobe_cap: one cap covers every strobe fixture, so use the minimum: "
                     f"byte {low} = strobe_cap {_cap01(low):.3f}")
    return lines


def run_strobe_calibration(*, rig_path: str | None, hardware: bool, slot: str | None = None,
                           seconds: float = 3.0, out_path: Path | None = None,
                           input_fn: Callable[[str], str] | None = None,
                           print_fn: Callable[[str], None] = print) -> int:
    """The --strobe-calibrate tool. Returns a process exit code."""
    if input_fn is None:
        input_fn = lambda prompt: input(prompt)  # noqa: E731 - looked up per call (tests patch builtins.input)
    out_path = Path(out_path) if out_path is not None else Path.cwd() / OUTPUT_FILE
    if not SECONDS_MIN <= seconds <= SECONDS_MAX:
        print_fn(f"--strobe-seconds must be {SECONDS_MIN:g}-{SECONDS_MAX:g}, got {seconds:g}")
        return 2
    rig = load_rig(rig_path)
    rig_label = rig_path or "(packaged default_rig.json)"
    candidates = strobe_fixtures(rig)
    if slot is not None:
        chosen = [fx for fx in candidates if getattr(fx, "slot_id", fx.label) == slot]
        if not chosen:
            names = ", ".join(getattr(fx, "slot_id", fx.label) for fx in candidates) or "none"
            print_fn(f"slot {slot!r} is not a fixture with a native strobe channel in this rig "
                     f"(strobe fixtures: {names})")
            return 2
    else:
        chosen = candidates
    if not chosen:
        print_fn("this rig has no fixture with a native strobe channel; nothing to calibrate")
        return 2
    try:
        load_results(out_path)   # fail now, before anything lights, if the file is damaged
    except (ValueError, OSError) as exc:
        print_fn(f"cannot use {out_path}: {exc}. Move it aside and run again.")
        return 2

    print_fn(WARNING)
    print_fn(f"\nRig: {rig.name} ({rig_label})")
    print_fn("Fixtures, one at a time: " + ", ".join(
        f"{fx.label} [{getattr(fx, 'slot_id', fx.label)}]" for fx in chosen))
    print_fn(f"Results: {out_path}")
    print_fn(HOW_TO.format(lead=LEAD_IN_S, secs=seconds))
    if hardware:
        try:
            ans = input_fn("\nType yes to open the Enttec and start: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = ""
        if ans != "yes":
            print_fn("aborted, the port was never opened.")
            return 1
    else:
        print_fn("\nDRY RUN (no --hardware): frames go to the null backend, nothing lights.")

    backend = build_backend(hardware)
    try:
        backend.open()
    except Exception as exc:  # noqa: BLE001
        print_fn(f"could not open the DMX output: {exc}")
        return 1
    sender = _Sender(backend)
    sender.start()
    clean = True
    try:
        for fx in chosen:
            res = _Session(rig, rig_label, sender, seconds, out_path, input_fn, print_fn).calibrate(fx)
            sender.set(bytes(UNIVERSE_SIZE))
            if res.quit:
                break
    except KeyboardInterrupt:
        print_fn("\ninterrupted (Ctrl-C)")
    except BaseException:
        clean = False
        raise
    finally:
        _stop_sender(sender)
        ok = blackout(backend, print_fn)
        try:
            backend.close()
        except (Exception, KeyboardInterrupt):  # noqa: BLE001
            pass
        print_fn("blacked out, port closed." if ok else "port closed (blackout FAILED, see above).")
        if clean:
            print_fn("\n=== Summary (every run in the results file) ===")
            try:
                for line in summarize(load_results(out_path), candidates):
                    print_fn(line)
            except (ValueError, OSError) as exc:
                print_fn(f"could not read {out_path} back: {exc}")
            print_fn(f"Saved to {out_path}. Send that file back.")
    return 0
