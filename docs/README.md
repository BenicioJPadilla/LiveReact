# LiveReact — Inherited-Project Analysis (`docs/`)

This directory is a full analysis of the **LiveReact** project as handed over in `../initial_docs/`. It was produced for a new owner who is inheriting the project, intends to **rebuild it from scratch**, is targeting **macOS (keeping the code cross-platform-capable)**, has **no access to the original author ("Josh") and no access to the prior source code**, and asked for the existing spec to be **critically challenged**, not taken as gospel.

> **What LiveReact is, in one line:** a beat-reactive DMX stage-lighting controller that reads musical timing from a Pioneer XDJ-XZ (Pro DJ Link over Ethernet + USB MIDI) and automatically drives an 8-fixture / 74-channel DMX rig through an Enttec DMX USB Pro at ~44 Hz, for live DJ sets.

## What's in `initial_docs/`

A **design portfolio**, not a codebase: 7 core docs (README, domain primer, hardware rig, architecture, design principles, build plan, testing/show-day), 5 appendices (DMX-512, Pro DJ Link, XDJ-XZ MIDI map, fixture manuals, glossary), and a `REFERENCE/` folder containing a *partial* v1 code snapshot (entry point + launchers only — no core logic) plus notes on a "v2 Phase 1" that reportedly built the input layer but whose source is **not included**. See [`01_PROJECT_STATE_ASSESSMENT.md`](01_PROJECT_STATE_ASSESSMENT.md).

## How to read this

Start with the executive summary, then read in order. Each document stands alone but they build on each other.

| # | Document | What it answers |
|---|----------|-----------------|
| 00 | [Executive Summary](00_EXECUTIVE_SUMMARY.md) | The whole analysis in 5 minutes: verdict + top recommendations |
| 01 | [Project State Assessment](01_PROJECT_STATE_ASSESSMENT.md) | What actually exists? What's real vs. aspirational? Where are the gaps? |
| 02 | [Goal & Requirements](02_GOAL_AND_REQUIREMENTS.md) | What is this trying to be? Functional + non-functional requirements, scope, acceptance criteria |
| 03 | [Domain Brief](03_DOMAIN_BRIEF.md) | Self-contained primer: DMX, Pro DJ Link, MIDI, lighting design — everything you need, no Josh required |
| 04 | [Hardware & Protocols](04_HARDWARE_AND_PROTOCOLS.md) | The rig, fixture channel maps, wire-level protocol detail, and the **data-availability reality check** |
| 05 | [Architecture Review](05_ARCHITECTURE_REVIEW.md) | Critique of the proposed v2 architecture; what to keep, fix, and add |
| 06 | [Tech-Stack Evaluation](06_TECH_STACK_EVALUATION.md) | "Challenge everything": language, Python version, UI toolkit, libraries — with recommendations |
| 07 | [Platform Strategy](07_CROSSPLATFORM_STRATEGY.md) | macOS-first deployment; portability via hardware abstractions; the Windows gotchas as revival reference |
| 08 | [Lighting Design & Safety](08_LIGHTING_DESIGN_AND_SAFETY.md) | Scene catalog, aesthetics, the frequency→color verdict, laser & strobe safety |
| 09 | [Risk Register](09_RISK_REGISTER.md) | Consolidated risks with likelihood, impact, and mitigation |
| 10 | [Open Questions & Assumptions](10_OPEN_QUESTIONS_AND_ASSUMPTIONS.md) | The "no Josh" gap: every question I'd have asked, with my best-guess working assumptions |
| 11 | [Recommended Approach](11_RECOMMENDED_APPROACH.md) | The brainstorm: how I'd actually rebuild this, and why |
| 12 | [Rebuild Roadmap](12_REBUILD_ROADMAP.md) | A phased, demo-first, macOS-first (portable) plan from empty repo to show-ready |
| 13 | [Decision Log](13_DECISION_LOG.md) | Every place this analysis deviates from the spec, with rationale |

## Provenance & confidence

- Everything attributed to the spec is cited to a file in `../initial_docs/`.
- External/technical claims (library health, OS behavior, safety regulations, perception science) were researched against current (mid-2026) sources; URLs are inline in the relevant documents (esp. 06, 07, 08).
- Where something is genuinely uncertain in 2026 or depends on hardware I can't test, it is **flagged explicitly** rather than asserted.
- The spec's own facts (channel maps, MIDI CCs, addresses) are reproduced but marked **"verify on hardware"** — they were "verified on Josh's unit" and firmware/mode changes can move them.

*Analysis date: 2026-06-01.*
