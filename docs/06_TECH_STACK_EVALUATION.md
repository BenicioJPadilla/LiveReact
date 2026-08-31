# 06 — Tech-Stack Evaluation ("challenge everything")

You asked for the locked stack to be challenged from first principles, not accepted. Here is the honest evaluation: **language, Python version, UI toolkit, and key libraries**, each with a recommendation. Sources are inline.

---

## 1. Language: keep Python (the ecosystem decides it)

The spec mandates Python; challenging it fairly, **Python wins anyway**, for one decisive reason: **the DJ/lighting integration layer lives in Python and nowhere else convenient.**

- `python-prodj-link` — the de-facto open Pro DJ Link library (github.com/flesniak/python-prodj-link).
- `mido` + `python-rtmidi` — the standard Python MIDI stack.
- `pyserial` — serial/DMX.

The only mature **non-Python** Pro DJ Link implementation is **Java `beat-link`** (Deep Symmetry). Everything else (Node `prolink-connect`, Go `prolink-go`) is stale/experimental. So your realistic choices are "Python in-process" or "another language + a Java/Python sidecar for PDL." Rewriting the reverse-engineered protocol yourself is a months-long tax for zero functional gain.

| Alternative | Verdict for LiveReact |
|---|---|
| **Rust** | Best real-time/jitter profile, great Tauri UI — but you'd reimplement PDL and lose mido/pyserial ergonomics. Justified only if jitter becomes a *proven* problem. Overkill. |
| **C# / .NET** | Excellent cross-platform real-time + UI, decent MIDI/serial — but **no PDL library**; you'd port the protocol. No. |
| **TypeScript/Node + Electron/Tauri** | Beautiful UIs, but weaker serial/MIDI/PDL story and you'd still want a Python/Java PDL sidecar → polyglot. No. |
| **Go** | Great concurrency, weak desktop-UI and DJ-ecosystem story. No. |

**Is the GIL a problem at ~60 Hz?** No. The workload is soft-real-time and I/O-adjacent, not CPU-bound; blocking serial/UDP/MIDI/sleep all release the GIL. 16 ms (60 Hz) / 22 ms (44 Hz) budgets have enormous headroom for interpreted code. Free-threaded ("no-GIL") Python is officially supported in 3.14 (PEP 779) but it's a separate build, your GUI/MIDI extensions aren't validated for it in mid-2026, and you're not CPU-bound — so it buys little. **Decision: standard GIL CPython, threaded design, written free-threading-clean so you could flip it later.**

> **Recommendation:** **Python, standard GIL build.** Revisit free-threading in 2027+ once native wheels catch up.

---

## 2. Python version: 3.11 or 3.12 — NOT the spec's 3.14

This is the **highest-leverage single decision in the whole rebuild**, and it reverses the spec. Two independent, concrete reasons:

