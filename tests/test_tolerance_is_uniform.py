"""Every threshold gets the same benefit of the doubt.

`_TOLERANCE` exists because the numbers in this module are judgements, not
measurements: ten percent of a boundary is the width of the doubt in the
boundary itself. Five checks used it. Two — the longest sentence and the longest
unbroken run of prose — were added later and compared hard.

So a run reporting a 372-word wall against a 350-word ceiling, six percent over
and well inside the doubt every other check is granted, counted as a defect. It
cost two full Writer calls. And because the loop decides it is "not converging"
by counting these problems, the noise did not merely reach the report — it
decided when to stop.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.readability_agent import (  # noqa: E402
    MAX_PROSE_RUN_WORDS,
    MAX_SENTENCE_WORDS,
    _TOLERANCE,
    prose_problems,
)


def stats(**over) -> dict:
    base = {
        "flesch_reading_ease": 67.0,
        "avg_sentence_length": 18.0,
        "sentence_length_stdev": 8.0,
        "short_sentence_share": 0.25,
        "long_sentence_share": 0.05,
        "longest_sentence_words": 20,
        "avg_syllables_per_word": 1.40,
        "difficult_word_share": 0.09,
        "longest_prose_run": 200,
        "list_line_share": 0.10,
    }
    base.update(over)
    return base


class UniformityTests(unittest.TestCase):
    def test_a_clean_draft_reports_nothing(self) -> None:
        self.assertEqual(prose_problems(stats()), [])

    def test_a_trivial_overshoot_on_the_wall_is_not_a_defect(self) -> None:
        """372 against 350 — the measured case that cost two Writer calls."""
        self.assertEqual(prose_problems(stats(longest_prose_run=372)), [])

    def test_a_real_wall_still_is(self) -> None:
        problems = prose_problems(stats(longest_prose_run=1305))
        self.assertEqual(len(problems), 1)
        self.assertIn("1305 words run", problems[0])

    def test_a_trivial_overshoot_on_one_sentence_is_not_a_defect(self) -> None:
        self.assertEqual(prose_problems(stats(longest_sentence_words=37)), [])

    def test_a_sentence_a_reader_would_notice_still_is(self) -> None:
        """51 and 63 words both shipped. Neither is a rounding error."""
        for words in (51, 63):
            problems = prose_problems(stats(longest_sentence_words=words))
            self.assertEqual(len(problems), 1, words)
            self.assertIn(f"{words} words", problems[0])

    def test_the_edge_of_the_tolerance_is_where_it_says_it_is(self) -> None:
        edge = int(MAX_PROSE_RUN_WORDS * (1 + _TOLERANCE))
        self.assertEqual(prose_problems(stats(longest_prose_run=edge)), [])
        self.assertEqual(len(prose_problems(stats(longest_prose_run=edge + 20))), 1)

    def test_no_check_compares_against_a_bare_threshold(self) -> None:
        """The two that did were added after the tolerance and missed it."""
        source = (REPO_ROOT / "src" / "readability_agent.py").read_text(encoding="utf-8")
        body = source[source.index("def prose_problems") : source.index("def prose_is_in_range")]
        bare = re.findall(r"if\s+\w+\s*[<>]\s*(?:MAX|MIN)_\w+", body)
        self.assertEqual(bare, [], f"compared without tolerance: {bare}")

    def test_the_tolerance_is_documented_where_it_lives(self) -> None:
        source = (REPO_ROOT / "src" / "readability_agent.py").read_text(encoding="utf-8")
        flat = re.sub(r"\s+", " ", source)
        self.assertIn("It applies to every check", flat)


class LoopEffectTests(unittest.TestCase):
    """The count is not just a report — it is the loop's stopping rule."""

    def test_noise_no_longer_counts_toward_convergence(self) -> None:
        noisy = stats(longest_prose_run=372, longest_sentence_words=37)
        self.assertEqual(len(prose_problems(noisy)), 0)

    def test_the_measured_draft_drops_one_of_its_four(self) -> None:
        draft = (
            REPO_ROOT / "outputs/t1/drafts"
            / "how-fast-can-an-arcade-machine-pay-for-itself-in-a-bar-or-ev.md"
        )
        if not draft.exists():
            self.skipTest("run output not present")
        from src.readability_agent import score_markdown

        md = draft.read_text(encoding="utf-8")
        body = md[: re.search(r"^##\s+FAQ", md, re.M | re.I).start()]
        problems = prose_problems(score_markdown(body))
        self.assertEqual(len(problems), 3)
        self.assertFalse(any("without a table" in p for p in problems))
        self.assertTrue(any("51 words" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
