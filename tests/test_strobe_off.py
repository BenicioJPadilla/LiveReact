"""Strobe off is a hard stop for EVERY strobe, the automatic one included
(2026-10-17, photosensitivity safety).

The bug: the phone's "Strobe off" only lowered ``strobe_cap``, which caps the
fixtures' own strobe channels in finalize. The automatic strobe never uses
those: it toggles the wash/par DIMMER (engines/reactive.py's _StrobeClock),
so it kept flashing after someone on the floor had switched strobe off.

These tests drive the scripted golden-frames song (tests/golden_frames.py:
a build the DJ arms, a drop, a peak) through the real pipeline, where the
automatic strobe demonstrably fires, and prove that with strobe off it never
does: not at the start, not after a phone reconnect or an audio dropout, and
not after a restart (config.json or the crash supervisor's live state).
"""

from __future__ import annotations

import json

import pytest

import golden_frames as gf
from livereact import config as app_config
from livereact import supervisor
from livereact.app import App, AppConfig
from livereact.clock import FakeClock
from livereact.core.frame_buffer import UNIVERSE_SIZE
from livereact.core.show_state import ShowSnapshot
from livereact.engines.reactive import STROBE_MAX, ReactiveLayerEngine
from livereact.fixtures.profiles import ChannelKind
from livereact.fixtures.rig import load_rig
from livereact.merge.merge import (Contribution, ManualParams, finalize, merge_contributions,
                                   strobe_allowed)
from livereact.output.null_log import NullLogBackend
from livereact.remote import PhoneConsole, PhoneServer

SONG_S = 72  # through the build strobe (45-53 s) and the first drop phrase tail (70.6 s)
BURST_AT = 60  # a Space burst, mid-drop


def _strobe_channels(rig) -> list[int]:
    """0-based indices of every fixture's own strobe channel."""
    out = []
    for fx in rig.fixtures:
        for i, kind in enumerate(fx.channel_kinds()):
            if kind == ChannelKind.STROBE:
                out.append(fx.offset + i)
    return out


def _run_song(app: App, seconds: int = SONG_S, at=None, burst: bool = True) -> dict:
    """Step ``app`` through the scripted song on its FakeClock, like
    golden_frames.run_rig. ``at(app, t)`` runs before every input tick.
    ``burst``: the operator presses Space (a burst on each light's own
    strobe channel) at BURST_AT, so native strobe channels are exercised.
    Returns what the automatic strobe did and every published frame."""
    clock = app.clock
    demo = app.sources[0]
    strobe_ticks = 0
    frames: list[bytes] = []
    strobe_bytes = _strobe_channels(app.rig)
    native_strobe_frames = 0
    for step in range(seconds * gf.GRID_HZ):
        t = step / gf.GRID_HZ
        clock._t = t
        if step == gf.CUE_BUILD_AT * gf.GRID_HZ:
            app.metronome.cue_build()
        if step == gf.ARM_DROP_AT * gf.GRID_HZ:
            app.metronome.arm_drop()
        if burst and step == BURST_AT * gf.GRID_HZ:
            app.manual.strobe_burst = True          # Space on the laptop ...
        if burst and step == (BURST_AT + 0.4) * gf.GRID_HZ:
            app.manual.strobe_burst = False         # ... released 0.4 s later (ui/console.py)
        if step % gf.INPUT_EVERY == 0:
            if at is not None:
                at(app, t)
            demo.tick()
            if not getattr(app, "_audio_unplugged", False):
                app.input_queue.put(gf.song_audio(t))
            app.metronome.tick()
        if step % gf.SHOW_EVERY == 0:
            frame = app.show_engine.tick()
            eng = app.reactive_engine
            if eng.strobe_on or eng.strobe_level > 0:
                strobe_ticks += 1
            if frame is not None:
                frames.append(frame)
                if any(frame[i] for i in strobe_bytes):
                    native_strobe_frames += 1
    return {"strobe_ticks": strobe_ticks, "frames": frames, "native_strobe_frames": native_strobe_frames}


def _app(config_path=None, rig_path=None) -> App:
    return App(AppConfig(demo=True, config_path=config_path, rig_path=rig_path),
               clock=FakeClock(), backend=NullLogBackend())


@pytest.fixture(autouse=True)
def _quiet_logs():
    import logging
    previous = logging.root.manager.disable
    logging.disable(logging.INFO)  # the metronome logs once a simulated second
    yield
    logging.disable(previous)


