# REFERENCE — context only, do not extend

The code and notes in this folder are **reference material**, not a starting point. The architecture, design principles, and build plan in the main portfolio docs are the authoritative description of what to build. This folder exists so you can answer questions like:

- "What was tried before?"
- "Why was X decided this way?"
- "How did v1 implement the fixture profile pattern?"
- "What does the Enttec driver code look like in practice?"

If you find yourself opening these files to copy logic wholesale into the new implementation, stop. Either the design docs are missing something (tell Josh, update them) or you're solving a problem the new architecture already solves differently.

## Contents

- **`v1_codebase/`** — The actual v1 source files. Built around USB audio FFT. Production-running before the v2 pivot.
- **`v1_codebase/NOTES.md`** — What v1 was, what worked, what didn't.
- **`v2_phase1_notes.md`** — Description of v2 Phase 1, which built and validated the dual-input → ShowState foundation. The Phase 1 source is not included; the patterns are documented in `03_ARCHITECTURE.md`.

## How to use

Read `v1_codebase/NOTES.md` first for the v1 context. Then skim `run.py`, `README.md`, and `version.py` to see the shape. Read `v2_phase1_notes.md` to understand what was validated and what's still to build.

Then close the folder and go build.
