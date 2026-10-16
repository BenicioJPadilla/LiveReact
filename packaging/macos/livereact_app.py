"""Frozen entry point for the macOS LiveReact.app (PyInstaller).

LiveReact resolves config.json, midi_map.json, recordings/, logs/, diagnostics/
and --rig paths relative to the current directory. A Finder-launched .app starts
with CWD "/", so this entry point:

1. chdirs into a per-user data folder (~/Documents/LiveReact, or $LIVEREACT_HOME),
   creating it on first launch;
2. copies the bundled rigs/*.json into <data>/rigs/ without ever overwriting a
   file that is already there (it may hold Venue-tab calibration);
3. with command-line arguments (a terminal launch, or the in-app supervisor
   re-executing sys.executable with a child marker): passes argv through to
   livereact.__main__.main() unchanged;
4. with no arguments (a Finder double-click): reads the launch arguments from
   <data>/launch-args.txt (created with a commented default on first launch),
   falls back to the demo when the file's rig is missing or its arguments do not
   parse, and adds --log-file logs/app-<timestamp>.log unless the arguments
   already log to a file (--log-file, --record or --session-dir).

The helpers below are pure so tests/test_packaging_entry.py can run them
without PyInstaller.
"""

from __future__ import annotations

import datetime
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
#   --demo --visualize
#   --hardware --visualize --record --rig rigs/josh_rig.json
--hardware --visualize --record --rig rigs/junior_crib.json
"""

# Flags that already route log output to a file.
_LOGGING_FLAGS = ("--log-file", "--record", "--session-dir")


# --------------------------------------------------------------------------- pure helpers
def parse_launch_args(text: str) -> list[str]:
    """Split launch-args.txt into argv. ``#`` comments and blank lines are
    ignored; non-comment lines are joined. Raises ValueError on bad quoting."""
    args: list[str] = []
    for line in text.splitlines():
        if line.strip().startswith("#"):
            continue
        args.extend(shlex.split(line, comments=True))
    return args


def find_option(args: list[str], name: str) -> str | None:
    """Value of ``--name VALUE`` or ``--name=VALUE`` (last one wins), else None."""
    value = None
    for i, arg in enumerate(args):
        if arg == name and i + 1 < len(args):
            value = args[i + 1]
        elif arg.startswith(name + "="):
            value = arg[len(name) + 1:]
    return value


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


def seed_rigs(src: Path, dest: Path) -> list[str]:
    """Copy src/*.json into dest/, never overwriting an existing file.
    Returns the names copied."""
    copied: list[str] = []
    if not src.is_dir():
        return copied
    dest.mkdir(parents=True, exist_ok=True)
    for f in sorted(src.glob("*.json")):
        target = dest / f.name
        if target.exists():
            continue
        shutil.copy2(f, target)
        copied.append(f.name)
    return copied


def resolve_default_args(data_dir: Path, validate=None) -> tuple[list[str], str | None]:
    """Arguments for a Finder launch, read from <data_dir>/launch-args.txt
    (created with the default on first use). Returns (args, reason) where reason
    is a human-readable explanation when the demo fallback was used.

    ``validate(args)`` may raise ValueError with a message when the arguments
    do not parse (the real entry point wires in livereact's own parser)."""
    path = data_dir / LAUNCH_ARGS_FILE
    try:
        if not path.exists():
            path.write_text(DEFAULT_LAUNCH_ARGS_TEXT, encoding="utf-8")
        args = parse_launch_args(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return list(DEMO_ARGS), f"could not read {path}: {exc}"
    if not args:
        return list(DEMO_ARGS), f"{path} has no arguments"
    rig = find_option(args, "--rig")
    if rig is not None:
        rig_path = Path(rig).expanduser()
        if not rig_path.is_absolute():
            rig_path = data_dir / rig_path
        if not rig_path.is_file():
            return list(DEMO_ARGS), f"rig file {rig_path} (from {path}) does not exist"
    if validate is not None:
        try:
            validate(args)
        except ValueError as exc:
            return list(DEMO_ARGS), f"arguments in {path} do not parse: {exc}"
    return args, None


# --------------------------------------------------------------------------- side effects
def _bundled_rigs_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "rigs"
    return Path(__file__).resolve().parents[2] / "rigs"  # repo checkout (dev runs)


def _data_dir() -> Path:
    """~/Documents/LiveReact (or $LIVEREACT_HOME); falls back to
    ~/Library/Application Support/LiveReact if Documents is not writable."""
    override = os.environ.get("LIVEREACT_HOME")
    candidates = [Path(override).expanduser()] if override else [
        Path.home() / "Documents" / APP_NAME,
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


def _validate_with_livereact_parser(args: list[str]) -> None:
    import contextlib
    import io

    from livereact.__main__ import _parse_args

    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            _parse_args(args)
    except SystemExit as exc:
        if exc.code not in (0, None):
            raise ValueError(err.getvalue().strip().splitlines()[-1] if err.getvalue().strip()
                             else f"exit {exc.code}") from None


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
        copied = seed_rigs(_bundled_rigs_dir(), data_dir / "rigs")
        if copied:
            _launcher_log(f"copied bundled rigs into {data_dir / 'rigs'}: {', '.join(copied)}")
    except OSError as exc:
        _launcher_log(f"could not copy bundled rigs: {exc}")

    # Older macOS versions pass -psn_X_Y to Finder-launched apps.
    argv = [a for a in sys.argv[1:] if not a.startswith("-psn_")]
    finder_launch = not argv
    if finder_launch:
        argv, reason = resolve_default_args(data_dir, validate=_validate_with_livereact_parser)
        if reason:
            _launcher_log(f"falling back to the demo: {reason}")
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