# ------------------------------------------------------------------ the bug


def test_the_scripted_song_does_fire_the_automatic_strobe():
    """The control: with strobe allowed, the song's armed build and drop
    tail really do strobe, so the "never fires" tests below mean something."""
    run = _run_song(_app())
    assert run["strobe_ticks"] > 60  # seconds of build strobe at 60 Hz
    assert run["native_strobe_frames"] > 0  # the Space burst lit a strobe channel


@pytest.mark.parametrize("how", ["switch", "phone", "limit at 0"])
def test_strobe_off_from_any_surface_stops_the_automatic_strobe(how):
    """The reported bug: the phone's "Strobe off" (then: strobe_cap 0) left
    the automatic strobe running. Every way to say "off" now stops it."""
    app = _app()
    if how == "switch":
        app.manual.strobe_enabled = False            # the console switch / X key
    elif how == "phone":
        assert PhoneConsole(app).apply({"action": "strobe", "value": False})[0] == 200
    else:
        assert PhoneConsole(app).apply({"action": "strobe_cap", "value": 0})[0] == 200  # an old phone page
    run = _run_song(app)
    assert run["strobe_ticks"] == 0
    assert run["native_strobe_frames"] == 0


def test_strobe_off_output_is_exactly_the_show_without_its_strobe():
    """Nothing else changes: with strobe off, every frame equals a run whose
    automatic strobe rate is forced to 0 at the source (every detector and
    gate still running), and differs from the strobe-on show only on frames
    where that show was strobing. This is why tests/golden/frames.json is
    unchanged: the golden runs have strobe allowed, the default."""
    on = _app()
    strobing: list[bool] = []
    real_tick = on.reactive_engine.tick

    def tick(snap, rig):
        c = real_tick(snap, rig)
        strobing.append(on.reactive_engine.strobe_level > 0)
        return c

    on.reactive_engine.tick = tick
    run_on = _run_song(on, burst=False)

    off = _app()
    off.manual.strobe_enabled = False
    run_off = _run_song(off, burst=False)

    forced = _app()
    real_rate = forced.reactive_engine._snare_accent_strobe_rate
    forced.reactive_engine._snare_accent_strobe_rate = lambda snap: real_rate(snap) * 0.0
    run_forced = _run_song(forced, burst=False)

    assert run_off["frames"] == run_forced["frames"]
    assert len(run_on["frames"]) == len(run_off["frames"]) == len(strobing)
    changed = [i for i, (a, b) in enumerate(zip(run_on["frames"], run_off["frames"])) if a != b]
    assert changed, "the strobe-on run should differ somewhere"
    assert all(strobing[i] for i in changed)


def test_blackout_still_wins_over_strobe_off_and_everything_else():
    app = _app()
    app.manual.strobe_enabled = False
    app.manual.blackout = True
    app.manual.freeze = True
    run = _run_song(app, seconds=60)
    assert run["frames"] and all(f == bytes(UNIVERSE_SIZE) for f in run["frames"])


# ------------------------------------------------------------------ switching mid-show


def test_strobe_off_mid_build_stops_it_within_one_frame_and_on_brings_it_back():
    app = _app()
    seen = {"during_off": 0, "after_on": 0}

    def at(app, t):
        app.manual.strobe_enabled = not (47.0 <= t < 50.0)  # off for 3 s of the build strobe (45-53 s)

    def observe(snap, rig, real=app.reactive_engine.tick):
        c = real(snap, rig)
        t = app.clock.monotonic()
        if app.reactive_engine.strobe_on:
            if 47.0 + 1 / 60 <= t < 50.0:
                seen["during_off"] += 1
            elif 50.0 <= t < 53.0:
                seen["after_on"] += 1
        return c

    app.reactive_engine.tick = observe
    _run_song(app, seconds=58, at=at)
    assert seen["during_off"] == 0
    assert seen["after_on"] > 0  # the person turned it back on: the build strobe resumes


