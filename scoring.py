"""osu!lazer mania judgements and scoring, ported from ppy/osu (default windows, no Classic mod)."""

import math

PERFECT, GREAT, GOOD, OK, MEH, MISS = "PERFECT", "GREAT", "GOOD", "OK", "MEH", "MISS"
RESULTS = (PERFECT, GREAT, GOOD, OK, MEH, MISS)  # best first

# Window sizes in ms at OD 0, 5 and 10 (ManiaHitWindows.cs)
WINDOW_RANGES = {
    PERFECT: (22.4, 19.4, 13.9),
    GREAT: (64, 49, 34),
    GOOD: (97, 82, 67),
    OK: (127, 112, 97),
    MEH: (151, 136, 121),
    MISS: (188, 173, 158),
}
BASE_SCORE = {PERFECT: 305, GREAT: 300, GOOD: 200, OK: 100, MEH: 50, MISS: 0}
COMBO_SCORE = {**BASE_SCORE, PERFECT: 300}
RELEASE_LENIENCE = 1.5  # hold releases get 1.5x wider windows (TailNote.cs)
RANK_CUTOFFS = ((0.95, "S"), (0.9, "A"), (0.8, "B"), (0.7, "C"))


def difficulty_range(od, at_0, at_5, at_10):
    if od > 5:
        return at_5 + (at_10 - at_5) * (od - 5) / 5
    if od < 5:
        return at_5 + (at_5 - at_0) * (od - 5) / 5
    return at_5


def hit_windows(od):
    """Seconds either side of a note that each result reaches."""
    return {r: (math.floor(difficulty_range(od, *WINDOW_RANGES[r])) + 0.5) / 1000 for r in RESULTS}


def result_for(windows, offset):
    """The result for pressing `offset` seconds off, or None if it's too far to count."""
    offset = abs(offset)
    for result in RESULTS:
        if offset <= windows[result]:
            return result
    return None


def is_better(result, than):
    return RESULTS.index(result) < RESULTS.index(than)


def combo_multiplier(combo):
    return min(max(0.5, math.log(combo, 4)), math.log(400, 4))


class ScoreKeeper:
    def __init__(self, judgement_count):
        self.total = judgement_count
        self.counts = dict.fromkeys(RESULTS, 0)
        self.combo = 0
        self.max_combo = 0
        self.base = 0
        self.max_base = 0
        self.judged = 0
        self.combo_portion = 0.0
        self.max_combo_portion = sum(COMBO_SCORE[PERFECT] * combo_multiplier(c) for c in range(1, judgement_count + 1))

    def add(self, result):
        self.counts[result] += 1
        self.combo = 0 if result == MISS else self.combo + 1
        self.max_combo = max(self.max_combo, self.combo)
        self.base += BASE_SCORE[result]
        self.max_base += BASE_SCORE[PERFECT]
        self.judged += 1
        if COMBO_SCORE[result]:
            self.combo_portion += COMBO_SCORE[result] * combo_multiplier(self.combo)

    def combo_break(self):
        self.combo = 0

    @property
    def accuracy(self):
        return self.base / self.max_base if self.max_base else 1.0

    @property
    def score(self):
        combo_progress = self.combo_portion / self.max_combo_portion if self.max_combo_portion else 1
        accuracy_progress = self.judged / self.total if self.total else 1
        acc = self.accuracy
        return round(150000 * combo_progress + 850000 * acc ** (2 + 2 * acc) * accuracy_progress)

    @property
    def rank(self):
        acc = self.accuracy
        if acc == 1:
            return "SS"
        for cutoff, rank in RANK_CUTOFFS:
            if acc >= cutoff:
                # Mania gives SS to any run with only PERFECT and GREAT
                if rank == "S" and not any(self.counts[r] for r in (GOOD, OK, MEH, MISS)):
                    return "SS"
                return rank
        return "D"
