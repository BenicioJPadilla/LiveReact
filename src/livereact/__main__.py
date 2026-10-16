"""Command-line entry point: ``python -m livereact`` (or the ``livereact`` script)."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from .app import App, AppConfig


def _configure_logging(level: str, log_file: str | None = None, error_file: str | None = None) -> None:
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(threadName)-12s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for h in list(root.handlers):  # reset (idempotent across calls/tests)
        root.removeHandler(h)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    if log_file:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    if error_file:
        eh = logging.FileHandler(error_file, encoding="utf-8")
        eh.setLevel(logging.WARNING)  # just problems, for a quick scan
        eh.setFormatter(fmt)
        root.addHandler(eh)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="livereact",
        description="Beat-reactive DMX stage-lighting controller for live DJ sets.",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--demo", action="store_true", help="Run with synthetic data, no hardware (default).")
    mode.add_argument("--hardware", action="store_true",
                      help="Use real devices (Enttec DMX + Pro DJ Link + XDJ MIDI/audio). Pair with --rig rigs/josh_rig.json.")
    p.add_argument("--rate", type=float, default=40.0, dest="rate", help="DMX refresh rate in Hz (default: 40).")
    p.add_argument("--duration", type=float, default=None, help="Run for N seconds then exit (default: until Ctrl-C).")
    p.add_argument("--visualize", action="store_true", help="Open the operator console + virtual rig (PySide6).")
    p.add_argument("--pdl-interface", default=None, help="Explicit network interface/IP for Pro DJ Link.")
    p.add_argument("--rig", default=None, help="Path to a custom rig JSON (default: the packaged 8-fixture default_rig.json).")
    p.add_argument("--full-catalog", action="store_true",
                   help="Rotate the full scene catalog instead of the default one-look-per-bucket core set.")
    p.add_argument("--bible-failsafe", action="store_true",
                   help="Bible-integration Phase 1 (gig-safe migration flag, off by default): "
                        "when set, the no-music auto-blackout failsafe fades to a real safe_default "
                        "look (LIGHTING_BIBLE.md LOOK-08) instead of an instant hard blackout. "
                        "The operator's own manual blackout switch is unaffected either way.")
    p.add_argument("--no-norm-seed", action="store_true",
                   help="Cold-start the energy normalizer instead of seeding it from the last "
                        "session's saved range (new venue / re-gained mixer).")
    p.add_argument("--audio-device", default=None, help="Explicit audio input device name/index for real audio analysis (default: auto-detect the XDJ).")
    p.add_argument("--log-level", default="INFO", help="DEBUG, INFO, WARNING, ERROR (default: INFO).")
    # Recording / feedback (capture a session to hand back for analysis).
    p.add_argument("--record", action="store_true", help="Record this session (logs + state + notes) to recordings/.")
    p.add_argument("--session-dir", default=None, help="Where to record (default: recordings/session-<timestamp>).")
    p.add_argument("--log-file", default=None, help="Also write all log output to this file.")
    # Hardware bring-up tools (each runs and exits).
    p.add_argument("--fixture-test", action="store_true", help="Open the manual fixture-test panel (drive raw DMX).")
    p.add_argument("--midi-monitor", action="store_true", help="Print/record incoming MIDI to remap the XDJ, then exit.")
    p.add_argument("--net-check", action="store_true", help="Print Pro DJ Link network diagnostics and exit.")
    p.add_argument("--doctor", action="store_true", help="Write an environment/device diagnostics report and exit.")
    p.add_argument("--bundle", nargs="?", const="__latest__", default=None,
                   help="Zip a session folder for sharing (default: the latest), then exit.")
    p.add_argument("--choose", action="store_true",
                   help="Open the launch dialog first to pick the rig, mode and options "
                        "(remembered in last-launch.json). Quit there exits.")
    p.add_argument("--force-start", action="store_true",
                   help="EMERGENCIES ONLY: start a --hardware show even though the light "
                        "adapter or the DJ board was not detected. The console shows a "
                        "warning banner for the whole set.")
    return p


def _parse_args(argv: list[str]) -> argparse.Namespace:
    return _build_parser().parse_args(argv)


# Options the launch dialog decides; everything else on a --choose command
# line (--log-file, --rate, ...) is passed through. value: takes an argument.
_CHOSEN_OPTIONS = {"--demo": False, "--hardware": False, "--visualize": False, "--record": False,
                   "--rig": True, "--audio-device": True, "--phone": None, "--choose": False}


def _passthrough(argv: list[str]) -> list[str]:
    """``argv`` minus the options the dialog chooses (and their values)."""
    out: list[str] = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        opt = tok.split("=", 1)[0]
        if opt in _CHOSEN_OPTIONS:
            takes = _CHOSEN_OPTIONS[opt]
            if "=" not in tok and i + 1 < len(argv):
                nxt = argv[i + 1]
                if takes or (takes is None and not nxt.startswith("-")):  # --phone [PORT]
                    i += 1
            i += 1
            continue
        out.append(tok)
        i += 1
    return out


def _choose(argv: list[str]) -> list[str] | None:
    """Run the launch dialog; the argv to continue with, or None on Quit.
    Raises ImportError when PySide6 is missing."""
    from .ui.launch_dialog import choose_launch_args

    phone = "--phone" in _build_parser()._option_string_actions
    chosen = choose_launch_args(os.getcwd(), phone_supported=phone,
                                force_start="--force-start" in argv)
    if chosen is None:
        return None
    return _passthrough(argv) + chosen


def _is_tool(args: argparse.Namespace) -> bool:
    """A bring-up tool that runs and exits (never gated: it is how gear is checked)."""
    return bool(args.doctor or args.bundle is not None or args.net_check
                or args.midi_monitor or args.fixture_test)


def _gear_gate(args: argparse.Namespace) -> tuple[bool, str]:
    """The --hardware start gate: (start?, the note for the console banner).
    Refuses (printing what is missing) when the light adapter or the DJ board
    is not detected, unless --force-start; "" note when nothing is missing."""
    from .devices import describe, detect_once

    det = detect_once(args.audio_device or "")
    if det.ok:
        print(f"Gear check:\n{describe(det)}")
        return True, ""
    missing = " and the ".join(det.missing())
    if not args.force_start:
        print(f"livereact: not starting the live show, the {missing} "
              f"{'is' if len(det.missing()) == 1 else 'are'} not connected.\n{describe(det)}\n"
              "Plug it in and start again, or use --demo. Emergencies only: --force-start.",
              file=sys.stderr)
        return False, ""
    print(f"WARNING: --force-start: starting without the {missing}.\n{describe(det)}", file=sys.stderr)
    return True, f"Forced start: no {missing} at launch. Check the gear."


def _bundle(which: str, log) -> int:
    """Zip a session folder into a single file for sharing."""
    import glob
    import shutil

    if which == "__latest__":
        sessions = sorted(glob.glob(os.path.join("recordings", "session-*")))
        if not sessions:
            log.error("No sessions found in recordings/.")
            return 1
        which = sessions[-1]
    if not os.path.isdir(which):
        log.error("Not a session directory: %s", which)
        return 1
    archive = shutil.make_archive(which.rstrip("/\\"), "zip", which)
    print(f"Bundled {which} -> {archive}")
    return 0


def _bringup_backend(demo: bool, rate: float):
    """Backend for the fixture-test tool: Enttec in hardware mode (fallback to
    NullLog), NullLog in demo."""
    from .output.null_log import NullLogBackend

    if not demo:
        try:
            from serial.tools import list_ports

            from .output.enttec import EnttecSerialBackend, select_enttec_port

            if select_enttec_port(list_ports.comports()):
                return EnttecSerialBackend()
            logging.getLogger("livereact").warning("No Enttec detected; using null backend.")
        except Exception:  # noqa: BLE001
            logging.getLogger("livereact").exception("Enttec unavailable; using null backend.")
    return NullLogBackend(log_every=int(rate))


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to cp1252; ensure UTF-8 so diagnostics/logs never
    # crash on a non-ASCII character.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass

    from_cli = argv is None
    argv = list(sys.argv[1:] if from_cli else argv)
    args = _parse_args(argv)

    # --choose: the launch dialog runs once, here, before any session dir or
    # log file exists; its answer is parsed as if it had been typed. Never in
    # an engine child (the supervisor's relaunch): that one gets the chosen
    # args, which do not contain --choose.
    engine_child = getattr(args, "engine_child", False)
    chose = False
    if args.choose and not engine_child:
        try:
            chosen = _choose(argv)
        except ImportError as exc:
            print(f"livereact: --choose needs PySide6 for the launch dialog ({exc}). "
                  'Install it with: python -m pip install -e ".[ui]"', file=sys.stderr)
            return 1
        if chosen is None:
            return 0
        argv = chosen
        chose = True
        if from_cli:
            sys.argv[1:] = argv  # anything that re-reads the command line sees the choice
        args = _parse_args(argv)

    demo = not args.hardware  # demo is the default; --demo is explicit-but-redundant

    # The gear gate: a live show starts only with the light adapter and the DJ
    # board detected. Before any session folder, so a refusal leaves nothing
    # behind. Not for the tools, not for an engine child (a crash relaunch
    # mid-set must never be held up), and not after the launch dialog, whose
    # Start already was the gate (except --force-start: the banner needs it).
    force_note = ""
    if not demo and not _is_tool(args) and not engine_child and (not chose or args.force_start):
        ok, force_note = _gear_gate(args)
        if not ok:
            return 2

    # Resolve a session directory if recording, and route logs into it.
    session_dir = None
    if args.record or args.session_dir:
        from .recorder import create_session_dir

        session_dir = args.session_dir or create_session_dir()
        os.makedirs(session_dir, exist_ok=True)  # an explicit --session-dir may not exist yet
    log_file = (os.path.join(session_dir, "session.log") if session_dir else args.log_file)
    error_file = os.path.join(session_dir, "errors.log") if session_dir else None
    _configure_logging(args.log_level, log_file=log_file, error_file=error_file)
    log = logging.getLogger("livereact")

    # --- standalone tools (run and exit) ---
    if args.doctor:
        from .diagnostics import write_report

        os.makedirs("diagnostics", exist_ok=True)
        path = os.path.join("diagnostics", "doctor.txt")
        env = write_report(path)
        from .diagnostics import format_report
        print(format_report(env))
        print(f"\nWritten to {path} (+ .json) — hand this back for analysis.")
        return 0
    if args.bundle is not None:
        return _bundle(args.bundle, log)
    if args.net_check:
        from .network import diagnostics
        print(diagnostics())
        return 0
    if args.midi_monitor:
        from .inputs.midi import monitor

        out = os.path.join(session_dir, "midi-monitor.txt") if session_dir else "midi-monitor.txt"
        monitor(duration=args.duration, out_path=out)
        print(f"MIDI capture written to {out}")
        return 0
    if args.fixture_test:
        from .clock import RealClock
        from .fixtures.rig import load_rig
        from .ui.fixture_test import run_fixture_test
        rig = load_rig(args.rig)
        backend = _bringup_backend(demo, args.rate)
        log.info("Fixture test using backend: %s", backend.name)
        run_fixture_test(rig, backend, RealClock(), dmx_rate_hz=args.rate, rig_path=args.rig)
        return 0

    config = AppConfig(demo=demo, dmx_rate_hz=args.rate, duration=args.duration,
                       pdl_interface=args.pdl_interface, rig_path=args.rig,
                       audio_device=args.audio_device,
                       norm_seed=not args.no_norm_seed,
                       bible_failsafe_enabled=args.bible_failsafe,
                       full_catalog=args.full_catalog, force_start_note=force_note,
                       record=bool(session_dir), session_dir=session_dir)
    app = App(config)

    if args.visualize:
        # Qt must own the main thread: run the pipeline in the background and the
        # operator console here; closing the window shuts everything down.
        from .ui.console import run_console

        app.install_signal_handlers()
        app.start()
        try:
            run_console(app)
        finally:
            app.shutdown()
    else:
        app.serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
