# 07 — Platform Strategy (macOS-first, cross-platform-capable)

> **Platform decision (2026-06): target macOS; keep the code portable.** The dev + show machine is a Mac (incoming). You are **not** committing to test, support, or package for Windows. But because every hardware boundary is abstracted (output backend, input source, clock, device discovery, paths — §8), the code stays OS-agnostic at almost no cost, so a Windows build remains a *low-cost future option* rather than dead weight.
>
> **How to read this document under that decision:**
> - **Active work** = the macOS items (serial `cu.*` node, link-local, signing/notarization) **and the OS-agnostic abstraction checklist in §8** — that checklist *is* the portability strategy; do it regardless of OS.
> - **Revival reference only** = the Windows-specific subsections (Pro DJ Link networking, single-client MIDI, timer resolution, AV/signing). Keep them for if/when you ship Windows; they also explain *why* staying portable is cheap. They are **not work to do now.**
> - **Interim bonus:** you're on Windows until the Mac arrives. Because the code stays portable, you can build and run **demo mode on Windows today** and lose nothing when you switch.

The original cross-platform framing follows; read the Windows parts as "later, if ever." The good news from the research: **the difficulty was always concentrated in a few specific Windows spots, not spread evenly** — and macOS sidesteps essentially all of them, which is exactly why macOS-first is the low-friction path.

---

## 1. The cross-platform risk map

| Integration | Windows risk | macOS risk | Primary mitigation |
|---|---|---|---|
| **Pro DJ Link (UDP)** | 🔴 High — link-local APIPA slow/flaky, Firewall drops UDP, interface auto-guess fails on multi-homed laptops | 🟢 Low | Static link-local IP + firewall rule + explicit interface override |
| **DMX timer cadence** | 🟡 Was high — legacy 15.6 ms `sleep` | 🟢 Low | **Solved by Python ≥3.11** + drift-corrected loop |
| **MIDI input** | 🟡 Single-client lock (historically) + no 3.13/14 wheels | 🟢 Low (multi-client) | Pin 3.12; handle "port busy"; substring matching |
| **Serial / Enttec** | 🟢 Low (FTDI VCP → COMx) | 🟢 Low (use `cu.*`) | Detect by VID/PID; OS-correct device string is automatic |
| **UI toolkit** | 🟢 Low (PySide6 native) | 🟢 Low | Avoid tkinter's mac quirks by not using tkinter |
| **Launch / packaging** | 🟡 AV false positives, signing | 🟡 Gatekeeper notarization | PyInstaller --onedir, code-sign both |

The two red/yellow clusters worth real attention are **Pro DJ Link networking on Windows** and **timing** (already handled by the Python-version choice).

---

## 2. Pro DJ Link on Windows — the #1 cross-platform hazard

This is where "works on my Mac, dead on the show laptop" failures come from, and **none of them are in your code.**

### 2.1 Link-local / APIPA address assignment
With no DHCP server (laptop ↔ XDJ-XZ direct or via a dumb switch), both ends must self-assign a `169.254.x.y/16` address.
- **macOS** falls back to link-local quickly and reliably.
- **Windows** APIPA fallback is **slower** (can take 30–60 s after DHCP times out) and is sometimes suppressed by drivers/Group Policy, leaving the adapter at `0.0.0.0`/"Identifying…". If the NIC isn't in `169.254.x.y/16`, you simply won't see the XDJ.
- **Mitigation (do this for show reliability):** statically assign the host Ethernet NIC to e.g. `169.254.50.50 / 255.255.0.0` on both OSes rather than depend on APIPA timing. Document it; consider a "network setup" helper in the UI.

### 2.2 Windows Firewall silently drops inbound UDP
PDL listens on UDP **50000/50001/50002**. Windows Firewall blocks inbound UDP for a new app by default; if the first-run prompt is dismissed, you receive **nothing**, silently.
- **Mitigation:** ship an inbound-UDP allow rule for those ports (install step, needs elevation once), prefer the "Private" profile, and surface a clear UI diagnostic: *"No DJ-Link device seen on interface X — check cable, IP (169.254.x.y), and firewall."*

