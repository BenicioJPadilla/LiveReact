"""Frozen entry point for the macOS LiveReact.app (PyInstaller).

LiveReact resolves config.json, midi_map.json, recordings/, logs/, diagnostics/
and --rig paths relative to the current directory. A Finder-launched .app starts
with CWD "/", so this entry point:

1. chdirs into a per-user data folder (~/LiveReact, or $LIVEREACT_HOME),
   creating it on first launch;
2. copies the bundled rigs/*.json into <data>/rigs/ without ever overwriting a
   file that is already there (it may hold Venue-tab calibration);
3. with command-line arguments (a terminal launch, or the in-app supervisor
   re-executing sys.executable with a child marker): passes argv through to
   livereact.__main__.main() unchanged;
4. with no arguments (a Finder double-click): reads the launch arguments from
   <data>/launch-args.txt (created with a commented default on first launch),
   falls back to the demo (with an on-screen alert) when the file's rig is
   missing or its arguments do not parse, passes the rig as an absolute path,
   and adds --log-file logs/app-<timestamp>.log unless the arguments
   already log to a file (--log-file, --record or --session-dir).

The helpers below are pure so tests/test_packaging_entry.py can run them
without PyInstaller.
"""

from __future__ import annotations

import datetime
import filecmp
import os
import shlex
import shutil
import sys
from pathlib import Path

APP_NAME = "LiveReact"
LAUNCH_ARGS_FILE = "launch-args.txt"
LAUNCHER_LOG = os.path.join("logs", "launcher.log")
DEMO_ARGS = ["--demo", "--visualize"]

DEFAULT_LAUNCH_ARGS_TEXT = """\
# LiveReact launch arguments, used when the app is opened from Finder.
# One line of arguments; lines starting with # are ignored. Quote paths that
# contain spaces. Relative paths are relative to this folder.
#
# If the --rig file below does not exist (or the arguments do not parse), the
# app starts the demo instead (--demo --visualize) and says why in
# logs/launcher.log.
#
# Examples:
#   --choose          (the launch dialog: pick the rig and options each time)
#   --demo --visualize
#   --hardware --visualize --record --rig rigs/josh_rig.json
--hardware --visualize --record --rig rigs/junior_crib.json
"""
# With the launch dialog available (livereact's --choose), a Finder launch
# asks instead of assuming a rig.
CHOOSE_LAUNCH_ARGS_TEXT = DEFAULT_LAUNCH_ARGS_TEXT.replace(
    "\n--hardware --visualize --record --rig rigs/junior_crib.json\n", "\n--choose\n")

# Flags that already route log output to a file.
_LOGGING_FLAGS = ("--log-file", "--record", "--session-dir")


# --------------------------------------------------------------------------- pure helpers
def _default_text(parse) -> str:
    """The first-launch launch-args.txt: --choose when this build has the
    launch dialog, a fixed rig line otherwise."""
    try:
        if getattr(parse(["--choose"]), "choose", False):
            return CHOOSE_LAUNCH_ARGS_TEXT
    except ValueError:
        pass
    return DEFAULT_LAUNCH_ARGS_TEXT


def parse_launch_args(text: str) -> list[str]:
    """Split launch-args.txt into argv. ``#`` comments and blank lines are
    ignored; non-comment lines are joined. Raises ValueError on bad quoting."""
    args: list[str] = []
    for line in text.splitlines():
        if line.strip().startswith("#"):
            continue
        args.extend(shlex.split(line, comments=True))
    return args


# Spellings argparse maps to --rig: the full name and its unambiguous prefix
# ("--r" also matches --rate and --record).
_RIG_SPELLINGS = ("--rig", "--ri")


def with_rig(args: list[str], rig: str) -> list[str]:
    """``args`` with every --rig value replaced by ``rig``; appended as
    ``--rig rig`` when no spelling of the option is found (argparse keeps the
    last value, so this is equivalent)."""
    out: list[str] = []
    replaced = False
    i = 0
    while i < len(args):
        arg = args[i]
        name, eq, _ = arg.partition("=")
        if name in _RIG_SPELLINGS and eq:
            out.append(f"--rig={rig}")
            replaced = True
        elif arg in _RIG_SPELLINGS and i + 1 < len(args):
            out += ["--rig", rig]
            replaced = True
            i += 1
        else:
            out.append(arg)
        i += 1
    return out if replaced else [*out, "--rig", rig]