def test_freeze_cannot_hold_a_native_strobe_once_strobe_is_off():
    """A frozen frame holding a Space burst (each light's own strobe
    channel) would keep the fixture strobing; strobe off strips it."""
    app = _app()
    app.show_engine.tick()
    app.manual.strobe_burst = True
    frame = app.show_engine.tick()
    strobe_bytes = _strobe_channels(app.rig)
    assert any(frame[i] for i in strobe_bytes)  # this rig's burst lights a strobe channel
    app.manual.freeze = True
    assert app.show_engine.tick() is None
    assert app.frame_buffer.latest() == frame  # frozen: held as is
    app.manual.strobe_enabled = False
    app.show_engine.tick()
    held = app.frame_buffer.latest()
    assert not any(held[i] for i in strobe_bytes)
    assert [b for i, b in enumerate(held) if i not in strobe_bytes] == \
        [b for i, b in enumerate(frame) if i not in strobe_bytes]  # nothing else moved


# ------------------------------------------------------------------ units


def test_finalize_strobe_off_zeroes_every_strobe_channel_and_the_burst():
    rig = load_rig()
    strobe_bytes = _strobe_channels(rig)
    assert strobe_bytes
    c = Contribution()
    for i in strobe_bytes:
        c.set(i + 1, 255)
    merged = merge_contributions([c], rig)
    on = finalize(merged, rig, ManualParams(strobe_burst=True))
    off = finalize(merged, rig, ManualParams(strobe_burst=True, strobe_enabled=False))
    assert any(on[i] for i in strobe_bytes)
    assert not any(off[i] for i in strobe_bytes)


def test_strobe_allowed():
    assert strobe_allowed(ManualParams())
    assert not strobe_allowed(ManualParams(strobe_enabled=False))
    assert not strobe_allowed(ManualParams(strobe_cap=0.0))
    assert not strobe_allowed(ManualParams(strobe_enabled=False, strobe_cap=0.5))


