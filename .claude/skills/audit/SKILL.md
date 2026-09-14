---
name: audit
description: Runs LiveReact's audit checklist against the current build — DMX address overlaps, Enttec packet size/protocol correctness, and sustained frame rate. Use before merging changes to dmx/, fixtures/, core/rig.py, or before a live show.
---

Run LiveReact's audit checklist against the current codebase and active
rig config, and report pass/fail for each item:

1. No DMX address range overlaps across all fixtures in the active rig file
   (`fixtures/rig.py::Rig._validate_and_index` raises `RigError` on collision)
2. Enttec packets are exactly 518 bytes
   (`output/enttec.py::build_enttec_frame` — 4 header + 1 start code + 512 + 1 end)
3. Enttec protocol framing is correct (start delimiter `0x7E`, label `0x06`,
   little-endian length = 513, DMX start code `0x00`, end delimiter `0xE7`)
4. Sustained frame rate meets target (40Hz — `output/writer.py::DmxWriter`'s
   `hz` default, matching `app.py`'s `dmx_rate_hz` config default; this
   replaces the previously-documented "83fps" target, which doesn't match
   any current default or the DMX-512 wire spec's own ~44Hz theoretical
   ceiling for a full 512-channel universe)
5. No fixture's channel footprint overflows the 512-channel universe
   (`fixtures/rig.py::Rig._validate_and_index` — `fx.address + fx.channel_count
   - 1 > UNIVERSE_SIZE` raises `RigError`; distinct failure mode from #1,
   same guard)
6. Every fixture's `channel_kinds()` length matches its declared
   `channel_count` (`fixtures/rig.py::Rig._validate_and_index` raises
   `RigError` on mismatch) — a silent mismatch would corrupt the merge
   layer's per-channel HTP/LTP-by-priority routing (`ChannelKind` map)
7. Fixture-specific channel validation — each profile's semantic setters
   (`set_intensity`/`set_color`/`set_position`/`set_strobe`) and
   `boot_defaults()` write to the DMX offsets documented in that class's
   own docstring (`fixtures/profiles.py`): `MovingHead` CH1/3=pan/tilt,
   CH6=dimmer, CH7=strobe, CH8=color wheel; `Laser` CH1=mode, CH2=pattern,
   CH12=color; `Par` CH1=dimmer, CH2-4=RGB; `WashBar` CH1=dimmer,
   CH2=strobe, CH3-6=RGBW. Flag any setter writing outside its fixture's
   documented channel map.
8. Laser safety gate — `Laser.apply_safety()` zeros all 12 channels unless
   `laser_enabled` is true AND `mount_height_m` is set and
   `>= min_beam_height_m` (fail-closed on unconfigured geometry, per
   LIGHTING_BIBLE.md LASER-08/09/10/11). Confirm no code path can set
   laser channels after this gate runs in `merge/merge.py`'s finalize
   sequence (`apply_safety` must run before send).
9. DMX byte-range clamping — every write path that touches the universe
   (semantic setters via `_to8`/`_intensity_to8`, and the finalize-stage
   passes `apply_master_brightness`/`cap_strobe`/`apply_color_bias`/
   `apply_slew_limit`/`apply_home_position`/`apply_onset_gate` in
   `merge/merge.py`, plus `Rig.boot_universe`'s `_UniBuffer.set`) clamps
   to 0-255 before the value reaches a `bytearray` — no unclamped
   float/out-of-range write should reach `DmxFrameBuffer.publish()`.
10. DMX writer fault tolerance — `output/writer.py::DmxWriter._run_loop`
    never lets an exception escape: a backend `send()` failure is caught,
    logged, triggers close+reopen (`_handle_send_error`) with capped
    backoff (`min(max_backoff, 0.05 * consecutive_errors)`), and the loop
    keeps ticking on the last published frame. This is the "DMX writer
    never stops" contract from `docs/05 §5.1` — confirm no new code path
    added to the writer loop can throw past the try/except.
11. Enttec port selection — `output/enttec.py::select_enttec_port` matches
    only by FTDI VID (`0x0403`), never by device name, and prefers a
    `cu.*` node over `tty.*` on macOS (the `tty.*` node blocks on open,
    per `docs/04 §5.3`).

Report results as a simple pass/fail table. If any check fails, name the
specific file and line responsible, not just the category.

Provenance note: checks 1-4 were the only ones documented in project notes
when this skill was first written; checks 5-11 were reconstructed by
reading the actual v2 source (`fixtures/rig.py`, `fixtures/profiles.py`,
`output/enttec.py`, `output/writer.py`, `merge/merge.py`) rather than
recovered from any v1 record of the original manual audit — the v1 audit
itself was never written down beyond the 4 items above. Treat 5-11 as a
good-faith reconstruction of what a real DMX-output audit should cover
for this rig, not a verified transcription of what Josh's original manual
pass actually checked. If Josh recalls specific v1 checks that aren't
covered above, replace the reconstructed ones with those.
