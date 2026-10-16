"""Every rig's demo-mode show must produce the recorded DMX frames.

A failure here means the audience would see something different. If that is
the intent of the change, re-record with ``python tests/golden_frames.py
--update`` and say so in the PR; otherwise it's a regression. See
tests/golden_frames.py for what the run covers.
"""

from __future__ import annotations

import json

import golden_frames


def test_every_rig_matches_its_golden_frames():
    expected = json.loads(golden_frames.GOLDEN_PATH.read_text(encoding="utf-8"))
    problems = golden_frames.diff(expected, golden_frames.run_all())
    assert not problems, "\n".join(problems)
