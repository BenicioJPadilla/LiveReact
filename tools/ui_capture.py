"""Screenshots and UI frame-time numbers for the operator console, headless.

Runs the real demo pipeline (App + show engine + DMX writer threads, synthetic
music) behind the console with Qt's offscreen platform, so it works over SSH
or in CI. Nothing in the engine is modified: timing is measured by wrapping
instance attributes from the outside.

    QT_QPA_PLATFORM=offscreen python tools/ui_capture.py shots  OUT_DIR [--tag before]
    QT_QPA_PLATFORM=offscreen python tools/ui_capture.py frametime [--seconds 30]
    QT_QPA_PLATFORM=offscreen python tools/ui_capture.py launch OUT_DIR

``shots`` writes <tag>-<screen>-<W>x<H>.png for every screen at 1440x900 and
1920x1080. ``frametime`` prints the console's refresh cost (UI thread), the
show-engine tick cost and the DMX writer's 40 Hz send interval while the
console runs on the Show tab. ``launch`` writes the ``--choose`` launch
dialog at its natural size, live and demo, listing the repo's rigs/.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from PySide6 import QtCore, QtWidgets  # noqa: E402

from livereact.app import App, AppConfig  # noqa: E402

SIZES = [(1440, 900), (1920, 1080)]


def _qt() -> QtWidgets.QApplication:
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _pump(seconds: float) -> None:
    qt = _qt()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qt.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 20)
        time.sleep(0.005)


def _console(rig: str | None):
    from livereact.ui.console import ConsoleWindow
    from livereact.ui.theme import apply_theme

    rig_path = os.path.join(ROOT, "rigs", rig) if rig else None
    app = App(AppConfig(demo=True, config_path=None, rig_path=rig_path))
    apply_theme(_qt())
    win = ConsoleWindow(app)
    app.start()
    timer = QtCore.QTimer()
    timer.timeout.connect(win.refresh)
    timer.start(33)
    return app, win, timer


def _grab(win: QtWidgets.QWidget, out_dir: str, tag: str, name: str, settle: float = 0.6) -> None:
    for w, h in SIZES:
        win.resize(w, h)
        win.show()
        _pump(settle)
        path = os.path.join(out_dir, f"{tag}-{name}-{w}x{h}.png")
        win.grab().save(path)
        print("wrote", path)


def _tab_index(win, label: str) -> int:
    for i in range(win.tabs.count()):
        if win.tabs.tabText(i) == label:
            return i
    raise KeyError(label)


def shots(out_dir: str, tag: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    # (rig file, screen name, tab label) -- the default rig carries the
    # accent-profile Show tab, Venue and Rig Config; the other rigs add the
    # profile-specific screens.
    plans = [
        (None, [("show", "Show"), ("venue", "Venue"), ("rig", "Rig Config")]),
        ("sophias_thai.json", [("laser-show", "Laser Show")]),
        ("junior_crib.json", [("show-manual-lasers", "Show")]),
    ]
    for rig, screens in plans:
        app, win, timer = _console(rig)
        try:
            _pump(6.0)                       # let the demo music reach a lit state
            for name, label in screens:
                win.tabs.setCurrentIndex(_tab_index(win, label))
                _grab(win, out_dir, tag, name)
            if rig is None:
                # the active states: blackout held, a build cued, the laser cue held
                win.tabs.setCurrentIndex(0)
                win.b_black.toggle()
                app.metronome.cue_build()
                win.b_laser_cue.toggle()
                _grab(win, out_dir, tag, "show-states")
                win.b_laser_cue.toggle()
                app.metronome.cue_build()
                win.b_black.toggle()
        finally:
            timer.stop()
            win.close()
            app.stop_event.set()
            app.shutdown()

    from livereact.core.frame_buffer import DmxFrameBuffer
    from livereact.fixtures.rig import load_rig
    from livereact.ui.fixture_test import FixtureTestPanel
    from livereact.ui.theme import apply_theme
    from livereact.ui.visualizer import VisualizerWindow, build_demo_universe

    apply_theme(_qt())
    rig = load_rig()
    panel = FixtureTestPanel(rig, DmxFrameBuffer())
    panel._flash(rig.fixture("par_l"))
    _grab(panel, out_dir, tag, "fixture-test")
    panel.close()

    viz = VisualizerWindow(rig)
    viz.update_from_universe(build_demo_universe(rig, 1.0))
    _grab(viz, out_dir, tag, "visualizer")
    viz.close()


def _fake_gear(adapter: bool, board: bool):
    """A Detection like the real watcher's, for the gate's screenshots."""
    from livereact.devices import Detection, find_dj_audio, find_dj_midi, find_dmx_adapters

    port = type("Port", (), dict(device="/dev/cu.usbserial-EN123456", vid=0x0403, pid=0x6001,
                                 serial_number="EN123456", manufacturer="ENTTEC", product="DMX USB PRO",
                                 description="DMX USB PRO", location=None))
    det = Detection()
    if adapter:
        det.adapters = find_dmx_adapters([port])
    if board:
        det.audio = find_dj_audio([{"name": "XDJ-XZ", "max_input_channels": 8}])
        det.midi = find_dj_midi(["XDJ-XZ (1)", "XDJ-XZ (2)"])
        det.djlink = ["XDJ-XZ"]
    return det


def launch(out_dir: str) -> None:
    import shutil
    import tempfile

    from livereact.__main__ import _build_parser
    from livereact.devices import remember_rig
    from livereact.ui.launch_dialog import LaunchDialog, save_last_launch
    from livereact.ui.theme import apply_theme

    os.makedirs(out_dir, exist_ok=True)
    apply_theme(_qt())
    phone = "--phone" in _build_parser()._option_string_actions
    with tempfile.TemporaryDirectory() as cwd:   # the repo's rigs, a clean memory file
        shutil.copytree(os.path.join(ROOT, "rigs"), os.path.join(cwd, "rigs"))
        home = os.path.join(cwd, "home")
        live = {"mode": "live", "rig": os.path.join("rigs", "josh_rig.json"), "record": True}
        for name, choice, gear, opts in [
            ("live-nothing", live, (False, False), {}),
            ("live-adapter-only", live, (True, False), {}),
            ("live-first-use", live, (True, True), {}),
            ("live-ready", {**live, "rig": os.path.join("rigs", "junior_crib.json")}, (True, True), {}),
            ("live-force-start", live, (False, True), {"force_start": True}),
            ("demo", {"mode": "demo", "rig": os.path.join("rigs", "sophias_thai.json"), "record": False},
             (False, False), {}),
        ]:
            if name == "live-ready":     # the adapter was used with Josh's rig before
                remember_rig("EN123456", os.path.join(cwd, "rigs", "josh_rig.json"), home)
            save_last_launch(cwd, choice)
            dlg = LaunchDialog(cwd, phone_supported=phone, watch=False, home=home, **opts)
            dlg.set_detection(_fake_gear(*gear))
            dlg.show()
            _pump(0.4)
            path = os.path.join(out_dir, f"launch-dialog-{name}.png")
            dlg.grab().save(path)
            print("wrote", path)
            dlg.close()


def _stats(xs: list[float]) -> str:
    if not xs:
        return "n=0"
    xs = sorted(xs)
    p = lambda q: xs[min(len(xs) - 1, int(q * len(xs)))]  # noqa: E731
    return (f"n={len(xs)} mean={statistics.fmean(xs):.2f} p50={p(0.5):.2f} "
            f"p95={p(0.95):.2f} p99={p(0.99):.2f} max={xs[-1]:.2f} ms")


def frametime(seconds: float, rig: str | None) -> None:
    app, win, timer = _console(rig)
    win.resize(1920, 1080)
    win.show()

    refresh_ms: list[float] = []
    orig_refresh = win.refresh

    def timed_refresh() -> None:
        t0 = time.perf_counter()
        orig_refresh()
        refresh_ms.append((time.perf_counter() - t0) * 1000)

    timer.timeout.disconnect()
    timer.timeout.connect(timed_refresh)

    tick_ms: list[float] = []
    orig_tick = app.show_engine.tick

    def timed_tick():
        t0 = time.perf_counter()
        out = orig_tick()
        tick_ms.append((time.perf_counter() - t0) * 1000)
        return out

    app.show_engine.tick = timed_tick        # run() looks tick up on the instance

    send_t: list[float] = []
    orig_send = app.backend.send

    def timed_send(universe: bytes) -> None:
        send_t.append(time.perf_counter())
        orig_send(universe)

    app.backend.send = timed_send

    # Paint cost lands in the UI event loop, so it is in the busy fraction.
    try:
        _pump(3.0)                           # warm-up
        refresh_ms.clear(); tick_ms.clear(); send_t.clear()
        busy = 0.0
        t_start = time.monotonic()
        qt = _qt()
        while time.monotonic() - t_start < seconds:
            t0 = time.perf_counter()
            qt.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 20)
            busy += time.perf_counter() - t0
            time.sleep(0.002)
        wall = time.monotonic() - t_start
    finally:
        timer.stop()
        win.close()
        app.stop_event.set()
        app.shutdown()

    intervals = [(b - a) * 1000 for a, b in zip(send_t, send_t[1:])]
    print(f"rig={rig or 'default'} seconds={wall:.1f}")
    print(f"console refresh (UI thread):   {_stats(refresh_ms)}")
    print(f"show-engine tick:              {_stats(tick_ms)}")
    print(f"DMX writer send interval:      {_stats(intervals)}  (target 25.00)")
    print(f"writer rate:                   {len(send_t) / wall:.2f} Hz")
    print(f"UI event loop busy:            {100 * busy / wall:.1f} % of wall time")


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("shots")
    s.add_argument("out_dir")
    s.add_argument("--tag", default="after")
    f = sub.add_parser("frametime")
    f.add_argument("--seconds", type=float, default=30.0)
    f.add_argument("--rig", default=None)
    la = sub.add_parser("launch")
    la.add_argument("out_dir")
    args = p.parse_args()
    _qt()
    if args.cmd == "shots":
        shots(args.out_dir, args.tag)
    elif args.cmd == "launch":
        launch(args.out_dir)
    else:
        frametime(args.seconds, args.rig)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
