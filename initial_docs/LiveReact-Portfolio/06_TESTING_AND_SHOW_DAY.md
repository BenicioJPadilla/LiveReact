# 06 — Testing and Show Day

How to validate LiveReact during development, during hardware integration, and on the night of a show. The 90% of bugs you don't catch in testing will catch you on stage. Treat this as your operations manual.

---

## 1. Test pyramid

| Level | What it covers | When you run it |
|---|---|---|
| **Demo mode** | All software logic without hardware | Continuously during development |
| **Unit tests** | Individual functions (e.g., merge logic, scene rendering) | Before commits to risky code |
| **Hardware bring-up** | Real DMX, real PDL, real MIDI, isolated | First day of hardware access |
| **Integration tests on rig** | Full system on full rig with real music | Days 7+ |
| **Dress rehearsal** | A full mock set with Josh DJing | Days 12–14 |
| **Show day** | The real thing | Show night |

---

## 2. Demo mode — the development substrate

Demo mode is what you'll use 80% of the time. It runs the entire system end-to-end with synthetic inputs.

### Running it

```bash
python run.py --demo
```

In demo mode:
- `DemoDataGenerator` produces a fixed BPM clock (default 124) advancing beats and bars
- A slow-cycling synthetic energy curve (rises and falls every ~64 bars)
- Optionally periodic synthetic transitions (every ~96 bars, simulates a crossfader move)
- Null DMX driver — output is logged, not sent

### What demo mode is good for

- Building and iterating on engines, scenes, the merge layer, UI — anything above the input layer
- Reproducing logic bugs without the rig
- Letting non-Josh people review the system

### What demo mode is **not** good for

- Tuning anything timing-related against real music (use real hardware)
- Tuning Transition Engine (real DJ behavior is the only valid test)
- Validating fixture-specific quirks (real fixtures have real quirks)

### Optional flags

Suggested CLI shape:

```bash
python run.py --demo                          # full demo mode
python run.py --demo --demo-bpm 128           # specify BPM
python run.py --demo --demo-no-transitions    # disable synthetic transitions
python run.py --demo --force-scene drop_1     # lock to one scene for testing
python run.py --hardware                      # force hardware mode (fail if not found)
python run.py                                  # auto-detect: hardware if found, else demo
```

---

## 3. Unit tests

Unit tests aren't expected to be exhaustive. Cover the parts where a logic bug would be invisible until live:

| Module | Test |
|---|---|
| `core/merge.py` | Multiple engine contributions on one channel combine correctly. ManualParams cap is applied. Blackout zeros everything. |
| `core/metronome.py` | Phase interpolation produces monotonic output between beats. PDL resync corrects drift. |
| `core/phrase_engine.py` | Bar-boundary detection fires once per boundary, not multiple times. `in_transition` suspends rotation. |
| `core/transition_engine.py` | Detection threshold doesn't trigger on small crossfader wiggles. Settles correctly after a real transition. |
| Each fixture profile | `get` / `set` map to correct DMX byte offsets. Default values are correct. |
| `dmx/enttec.py` | Frame structure matches the Enttec Widget API spec (header bytes, length, payload, end byte). |

Use `pytest`. Aim for a test run under 10 seconds total — fast feedback is more valuable than coverage.

---

## 4. Hardware bring-up — first day of rig access

Schedule this with Josh. Plan a half-day; allocate the full day in case of cable / power / driver issues.

### Pre-arrival checklist (the day before)

