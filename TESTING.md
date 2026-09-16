# Hardware Testing & Feedback Guide

This is the **exact procedure** for testing LiveReact on the real rig, and the
system for capturing what happens so you can hand it straight back to Claude for
analysis. Pair it with [`HARDWARE.md`](HARDWARE.md) (the deeper setup reference).

> First contact between this code and real devices **will** surface mismatches
> (channel maps, MIDI CCs) — that's expected and exactly what these tools are for.
> Don't try to fix code yourself; **record the session and send it back.**

---

# Part 0 — Total beginner setup (start here)

**Never used a "command line" or installed code from the internet before? Read this
part.** It walks you through everything from a blank computer to running your first
test. You do this whole part **once**. After that you only use the tests further
down the page.

You do **not** need to understand any of it — just follow the steps in order and
copy-paste the commands exactly. Each step tells you what to type, why, and what you
should see. If a step doesn't look right, stop and send a screenshot back to Claude.

> **A few words you'll see, in plain English:**
> - **Terminal** / **PowerShell** — a window where you type commands instead of
>   clicking buttons. That's the black or blue text window you'll open below.
> - **Python** — the programming language LiveReact is written in. The computer
>   needs it installed to run the app, like needing a music player to play an MP3.
> - **A command** — one line of text you paste into the terminal and press Enter.
> - **The project folder** — the `LiveReact` folder containing all the code, which
>   you'll download in Step 2.

---

## Step 1 — Install Python (version 3.12)

This gives your computer the engine that runs LiveReact. **You must use version
3.12** — newer or older versions can cause errors with the lighting hardware.

**Windows**
1. Go to **https://www.python.org/downloads/release/python-3127/**
2. Scroll to the bottom, under "Files" click **Windows installer (64-bit)** to
   download it.
3. Open the downloaded file. On the first screen, **tick the box that says
   "Add python.exe to PATH"** (bottom of the window) — this is important.
4. Click **Install Now** and let it finish, then click Close.

**Mac**
1. Go to **https://www.python.org/downloads/release/python-3127/**
2. At the bottom under "Files" click **macOS 64-bit universal2 installer**.
3. Open the downloaded `.pkg` file and click through Continue → Agree → Install.

**Check it worked.** Open a terminal (see Step 3 for exactly how) and paste this:

```
# Windows
py -3.12 --version
```
```
# Mac
python3.12 --version
```

You should see something like `Python 3.12.7`. If you instead see "not found" or a
different version number, Python didn't install correctly — redo this step (on
Windows, the most common cause is forgetting to tick "Add python.exe to PATH").

---

## Step 2 — Download the LiveReact code

This puts a copy of the app on your computer.

**The simple way (no extra tools):**
1. Go to **https://github.com/danfirsten/LiveReact**
2. Click the green **`< > Code`** button, then **Download ZIP**.
3. Find the downloaded `LiveReact-main.zip` (usually in your **Downloads** folder),
   right-click it → **Extract All** (Windows) or double-click it (Mac).
4. You now have a folder called `LiveReact-main` (or `LiveReact`). **Remember where
   it is** — for example your Desktop or Downloads. This is your **project folder**.

> Whenever Claude sends you a fix later, you'll come back here, download a fresh ZIP,
> and replace the folder. (If you happen to know `git`, `git clone
> https://github.com/danfirsten/LiveReact.git` and later `git pull` is smoother —
> but the ZIP method works perfectly.)

---

## Step 3 — Open a terminal *inside* the project folder

Every command on this page must be run **from inside the project folder**, or the
computer won't know where the app is.

**Windows**
1. Open the `LiveReact` folder in File Explorer so you can see files like
   `README.md` and `TESTING.md` inside it.
2. Hold **Shift** and **right-click** an empty area inside the folder.
3. Click **"Open PowerShell window here"** (or "Open Terminal here"). A blue or
   black window opens — that's your terminal.

**Mac**
1. Open the **Terminal** app (press `Cmd+Space`, type `Terminal`, press Enter).
2. Type `cd ` (the letters c, d, then a space) but **don't press Enter yet**.
3. Drag the `LiveReact` folder from Finder onto the Terminal window — it pastes the
   location for you — then press Enter.

To confirm you're in the right place, paste this and press Enter:

```
# Windows
dir
```
```
# Mac
ls
```

You should see a list that includes `README.md`, `TESTING.md`, and a `src` folder.
If you don't, you're not in the project folder — redo this step.

---

## Step 4 — One-time install (sets up the app)

This creates a private workspace for the app and downloads the pieces it needs to
talk to your lighting and DJ gear. It can take a couple of minutes and will print a
lot of text — that's normal. **Copy and paste each line one at a time, pressing
Enter after each, and wait for it to finish before the next.**

**Windows** (paste these one at a time):
```
py -3.12 -m venv .venv
```
```
.venv\Scripts\python -m pip install -e ".[hardware,ui]"
```

