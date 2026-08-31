"""Merge layer (Phase 2): combine engine contributions per channel (max for
color/dimmer, last-write-wins for movement, capped strobe), apply manual
biases/caps, and enforce safety clamps (laser off unless explicitly enabled,
strobe rate cap) before writing the 512-byte universe. (Analysis: docs/05 §5,
docs/08 §5.)"""
