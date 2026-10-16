"""Strobe calibration tool (livereact/strobe_cal.py): the search state
machine, the Hz math, the JSON merge, the frames it builds on Josh's rig, and
a scripted dry run through the CLI. No hardware, no real input()."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from livereact import strobe_cal
from livereact.__main__ import main
from livereact.core.frame_buffer import UNIVERSE_SIZE
from livereact.fixtures.profiles import ChannelKind, MovingHead, WashBar
from livereact.fixtures.rig import load_rig
from livereact.strobe_cal import (
    Reading,
    StrobeSearch,
    build_frame,
    derive,
    hz_from_count,
    hz_upper_from_count,
    merge_reading,
    summarize,
)

ROOT = Path(__file__).resolve().parents[1]
JOSH_RIG = str(ROOT / "rigs" / "josh_rig.json")


def run_search(curve, **kw) -> tuple[StrobeSearch, list[int]]:
    """Drive a search against a fake fixture whose Hz is curve(byte)."""
    s = StrobeSearch(**kw)
    seen: list[int] = []
    while (b := s.next_byte()) is not None:
        seen.append(b)
        s.record(b, curve(b))
        assert len(seen) < 100
    return s, seen


# --- Hz math ---

def test_hz_is_flashes_over_seconds():
    assert hz_from_count(12, 3.0) == 4.0
    assert hz_from_count(0, 3.0) == 0.0
    with pytest.raises(ValueError):
        hz_from_count(-1, 3.0)
    with pytest.raises(ValueError):
        hz_from_count(3, 0.0)


def test_upper_bound_assumes_one_missed_flash():
    assert hz_upper_from_count(11, 3.0) == pytest.approx(4.0)
    assert hz_upper_from_count(12, 3.0) == pytest.approx(13 / 3)
    assert hz_upper_from_count(0, 3.0) == pytest.approx(1 / 3)


def test_search_classifies_by_the_upper_bound():
    s = StrobeSearch()
    s.record(8, hz_from_count(11, 3.0), hz_upper_from_count(11, 3.0))   # 3.67, up to 4.0: safe
    assert (s.lo, s.hi, s.phase) == (8, None, "ascend")
    s.record(16, hz_from_count(12, 3.0), hz_upper_from_count(12, 3.0))  # 4.0 raw, up to 4.33: over
    assert (s.lo, s.hi, s.phase) == (8, 16, "bisect")
    s.record(12, hz_from_count(23, 3.0), hz_upper_from_count(23, 3.0))  # 7.67 raw, up to 8.0: abort
    assert s.over_absolute and s.done


# --- search state machine ---

def test_ascent_stops_at_first_reading_above_4hz():
    s, seen = run_search(lambda b: b / 10)          # 4.0 Hz at byte 40, 4.8 at 48
    ascent = seen[:seen.index(48) + 1]
    assert ascent == [8, 16, 24, 32, 40, 48]
    assert s.history[len(ascent) - 1] == (48, 4.8)
    assert all(b < 48 for b in seen[len(ascent):])  # only bisection below it after that


def test_bisection_converges_to_a_two_byte_bracket():
    s, seen = run_search(lambda b: b / 10.5)        # crosses 4 Hz between 42 and 43
    assert s.done
    assert s.hi - s.lo <= strobe_cal.BISECT_BRACKET
    assert s.lo <= 42 < s.hi
    assert "bracketed" in s.stop_reason


def test_bisection_with_one_byte_bracket_finds_the_exact_edge():
    s, _ = run_search(lambda b: b / 10.5, bracket=1)
    assert (s.lo, s.hi) == (42, 43)


def test_reading_at_or_above_8hz_aborts_with_no_bisection():
    s, seen = run_search(lambda b: 2.0 if b < 24 else 9.0)
    assert seen == [8, 16, 24]
    assert s.done and s.over_absolute
    assert s.next_byte() is None
    assert "8 Hz" in s.stop_reason


def test_8hz_during_bisection_also_stops():
    def curve(b):
        return 3.0 if b <= 40 else 12.0 if b == 44 else 5.0
    s, seen = run_search(curve)
    assert seen == [8, 16, 24, 32, 40, 48, 44]
    assert s.over_absolute


@pytest.mark.parametrize("curve", [
    lambda b: b / 10,
    lambda b: b / 3,                                # steep: 5.3 Hz at byte 16
    lambda b: 0.0 if b < 40 else b / 12,            # dead zone, then strobes
    lambda b: 5.0,                                  # over 4 Hz from the very first byte
    lambda b: (b % 17) / 3,                         # noisy, non-monotonic counts
    lambda b: 1.0,                                  # never passes 4 Hz
])
def test_no_byte_ever_exceeds_the_first_byte_over_4hz(curve):
    s, seen = run_search(curve)
    over = [b for b in seen if curve(b) > 4.0]
    if over:
        first_over = over[0]
        later = seen[seen.index(first_over) + 1:]
        assert all(b < first_over for b in later)
        assert max(seen) == first_over
    assert all(1 <= b <= 255 for b in seen)


def test_zero_flash_readings_keep_ascending():
    s, seen = run_search(lambda b: 0.0 if b < 40 else b / 10)
    assert seen[:6] == [8, 16, 24, 32, 40, 48]


def test_record_rejects_a_byte_the_search_did_not_ask_for():
    s = StrobeSearch()
    with pytest.raises(ValueError):
        s.record(200, 1.0)


def test_quit_ends_the_search():
    s = StrobeSearch()
    s.quit()
    assert s.done and s.next_byte() is None


# --- derived values + JSON merge ---

def _reading(dmx: int, flashes: int, seconds: float = 3.0) -> Reading:
    return Reading(dmx=dmx, flashes=flashes, seconds=seconds, hz=hz_from_count(flashes, seconds),
                   hz_upper=hz_upper_from_count(flashes, seconds), measured_at="2026-10-16T12:00:00")


def _row(dmx: int, flashes: int) -> dict:
    from dataclasses import asdict
    return asdict(_reading(dmx, flashes))


def test_derive_is_conservative_about_contradictory_readings():
    rows = [_row(40, 10), _row(48, 14), _row(56, 9)]
    d = derive(rows)
    assert d["max_dmx_at_or_below_4hz"] == 40       # 56's low reading sits above a > 4 Hz byte
    assert d["hz_at_max_dmx"] == pytest.approx(10 / 3, abs=1e-3)
    assert d["hz_upper_at_max_dmx"] == pytest.approx(11 / 3, abs=1e-3)
    assert d["max_hz_observed"] == pytest.approx(14 / 3, abs=1e-3)
    assert derive([])["max_dmx_at_or_below_4hz"] is None


def test_derive_only_counts_bytes_whose_upper_bound_is_at_most_4hz():
    # 12 flashes in 3 s is 4.0 Hz raw, but up to 4.33 Hz: NOT safe.
    d = derive([_row(8, 6), _row(16, 12)])
    assert d["max_dmx_at_or_below_4hz"] == 8
    assert d["max_hz_upper_observed"] == pytest.approx(13 / 3, abs=1e-3)
    # Rows without hz_upper (hand-edited, older) get it computed from flashes.
    assert derive([{"dmx": 16, "flashes": 12, "seconds": 3.0, "hz": 4.0}])["max_dmx_at_or_below_4hz"] is None


def test_merge_preserves_other_fixtures_and_appends():
    existing = {
        "shehds_180w_mh": {"mh": {"label": "Moving Head", "readings": [{"dmx": 8, "hz": 1.0}],
                                  "max_dmx_at_or_below_4hz": 8}},
        "ok103_wash_bar": {"bar_l": {"label": "Bar L", "readings": []}},
    }
    meta = dict(fixture_type="ok103_wash_bar", slot="bar", label="Wash Bar", address=69,
                strobe_channel=2, rig="rigs/josh_rig.json")
    out = merge_reading(existing, reading=_reading(8, 3), **meta)
    out = merge_reading(out, reading=_reading(16, 6), **meta)
    assert out["shehds_180w_mh"] == existing["shehds_180w_mh"]
    assert out["ok103_wash_bar"]["bar_l"] == existing["ok103_wash_bar"]["bar_l"]
    bar = out["ok103_wash_bar"]["bar"]
    assert [r["dmx"] for r in bar["readings"]] == [8, 16]
    assert bar["max_dmx_at_or_below_4hz"] == 16
    assert bar["rig"] == "rigs/josh_rig.json"
    assert "bar" not in existing["ok103_wash_bar"]   # input not mutated


def test_load_results_refuses_a_non_object(tmp_path):
    p = tmp_path / "strobe_calibration.json"
    p.write_text("[1, 2]")
    with pytest.raises(ValueError):
        strobe_cal.load_results(p)


# --- frames on Josh's real rig ---

def _laser_channels(rig) -> list[int]:
    return [i for i in range(UNIVERSE_SIZE) if rig.kind_at(i) == ChannelKind.LASER]


def _outside(fx, frame: bytes) -> list[int]:
    own = set(range(fx.offset, fx.offset + fx.channel_count))
    return [i for i, v in enumerate(frame) if v and i not in own]


def test_strobe_fixtures_on_josh_rig_are_the_bar_and_the_head():
    rig = load_rig(JOSH_RIG)
    assert [type(fx) for fx in strobe_cal.strobe_fixtures(rig)] == [MovingHead, WashBar]


def test_wash_bar_frame():
    rig = load_rig(JOSH_RIG)
    bar = rig.fixture("bar")
    assert _laser_channels(rig)                      # the rig does have a laser
    frame = build_frame(rig, bar, 40)
    o = bar.offset
    assert frame[o:o + 6] == bytes([WashBar.STROBE_BRIGHTNESS_CAP_DMX, 40, 0, 0, 0, 255])
    assert all(frame[i] == 0 for i in _laser_channels(rig))
    assert _outside(bar, frame) == []
    assert build_frame(rig, bar, None) == bytes(UNIVERSE_SIZE)


def test_moving_head_frame():
    rig = load_rig(JOSH_RIG)
    mh = rig.fixture("mh")
    frame = build_frame(rig, mh, 24)
    o = mh.offset
    assert frame[o + 6] == 24                        # ch7 strobe
    assert 150 <= frame[o + 5] <= WashBar.STROBE_BRIGHTNESS_CAP_DMX   # ch6 dimmer, lit but not full
    assert frame[o + 7] == 0                         # ch8 colour wheel: open / white
    boot = rig.boot_universe()
    assert frame[o:o + 5] == boot[o:o + 5]           # aim = boot_defaults pose, not raw centre
    assert frame[o + 2] == 80                        # tilt angled down
    assert frame[o + 12] == 0                        # ch13 macro off
    assert all(frame[i] == 0 for i in _laser_channels(rig))
    assert _outside(mh, frame) == []
    dark = build_frame(rig, mh, None)
    assert dark[o + 5] == 0 and dark[o + 6] == 0     # dark: dimmer and strobe off ...
    assert dark[o:o + 4] == frame[o:o + 4]           # ... and the head does not move


def test_every_strobe_byte_lands_exactly():
    rig = load_rig(JOSH_RIG)
    for fx in strobe_cal.strobe_fixtures(rig):
        for b in range(1, 256):
            frame = build_frame(rig, fx, b)
            assert frame[fx.offset + strobe_cal.strobe_channel(fx) - 1] == b


def test_frame_rejects_out_of_range_bytes():
    rig = load_rig(JOSH_RIG)
    with pytest.raises(ValueError):
        build_frame(rig, rig.fixture("bar"), 0)
    with pytest.raises(ValueError):
        build_frame(rig, rig.fixture("bar"), 256)


# --- the CLI, dry run, scripted input ---

class RecordingBackend:
    def __init__(self) -> None:
        self.frames: list[bytes] = []
        self.closed = False

    name = "recording"

    def open(self) -> None:
        pass

    def send(self, universe: bytes) -> None:
        self.frames.append(bytes(universe))

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def scripted(monkeypatch, tmp_path):
    """Run the CLI in tmp_path with no real waits; returns (backend, feed)."""
    monkeypatch.chdir(tmp_path)
    backend = RecordingBackend()
    monkeypatch.setattr(strobe_cal, "build_backend", lambda hardware: backend)
    monkeypatch.setattr(strobe_cal, "_sleep", lambda s: None)

    def feed(answers: list[str]) -> None:
        it = iter(answers)

        def fake_input(prompt: str = "") -> str:
            try:
                return next(it)
            except StopIteration:
                raise EOFError from None
        monkeypatch.setattr("builtins.input", fake_input)
    return backend, feed


def test_cli_dry_run_measures_saves_and_blacks_out(scripted, tmp_path):
    backend, feed = scripted
    # bar: 8 -> 3 flashes (1 Hz), 16 -> 15 flashes (5 Hz, over), then q at the bisection step.
    feed(["", "", "3", "", "15", "q"])
    rc = main(["--strobe-calibrate", "--rig", JOSH_RIG, "--strobe-fixture", "bar",
               "--log-level", "WARNING"])
    assert rc == 0
    assert backend.closed
    zero = bytes(UNIVERSE_SIZE)
    assert backend.frames[-strobe_cal.BLACKOUT_FRAMES:] == [zero] * strobe_cal.BLACKOUT_FRAMES
    rig = load_rig(JOSH_RIG)
    bar = rig.fixture("bar")
    lasers = _laser_channels(rig)
    strobe_i = bar.offset + 1
    lit = [f for f in backend.frames if f[strobe_i]]
    assert {f[strobe_i] for f in lit} == {8, 16}     # both steps really went out
    for f in lit:
        assert f[bar.offset:bar.offset + 6] == bytes(
            [WashBar.STROBE_BRIGHTNESS_CAP_DMX, f[strobe_i], 0, 0, 0, 255])
        assert _outside(bar, f) == []
    assert all(f[i] == 0 for f in backend.frames for i in lasers)

    data = json.loads((tmp_path / "strobe_calibration.json").read_text())
    entry = data["ok103_wash_bar"]["bar"]
    assert [(r["dmx"], r["flashes"], r["hz"]) for r in entry["readings"]] == [(8, 3, 1.0), (16, 15, 5.0)]
    assert [r["hz_upper"] for r in entry["readings"]] == [pytest.approx(4 / 3, abs=1e-3), pytest.approx(16 / 3, abs=1e-3)]
    assert entry["max_dmx_at_or_below_4hz"] == 8
    assert entry["max_hz_observed"] == 5.0


def test_cli_ctrl_c_mid_strobe_still_blacks_out(scripted, monkeypatch):
    backend, feed = scripted
    feed(["", ""])

    def boom(s: float) -> None:
        if s == 3.0:                                 # the strobe window, not the lead-in
            raise KeyboardInterrupt
    monkeypatch.setattr(strobe_cal, "_sleep", boom)
    rc = main(["--strobe-calibrate", "--rig", JOSH_RIG, "--strobe-fixture", "bar",
               "--log-level", "WARNING"])
    assert rc == 0
    bar = load_rig(JOSH_RIG).fixture("bar")
    assert any(f[bar.offset + 1] == 8 for f in backend.frames)   # it WAS strobing when interrupted
    zero = bytes(UNIVERSE_SIZE)
    assert backend.frames[-strobe_cal.BLACKOUT_FRAMES:] == [zero] * strobe_cal.BLACKOUT_FRAMES


def test_cli_exception_still_blacks_out(scripted, monkeypatch):
    backend, feed = scripted
    feed(["", "", "3"])
    monkeypatch.setattr(strobe_cal, "save_results", lambda p, d: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        main(["--strobe-calibrate", "--rig", JOSH_RIG, "--strobe-fixture", "bar",
              "--log-level", "WARNING"])
    zero = bytes(UNIVERSE_SIZE)
    assert backend.frames[-strobe_cal.BLACKOUT_FRAMES:] == [zero] * strobe_cal.BLACKOUT_FRAMES
    assert backend.closed


def test_cli_hardware_needs_typed_yes_before_opening(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    opened: list[bool] = []
    monkeypatch.setattr(strobe_cal, "build_backend", lambda hardware: opened.append(hardware))
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    rc = main(["--strobe-calibrate", "--hardware", "--rig", JOSH_RIG, "--log-level", "WARNING"])
    assert rc == 1
    assert opened == []


def test_cli_unknown_or_non_strobe_slot_is_refused(scripted):
    backend, feed = scripted
    feed([])
    for slot in ("nope", "laser", "par"):
        assert main(["--strobe-calibrate", "--rig", JOSH_RIG, "--strobe-fixture", slot,
                     "--log-level", "WARNING"]) == 2
    assert backend.frames == []


def test_cli_stray_key_at_the_strobe_prompt_does_not_strobe(scripted):
    backend, feed = scripted
    feed(["", "s", "x", "q"])                        # start fixture, two stray keys, quit
    assert main(["--strobe-calibrate", "--rig", JOSH_RIG, "--strobe-fixture", "bar",
                 "--log-level", "WARNING"]) == 0
    bar = load_rig(JOSH_RIG).fixture("bar")
    assert all(f[bar.offset + 1] == 0 for f in backend.frames)


def test_cli_suspiciously_low_count_must_be_typed_twice(scripted, tmp_path):
    backend, feed = scripted
    # 8 -> 9 flashes (3 Hz); 16 -> "1" (0.33 Hz, a likely typo) not confirmed, redo -> 10; then q.
    feed(["", "", "9", "", "1", "s", "", "10", "q"])
    assert main(["--strobe-calibrate", "--rig", JOSH_RIG, "--strobe-fixture", "bar",
                 "--log-level", "WARNING"]) == 0
    data = json.loads((tmp_path / "strobe_calibration.json").read_text())
    assert [r["flashes"] for r in data["ok103_wash_bar"]["bar"]["readings"]] == [9, 10]


# --- summary from the merged file ---

def test_summary_reads_the_file_and_gives_the_minimum_cap():
    rig = load_rig(JOSH_RIG)
    fixtures = strobe_cal.strobe_fixtures(rig)          # mh, bar
    meta = dict(address=1, strobe_channel=2, rig="r")
    data = merge_reading({}, fixture_type="ok103_wash_bar", slot="bar", label="Wash Bar",
                         reading=_reading(40, 9), **meta)
    lines = summarize(data, fixtures)
    assert "highest safe byte for Moving Head: none measured yet" in lines
    assert "highest safe byte for Wash Bar: 40 (3.0 Hz" in lines[1]
    assert "not possible yet" in lines[-1] and "Moving Head" in lines[-1]

    data = merge_reading(data, fixture_type="shehds_180w_mh", slot="mh", label="Moving Head",
                         reading=_reading(24, 6), **meta)
    lines = summarize(data, fixtures)
    assert lines[-1].endswith("byte 24 = strobe_cap 0.094")


def test_cap01_never_maps_above_the_byte():
    from livereact.fixtures.profiles import _to8
    for b in range(1, 256):
        assert _to8(strobe_cal._cap01(b)) <= b


# --- sender / shutdown robustness ---

def test_sender_flush_and_final_zero_frame():
    backend = RecordingBackend()
    sender = strobe_cal._Sender(backend)
    sender.start()
    lit = bytes([7] * UNIVERSE_SIZE)
    sender.set(lit)
    sender.flush()
    assert lit in backend.frames
    sender.stop.set()
    sender.wake()
    sender.join(timeout=1.0)
    assert backend.frames[-1] == bytes(UNIVERSE_SIZE)


def test_sender_failure_surfaces_in_flush():
    class Broken(RecordingBackend):
        def send(self, universe: bytes) -> None:
            raise OSError("unplugged")
    sender = strobe_cal._Sender(Broken())
    sender.start()
    sender.set(bytes([1] * UNIVERSE_SIZE))
    with pytest.raises(RuntimeError, match="DMX output failed"):
        sender.flush()


def test_stop_sender_survives_a_second_ctrl_c():
    calls: list[str] = []

    class Flaky(strobe_cal._Sender):
        def join(self, timeout=None):
            calls.append("join")
            if len(calls) == 1:
                raise KeyboardInterrupt
            super().join(timeout)

    backend = RecordingBackend()
    sender = Flaky(backend)
    sender.start()
    strobe_cal._stop_sender(sender)
    assert calls == ["join", "join"]
    assert not sender.is_alive()


def test_hardware_enttec_gets_a_write_timeout(monkeypatch):
    serial = pytest.importorskip("serial")
    from livereact.output import enttec

    class FakeSerial:
        def __init__(self, port, baudrate, timeout):
            self.port, self.write_timeout = port, None

        def close(self) -> None:
            pass

    monkeypatch.setattr(serial, "Serial", FakeSerial)
    monkeypatch.setattr(enttec, "select_enttec_port", lambda ports: "/dev/cu.fake")
    backend = strobe_cal.build_backend(True)
    backend.open()
    assert backend._serial.write_timeout == strobe_cal.WRITE_TIMEOUT_S