### 2.3 Interface selection
`python-prodj-link` **auto-guesses** the interface by subnet-matching against traffic it already sees — which fails on a multi-homed dev laptop (Wi-Fi + Ethernet + VPN/virtual adapters), a chicken-and-egg if your NIC has the wrong IP, and uses GUID-style interface names on Windows (not "Ethernet 2").
- **Mitigation:** patch in an **explicit interface/IP override** (select by configured subnet/IP, not name). This is a small, well-contained change to the library. Expose it as a setting.

### 2.4 No admin, no pcap
Reassuring: it uses **ordinary UDP sockets**, so **no Npcap and no admin privileges** are required (ports 50000+ are unprivileged). Only the one-time firewall rule needs elevation.

### 2.5 Device-number collision
Your virtual-CDJ identity must claim a **free player number (5–7)** so it doesn't collide with the XDJ-XZ's internal players — a known "won't go online" failure if it collides. The library handles this, but verify.

> **If PDL-on-Windows reliability becomes a recurring fight,** the fallback is to run Java **beat-link** as a sidecar (bundled JRE, emits OSC/MIDI/UDP that LiveReact consumes). It's the best-maintained, XDJ-XZ-confirmed implementation and behaves identically on both OSes. Heavier (a JVM + an IPC channel), but it removes the networking-library variable.

---

## 3. DMX timer cadence — solved by the Python choice + a good loop

A steady 40 Hz = 25 ms period. The historical Windows killer was `time.sleep()` quantizing to the ~15.6 ms scheduler tick → wild jitter.

- **The fix is the Python version:** CPython **≥3.11** uses a high-resolution waitable timer for `time.sleep()` on Windows automatically — sub-millisecond, no `timeBeginPeriod`, no system-wide side effects. macOS already has ~1 ms-class timers. So **pin 3.12 and the platform divergence here mostly disappears.**
- **Still do drift-corrected scheduling** with a short busy-wait tail (absolute deadlines off `perf_counter()`, sleep most of the way, spin the last ~1.5 ms). This makes both OSes behave identically under jitter and prevents drift accumulation.

```python
import time
SPIN_MARGIN = 0.0015   # tune per machine; covers post-3.11 Win + mac jitter

def precise_sleep_until(deadline: float):
    while True:
        rem = deadline - time.perf_counter()
        if rem <= 0: return
        if rem > SPIN_MARGIN: time.sleep(rem - SPIN_MARGIN)   # coarse
        # else: busy-wait the final sliver

def steady_loop(stop, period, body):           # e.g. period = 1/40
    nxt = time.perf_counter() + period
    while not stop.is_set():
        body()
        precise_sleep_until(nxt)
        nxt += period
        now = time.perf_counter()
        if nxt < now - period:                 # fell badly behind → resync, don't burst
            nxt = now + period
```

Run the DMX writer on its **own thread** so UI/MIDI work can't stall the refresh. The ~7%-of-one-core cost of the spin tail at 40 Hz is fine for a dedicated controller; make `SPIN_MARGIN` adaptive if you care about laptop battery.

---

## 4. MIDI cross-platform

- **Wheels:** `python-rtmidi` 1.5.8 has wheels for **3.8–3.12** on Win + Mac, **none for 3.13/3.14** → **pin 3.12** (same decision as DMX). No compiler needed on 3.12.
- **Single-client limitation:** classic Windows (WinMM) gives **exclusive** MIDI-input access — only one app at a time; if Rekordbox/Serato holds the XDJ port, your `open_input()` fails. macOS CoreMIDI is multi-client. The 2026 **Windows MIDI Services** rollout (Win 11 24H2/25H2/26H1) makes endpoints multi-client and re-plumbs the legacy APIs — but you **cannot assume** a given show laptop has it. **Mitigation:** catch open failures, retry, and show "another app is using the controller — close it."
- **Port naming differs** (WinMM appends/truncates; CoreMIDI is cleaner). **Always substring/case-insensitive match** (`"xdj" in name.lower()`), never exact equality. Handle absent/multiple matches.
- **Channels are 0-indexed in `mido`** (hardware docs say 1–16). Account for the off-by-one. Use the **callback API** (non-blocking) and `cancel_callback()`/`close_port()` on shutdown.

