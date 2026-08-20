"""Readability is a band, and rhythm is measured alongside it.

The target used to be Flesch Reading Ease >= 90 — a fifth-grade level, and for
this subject matter arithmetically unreachable: at 90 the prose may average
about 1.24 syllables per word, while "payback" is 2, "maintenance" 3,
"electricity" 5 and "profitability" 6. A measured article came in at 1.47.

The consequence was not a missed target, it was a loop that never terminated
satisfied and told the Writer to cut again on every pass. What came back read
like a checklist with the bullets removed: 13.2 words per sentence, 64% of them
under fifteen, 44-word paragraphs. These tests pin the band in both directions.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.readability_agent import (  # noqa: E402
    MAX_MEAN_SENTENCE,
    MAX_SHORT_SENTENCE_SHARE,
    MIN_MEAN_SENTENCE,
    MIN_SENTENCE_STDEV,
    TARGET_MAX,
    TARGET_MIN,
    prose_is_in_range,
    prose_problems,
    score_markdown,
)


def stats(score=62.0, mean=18.0, stdev=9.0, short=0.30) -> dict:
    return {
        "flesch_reading_ease": score,
        "avg_sentence_length": mean,
        "sentence_length_stdev": stdev,
        "short_sentence_share": short,
    }


class BandTests(unittest.TestCase):
    def test_the_target_is_reachable_for_this_subject_matter(self) -> None:
        # At 90, with 15-word sentences, the ceiling is ~1.20 syllables/word.
        # "profitability" alone is six. Anything above ~85 is unreachable prose
        # for a business topic, so the band must sit well below it.
        self.assertLess(TARGET_MAX, 85)

    def test_plain_business_prose_passes(self) -> None:
        self.assertTrue(prose_is_in_range(stats()))

    def test_dense_prose_is_flagged(self) -> None:
        problems = prose_problems(stats(score=TARGET_MIN - 10))
        self.assertTrue(any("harder work" in p for p in problems))

    def test_over_simplified_prose_is_flagged_too(self) -> None:
        # The direction that used to be the goal is now a defect.
        problems = prose_problems(stats(score=TARGET_MAX + 10))
        self.assertTrue(any("choppy" in p for p in problems))

    def test_the_feedback_never_only_says_simplify(self) -> None:
        for p in prose_problems(stats(score=TARGET_MAX + 10)):
            self.assertNotIn("Simplify", p)


class RhythmTests(unittest.TestCase):
    def test_checklist_cadence_is_flagged(self) -> None:
        problems = prose_problems(stats(mean=MIN_MEAN_SENTENCE - 2))
        self.assertTrue(any("checklist cadence" in p for p in problems))

    def test_rambling_is_flagged(self) -> None:
        problems = prose_problems(stats(mean=MAX_MEAN_SENTENCE + 5))
        self.assertTrue(any("Split the" in p for p in problems))

    def test_uniform_sentence_length_is_flagged(self) -> None:
        problems = prose_problems(stats(stdev=MIN_SENTENCE_STDEV - 3))
        self.assertTrue(any("barely varies" in p for p in problems))

    def test_mostly_short_sentences_is_flagged(self) -> None:
        problems = prose_problems(stats(short=MAX_SHORT_SENTENCE_SHARE + 0.2))
        self.assertTrue(any("under twelve words" in p for p in problems))

    def test_every_problem_says_what_to_do(self) -> None:
        # These strings go straight to the Writer, so each must be an
        # instruction rather than a complaint.
        problems = prose_problems(stats(score=90.0, mean=10.0, stdev=2.0, short=0.8))
        self.assertEqual(len(problems), 4)
        for p in problems:
            self.assertGreater(len(p), 80, p)


CHECKLIST_PROSE = (
    "# T\n\n" + "The machine costs money. The split is even. Payback takes time. "
    "You must plan. The room matters most. Traffic drives the drop. " * 12
)

NARRATIVE_PROSE = (
    "# T\n\n"
    + (
        "The machine costs four thousand dollars, which sounds like the whole "
        "question until you look at where the money actually comes back from, "
        "because the room does more work than the hardware ever will. Traffic "
        "drives the drop. A quiet bar with a good machine earns less than a busy "
        "one with a mediocre machine, and no specification sheet will tell you "
        "that, which is why the first number to establish is not the price but "
        "the count of people who walk past the spot on a Friday. Plan for the "
        "middle case. "
    ) * 8
)


class MeasuredProseTests(unittest.TestCase):
    def test_checklist_cadence_is_caught_on_real_text(self) -> None:
        problems = prose_problems(score_markdown(CHECKLIST_PROSE))
        self.assertTrue(problems, "staccato prose should not pass")

    def test_stats_carry_the_rhythm_fields(self) -> None:
        s = score_markdown(NARRATIVE_PROSE)
        self.assertIn("sentence_length_stdev", s)
        self.assertIn("short_sentence_share", s)
        self.assertGreater(s["avg_sentence_length"], MIN_MEAN_SENTENCE)

    def test_empty_input_does_not_crash(self) -> None:
        s = score_markdown("")
        self.assertEqual(s["sentence_length_stdev"], 0.0)
        self.assertEqual(s["short_sentence_share"], 0.0)


if __name__ == "__main__":
    unittest.main()
