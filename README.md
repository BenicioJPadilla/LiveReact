# LiveReact

A beat-reactive DMX stage-lighting controller for live DJ sets. It listens to
the music (real audio analysis from the DJ board's USB audio interface, plus
Pro DJ Link beat-grid timing and read-only MIDI from a Pioneer XDJ-XZ when
present), classifies the set's energy (BREAK / BUILD / DROP / PEAK / OUTRO),
and drives a DMX rig through an Enttec DMX USB Pro at 40 Hz. **Automation is
the default**; a human only nudges brightness, strobe cap, blackout, and
(on some rigs) laser cues.

It has run real sets: a bar residency, a Thai-restaurant set (two lasers + a
wash bar), and a house-party rig with two moving heads, two lasers and a wash
bar. Everything in `rigs/` reflects fixtures verified on hardware by channel
probing, not datasheets.

Design history lives in [`docs/`](docs/) — start with
[`docs/00_EXECUTIVE_SUMMARY.md`](docs/00_EXECUTIVE_SUMMARY.md). The original
build checklist is [`PLAN.md`](PLAN.md) (frozen at the end of the clean-room
rebuild; see its scope note), deferred hardware/usage decisions are in
[`ASSUMPTIONS.md`](ASSUMPTIONS.md), and the hardware test procedure is in
[`TESTING.md`](TESTING.md).

## Status

**Deployed and gigging.** The full pipeline (inputs → ShowState → Reactive +
Phrase + Transition engines → priority merge / safety → DMX writer) runs on real
hardware with an operator console. The Enttec serial output, real audio
capture + FFT analysis, Pro DJ Link beat grid, and MIDI input have all been
verified on the physical rig. `--hardware` still degrades gracefully: with no
Enttec it keeps looking for one and starts sending when it's plugged in; with no XDJ, point
`--audio-device` at the laptop mic and beat timing falls back to tap tempo and
a free-running metronome.

Known rough edges, tracked in the repo rather than hidden:

- `tests/test_spec_conformance_gaps.py` holds **3 known-gap tests** that encode
  spec behaviour the merge/failsafe code does not yet implement. They are
  marked `xfail(strict=True)`: the suite stays green, and a gap that starts
  passing fails the run until its marker comes off.
- Python 3.14's garbage collector has segfaulted inside the show-engine thread
  on live nights. Shows run on Python 3.13 (`.venv313`), which has not
  reproduced it; `pyproject.toml` caps installs below 3.14, and the app's own
  supervisor (`src/livereact/supervisor.py`) relaunches the engine after a crash. Every show run
  arms a crash log (`logs/crash-*.log`, Python stacks of every thread even on
  a segfault; empty ones are removed on a clean exit), and `--hardware` runs
  always write `logs/launch-*.log` when no other log file is given.
- The Enttec is hot-pluggable (2026-10-16): absent at launch or pulled mid-set,
  the DMX writer keeps retrying about once a second and output resumes by
  itself within about a second of plugging it back in. No relaunch needed.
- The fixture-side strobe flash rate is set by a static DMX byte, so photosensitive-safety
  frequency limits cannot be enforced in software. See `spec/LIGHTING_BIBLE.md`.

## Running it

```bash
# Demo mode: synthetic music, no hardware, operator console + virtual rig
.venv/bin/python -m livereact --demo --visualize

# A live night: hardware, recording, a specific rig. Any --hardware run is
# supervised: if the engine crashes it is relaunched within ~1 s, with the
# operator's blackout / brightness / strobe cap / laser disarm restored
# (logs/supervisor.log says when and why). --no-supervise turns that off.
python -m livereact --hardware --visualize --record --rig rigs/junior_crib.json --audio-device 1
#   or, with the .venv313 interpreter and a per-night log:
nohup tools/run_show.sh --hardware --visualize --record --rig rigs/junior_crib.json \
    --audio-device 1 > logs/watchdog.log 2>&1 & disown
#   stop it: close the window (or touch logs/STOP, then close it)

# Bring-up and diagnostics
python -m livereact --fixture-test           # drive raw DMX channels
python -m livereact --midi-monitor           # discover the XDJ's MIDI CCs
python -m livereact --net-check              # Pro DJ Link network readiness
python -m livereact --doctor                 # environment + detected-devices report
python -m livereact --strobe-calibrate --hardware --rig rigs/josh_rig.json   # measure strobe byte -> Hz (bench only, TESTING.md Test 7)
```

Useful flags: `--rig <json>` (fixtures + laser profile), `--audio-device
<name|index>` (default: auto-detect the XDJ; `1` is usually the MacBook mic),
`--record` (logs + state + notes into `recordings/session-<timestamp>/`),
`--full-catalog` (rotate all 29 scenes instead of the 6-scene core set),
`--bible-failsafe` (fade to a safe-default look instead of hard blackout when
music stops), `--no-norm-seed` (cold-start the energy normaliser at a new venue).
`python -m livereact --help` lists the rest.

