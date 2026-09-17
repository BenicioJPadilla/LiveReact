"""The rise phase: when intensity is building toward a drop (2026-09-17).

Josh, after run 10 (recordings/session-20260917-154312): "my goal would be
to arm the strobe and then it correctly identifies in the next however many
bars when the strobe starts and when it ends... find a way to analyze when
intensity is building within the rising phase." The loudness classifier's
BUILD is a plateau guess -- on that run it ran the build strobe for 42 s
before the drop, while the audible rise (high band 0.09 -> 0.18, onset rate
4 -> 8.6/s, flux 0.038 -> 0.062) only began ~8 bars out.

What a rise looks like in this project's own features, per bar, on every
real drop of the day's four captures: the high band's LEVEL and its ONSET
DENSITY (inputs/audio.py ONSET_*) both climb to ~2-3x what the track ran a
few bars earlier, and keep climbing into the hit; the two false drops of the
day sat at ~1.1x. So the detector is a ratio: the last bar's high-band level
and onset rate against the median of the bars before the rise could have
started (a window that ends RISE_BASE_GAP_BARS ago, frozen while a rise is
active so the rise can't erode its own reference), averaged into one
intensity index `I`, smoothed over ~a bar.

`I` drives two things upstream: engines/reactive.py's build strobe RATE
(2 Hz at RISE_ON, 4 Hz at RISE_FULL -- the strobe only runs while
the drop is ARMED and the rise is on), and optionally the metronome's
auto-arm (RISE_ARM held RISE_ARM_BARS). Per-beat resolution: the metronome
feeds one sample per beat; everything here counts in beats/bars, nothing in
seconds. Thresholds are [CONVENTION] against 2026-09-17's captures; re-score
with tools/simulations/replay_state.py before touching them.
"""
from __future__ import annotations

import math
from collections import deque

RISE_BASE_BARS = 12       # the reference: median over this many bars ...
RISE_BASE_GAP_BARS = 4    # ... ending this many bars ago (the rise itself is excluded)
RISE_BASE_MIN_BARS = 8    # no rise can be judged until this much reference exists (a track
                          # that starts from silence is blind for its first ~12 bars: a
                          # rise is relative to what THIS track has been doing, and the
                          # metronome never feeds silent beats -- see _derive_rise)
RISE_ON = 1.6             # index that starts a rise ... (1.4 -> 1.6: at 1.4 the kick-plateau
                          # before run 10's second drop read as a 36 s rise; at 1.6 every real
                          # rise of the day still starts 6-8 s before its hit)
RISE_ON_BEATS = 2         # ... once held this many beats
RISE_OFF = 1.15           # index under this ends the rise ...
RISE_OFF_BARS = 2         # ... once held this many bars
RISE_MAX_BARS = 24        # a "rise" longer than this is a texture, not a build
RISE_FLAT_BARS = 4        # ... and one that has stopped CLIMBING for this long is a
                          # plateau, not a rise (replaying the 2026-09-15 captures: a
                          # track's intro -> groove step read as a 45 s "rise" at 6-9x
                          # -- higher, yes, but flat from the second bar on)
RISE_CLIMB_RATIO = 1.05   # the last two bars' mean RAW index must be at least this much
                          # above the two bars before them to count as still climbing
RISE_FULL = 2.6           # index at which the strobe reaches its top rate (2 Hz at RISE_ON;
                          # run 9's kick plateau sits at 1.7-1.95 = a slow pulse, its roll at 3.3)
RISE_ARM = 1.8            # auto-arm threshold (metronome) ...
RISE_ARM_BARS = 2         # ... held this many bars ...
RISE_ARM_ONSET = 1.4      # ... with the onset-density ratio alone at least this: the level
                          # alone can't arm (the 2026-09-15 captures' intro -> groove steps
                          # read 5-9x in level with no density change; a roll or a riser
                          # brings hats/snares, a louder section doesn't)
RISE_SMOOTH_BEATS = 4.0   # EMA over ~a bar of beats
ONSET_BASE_MIN = 2.0      # onsets/s; under this the onset ratio is meaningless (no hats)
LEVEL_FLOOR = 0.02        # high-band level under this is noise
BEATS_PER_BAR = 4