def test_reactive_engine_never_toggles_the_dimmer_while_strobe_is_off():
    """Unit level: armed + rising (the build strobe) and a drop's phrase
    tail, both at full rate, never flash with strobe off."""
    clock = FakeClock()
    rig = load_rig()
    manual = ManualParams(strobe_enabled=False)
    eng = ReactiveLayerEngine(clock, manual=manual)
    wash = [fx for fx in rig.by_role("wash")]
    dimmers = set()
    for i in range(600):
        clock.advance(1 / 60)
        bar, beat = divmod(i // 30, 4)
        for kw in (dict(bucket="break", drop_armed=True, rising=True, rise_index=3.0),
                   dict(bucket="drop", drop_start_bar=0)):
            snap = ShowSnapshot(bpm=120.0, energy=0.9, energy_norm=0.9, bar=bar, beat_in_bar=beat + 1,
                                beat_phase=0.0, drop_hit_intensity=1.0, **kw)
            c = eng.tick(snap, rig)
            assert eng.strobe_level == 0 and not eng.strobe_on
            dimmers.add(tuple(c.values[fx.offset] for fx in wash))
    # A flash's OFF phase writes the wash dimmer to 0; with strobe off it
    # only ever carries the bucket's (breathing) wash level.
    assert all(v > 0 for d in dimmers for v in d)
    manual.strobe_enabled = True
    snap = ShowSnapshot(bpm=120.0, energy=0.9, energy_norm=0.9, bar=0, beat_in_bar=1, beat_phase=0.0,
                        bucket="break", drop_armed=True, rising=True, rise_index=3.0, drop_hit_intensity=1.0)
    eng.tick(snap, rig)
    assert eng.strobe_level == pytest.approx(STROBE_MAX) and eng.strobe_on


def test_the_apps_reactive_engine_reads_the_apps_switch():
    """The gate lives in the engine, so the app must hand it the live
    ManualParams (an engine built without one would ignore the switch)."""
    app = _app()
    assert app.reactive_engine.manual is app.manual


# ------------------------------------------------------------------ the phone


def test_phone_can_only_switch_strobe_off():
    app = _app()
    console = PhoneConsole(app)
    assert console.state()["strobe_allowed"] is True
    status, body = console.apply({"action": "strobe", "value": False})
    assert status == 200 and body["state"]["strobe_allowed"] is False
    assert body["state"]["strobe_enabled"] is False
    assert console.apply({"action": "strobe", "value": True})[0] == 403
    assert app.manual.strobe_enabled is False
    for bad in ("false", 0, None):
        assert console.apply({"action": "strobe", "value": bad})[0] == 400
    assert app.manual.strobe_enabled is False
    assert console.used_copy().keys() == {"strobe"}


def test_phone_page_strobe_off_button_sends_the_hard_off():
    from livereact.remote.page import PAGE_HTML
    assert 'id="strobeoff"' in PAGE_HTML
    assert 'send({ action: "strobe", value: false })' in PAGE_HTML
    assert "STROBE OFF" in PAGE_HTML


def test_strobe_stays_off_across_a_phone_reconnect_and_an_audio_dropout():
    """Off from the phone at 30 s; then the phone's server goes away and a
    new phone connects (a page reload on a new connection) and tries to
    switch it back on; the DJ board's audio drops out mid-build and comes
    back. The automatic strobe never fires."""
    import urllib.error
    import urllib.request

    app = _app()
    server = PhoneServer(PhoneConsole(app), port=0, host="127.0.0.1")
    server.start()

    def post(srv, body):
        req = urllib.request.Request(f"http://127.0.0.1:{srv.port}/api/action",
                                     data=json.dumps(body).encode(), method="POST")
        req.add_header("X-LiveReact-Key", srv.token)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    state = {"server": server, "refused": None, "after": None}

    def at(app, t):
        if t == 30.0:
            assert post(state["server"], {"action": "strobe", "value": False})[0] == 200
            state["server"].stop()                    # the phone loses the laptop
        if t == 35.0:
            new = PhoneServer(PhoneConsole(app), port=0, host="127.0.0.1")
            new.start()                               # ... and reconnects
            state["server"] = new
            state["refused"] = post(new, {"action": "strobe", "value": True})[0]
            state["after"] = post(new, {"action": "brightness", "by": 0.0})[1]["state"]
        app._audio_unplugged = 50.0 <= t < 52.0       # the board's USB audio drops out and returns

    try:
        run = _run_song(app, at=at)
    finally:
        state["server"].stop()
    assert state["refused"] == 403
    assert state["after"]["strobe_allowed"] is False   # the reconnected page shows it off
    assert app.manual.strobe_enabled is False
    assert run["strobe_ticks"] == 0 and run["native_strobe_frames"] == 0


# ------------------------------------------------------------------ restarts


def test_strobe_off_survives_a_restart_without_a_clean_shutdown(tmp_path):
    """Live runs end with kill -9, which skips the shutdown save. The latch
    saves config.json the moment strobe is switched off, so the next launch
    starts with it off, and the automatic strobe never fires in that run."""
    path = str(tmp_path / "config.json")
    first = _app(config_path=path)
    assert first.manual.strobe_enabled is True
    assert first.save_strobe_latch() is False          # nothing changed yet
    PhoneConsole(first).apply({"action": "strobe", "value": False})  # saves at once
    assert first.save_strobe_latch() is False                         # already on disk
    assert json.loads((tmp_path / "config.json").read_text())["strobe_enabled"] is False
    # no shutdown(): the process is killed here
    second = _app(config_path=path)
    assert second.manual.strobe_enabled is False
    run = _run_song(second)
    assert run["strobe_ticks"] == 0 and run["native_strobe_frames"] == 0
    # switched back on by the person: saved, and the next launch strobes again
    second.manual.strobe_enabled = True
    assert second.save_strobe_latch() is True
    assert _app(config_path=path).manual.strobe_enabled is True


def test_strobe_latch_thread_saves_without_being_called(tmp_path):
    """The latch runs on its own thread from App.start (here: just that
    loop, against a real clock-free stop event)."""
    import threading
    import time

    path = tmp_path / "config.json"
    app = _app(config_path=str(path))
    app.STROBE_LATCH_INTERVAL_S = 0.01
    th = threading.Thread(target=app._strobe_latch_loop, daemon=True)
    th.start()
    try:
        app.manual.strobe_enabled = False
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if path.exists() and json.loads(path.read_text()).get("strobe_enabled") is False:
                break
            time.sleep(0.01)
        else:
            pytest.fail("the latch never saved strobe off")
    finally:
        app.stop_event.set()
        th.join(timeout=2)


@pytest.mark.parametrize("stored", ["no", 0, None, [], {"x": 1}])
def test_a_corrupt_strobe_switch_in_config_loads_as_off(tmp_path, stored):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"strobe_enabled": stored}))
    manual = ManualParams()
    app_config.load_into(manual, str(path))
    assert manual.strobe_enabled is False


def test_an_old_config_without_the_switch_keeps_strobe_allowed(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"master_brightness": 0.8}))
    manual = ManualParams()
    app_config.load_into(manual, str(path))
    assert manual.strobe_enabled is True


