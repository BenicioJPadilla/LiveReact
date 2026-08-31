# 10 — Open Questions & Working Assumptions

The spec repeatedly says *"ask Josh."* You have no Josh. This document collects **every question you'd otherwise put to him**, and gives each a **working assumption** (my best researched answer) so you are never blocked. Each is tagged by how to eventually confirm it. Treat assumptions as defaults to build on and revise — make them visible in code/config so they're cheap to change.

Legend — **Confirm by:** 🔧 hardware test · 🎚️ DJ/usage feedback · 🔬 already researched (treat as settled) · 🧩 your product call.

---

## A. Hardware & protocol

| # | Question | Working assumption | Confirm by |
|---|----------|--------------------|-----------|
| A1 | Are the DMX channel maps / fixture modes exactly as documented? | Yes for the SHEHDS 180W (PDF exists); **hypotheses** for laser, par, wash bar. Build from them; verify each fixture via the manual-test panel. | 🔧 |
| A2 | Is the XDJ-XZ MIDI CC map correct? | **Assume it's approximately right but verify everything.** XDJ-XZ MIDI is poorly documented and may use HID for some controls. Ship a MIDI-learn tool; persist the discovered map. | 🔧 |
| A3 | Does the XDJ-XZ expose what we need over PDL? | BPM, beat(1–4), on-air, master, loop, play = yes. **Bar = inferred; phrase = unavailable; beat-phase = interpolated; absolute position = unavailable.** Design to this. | 🔬 |
| A4 | One Enttec, one universe, 74 channels — final? | Yes. Non-goal: multi-universe. | 🔬/🧩 |
| A5 | Will the show machine be Windows, Mac, or either? | **Mac** (primary; you're getting one). Build macOS-first but keep code portable. Static-IP/network setup tuned for macOS; Windows is a future option, not active work. | 🧩 |
| A6 | Static IP or APIPA for the XDJ link? | **Static link-local** (`169.254.50.50/16` host side) for reliability, especially on Windows. Offer APIPA as the zero-config fallback. | 🔬/🔧 |

## B. Lighting aesthetics & behavior

| # | Question | Working assumption | Confirm by |
|---|----------|--------------------|-----------|
| B1 | Is the frequency→color rule truly fixed? | **Keep it** (consistency = the real reason). Energy→brightness/saturation is mandatory; band→hue is tunable data. Don't claim neuroscience. | 🔬/🎚️ |
| B2 | How aggressive should strobe be by default? | **Conservative.** Sustained strobing near the 3 Hz known-safe line; high-rate only as short auto-expiring drop bursts; white preferred over red. | 🔬/🎚️ |
| B3 | When exactly do lasers turn on? | **Only in explicit drop scenes**, static/above-head, never sound-active modes, off by default, fail-safe to off. | 🔬 |
| B4 | What does a "drop" feel like? | Dip on the last build beat → full white hit on bar 1 of the drop; lasers/beams engage; symmetric MH movement; strobe within cap. | 🎚️ (catalog in [08 §3](08_LIGHTING_DESIGN_AND_SAFETY.md)) |
| B5 | How many scenes, and which? | ~8 for v1 from the 12-scene starter catalog; expand during tuning. | 🧩/🎚️ |
| B6 | Rotation cadence — 8, 16, or 32 bars? | Default **16 bars**; allow **32** for high-energy sustained sections; never below 8. | 🎚️ |
| B7 | Scene-selection policy? | Start **round-robin within an energy bucket**; upgrade to energy-weighted later. Don't build a Markov chain in v1. | 🧩 |
| B8 | How is "energy" estimated without audio? | Heuristic from MIDI EQ/fader state + which bands are engaged + phrase position, smoothed. Not from PDL (no phrase data) and not from audio (dropped). | 🔬/🎚️ |

## C. Product scope & UX

| # | Question | Working assumption | Confirm by |
|---|----------|--------------------|-----------|
| C1 | Truly stateless across runs, or some persistence? | Add a **small optional `config.json`** (last brightness, discovered MIDI map, selected rig, per-scene tuning). Doesn't violate the "no cloud/accounts/presets" non-goal; saves real pain during iteration. | 🧩 |
| C2 | Is tkinter required, or open to better UI? | **Open** — recommend PySide6 (your "challenge everything" answer). | 🧩 ([06](06_TECH_STACK_EVALUATION.md)) |
| C3 | Is the 2.5-week deadline still real? | **Assume no fixed external deadline** for the inherited rebuild; plan by phases, not calendar. Re-scope if a real deadline exists. | 🧩 |
| C4 | Single rig forever, or multiple rig configs? | Support the **rig-file** format (already specified) so other layouts are possible, but only ship the one full-show rig. | 🧩 |
| C5 | Who runs it live — you, or non-technical users? | Assume **you** for now (so a slightly technical setup is OK), but keep the one-click launcher + auto-detect so a non-technical operator could. | 🧩/🎚️ |
| C6 | Tap-tempo / manual BPM fallback needed? | Yes — keep it as the emergency path when PDL is unavailable. | 🔬 |

## D. Engineering decisions (your call, defaults proposed)

| # | Question | Working assumption | Confirm by |
|---|----------|--------------------|-----------|
| D1 | Threads, asyncio, or hybrid? | **Threads + queues** + injected clock. | 🔬 ([05 §6](05_ARCHITECTURE_REVIEW.md)) |
| D2 | Roll the Enttec driver or use a library? | **Roll it** (~30 lines) — removes a dependency-health risk, gives loop control. | 🔬 |
| D3 | Add an Art-Net/sACN backend? | **Yes** — cheap, OS-agnostic, enables hardware-free visualizer testing. | 🔬 |
| D4 | Free-threaded (no-GIL) Python? | **No for v1**; write free-threading-clean so you can flip it in 2027+. | 🔬 |
| D5 | Vendor `python-prodj-link` or pip-from-git? | **Vendor or pin a SHA** (it's git-only and low-velocity). Wrap behind an interface. | 🔬 |
| D6 | How to test real-time logic? | Injected `Clock` + `FakeClock` fast-forward; fake serial sink; synthetic input messages. <10 s suite. | 🔬 ([05 §5.2](05_ARCHITECTURE_REVIEW.md)) |

---

## How to use this list
- Nothing here blocks starting the **demo-first** build. Every 🔬 is settled; every 🔧/🎚️ is deferred to the hardware/usage phase; every 🧩 is a product default you can run with.
- Keep a living copy in the repo and tick items off as hardware/usage confirms or refutes them. The dangerous failure mode is treating an assumption as a fact — so **surface them in the UI/logs** (e.g. "MIDI map: defaults, unverified") until confirmed.