class RiseDetector:
    """Feed it one sample per BEAT (`on_beat(hi, onset)`); read `rising`,
    `index`, `rise_beats`. `drop_landed()` ends a rise from outside."""

    def __init__(self) -> None:
        self._beats: deque[tuple[float, float]] = deque(
            maxlen=(RISE_BASE_BARS + RISE_BASE_GAP_BARS) * BEATS_PER_BAR
        )
        self._frozen_base: tuple[float, float] | None = None
        self.index = 1.0
        self._raw_index = 1.0
        self.rising = False
        self._on_beats = 0
        self._off_beats = 0
        self.rise_beats = 0
        self._arm_beats = 0
        self.arm_ready = False    # True on the beat RISE_ARM has been held RISE_ARM_BARS
        self._raw_hist: deque[float] = deque(maxlen=4 * BEATS_PER_BAR)  # last four bars of raw index
        self._flat_beats = 0
        self.onset_ratio = 1.0    # the density half of the index, for RISE_ARM_ONSET
        self._wait_below_off = False  # after a plateau end: no new rise until the index falls under RISE_OFF

    # --- reference --------------------------------------------------------
    def _baseline(self) -> tuple[float, float] | None:
        if self._frozen_base is not None:
            return self._frozen_base
        gap = RISE_BASE_GAP_BARS * BEATS_PER_BAR
        hist = list(self._beats)[:-gap] if len(self._beats) > gap else []
        if len(hist) < RISE_BASE_MIN_BARS * BEATS_PER_BAR:
            return None  # not enough history for a reference yet
        his = sorted(h for h, _ in hist)
        ons = sorted(o for _, o in hist)
        return his[len(his) // 2], ons[len(ons) // 2]

    @staticmethod
    def _index_of(hi: float, onset: float, base: tuple[float, float]) -> tuple[float, float]:
        """(index, onset ratio) -- the onset ratio is 1.0 when there are no hats to compare."""
        base_hi, base_on = base
        r_hi = hi / max(base_hi, LEVEL_FLOOR)
        if base_on >= ONSET_BASE_MIN:
            r_on = onset / base_on
            return 0.5 * r_hi + 0.5 * r_on, r_on
        return r_hi, 1.0

    # --- per beat -----------------------------------------------------------
    def on_beat(self, hi: float, onset: float) -> bool:
        """One completed beat's mean high-band level and onset rate. Returns
        True while a rise is on."""
        base = self._baseline()
        self._beats.append((hi, onset))
        self.arm_ready = False
        if base is None:
            self._raw_index = self.index = 1.0
            return self.rising
        self._raw_index, r_on = self._index_of(hi, onset, base)
        coeff = 1 - math.exp(-1.0 / RISE_SMOOTH_BEATS)
        self.index += coeff * (self._raw_index - self.index)
        self.onset_ratio += coeff * (r_on - self.onset_ratio)
        if self._wait_below_off and self.index < RISE_OFF:
            self._wait_below_off = False
        self._raw_hist.append(self._raw_index)
        if len(self._raw_hist) == self._raw_hist.maxlen:
            half = 2 * BEATS_PER_BAR
            older = sum(list(self._raw_hist)[:half]) / half
            newer = sum(list(self._raw_hist)[half:]) / half
            climbing = newer >= older * RISE_CLIMB_RATIO
        else:
            climbing = True

        if not self.rising:
            self._on_beats = self._on_beats + 1 if self.index >= RISE_ON and not self._wait_below_off else 0
            if self._on_beats >= RISE_ON_BEATS:
                self.rising = True
                self._frozen_base = base  # judge the whole rise against the level before it
                self.rise_beats = 0
                self._off_beats = 0
                self._on_beats = 0
        else:
            self.rise_beats += 1
            self._off_beats = self._off_beats + 1 if self.index < RISE_OFF else 0
            self._flat_beats = 0 if climbing else self._flat_beats + 1
            plateau = (self._flat_beats >= RISE_FLAT_BARS * BEATS_PER_BAR
                       or self.rise_beats >= RISE_MAX_BARS * BEATS_PER_BAR)
            if self._off_beats >= RISE_OFF_BARS * BEATS_PER_BAR or plateau:
                self._end()
                self._wait_below_off = plateau  # a plateau must fall back before it can rise again
        # auto-arm: a STRONG rise held RISE_ARM_BARS (the metronome decides what to do with it)
        strong = self.index >= RISE_ARM and self.onset_ratio >= RISE_ARM_ONSET
        self._arm_beats = self._arm_beats + 1 if strong else 0
        if self._arm_beats == RISE_ARM_BARS * BEATS_PER_BAR:
            self.arm_ready = True
        return self.rising

    def drop_landed(self) -> None:
        """The drop committed: the rise is over, and the drop's own bars must
        not become the next reference until they've aged past the gap."""
        self._end()

    def _end(self) -> None:
        self.rising = False
        self._frozen_base = None
        self.rise_beats = 0
        self._off_beats = 0
        self._on_beats = 0
        self._arm_beats = 0
        self._flat_beats = 0

    @property
    def strobe01(self) -> float:
        """The build strobe's rate, 0..1, from the intensity (engines/reactive.py)."""
        if not self.rising:
            return 0.0
        return max(0.0, min(1.0, (self.index - RISE_ON) / (RISE_FULL - RISE_ON)))