def has_flag(args: list[str], name: str) -> bool:
    return any(a == name or a.startswith(name + "=") for a in args)


def with_log_file(args: list[str], now: datetime.datetime | None = None) -> list[str]:
    """Append ``--log-file logs/app-<timestamp>.log`` unless ``args`` already log
    to a file (--log-file, or --record / --session-dir which log into the
    session folder)."""
    if any(has_flag(args, f) for f in _LOGGING_FLAGS):
        return list(args)
    stamp = (now or datetime.datetime.now()).strftime("%Y%m%d-%H%M%S")
    return [*args, "--log-file", os.path.join("logs", f"app-{stamp}.log")]


def seed_rigs(src: Path, dest: Path) -> tuple[list[str], list[str]]:
    """Copy src/*.json into dest/, never overwriting an existing file.
    Returns (names copied, names kept although they differ from the bundled
    copy), so a newer bundled rig never silently replaces a calibrated one."""
    copied: list[str] = []
    differ: list[str] = []
    if not src.is_dir():
        return copied, differ
    dest.mkdir(parents=True, exist_ok=True)
    for f in sorted(src.glob("*.json")):
        target = dest / f.name
        if target.exists():
            if not filecmp.cmp(f, target, shallow=False):
                differ.append(f.name)
            continue
        shutil.copy2(f, target)
        copied.append(f.name)
    return copied, differ


