"""Crash logging: leave evidence behind when the process dies.

Why (2026-10-16): on 2026-10-08 Python 3.14.3's garbage collector segfaulted
twice inside the show-engine thread mid-set. A segfault kills the process
before any Python logging runs, so the only trace was macOS's own crash
report, and nothing said which thread or which line. ``install()`` arms
:mod:`faulthandler` on a per-launch file in ``logs/``, which the interpreter
writes from its signal handler (every thread's Python stack) even on a hard
crash, and routes uncaught exceptions on any thread into the same file and
the normal log. A launch that ends cleanly removes its empty crash file. A
file left with stacks in it is a crash; one left with only its header means
the process was killed (force quit, kill -9, a closed terminal), since then
nothing at all runs on the way out. On Windows faulthandler also reports
some exceptions that were later handled, so read those entries with care.
"""

from __future__ import annotations

import atexit
import faulthandler
import logging
import os
import platform
import sys
import threading
import time
import traceback

log = logging.getLogger(__name__)


def python_warning() -> str | None:
    """A warning to log when this interpreter is one shows must not run on."""
    if sys.version_info[:2] >= (3, 14):
        return (f"Python {platform.python_version()} is running this show. 3.14's garbage "
                "collector segfaulted mid-set on 2026-10-08; use Python 3.13 (.venv313).")
    return None


def install(log_dir: str = "logs") -> str:
    """Arm crash logging for this process; returns the crash file's path."""
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, f"crash-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}.log")
    # Kept open for the life of the process: faulthandler writes to the raw
    # file descriptor from inside a signal handler, where nothing can be opened.
    fh = open(path, "a", encoding="utf-8")  # noqa: SIM115
    fh.write(f"LiveReact pid {os.getpid()} started {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
             f"python {sys.version.split()[0]} on {platform.platform()}\n"
             f"argv {sys.argv}\n")
    fh.flush()
    header_size = fh.tell()
    faulthandler.enable(file=fh, all_threads=True)
    lock = threading.Lock()  # two threads failing at once must not interleave

    def record(title: str, exc_type, exc, tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            with lock:
                fh.write(f"\n{time.strftime('%H:%M:%S')} {title}\n{text}")
                fh.flush()
        except Exception:  # noqa: BLE001 - never let crash logging raise
            pass
        log.critical("%s\n%s", title, text.rstrip())

    def excepthook(exc_type, exc, tb) -> None:
        # Also what PySide6 calls for an exception escaping a Qt slot (the
        # console keeps running; the trace must still land somewhere).
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        record("Uncaught exception", exc_type, exc, tb)

    def thread_excepthook(args: threading.ExceptHookArgs) -> None:
        if issubclass(args.exc_type, SystemExit):
            return  # what the default hook does too: a thread asking to end isn't a crash
        name = args.thread.name if args.thread is not None else "?"
        record(f"Uncaught exception in thread {name}", args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = excepthook
    threading.excepthook = thread_excepthook

    def tidy() -> None:
        # A clean exit: drop the file if nothing beyond the header was written.
        try:
            faulthandler.disable()
            with lock:
                empty = fh.tell() <= header_size
            fh.close()
            if empty:
                os.remove(path)
        except Exception:  # noqa: BLE001
            pass

    atexit.register(tidy)
    log.info("Crash log armed: %s", path)
    return path