**Mac** (paste these one at a time):
```
python3.12 -m venv .venv
```
```
.venv/bin/python -m pip install -e ".[hardware,ui]"
```

When the second command finishes you'll see a line like
`Successfully installed livereact ...`. That means setup worked. If it ends in red
"ERROR" text instead, copy the whole window and send it back to Claude.

---

## Step 5 — "Turn on" the workspace (do this each time you open a new terminal)

Before running any test, you "activate" the workspace you just made. **You repeat
this one step every time you open a fresh terminal window** (it's not permanent).

**Windows**
```
.venv\Scripts\Activate.ps1
```

> **If Windows shows a red error about "running scripts is disabled on this
> system":** paste the line below once, press Enter, type `Y` and Enter if asked,
> then run the activate command above again. (This just allows the workspace to
> switch on; it's safe.)
> ```
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```

**Mac**
```
source .venv/bin/activate
```

**How you know it worked:** the start of your terminal line now shows `(.venv)`. As
long as you see `(.venv)`, the plain `python ...` commands in the rest of this guide
will work.

> **Shortcut if activation keeps giving you trouble:** you can skip this step
> entirely and instead put `.venv\Scripts\` (Windows) or `.venv/bin/` (Mac) in front
> of the word `python` in any command below. For example, instead of
> `python -m livereact --doctor`, type `.venv\Scripts\python -m livereact --doctor`.

---

## Step 6 — Your first command (the health check)

Let's make sure everything is working and see what gear your computer can detect.
With `(.venv)` showing, paste:

```
python -m livereact --doctor
```

This runs a self-check and writes a file called `diagnostics/doctor.txt` inside your
project folder. **This file is the single most useful thing to send Claude first** —
it lists exactly what your computer sees (lighting interface, DJ mixer, versions).

🎉 **That's the setup done.** From here on, you only open a terminal in the folder
(Step 3), turn on the workspace (Step 5), and run the tests below. The rest of this
guide is the actual testing procedure.

---

# Part 1 — The testing procedure

## The feedback loop (how this works)

```
  1. Run a test with --record   →  creates recordings/session-<timestamp>/
  2. Watch the lights, fill in     NOTES.md in that folder (what you saw)
  3. Hand the folder back to Claude ("analyze recordings/session-<timestamp>")
  4. Claude reads logs + state + your notes, proposes/makes fixes
  5. Repeat
```

Every recorded session folder contains:

| File | What it is |
|------|------------|
| `session.log` | All output (info/warnings/errors + tracebacks) |
| `errors.log`  | Just warnings/errors — quick scan for problems |
| `state.jsonl` | What the show did, sampled ~10×/sec (BPM, beat, energy, inputs, active DMX channels) |
| `meta.json`   | Your machine + detected devices + run settings at startup |
| `summary.json`| Totals (frames sent, samples) at shutdown |
| `NOTES.md`    | **You fill this in** — what you expected vs. what actually happened |

To send it back: either point Claude at the folder path, or zip it:
```
python -m livereact --bundle          # zips the latest session
```

---

## Before you start

First time on this machine? Do **Part 0** above once. Every time after that, open a
terminal in the project folder and turn on the workspace (Steps 3 and 5) so you see
`(.venv)`, then run the health check:

```
# Confirm the environment + detected devices:
python -m livereact --doctor
```

`--doctor` writes `diagnostics/doctor.txt` — **send that first**; it tells Claude
exactly what your machine sees (serial ports with VID/PID, MIDI inputs, versions).

```
# Only if you're using Pro DJ Link (the Ethernet beat-sync), install this extra
# library one time:
python -m pip install "git+https://github.com/flesniak/python-prodj-link"
```

---

## Test 1 — Fixtures, one at a time (safest; no DJ gear needed)

Goal: confirm each of the 8 fixtures is wired/addressed correctly and that every
channel does what the profile claims.

```
python -m livereact --hardware --fixture-test --record --rig rigs/josh_rig.json
```

> **Always pass `--rig rigs/josh_rig.json`** (found 2026-09-14): without it the
> app silently loads the packaged 8-fixture `default_rig.json`, whose addresses
> don't match the real rig — the MH goes dark and the laser receives MH-shaped
> data on its own address and cycles patterns by itself. Only the wash bar
> (address 69 in both files) behaves. If the wash bar is physically out, use
> `rigs/josh_rig_no_bar.json` instead.
>
> Since 2026-09-15 the show rotates only the six core looks (one per energy
> state, `scenes/library.py`'s `CORE_SCENES`); add `--full-catalog` to rotate
> the whole library again.

For **each** fixture (MH L/R, Laser L/R, Par L/R, Bar L/R):
1. Click its **Flash** button — the right fixture should light up. Note in `NOTES.md`
   if the *wrong* fixture lights (addressing problem).
2. Drag each channel slider and confirm the behavior matches the label
   (pan / tilt / dimmer / red / green / blue / strobe / …). Note any mismatch.

⚠️ **Laser safety:** raise laser channels only briefly, with beams pointed safely
above head height. Confirm the laser is OFF at slider 0.

**Expected:** every fixture identifiable; every channel does what its label says.
**Record:** per-fixture observations in `NOTES.md`.

---

## Test 2 — Network / Pro DJ Link

```
python -m livereact --net-check          # check the link-local IP + firewall first
python -m livereact --hardware --visualize --record --rig rigs/josh_rig.json
```

> **Laser on the bench:** add `--testing` when the laser is in a confirmed-safe spot with no
> crowd. Josh's rig declares the laser at 0.91 m (below the 3 m rule), so without `--testing`
> the software forces it off every run. Arming is per track: the laser is DISARMED at every
> launch (not saved in config.json any more), press **L** (or tick "Arm lasers") for the tune
> you want it on. Once armed it sweeps once per 8-bar block in PEAK only, one bar per sweep
> (`engines/laser.py`), and never at a show with this flag.

Play a track on the XDJ-XZ.

**Expected:** in the console, BPM shows the track tempo, the beat/bar counters
advance, and "clock=locked / PDL fresh". The rig pulses on the **real** beats.
**If you see "No DJ-Link device seen":** check the static IP (`169.254.50.50/16`),
that Link is on, and the firewall (UDP 50000–50002) — see `HARDWARE.md`.
**Record:** `state.jsonl` captures whether `pdl_fresh` / `bpm` / `bar` are correct.

---

## Test 3 — MIDI (the XDJ mixer)

The default CC map is a guess and almost certainly needs remapping for your unit.

```
python -m livereact --midi-monitor --record
```

Move each control and watch the printed `channel`/`cc`:
- channel faders A and B
- crossfader
- EQ low/mid/high on each channel

Write down which `channel`/`cc` each control reports. (This is captured to
`midi-monitor.txt` in the session folder.) Then either send it to Claude to build
your `midi_map.json`, or fill it in yourself (keys are `"channel:cc"`):
```json
{ "5:31": "crossfader", "5:23": "fader_a", "5:24": "fader_b" }
```

**Expected:** moving controls prints CC events. (Some controls may be HID and not
appear at all — note which.)

---

## Test 4 — Full end-to-end

```
python -m livereact --hardware --visualize --record --rig rigs/josh_rig.json
```

Play a set: a track, a build, a drop, then mix into another track.

**Expected:**
- lights pulse on the beat, color follows the EQ
- scenes rotate every ~16 bars
- a drop's PEAK (8 bars in) brings one laser fan sweep per 8-bar block (once armed with **L**, and only with `--testing` on this rig) + bigger movement
- press **C** ("Cue build") when a build starts that the lights aren't reacting to: BUILD commits
  now and holds (strobe ramp, wash ramp) until the drop lands, 32 bars pass, or you press C again.
  Exists because a kick-only intro reads louder than a mid-heavy build to a loudness classifier
  (2026-09-16) — the DJ sees the build, the RMS doesn't
- press **S** (or tick "Synth Sync") on a garage track: the par + wash bar stop following the
  bucket model and pulse with the synth stabs instead; strobes pause while it's on. Press S again
  to hand the wash back to the automation. Off at every startup.
- crossfading into the next track is detected (console shows TRANSITION) and the
  show settles into a new look afterward
- the operator controls (brightness, blackout, freeze, skip) all respond

**Record:** the whole thing. Note anything that felt wrong (timing, color, a fixture
misbehaving) in `NOTES.md`.

---

## Quick troubleshooting

| Symptom | First thing to check |
|--------|----------------------|
| No lights at all | `--doctor` shows the Enttec (FTDI VID `0x0403`)? DMX terminator on? |
| Wrong fixture responds | DMX address/mode on that fixture vs. `default_rig.json` |
| A channel does the wrong thing | Channel map in `fixtures/profiles.py` (send the session, Claude fixes it) |
| "No DJ-Link device seen" | Static IP `169.254.50.50/16`, Link on, firewall UDP 50000–50002 |
| Beat not locking | `state.jsonl` — is `bpm` right and `pdl_fresh` true? Else network/PDL issue |
| MIDI does nothing | `--midi-monitor` — do controls show up? Enable Utility→MIDI on the XZ |
| Lasers won't light | Arm them (**L**) — disarmed at every launch; they only sweep on 8-bar boundaries in PEAK, with `--testing` on this rig |

---

## What to send back to Claude

For any issue, the most useful bundle is:
1. `diagnostics/doctor.txt` (or `.json`)
2. the whole `recordings/session-<timestamp>/` folder (especially `NOTES.md`,
   `errors.log`, and `state.jsonl`)
3. for MIDI: the `midi-monitor.txt` capture

Then just say: *"analyze this session and tell me what's wrong / fix it."*