- [ ] LiveReact in demo mode runs cleanly on your machine
- [ ] You can read all four fixture manuals (in `APPENDICES/`)
- [ ] You have a USB-A to USB-B cable for the XDJ
- [ ] You have a USB-C to Ethernet adapter for the MacBook side
- [ ] You have a 120Ω DMX terminator (Josh provides if you don't)
- [ ] You've installed `python-prodj-link` and tested its examples can at least *start* without errors

### Bring-up sequence

**Step 1: Power and DMX chain only (no XDJ, no LiveReact)**
1. Power on each fixture in order.
2. Set DMX addresses and channel modes per `02_HARDWARE_RIG.md`.
3. Run each fixture's built-in self-test mode (usually `Auto` mode in the fixture menu) to confirm it physically works.

**Step 2: Enttec connection (still no LiveReact code running)**
1. Plug Enttec into the MacBook USB.
2. Run `ls /dev/tty.usbserial-* /dev/cu.usbserial-*` — confirm the port appears.
3. Use a known-good DMX test tool (e.g., a Python one-liner that sends a constant value, or QLC+ briefly) to verify the Enttec is talking to the chain.

**Step 3: LiveReact in "fixture test mode" — one fixture at a time**

You'll want a special UI panel (suggested for Phase 6) that lets you manually drive individual channels of individual fixtures. Use it to:

1. Set RGBW par CH1 (red) to 255 — confirm visible red.
2. Set each color channel on each par. Confirm all four channels work.
3. Set Moving Head dimmer to 255. Should light up (white).
4. Set Pan to 64, then 192. Should physically move.
5. Set color wheel value to a color position. Confirm color changes.
6. Set Gobo wheel value. Confirm gobo changes.
7. Set Laser CH1 = 0 (off), then CH1 = 64 (manual mode), CH2/CH3 = 128 each. Confirm laser activates. **Point it at a wall, not at faces.**
8. Set Wash Bar CH1 = 255, CH3 = 255. Confirm red wash.

For each fixture, write down (or record video of) the test results. If something doesn't respond:
- Check DMX address and chain order
- Confirm the previous fixture in the chain isn't terminated mid-chain
- Confirm channel mode matches profile expectations

**Step 4: XDJ-XZ — Pro DJ Link**
1. Connect XDJ Ethernet to MacBook (via USB-C to Ethernet adapter).
2. Enable Link mode on the XDJ.
3. Run a `python-prodj-link` example script. Wait up to 10 seconds. Confirm beat/status packets are being received.
4. If nothing arrives: check that the MacBook's Ethernet interface got a `169.254.x.x` IP (or whatever you configured). Confirm the XDJ has its IP visible in settings.

**Step 5: XDJ-XZ — MIDI**
1. Connect XDJ USB-B to MacBook.
2. Open `Audio MIDI Setup → MIDI Studio`. Confirm `XDJ-XZ` appears as a MIDI device.
3. Run a small `mido` script that prints incoming MIDI messages.
4. Move each fader, knob, and button on the XDJ. Record which CC number is sent for each control. Update `APPENDICES/C_XDJ_XZ_MIDI_MAP.md` if anything has changed.

**Step 6: Full system**
1. Run `python run.py` (no flags — should auto-detect hardware).
2. Confirm UI shows real BPM (matches what's on the XDJ display).
3. Confirm beat counter advances with the actual track playing.
4. Move the crossfader on the XDJ — confirm UI's crossfader display tracks.
5. Confirm lights pulse on real beats.

**Bring-up done.** From here, every test is a real-music test.

---

## 5. Integration testing on the rig

Once bring-up is clean, this is the bulk of remaining work. Each test session: 1–2 hours.

### Session structure

1. **Set up rig** (Josh handles physical, you handle software).
2. **Start LiveReact**, confirm UI shows live PDL + MIDI data.
3. **Josh DJs** — usually a 30–60 minute set.
4. **You watch the rig**, take notes on what looks wrong.
5. **Debrief.** Both observe a list of fixes. Push the easy ones immediately; queue the bigger changes.
6. **Repeat next day with fixes.**

### What to watch for

- **Beat lock:** Are pulses *on* the beat or slightly off? (If slightly off, tune metronome interpolation.)
- **Color fit:** Does the color choice match what the music is doing? If a hard bass section is producing cyan, something is wrong with EQ-to-color mapping.
- **Scene rotation:** Does a new scene feel like an arrival or a glitch? Crossfade duration tuning lives here.
- **Strobe intensity:** Strobes that feel "tasteful" in demo can feel overwhelming live. Tune down by default; allow scenes to override.
- **Laser safety:** Lasers should never point at face level. Confirm physical mounting before every show. Confirm software never enables lasers in non-drop scenes.
- **Transitions:** Does the rig feel like it's "moving with" the transition, or fighting it?
- **Loops:** When Josh hits a loop, does the rig appropriately hold and release?

### Common things you'll find and how to fix them

| Symptom | Likely cause | Fix |
|---|---|---|
| Lights freeze for a few seconds during a build | PDL dropping packets during heavy CPU on the XDJ | Tune local metronome to free-run more aggressively when packets stale |
| All scenes look samey | Scenes too parameterized on energy, not enough distinct movement / color logic | Hand-tune individual scenes more aggressively |
| Lasers come on at unexpected times | Wrong scene activating laser CH1 | Audit which scenes enable lasers — only drop scenes should |
| Lights stutter every few beats | DMX writer thread not keeping up | Confirm writer thread is at correct priority, frame interval is ~22ms |
| Strobes too aggressive | Strobe rate scaling factor too high | Reduce default strobe ceiling; let ManualParams strobe cap moderate it |
| Crossfader detection fires spuriously | Detection threshold too sensitive | Increase the value-range threshold or extend the window |
| Scenes rotate too often | 16 bars is too short in this BPM band | Switch to 32-bar rotation for high-energy sections |

---

## 6. Dress rehearsal (Day 12–14)

A full simulation of show night.

- **Set up the actual show-night rig** (not the test rig, if different).
- **Run a 60–90 minute set**, treat it as real.
- **Note every intervention** Josh has to make — those are bugs.
- **Don't** push code changes during the rehearsal — write them down for after.
- After the rehearsal: triage notes by severity, fix critical issues, defer minor ones.

If the rehearsal goes badly, you have buffer days (Phase 9) to recover. Don't skip it.

---

## 7. Show night

### Pre-show checklist (1–2 hours before doors)

- [ ] Rig powered, all fixtures responding to a manual test cycle
- [ ] DMX chain terminated, all addresses correct
- [ ] MacBook plugged into AC power (do not run on battery)
- [ ] MacBook energy saver: never sleep, never dim display
- [ ] All notifications and updates disabled
- [ ] LiveReact running, hardware mode confirmed (no "DEMO" banner)
- [ ] BPM display in UI matches XDJ display
- [ ] Moving the crossfader produces UI update
- [ ] Lights pulse on a test track played for 30 seconds
- [ ] All scenes verified via a quick "force scene" cycle through the catalog
- [ ] Laser pointing angle verified (above audience head height)
- [ ] Master brightness set to ~80% (leave headroom for peaks)
- [ ] Blackout key (`B`) tested
- [ ] Strobe burst (`Space`) tested
- [ ] Spare DMX cable, USB cable, and 120Ω terminator on hand

### During the show

Hands-off is the goal. Use the UI for:
- **Master brightness** during particularly hot or particularly chilled-out sections
- **Strobe cap** if a scene's auto-strobe is too aggressive for the room
- **Blackout** (`B`) during MC announcements or unexpected pauses
- **Skip scene** (`→`) if a scene clearly isn't working with the current track

Avoid:
- Restarting the app mid-set (a brief blackout + reboot = ~30 seconds of dark)
- Touching the laptop unless something's broken
- Live-editing code

### When something goes wrong mid-set

| Symptom | Action |
|---|---|
| Lights stutter or freeze | Press `F` (freeze) then `F` again to release. If still bad, blackout and check UI for stale-data warnings. |
| One fixture goes dark | Likely DMX chain issue. Don't restart LiveReact. After the set, check connections. |
| All lights go dark | Check Enttec USB connection. Check terminal for errors. Worst case, restart LiveReact (lights will be dark for ~30 sec). |
| Lasers won't turn off | `B` (blackout) zeros everything. Then disable laser via UI. |
| UI freezes but lights still react | tkinter event loop hung; ignore unless you need a control. The DMX writer is on its own thread, lights keep going. |

### After the show

- [ ] Power down rig in reverse order (fixtures last, after waiting for moving heads to cool)
- [ ] Check LiveReact terminal for any errors logged during the set
- [ ] Note any visual artifacts you saw or Josh noticed
- [ ] Save the log file with a timestamp

---

## 8. Failure modes and graceful degradation

LiveReact should never fully crash mid-set. These are the failure-mode policies:

| Component fails | LiveReact response |
|---|---|
| PDL packet loss > 1 sec | Metronome free-runs at last known BPM. Log warning. UI shows "PDL: stale" indicator. |
| MIDI device disconnects | Hold last fader/EQ values. Scenes continue running off PDL only. |
| Enttec serial write fails | Retry once; if still fails, log error and continue trying every frame. Don't crash. |
| Scene rendering throws an exception | Catch in show engine tick loop, log, hold previous scene contribution for one tick, continue. |
| Phrase Engine error | Catch, log, skip Phrase Engine for that tick. Reactive Layer keeps producing — rig keeps moving. |
| UI thread error | UI may freeze; show engine and DMX writer are separate threads and continue. |
| Out of memory / general crash | Hard restart required. Aim to never get here. |

The principle: **engines fail open, UI fails secondary, DMX writer never stops.** The DMX writer is the most critical thread — it should be the most defensively-coded.

---

## 9. Logging discipline

- All threads log to a single file (`livereact-{timestamp}.log`).
- Use `logging` module, not `print`.
- Log levels:
  - `DEBUG` — verbose, off by default in production
  - `INFO` — startup, shutdown, scene rotations, transitions detected
  - `WARNING` — staleness, retries, recoverable errors
  - `ERROR` — exceptions caught, fixture failures
- During development: console + file. During show: file only (console doesn't help on stage).
- Keep logs for 30 days. Useful for post-mortems.

---

## 10. Post-show feedback loop

After each real show:
1. Review logs for warnings/errors
2. Get Josh's notes on what felt wrong
3. Compare against your observations during the set
4. Triage: critical (next-show blocking) → important (this week) → polish (whenever)
5. Push fixes

This is how the system gets dialed in over time. Two or three shows in, LiveReact should feel like it disappears.

---

That's the end of the main portfolio. The `REFERENCE/` and `APPENDICES/` folders contain the v1 code, protocol notes, MIDI map, fixture manuals, and a glossary. Reach for them as needed.

Good luck. — Josh