def test_crash_relaunch_restores_strobe_off_and_never_switches_it_on(tmp_path):
    """The supervisor's live-state file (written 10x a second by the child):
    a crash with strobe off comes back with strobe off. A saved True never
    overrides an off loaded from config.json."""
    app = _app()
    app.manual.strobe_enabled = False
    path = str(tmp_path / "live-state.json")
    supervisor._write_state(app.manual, path)
    assert json.loads(open(path).read())["strobe_enabled"] is False

    relaunched = _app()
    assert relaunched.manual.strobe_enabled is True
    supervisor.restore_live_state(relaunched.manual, path)
    assert relaunched.manual.strobe_enabled is False
    run = _run_song(relaunched)
    assert run["strobe_ticks"] == 0 and run["native_strobe_frames"] == 0

    (tmp_path / "on.json").write_text(json.dumps({"strobe_enabled": True}))
    manual = ManualParams(strobe_enabled=False)
    supervisor.restore_live_state(manual, str(tmp_path / "on.json"))
    assert manual.strobe_enabled is False


# ------------------------------------------------------------------ laser chops


def test_strobe_off_holds_the_laser_chop_steady():
    """The laser SHOW profile's Armed chop and drop accent switch CH1 on and
    off at up to ~4 Hz: a flashing light. With strobe off they hold steady
    (the arm switch and blackout still gate the lasers as before)."""
    def flashes(strobe_on: bool) -> int:
        app = _app(rig_path=str(gf.RIGS_DIR / "sophias_thai.json"))
        assert app.rig.laser_profile == "show"
        app.manual.laser_enable = True
        app.manual.strobe_enabled = strobe_on
        frames = _run_song(app)["frames"]
        worst = 0
        for laser in app.rig.by_role("laser"):
            ch1 = [f[laser.offset] > 0 for f in frames]
            toggles = [i for i in range(1, len(ch1)) if ch1[i] != ch1[i - 1]]
            j = 0
            for i in range(len(toggles)):
                while toggles[i] - toggles[j] >= 60:  # any one second of 60 Hz frames
                    j += 1
                worst = max(worst, i - j + 1)
        return worst

    assert flashes(True) >= 4      # the control: the chop really flashes
    assert flashes(False) <= 1     # strobe off: at most one change in any second


# ------------------------------------------------------------------ saves that fail


def test_a_failed_strobe_save_is_retried(tmp_path):
    """A full disk or a missing folder must not leave the latch believing
    strobe off is on disk: it keeps trying until the save lands."""
    folder = tmp_path / "not-yet"
    path = folder / "config.json"
    app = _app(config_path=str(path))
    app.manual.strobe_enabled = False
    assert app.save_strobe_latch() is False and not path.exists()
    folder.mkdir()
    assert app.save_strobe_latch() is True
    assert json.loads(path.read_text())["strobe_enabled"] is False


def test_phone_strobe_off_is_on_disk_before_the_reply(tmp_path):
    path = tmp_path / "config.json"
    app = _app(config_path=str(path))
    assert PhoneConsole(app).apply({"action": "strobe", "value": False})[0] == 200
    assert json.loads(path.read_text())["strobe_enabled"] is False


@pytest.mark.parametrize("content", ["", "{not json", "[1, 2]"])
def test_an_unreadable_config_loads_strobe_off(tmp_path, content):
    """A power cut can leave config.json empty or torn; it may have held
    strobe off, so strobe fails safe (the other settings fall back to
    their defaults, as before)."""
    path = tmp_path / "config.json"
    path.write_text(content)
    manual = ManualParams()
    assert app_config.load_into(manual, str(path)) is False
    assert manual.strobe_enabled is False
    assert manual.master_brightness == 1.0


def test_a_stale_concurrent_save_cannot_leave_the_file_on_while_the_switch_is_off(tmp_path):
    """Review finding: a save that read OFF but wrote ON (strobe toggled back
    on while it waited for the file lock), followed by another toggle to OFF,
    must still end with OFF on disk. The latch compares against what the
    file holds, not against what it last asked for."""
    path = tmp_path / "config.json"
    app = _app(config_path=str(path))
    app.manual.strobe_enabled = False
    assert app.save_strobe_latch() is True
    app.manual.strobe_enabled = True
    app_config.save_from(app.manual, str(path))      # another writer lands ON
    app.manual.strobe_enabled = False                # and the operator switches it off again
    assert app.save_strobe_latch() is True
    assert json.loads(path.read_text())["strobe_enabled"] is False
    assert app.save_strobe_latch() is False          # in sync now