A double-click macOS app (no terminal or venv) can be built with
`packaging/macos/build_app.sh`; see `packaging/macos/README.md`.

No terminal needed: `python -m livereact --choose` opens a launch dialog first
(rig from `rigs/` in the current folder or Browse..., Live show or Demo, Record
this session, audio device). Start runs exactly the command line those choices
stand for, with the console; Quit exits. The last choice is remembered in
`last-launch.json` next to `rigs/` and prefilled next time. Any other flags on
the `--choose` command line (`--log-file`, `--rate`, ...) are kept. Not for
`tools/run_show.sh`: its crash relaunch would ask again.

**The gear gate.** A live show needs the gear plugged in. The dialog's Gear card
checks about once a second for the light adapter (the Enttec, with its model and
serial number) and the DJ board (the XDJ's USB audio or MIDI, or its Pro DJ
Link keepalives). **Start** stays off for a live show until both are found and
turns on the moment they are; demo is never gated. The rig is picked by itself
when that adapter was used with a rig before (`rig-by-adapter.json` in
`~/LiveReact`, or `$LIVEREACT_HOME`); the first time, it asks. `--hardware`
on the command line does the same check and refuses to start, printing what is
missing. **`--force-start` is for emergencies only**: it starts anyway, and the
console shows a red warning banner for the whole set (in the Mac app, add it to
the `--choose` line of `~/LiveReact/launch-args.txt`). Once a show is running
nothing is gated: a pulled cable is handled by hot-plug and the failsafes.
Plain DMX is one-way, so the lights themselves cannot be detected (LiveReact
has no RDM); the Gear card lists the rig's fixtures and **Flash each light**
opens the fixture test to confirm each one by eye.

### Rigs and laser profiles

`--rig rigs/<file>.json` picks the fixtures, their DMX addresses, the venue
geometry, and the **laser profile** (`fixtures/rig.py`, `LASER_PROFILES`):

| Profile | Behaviour | Engine | Rig(s) |
|---|---|---|---|
| `accent` | One sweep per 8-bar block during a PEAK | `engines/laser.py` | `josh_rig.json` (default when unset) |
| `feature` | Two lasers as the main light, lit for the whole set | `engines/laser_feature.py` | `bar_rig.json` |
| `trigger` | Lasers as punctuation: dark by default, 2-bar moments on drop hits and sustained peaks; **J** fires one now, **K** holds | `engines/laser_trigger.py` | `testing_setup.json` (garage truss rig) |
| `show` | Lasers lit all set; follow-the-music / rotate / hold modes and the looks in the console's Pro controls (Lasers) | `engines/laser_show.py` | `sophias_thai*.json` |
| `manual` | Nothing listens to the music; scene cue buttons (OFF + Rainbow, Slow Rainbow, Rainbow Dots, Blue Sweep, White, Green) in the console's Pro controls (Lasers), off at launch | `engines/laser_manual.py` | `junior_crib.json` |

After a drop, moving heads run `scenes/movement.py`'s tempo-locked shapes
inside a per-head **motion box** (pan/tilt boundaries captured live from the
Lights page, Room) around the calibrated crowd aim.

### The console

With `--visualize`, a sidebar picks the page:

- **Live**: the floor plan lit by the show with a plain-language status
  ("Listening.", "Blackout."), the beat, what the music is doing and the last
  two minutes as sections; Brightness and the **Blackout** key (B).
  **Pro controls** (the switch top right, remembered between launches) adds
  Moments (build C, drop D, strobe burst Space, next look →, freeze F, tap T),
  Lasers (arm L, hit J, hold K, and the `show` / `manual` rig controls), Feel
  (strobe limit, warm/cool, Synth Sync S) and Under the hood (BPM, section,
  link dots, activity). While Pro controls are hidden only B works from the
  keyboard. The first time lasers are armed in a run that started with them
  off, the console asks to confirm the mounting first.
- **Lights**: Room (editable floor plan in feet, per-fixture
  position/height/facing, moving-head calibration: jog live, set aim, capture
  motion-box bounds, save rig) and Addresses (the rig table).
- **Phone remote** and **Safety**: what the phone console and the safety rules
  do, in plain words.

### Phone console

`--phone [PORT]` (default port 8765, off unless passed) serves a small web page
on the laptop's network so a phone on the same Wi-Fi can make the show
**safer**, never more intense:

- **Blackout**: on only. Releasing it is the laptop's job (B / the console button),
  so use `--phone` with `--visualize`: headless, only a restart clears it (a
  warning is logged).
- **Dim**: brightness can only go down (-10 %, 50 %, 25 %).
- **Strobe**: the strobe cap can only go down (cap 50 %, strobe off).
- **Lasers**: disarm only, never arm.

Blackout and disarm also release FREEZE, since a held frame may contain a lit
laser (and blackout always wins over freeze in the show engine anyway).