def resolve_default_args(data_dir: Path, parse=None) -> tuple[list[str], str | None]:
    """Arguments for a Finder launch, read from <data_dir>/launch-args.txt
    (created with the default on first use). Returns (args, reason) where reason
    is a human-readable explanation when the demo fallback was used.

    ``parse(args)`` returns the parsed namespace (with a ``rig`` attribute) or
    raises ValueError; it defaults to livereact's own command-line parser. The
    rig is read from the namespace, so any spelling argparse accepts counts,
    and is passed on as an absolute path (``~`` expanded, relative paths taken
    from ``data_dir``)."""
    parse = parse or parse_livereact_args
    path = data_dir / LAUNCH_ARGS_FILE
    try:
        if not path.exists():
            path.write_text(_default_text(parse), encoding="utf-8")
        args = parse_launch_args(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return list(DEMO_ARGS), f"could not read {path}: {exc}"
    if not args:
        return list(DEMO_ARGS), f"{path} has no arguments"
    try:
        ns = parse(args)
    except ValueError as exc:
        return list(DEMO_ARGS), f"arguments in {path} do not parse: {exc}"
    if ns.rig is not None:
        rig_path = Path(ns.rig).expanduser()
        if not rig_path.is_absolute():
            rig_path = data_dir / rig_path
        if not rig_path.is_file():
            return list(DEMO_ARGS), f"rig file {rig_path} (from {path}) does not exist"
        args = with_rig(args, str(rig_path))
    return args, None


# --------------------------------------------------------------------------- side effects
def _bundled_rigs_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "rigs"
    return Path(__file__).resolve().parents[2] / "rigs"  # repo checkout (dev runs)


def _data_dir() -> Path:
    """~/LiveReact (or $LIVEREACT_HOME); falls back to
    ~/Library/Application Support/LiveReact if the home folder is not writable.
    Not ~/Documents (2026-10-16): Documents is privacy-protected, so an
    unsigned app's first file access there blocks until someone answers the
    macOS prompt, and a missed prompt in a dark booth looks like a dead app."""
    override = os.environ.get("LIVEREACT_HOME")
    candidates = [Path(override).expanduser()] if override else [
        Path.home() / APP_NAME,
        Path.home() / "Library" / "Application Support" / APP_NAME,
    ]
    last_exc: OSError | None = None
    for d in candidates:
        try:
            (d / "logs").mkdir(parents=True, exist_ok=True)
            return d
        except OSError as exc:
            last_exc = exc
    raise SystemExit(f"{APP_NAME}: no writable data folder ({last_exc})")


def _launcher_log(msg: str) -> None:
    try:
        with open(LAUNCHER_LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
    except OSError:
        pass


def parse_livereact_args(args: list[str]):
    """Parse with livereact's own parser; ValueError instead of exiting. Any
    exit counts as invalid, including --help / exit 0, since there would be
    no show to start."""
    import contextlib
    import io

    from livereact.__main__ import _parse_args

    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            return _parse_args(args)
    except SystemExit as exc:
        if exc.code in (0, None):
            raise ValueError("an option such as --help prints and exits "
                             "instead of starting a show") from None
        lines = err.getvalue().strip().splitlines()
        raise ValueError(lines[-1] if lines else f"the parser exited (code {exc.code})") from None


def _alert_demo_fallback(reason: str) -> None:
    """Show a macOS alert without blocking the launch; a Finder user has no
    other way to notice the fallback. The reason goes in as an osascript
    argument, so quotes in paths cannot break the script."""
    import subprocess

    try:
        subprocess.Popen(
            ["osascript",
             "-e", "on run argv",
             "-e", 'display alert "LiveReact started the DEMO" message (item 1 of argv)',
             "-e", "end run",
             f"{reason}\n\nEdit launch-args.txt in your LiveReact folder, then reopen the app."],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
    except OSError:
        pass


# Optional modules the app imports lazily; LIVEREACT_IMPORT_CHECK=1 imports
# them all and exits, to verify a build without hardware.
CHECK_MODULES = ("numpy", "sounddevice", "serial", "serial.tools.list_ports",
                 "mido", "mido.backends.rtmidi", "rtmidi",
                 "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets", "prodj.network.packets")


def _import_check() -> int:
    import importlib

    failed = 0
    for name in CHECK_MODULES:
        try:
            importlib.import_module(name)
            print(f"ok      {name}")
        except Exception as exc:  # noqa: BLE001
            optional = name == "prodj"  # git-only; the app degrades without it
            failed += 0 if optional else 1
            print(f"{'absent' if optional else 'FAILED'}  {name}: {exc}")
    if failed == 0:
        import sounddevice

        print(f"PortAudio: {sounddevice.get_portaudio_version()[1]}")
    return 1 if failed else 0


def main() -> int:
    if os.environ.get("LIVEREACT_IMPORT_CHECK"):
        return _import_check()

    # A windowed .app may have no usable stdio; give logging somewhere to write.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")  # noqa: SIM115

    data_dir = _data_dir()
    os.chdir(data_dir)
    try:
        copied, differ = seed_rigs(_bundled_rigs_dir(), data_dir / "rigs")
        if copied:
            _launcher_log(f"copied bundled rigs into {data_dir / 'rigs'}: {', '.join(copied)}")
        for name in differ:
            _launcher_log(f"kept your rigs/{name}; it differs from the bundled copy "
                          "(rename yours to get the bundled one)")
    except OSError as exc:
        _launcher_log(f"could not copy bundled rigs: {exc}")

    # Older macOS versions pass -psn_X_Y to Finder-launched apps.
    argv = [a for a in sys.argv[1:] if not a.startswith("-psn_")]
    finder_launch = not argv
    if finder_launch:
        argv, reason = resolve_default_args(data_dir)
        if reason:
            _launcher_log(f"falling back to the demo: {reason}")
            _alert_demo_fallback(reason)
        argv = with_log_file(argv)
        _launcher_log(f"launching from {data_dir} with: {shlex.join(argv)}")

    from livereact.__main__ import main as livereact_main

    try:
        return livereact_main(argv)
    except BaseException as exc:
        clean = isinstance(exc, KeyboardInterrupt) or (
            isinstance(exc, SystemExit) and exc.code in (0, None))
        if finder_launch and not clean:
            import traceback

            _launcher_log("LiveReact exited with an error:\n" + traceback.format_exc())
        raise


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    raise SystemExit(main())
