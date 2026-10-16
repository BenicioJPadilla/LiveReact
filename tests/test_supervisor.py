"""The in-app supervisor (livereact/supervisor.py): relaunch on a crash,
stop on a clean exit / logs/STOP / a signal, and never let a relaunch undo
the operator's blackout or arm a laser."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from livereact import supervisor
from livereact.merge.merge import ManualParams


class FakeChild:
    def __init__(self, code: int, on_wait=None) -> None:
        self.pid = 4242
        self.code = code
        self.on_wait = on_wait
        self.terminated = self.killed = False

    def wait(self, timeout=None):
        if self.on_wait:
            self.on_wait()
        return self.code

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class Clock:
    def __init__(self):
        self.t = 0.0
        self.sleeps: list[float] = []

    def monotonic(self):
        self.t += 30.0  # every engine "runs" 30 s unless a test says otherwise
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)


def _run(codes, tmp_path, monkeypatch, clock=None, on_wait=None):
    monkeypatch.chdir(tmp_path)
    clock = clock or Clock()
    launched = []

    def popen(cmd, env):
        launched.append((cmd, env))
        return FakeChild(codes[len(launched) - 1], on_wait)

    rc = supervisor.supervise(["--hardware", "--rig", "rigs/josh_rig.json"], popen=popen,
                              sleep=clock.sleep, monotonic=clock.monotonic, install_signals=False)
    return rc, launched, clock


def test_crashes_relaunch_quickly_and_a_clean_exit_ends_the_loop(tmp_path, monkeypatch):
    rc, launched, clock = _run([-11, 1, 0], tmp_path, monkeypatch)  # 1 after a running show: relaunch
    assert rc == 0
    assert len(launched) == 3
    assert clock.sleeps == [supervisor.RELAUNCH_DELAY_S] * 2
    cmd, env = launched[0]
    assert cmd[-1] == supervisor.CHILD_FLAG and "--hardware" in cmd
    assert supervisor.RELAUNCH_ENV not in env
    assert launched[2][1][supervisor.RELAUNCH_ENV] == "2"


def test_a_crash_loop_backs_off_but_never_gives_up(tmp_path, monkeypatch):
    class Quick(Clock):
        def monotonic(self):
            self.t += 1.0  # dies 1 s after every launch
            return self.t

    rc, launched, clock = _run([-11] * 7 + [0], tmp_path, monkeypatch, clock=Quick())
    assert rc == 0 and len(launched) == 8
    assert clock.sleeps[0] == supervisor.RELAUNCH_DELAY_S
    assert clock.sleeps[1:] == sorted(clock.sleeps[1:])  # growing ...
    assert max(clock.sleeps) == supervisor.MAX_BACKOFF_S  # ... up to the cap


def test_stop_file_ends_the_loop_even_after_a_crash(tmp_path, monkeypatch):
    def touch_stop():
        Path("logs/STOP").write_text("")

    rc, launched, _ = _run([-9, -9], tmp_path, monkeypatch, on_wait=touch_stop)
    assert rc == 0 and len(launched) == 1
    assert not Path("logs/STOP").exists()


def test_a_stale_stop_file_and_state_from_last_night_are_cleared(tmp_path, monkeypatch):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "STOP").write_text("")
    (tmp_path / "logs" / "live-state.json").write_text('{"blackout": true}')
    rc, launched, _ = _run([0], tmp_path, monkeypatch)
    assert rc == 0 and len(launched) == 1
    assert not (tmp_path / "logs" / "live-state.json").exists()


def test_restore_keeps_a_blackout_and_never_arms_a_laser(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"blackout": True, "master_brightness": 0.4,
                                "strobe_cap": 0.2, "laser_enable": True}))
    manual = ManualParams()
    assert manual.laser_enable is False
    supervisor.restore_live_state(manual, str(path))
    assert manual.blackout is True
    assert manual.master_brightness == 0.4 and manual.strobe_cap == 0.2
    assert manual.laser_enable is False  # saved armed, restored still disarmed

    armed = ManualParams(laser_enable=True)  # a "show" profile arms at launch
    path.write_text(json.dumps({"laser_enable": False}))
    supervisor.restore_live_state(armed, str(path))
    assert armed.laser_enable is False  # the operator had disarmed it


def test_restore_ignores_garbage(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"blackout": "yes", "master_brightness": 7, "strobe_cap": None}))
    manual = ManualParams()
    supervisor.restore_live_state(manual, str(path))
    assert manual == ManualParams()
    assert supervisor.restore_live_state(manual, str(tmp_path / "missing.json")) is None


def test_child_command_reruns_this_program():
    assert supervisor.child_command(["--hardware"])[:3] == [sys.executable, "-m", "livereact"]


def test_describe_exit_names_the_signal():
    assert supervisor.describe_exit(-11) == "signal SIGSEGV"
    assert supervisor.describe_exit(70) == "exit code 70"


@pytest.mark.skipif(sys.platform == "win32", reason="SIGKILL")
def test_a_killed_engine_is_back_within_three_seconds(tmp_path):
    """End to end in demo mode: kill -9 the engine child, a new one starts."""
    import signal
    import time

    src = str(Path(supervisor.__file__).resolve().parents[1])
    env = dict(os.environ, PYTHONPATH=src)
    parent = subprocess.Popen([sys.executable, "-m", "livereact", "--demo", "--supervise", "--duration", "4"],
                              cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines: list[str] = []
    reader = threading.Thread(target=lambda: lines.extend(iter(parent.stdout.readline, "")), daemon=True)
    reader.start()
    deadline = time.monotonic() + 30
    while not any("NullLogBackend open" in l for l in lines) and time.monotonic() < deadline:
        time.sleep(0.05)
    child_pid = int(next(l for l in lines if "engine started (pid" in l).split("pid ")[1].split(",")[0])
    killed_at = time.monotonic()
    os.kill(child_pid, signal.SIGKILL)
    while sum("NullLogBackend open" in l for l in lines) < 2 and time.monotonic() < deadline:
        time.sleep(0.05)
    back_after = time.monotonic() - killed_at
    parent.wait(timeout=30)
    assert parent.returncode == 0
    assert back_after < 3.0, back_after
    assert any("ENGINE DIED (signal SIGKILL)" in l for l in lines)


def test_a_first_launch_that_errors_out_is_not_relaunched(tmp_path, monkeypatch):
    """A typo'd --rig exits 1 at startup; relaunching forever can't fix it."""
    class Quick(Clock):
        def monotonic(self):
            self.t += 1.0
            return self.t

    rc, launched, _ = _run([1, 0], tmp_path, monkeypatch, clock=Quick())
    assert rc == 1 and len(launched) == 1


def test_a_first_launch_segfault_is_still_relaunched(tmp_path, monkeypatch):
    class Quick(Clock):
        def monotonic(self):
            self.t += 1.0
            return self.t

    rc, launched, _ = _run([-11, 0], tmp_path, monkeypatch, clock=Quick())
    assert rc == 0 and len(launched) == 2


class _FakeApp:
    def __init__(self):
        from livereact.merge.merge import ManualParams

        self.stop_event = threading.Event()
        self.manual = ManualParams()
        self.metronome = threading.Thread(target=lambda: None, name="metronome")
        self.show_engine = threading.Thread(target=self.stop_event.wait, name="show-engine")
        self.writer = threading.Thread(target=self.stop_event.wait, name="dmx-writer")


def test_child_saves_the_operator_state_and_a_dead_thread_exits(tmp_path, monkeypatch):
    import time

    exits = []
    monkeypatch.setattr(supervisor.os, "_exit", lambda code: exits.append(code))
    monkeypatch.setattr(supervisor, "WATCHDOG_INTERVAL_S", 0.02)
    monkeypatch.setattr(supervisor, "STATE_SAVE_INTERVAL_S", 0.02)
    app = _FakeApp()
    for t in (app.show_engine, app.writer):
        t.start()
    path = tmp_path / "logs" / "live-state.json"
    supervisor.start_child_threads(app, str(path))

    app.manual.blackout = True
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not (path.exists() and json.loads(path.read_text())["blackout"]):
        time.sleep(0.01)
    assert json.loads(path.read_text())["blackout"] is True
    assert exits == []  # the metronome never started: not "dead"

    app.metronome.start()
    app.metronome.join()
    while time.monotonic() < deadline and not exits:
        time.sleep(0.01)
    assert exits and exits[0] == 70
    app.stop_event.set()