---

## 5. Serial / Enttec cross-platform (the easy one)

- The Enttec is an **FTDI VCP** device → `COMx` on Windows, `/dev/tty.usbserial-*` **and** `/dev/cu.usbserial-*` on macOS.
- **Always open the macOS `cu.*` node** — the `tty.*` node blocks on open waiting for carrier detect. This is the #1 macOS serial gotcha.
- **Auto-detect by USB VID/PID** (`serial.tools.list_ports`), not by name; `port.device` already returns the OS-correct string, so the open call doesn't branch on OS:
```python
from serial.tools.list_ports import comports
def find_enttec():
    for p in comports():
        if p.vid == 0x0403 and p.pid == 0x6001:   # FTDI; fall back to serial_number if multiple
            return p.device
    return None
```
- **Windows driver:** needs the FTDI **VCP** driver (not D2XX) so a COM port appears; Win 11 usually auto-installs it, a clean machine may not. **macOS 11+** has an in-kernel FTDI driver — no install.
- Latency: negligible vs the 22 ms frame budget on both OSes; your loop timing (§3) dominates, not the serial stack.

---

## 6. Output insurance: an Art-Net/sACN backend

Because Art-Net/sACN are pure UDP (no drivers, no COM ports, fully OS-agnostic), adding a second output backend (`pyartnet` v2.0 or `sacn`) is cheap and buys a lot:
- **Hardware-free development/testing** against software DMX visualizers (QLC+, Resolume) on either OS.
- An escape hatch if a user has an Ethernet-DMX node instead of the Enttec.
- It sidesteps every serial/driver issue on Windows.

Abstract output behind one interface; backends: `EnttecSerial`, `ArtNet`/`sACN`, `NullLog` (demo).

---

## 7. Launch & packaging cross-platform

- **Dev:** ship both a `run.command` (mac, chmod +x) and a `run.bat`/`run.ps1` (Windows) that select Python, ensure the venv/deps, auto-detect devices (mirroring the spec's `LiveReact.command` logic), and launch with `--demo` fallback. Replace the spec's mac-only `portaudio`/`sounddevice` setup — **not needed** (no audio path in v2).
- **Distribution:** PyInstaller `--onedir`, **code-signed** on Windows (Authenticode, fixes AV false positives) and **signed + notarized** on macOS (Hardened Runtime + `notarytool`, $99/yr Apple account). Trim unused Qt modules. **Always test the packaged build on a clean machine** — bundled `python-rtmidi`/pyserial/Qt-plugin gaps only show up there.

---

## 8. A cross-platform abstraction checklist

Wrap every OS-touching thing behind a small interface so the rest of the code is platform-agnostic:

- [ ] **Device discovery** — `find_enttec()`, `find_xdj_midi()`, `select_pdl_interface()` return OS-correct identifiers.
- [ ] **Paths** — use `pathlib` and a per-OS config dir (`%APPDATA%` / `~/Library/Application Support`), not hard-coded paths.
- [ ] **Output backend** — Enttec / Art-Net / null behind one interface.
- [ ] **Input source** — PDL+MIDI listeners and DemoDataSource behind one interface.
- [ ] **Clock** — injected, so timing is testable and OS-independent.
- [ ] **Launcher** — mac + Windows scripts; no `.command`-only assumptions.
- [ ] **No `/dev/*`, `ifconfig`, `en7`, `/dev/null`** literals in logic — all behind discovery/abstraction.

Get these right and "cross-platform" stops being a pervasive concern and becomes a handful of well-contained adapters.
