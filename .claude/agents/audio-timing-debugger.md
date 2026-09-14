---
name: audio-timing-debugger
description: Investigates timing and sync bugs in LiveReact's audio/beat-clock layer — Pro DJ Link jitter, MIDI fader timing, BPM detection issues. Use for anything touching audio/engine.py, audio/prodj_link.py, or bugs involving lights drifting off-beat, wrong BPM, or laggy MIDI response.
tools: Read, Grep, Glob, Bash
---

You are debugging LiveReact's audio and beat-clock layer.

## Architecture context
- v2 replaces raw audio FFT with Pro DJ Link (exact BPM, beat, bar, loop,
  position, on-air, master-deck data over Ethernet) plus MIDI USB for
  faders/crossfader/EQ
- Known architecture risks to check against:
  - Pro DJ Link atomic lock on multi-field writes — partial/torn reads can
    produce inconsistent beat state
  - Beat jitter — mitigated via a local metronome synced to PDL, not raw
    PDL timestamps consumed directly
  - Phrase Engine follows one deck while the Transition Engine manages
    handoff — a bug in one can look like a bug in the other
- Phase 1 scaffolding already in place: ProDJLinkListener, MidiInputListener,
  DemoDataGenerator

## Investigation approach
1. Determine whether the symptom is in PDL data ingestion, the local
   metronome sync, or downstream consumption (ShowState,
   EnergyModeDetector, ReactiveLayerEngine)
2. Check for partial/torn reads on multi-field PDL writes before assuming
   a beat-detection logic bug
3. If it's a MIDI issue, confirm whether it's fader intent (MidiInputListener)
   vs audio-driven bias — these are separate paths in v2

## What to report back
Return only:
- Root cause (one or two sentences)
- The specific file and fix
- Whether it's a data-ingestion bug, a sync/jitter bug, or a downstream
  consumer bug

Do not report your exploration trail — just the diagnosis and fix.