1. **MIDI wheels.** `python-rtmidi` (mido's backend) ships prebuilt binary wheels on PyPI for **CPython 3.8–3.12** on Windows + macOS, but **no cp313/cp314 wheels** as of mid-2026 (latest release 1.5.8). On 3.13/3.14, `pip install` tries to **build from source** → needs MSVC Build Tools on Windows / Xcode CLT on macOS → a miserable end-user install. (Source: pypi.org/project/python-rtmidi, github.com/SpotlightKid/python-rtmidi/releases.)
2. **Timing is already solved at 3.11.** The high-resolution `time.sleep()` on Windows (via `CREATE_WAITABLE_TIMER_HIGH_RESOLUTION`) that makes a steady 44 Hz writer achievable landed in **CPython 3.11** (cpython#89592). You do **not** need 3.14 to get it.

Also: `python-prodj-link`'s dependency `netifaces` is fragile to install on the newest Pythons (no wheels, build failures); pinning lower sidesteps it (or swap to `netifaces2`/`psutil`).

> **Recommendation:** **Target CPython 3.12** (3.11 acceptable). One decision retires both the MIDI-install risk and the Windows-timing risk. The spec's "3.11+ should work" footnote is actually the right guidance; its "3.14 target" headline is not.

---

## 3. UI toolkit: drop tkinter

tkinter is the spec's only stack choice with a **hard ceiling exactly where this project needs headroom**: a 60 Hz live console + a smooth 2-D rig visualizer + a modern look on two OSes. Evaluation of the realistic options:

| Toolkit | Fit for a real-time console + visualizer | Verdict |
|---|---|---|
| **tkinter** (stdlib) | Zero-install, fast first prototype. But `Canvas` is retained-mode (create/delete/`coords` churn at 60 Hz gets sluggish, flickers); no GPU; dated macOS dark-mode/HiDPI quirks; official installers still bundle Tcl/Tk 8.6. | **Don't ship it.** Emergency fallback only. |
| **PySide6 (Qt6)** | `QGraphicsView`/`QGraphicsScene` is purpose-built for an interactive 2-D rig; native, fast, professional look on both OSes; **LGPLv3** (ship closed apps freely, unlike PyQt6's GPL/commercial). **Already pulled in transitively by `python-prodj-link` (PyQt5)**, so Qt is in your tree anyway. Heaviest bundle (~40–150 MB; trim modules). | **Primary recommendation.** |
| **Dear PyGui** | GPU immediate-mode (Dear ImGui); *ideal* for high-rate meters and a drawn rig — no retained-tree churn. Production-stable in 2026 (2.3.1, May 2026). Smaller ecosystem/theming; "instrument-panel" aesthetic; different mental model. | **Strong backup** — pick it if you value a lean GPU instrument panel over Qt's breadth. |
| **Local web UI** (FastAPI + WebSocket + browser Canvas/WebGL, optionally `pywebview`) | Best-looking visualizer ceiling; tablet-at-FOH for free. But two languages/toolchains, a 60 Hz telemetry push loop to maintain, fiddlier one-click launch. | **Third option** — only if the visualizer/looks become the centerpiece. |
| Kivy / Toga / Flet / NiceGUI / Textual | Kivy: non-native, overkill. Toga: immature for dense dashboards. Flet: pretty but weak for a custom rig canvas. NiceGUI: the web route with less control. Textual: great headless debug TUI, no graphical visualizer. | Skip for v1 (Textual useful as a secondary debug console). |

> **Recommendation:** **PySide6 (primary), Dear PyGui (backup).** Keep the UI thread strictly separate from the engine/writer threads and marshal updates via Qt queued signals (never touch widgets off the GUI thread).

---

## 4. Key libraries — health & recommendation (mid-2026)

| Need | Recommended | State / risk |
|---|---|---|
| **Pro DJ Link** | `python-prodj-link` (flesniak), hardened | Lightly maintained (last commit ~May 2025), **git-only** (not on PyPI → vendor or pin a SHA), auto-guesses interface (patch in an explicit IP/subnet override), depends on `netifaces`+PyQt5+PyOpenGL (strip Qt/GL for headless; swap netifaces). **Biggest-reliability alternative:** Java **beat-link** as a sidecar (best-maintained, XDJ-XZ-confirmed) if PDL reliability becomes paramount. |
| **MIDI** | `mido` + `python-rtmidi` | Standard; wheels for 3.8–3.12 (← pin Python accordingly). Substring port-matching; handle Windows single-client open failure. |
| **Serial/DMX** | `pyserial` 3.5 | Solid cross-platform. Detect Enttec by FTDI VID/PID; use macOS `cu.*` node. |
| **Enttec framing** | Roll your own (~30 lines) or `DMXEnttecPro` | The Widget frame is trivial; rolling your own removes a dependency-health risk and gives you control of the refresh loop (the part that matters). `DMXEnttecPro`/`pyenttec` exist but verify current maintenance before depending. |
| **Art-Net/sACN (optional backend)** | `pyartnet` (v2.0, Nov 2025) or `sacn` | OS-agnostic (pure UDP, no drivers); great for testing against QLC+/Resolume and for Ethernet-DMX nodes. `stupidArtnet` is a simpler alternative. |
| **Numerics** | `numpy` | Only if you need vectorized channel math/DSP; releases the GIL on big ops. Not required for a 74-channel rig. |
| **Interface enumeration** | `psutil` or `netifaces2` | Replace fragile classic `netifaces` for PDL interface selection on newer Python. |

---

## 5. Packaging & one-click launch (cross-platform)

The spec wants double-click launch; macOS used `.command`, Windows needs its own path. **Under the macOS-first decision ([07](07_CROSSPLATFORM_STRATEGY.md)), the signed + notarized macOS `.app` is the primary deliverable; treat a Windows `.exe` as a later, optional build.**

- **PyInstaller** (`--onedir`, not `--onefile`) is the workhorse for bundling native deps (`python-rtmidi`, pyserial backends, Qt plugins) into a Win `.exe` + macOS `.app`. `--onefile` triggers more AV flags and slow cold-start.
- **Realistic pain points:** Windows **antivirus false positives** on PyInstaller bootloaders (mitigate with an **Authenticode code-signing cert**); macOS **Gatekeeper** requires **signing + notarization** (`codesign -o runtime` + `notarytool`, needs a **$99/yr Apple Developer account**); bundled serial/MIDI native libs are the usual "works in `python main.py`, missing in the bundle" culprits — **test the packaged artifact on a clean machine**. Trim unused Qt modules to cut tens of MB.
- **Alternative:** **Briefcase (BeeWare)** produces proper signed installers (`.dmg`/MSI) — cleaner packaging/signing flow, more setup.
- For dev, a simple cross-platform launcher pair (a `.command`/shell script on mac, a `.bat`/`.ps1` on Windows) that activates the venv and runs the app is enough until you package.

---

## 6. The recommended stack (one place)

| Layer | Choice | Why |
|---|---|---|
| Language | **Python 3.12** (GIL build) | Ecosystem lock-in; retires MIDI-wheel + Windows-timer risks |
| Concurrency | **Threads + queues**, injected clock | Right for soft-real-time I/O workload ([05](05_ARCHITECTURE_REVIEW.md)) |
| UI | **PySide6** (backup: Dear PyGui) | Best visualizer + cross-platform look; LGPL; already in tree |
| PDL | **python-prodj-link** (hardened) | Only viable in-process option; sidecar `beat-link` if needed |
| MIDI | **mido + python-rtmidi** | Standard; behind an interface so demo source can replace it |
| DMX out | **pyserial Enttec** + **pyartnet/sacn** backend | Serial primary; Art-Net for hardware-free + node testing |
| Packaging | **PyInstaller --onedir**, signed/notarized | Cross-platform double-click; Briefcase as alternative |

**Honest trade-offs:** PySide6 is the heaviest bundle and macOS notarization of a Qt app takes real effort; Qt has a learning curve and strict threading rules. If those costs bite, Dear PyGui is a lighter path with a smaller ecosystem. Neither changes the core decisions above.

**Net deviation from spec:** keep Python; **change 3.14→3.12**, **tkinter→PySide6**, **macOS-only→macOS-first/portable**, **add Art-Net backend**. Note the two biggest changes (Python version, UI toolkit) are *not* OS-driven, so they survive the macOS-first decision intact. Everything else in the spec's tech guidance (type hints, dataclasses, logging-not-print, small dependency set) stands. Full deviation list in [13](13_DECISION_LOG.md).
