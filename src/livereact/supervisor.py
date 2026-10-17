"""In-app supervisor: relaunch the show engine within seconds of a crash.

Replaces tools/run_show.sh's zsh loop (2026-10-16), so the relaunch also
works from the double-click macOS app, which has no shell. A hardware show
run (``--hardware``, or ``--supervise``) becomes two processes: this small
parent, which imports nothing heavy and never touches DMX, and the engine
child (the same command plus ``--engine-child``), which does everything it
always did. When the child dies (a segfault, an uncaught crash, a core
thread found dead by the watchdog below) the parent starts a new one after
RELAUNCH_DELAY_S. While the engine is down the Enttec keeps repeating the
last frame it was sent, so the rig holds its look through the gap.

The loop ends when the engine exits cleanly (the operator closed the
window), when ``logs/STOP`` exists as it exits (run_show.sh's convention),
or on SIGINT/SIGTERM to the parent, which it passes on to the engine.

What a relaunch must not do is undo the operator: a crash during a blackout
must not come back lit. The child saves its live safety state (blackout,
brightness, strobe cap, strobe allowed, laser arm) to ``logs/live-state.json``
ten times a second, and a relaunched child restores it. Lasers are restored
DISarmed if they were disarmed, and strobe OFF if it was off, but the restore
never arms a laser or switches strobe back on.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time

log = logging.getLogger(__name__)

CHILD_FLAG = "--engine-child"
RELAUNCH_ENV = "LIVEREACT_RELAUNCH"  # how many times the child has been relaunched; unset on the first launch
STOP_FILE = os.path.join("logs", "STOP")
STATE_FILE = os.path.join("logs", "live-state.json")
LOG_FILE = os.path.join("logs", "supervisor.log")

RELAUNCH_DELAY_S = 0.5   # death -> new engine process; Python + imports take ~1-2 s more
QUICK_DEATH_S = 10.0     # an engine that dies this soon after launch is crash-looping ...
MAX_BACKOFF_S = 3.0      # ... so back off, doubling up to this (run_show.sh's old fixed 3 s;
                         # the Enttec repeats the last frame through the gap, so keep it short),
                         # but never give up mid-show
STOP_GRACE_S = 5.0       # after passing on a stop signal, wait this long before SIGKILL
WATCHDOG_INTERVAL_S = 0.5
STATE_SAVE_INTERVAL_S = 0.1  # a dict compare when nothing changed; a blackout pressed just
                             # before a crash must still be there after the relaunch
SAFETY_FIELDS = ("blackout", "master_brightness", "strobe_cap", "strobe_enabled", "laser_enable")


def child_command(argv: list[str]) -> list[str]:
    """The engine child's command line: this same program and arguments.
    Frozen (the PyInstaller app), ``sys.executable`` IS the program."""
    if getattr(sys, "frozen", False):
        return [sys.executable, *argv, CHILD_FLAG]  # env: see _child_env
    return [sys.executable, "-m", "livereact", *argv, CHILD_FLAG]


def describe_exit(code: int) -> str:
    if code < 0:
        try:
            return f"signal {signal.Signals(-code).name}"
        except ValueError:
            return f"signal {-code}"
    return f"exit code {code}"


def _configure_parent_logging() -> None:
    os.makedirs("logs", exist_ok=True)
    fmt = logging.Formatter("%(asctime)s supervisor: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    for handler in (logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()):
        handler.setFormatter(fmt)
        log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False


def supervise(argv: list[str], *, popen=subprocess.Popen, sleep=time.sleep,
              monotonic=time.monotonic, install_signals: bool = True) -> int:
    """Run the engine as a child process and relaunch it whenever it dies.
    Returns the exit code for the parent process."""
    if install_signals:
        _configure_parent_logging()
    os.makedirs("logs", exist_ok=True)
    for stale in (STOP_FILE, STATE_FILE):  # a fresh run: last night's STOP / state don't apply
        if os.path.exists(stale):
            os.remove(stale)

    state = {"stopping": False, "stop_at": 0.0, "child": None}

    def on_signal(signum, _frame) -> None:
        log.info("received %s: stopping the engine", signal.Signals(signum).name)
        state["stopping"] = True
        state["stop_at"] = monotonic()
        child = state["child"]
        if sys.platform == "win32" and signum == signal.SIGINT:
            return  # Ctrl-C reached the engine too; TerminateProcess would cut its clean shutdown
        if child is not None and child.poll() is None:
            child.terminate()  # the engine's own handler sets stop_event and closes cleanly

    if install_signals:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, on_signal)

    launches = 0
    quick_deaths = 0
    while True:
        env = dict(os.environ)
        if getattr(sys, "frozen", False):
            # PyInstaller: the child is an independent instance of the app,
            # not a helper sharing this one's bootloader state.
            env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        if launches:
            env[RELAUNCH_ENV] = str(launches)
        cmd = child_command(argv)
        started = monotonic()
        child = popen(cmd, env=env)
        state["child"] = child
        log.info("engine started (pid %s, launch %d): %s", child.pid, launches + 1, " ".join(argv))
        code = _wait(child, state, monotonic)
        uptime = monotonic() - started
        launches += 1

        if state["stopping"]:
            log.info("engine stopped (%s); supervisor done", describe_exit(code))
            return 0
        if os.path.exists(STOP_FILE):
            os.remove(STOP_FILE)
            log.info("engine exited (%s) with logs/STOP present; supervisor done", describe_exit(code))
            return 0
        if code == 0:
            log.info("engine closed cleanly after %.0f s; supervisor done", uptime)
            return 0
        if launches == 1 and code > 0 and uptime < QUICK_DEATH_S:
            # The very first launch failed with an error, not a crash: a typo'd
            # --rig, a bad rig file, a missing package. Relaunching can't fix
            # that, and each attempt would open (and with --record, create)
            # another session; say so once and stop, like an unsupervised run.
            log.error("engine failed to start (%s); not relaunching. See the log above.",
                      describe_exit(code))
            return code

        quick_deaths = quick_deaths + 1 if uptime < QUICK_DEATH_S else 0
        delay = min(MAX_BACKOFF_S, RELAUNCH_DELAY_S * 2 ** quick_deaths) if quick_deaths > 1 else RELAUNCH_DELAY_S
        log.warning("ENGINE DIED (%s) after %.1f s; relaunching in %.1f s (relaunch #%d). "
                    "Crash details: logs/crash-*.log and the launch log.",
                    describe_exit(code), uptime, delay, launches)
        sleep(delay)
        if state["stopping"]:
            return 0


def _wait(child, state: dict, monotonic) -> int:
    """Wait for the child; once a stop was requested, SIGKILL it if it hasn't
    gone after STOP_GRACE_S (a wedged engine must not keep the app alive)."""
    while True:
        try:
            return child.wait(timeout=0.25)
        except subprocess.TimeoutExpired:
            if state["stopping"] and monotonic() - state["stop_at"] > STOP_GRACE_S:
                log.warning("engine ignored the stop for %.0f s; killing it", STOP_GRACE_S)
                child.kill()


# ---------------------------------------------------------------- child side

def relaunch_count() -> int:
    try:
        return int(os.environ.get(RELAUNCH_ENV, "0"))
    except ValueError:
        return 0


def restore_live_state(manual, path: str = STATE_FILE) -> str | None:
    """On a relaunch, put back what the operator had set when the engine
    died. Returns a summary for the log, or None if there was nothing."""
    try:
        with open(path, encoding="utf-8") as fh:
            saved = json.load(fh)
    except (OSError, ValueError):
        return None
    if isinstance(saved.get("blackout"), bool):
        manual.blackout = saved["blackout"]
    for field in ("master_brightness", "strobe_cap"):
        value = saved.get(field)
        if isinstance(value, (int, float)) and 0.0 <= value <= 1.0:
            setattr(manual, field, float(value))
    if saved.get("laser_enable") is False:
        manual.laser_enable = False  # a restore may disarm, never arm
    if saved.get("strobe_enabled") is False:
        manual.strobe_enabled = False  # a restore may switch strobe off, never on
    return ", ".join(f"{f}={getattr(manual, f)!r}" for f in SAFETY_FIELDS)


def _write_state(manual, path: str) -> dict:
    snapshot = {f: getattr(manual, f) for f in SAFETY_FIELDS}
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh)
    os.replace(tmp, path)  # atomic: a crash mid-write leaves the previous state
    return snapshot


def start_child_threads(app, path: str = STATE_FILE) -> None:
    """Engine-child helpers: save the live safety state, and turn a dead core
    thread into a process exit the supervisor can see. Without the watchdog
    a crashed show-engine thread (its run() logs and returns) leaves the rig
    frozen on its last frame until someone notices; exiting gets a relaunch
    within seconds instead."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def save_loop() -> None:
        last = None
        while not app.stop_event.wait(STATE_SAVE_INTERVAL_S):
            try:
                current = {f: getattr(app.manual, f) for f in SAFETY_FIELDS}
                if current != last:
                    last = _write_state(app.manual, path)
            except Exception:  # noqa: BLE001 - a full disk must not touch the show
                log.debug("live-state save failed", exc_info=True)

    # The three the show can't run without (a dead recorder is not worth a
    # relaunch gap): clock, conductor, DMX out.
    vital = (app.metronome, app.show_engine, app.writer)

    def watchdog() -> None:
        while not app.stop_event.wait(WATCHDOG_INTERVAL_S):
            dead = [t.name for t in vital if t.ident is not None and not t.is_alive()]
            if dead and not app.stop_event.is_set():
                log.critical("Core thread(s) %s died; exiting so the supervisor relaunches the engine",
                             ", ".join(dead))
                logging.shutdown()
                os._exit(70)

    threading.Thread(target=save_loop, name="live-state", daemon=True).start()
    threading.Thread(target=watchdog, name="engine-watchdog", daemon=True).start()