The server enforces these rules, not just the page: anything that would raise
intensity is refused and changes nothing. The page also shows the bucket, BPM,
scene, the current caps, whether DMX is connected, and which phone controls
have been used. Access needs a 6-character code generated at every launch; the
full URL including it (`http://<laptop IP>:8765/?k=XXXXXX`) is logged at
startup. Each request has a 10 s deadline and at most 16 connections are
served at once, so a misbehaving client on the Wi-Fi can lock the phone out but
cannot pile up threads on the laptop. Dim and strobe-cap changes are saved to `config.json` at shutdown, like
the laptop sliders. Stdlib only, no new dependencies; see `src/livereact/remote/`
and TESTING.md Test 8. On a Mac, allow incoming connections when the firewall asks.

## Quick start

Python **3.13** for shows (3.12 also works). `pyproject.toml` refuses 3.14,
whose garbage collector crashed mid-set (see Status), and the app warns at
launch if it finds itself on one anyway.

```bash
# macOS / Linux
python3.13 -m venv .venv
.venv/bin/python -m pip install -e ".[ui,hardware,dev]"
.venv/bin/python -m livereact --demo --duration 3     # short headless demo
.venv/bin/python -m pytest                            # test suite

# Windows (PowerShell)
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[ui,hardware,dev]"
.venv\Scripts\python -m livereact --demo --duration 3
.venv\Scripts\python -m pytest
```

Extras: `ui` (PySide6 console), `hardware` (pyserial, mido, python-rtmidi,
sounddevice, numpy), `net` (Art-Net output), `dev` (pytest). Pro DJ Link needs
the git-only `python-prodj-link` library; see [`HARDWARE.md`](HARDWARE.md).
The dev launchers `run.bat` / `./run.command` start demo mode from `.venv`.

CI (`.github/workflows/ci.yml`) runs the suite on macOS, Windows and Linux.
`tests/test_golden_frames.py` replays every rig's demo show (a scripted
break, build, drop and peak) and compares each DMX frame's hash with
`tests/golden/frames.json`. If a change is meant to alter the show,
re-record with `python tests/golden_frames.py --update` and say so in the PR.

## Lighting spec & look library

The *content* of the show — which look plays for a given energy state, its
colours and movement, how it degrades — is driven by
[`spec/LIGHTING_BIBLE.md`](spec/LIGHTING_BIBLE.md), a normative lighting-design
spec, with [`spec/conformance.md`](spec/conformance.md) tracking implementation
status rule by rule and
[`docs/bible_integration/RULES_MATRIX.md`](docs/bible_integration/RULES_MATRIX.md)
the current state. [`src/livereact/scenes/library.py`](src/livereact/scenes/library.py)
holds 29 scenes across every energy bucket; a core set of 6 (one per bucket, two
for BREAK) rotates by default. A few Bible-named looks are deliberately
deferred and documented in-code, pending hardware this rig lacks (a gobo wheel,
haze).

## Layout

```
src/livereact/
  __main__.py / app.py   CLI entry point; supervisor that wires components and owns shutdown
  clock.py               Clock / RealClock / FakeClock + drift-corrected LoopTimer
  core/                  ShowState, Metronome, show engine, build/rise/snare/silence detectors
  inputs/                InputSource interface; demo, real audio (FFT), Pro DJ Link, MIDI
  engines/               Reactive / Phrase / Transition layers, colour + palette, 5 laser profiles
  scenes/                29-scene library, catalog, tempo-locked moving-head movement
  merge/                 priority merge + manual caps + safety clamps
  fixtures/              fixture profiles, rig loader/saver, venue geometry + head calibration
  output/                backend interface, null/log backend, Enttec serial, 40 Hz writer
  ui/                    PySide6 console (Live / Lights / Phone remote / Safety), floor plan, visualizer
  remote/                opt-in phone console (--phone): stdlib web page that can only make the show safer
  recorder.py, diagnostics.py, network.py, tap_tempo.py, dynamics.py
rigs/                    rig JSON files (fixtures, addresses, venue geometry, laser profile)
spec/                    LIGHTING_BIBLE.md + conformance.md
tools/                   run_show.sh (picks .venv313), laser_probe.py, offline simulators / replays
tests/                   pytest suite (deterministic via FakeClock); golden_frames.py hashes
                         every rig's demo show so a PR proves the looks are unchanged
```

## Design notes baked into the foundation

- **Injected clock everywhere** — real-time logic is unit-testable; a 90-min show
  simulates in milliseconds.
- **Double-buffered DMX** — the writer always emits the last *complete* frame, so
  an engine stall holds the lights steady instead of flickering.
- **The writer never stops** — every backend fault is contained; it reopens with
  backoff and keeps ticking.
- **Output behind an interface** — null/log, Enttec serial and Art-Net are
  swapped without touching engine code.
- **Real-time audio discipline** — the capture callback only copies into a ring
  buffer; FFT and band analysis run on a separate thread.
- **Verified on hardware, not assumed** — channel maps, addresses, and the
  XDJ's audio-over-USB path were each confirmed on the rig before being relied on.

## License

[MIT](LICENSE).
