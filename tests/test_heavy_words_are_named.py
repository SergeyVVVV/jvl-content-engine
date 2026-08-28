"""The vocabulary check pointed at nothing the Writer could find.

Every other check names its target. "One sentence runs 44 words." "379 words run
without a break." The Writer can go and look.

The vocabulary check handed over two ratios and a generic example — and the list
of the draft's actual heavy words sat unused in the same stats dict the whole
time. It was the check drafts failed most often and fixed least: 13% difficult
words in one run, 14% in three others, against an 11% ceiling.

Two changes. The words are named. And they are chosen by what they cost the
reader rather than by where they happen to appear.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.readability_agent import prose_problems, score_markdown  # noqa: E402


def stats(**over) -> dict:
    base = {
        "flesch_reading_ease": 67.0, "avg_sentence_length": 18.0,
        "sentence_length_stdev": 8.0, "short_sentence_share": 0.25,
        "long_sentence_share": 0.05, "longest_sentence_words": 20,
        "avg_syllables_per_word": 1.60, "difficult_word_share": 0.16,
        "longest_prose_run": 200, "list_line_share": 0.10,
        "hardest_words": [
            {"word": "depreciation", "syllables": 5, "occurrences": 3},
            {"word": "configuration", "syllables": 5, "occurrences": 2},
        ],
    }
    base.update(over)
    return base


def vocabulary_problem(s: dict) -> str:
    return next(p for p in prose_problems(s) if "vocabulary is heavier" in p)


class NamingTests(unittest.TestCase):
    def test_the_offending_words_are_in_the_instruction(self) -> None:
        problem = vocabulary_problem(stats())
        self.assertIn("depreciation", problem)
        self.assertIn("configuration", problem)

    def test_the_writer_is_told_which_ones_to_leave(self) -> None:
        """"pessimistic" is four syllables because the brief asked for it."""
        self.assertIn("A term the brief asked for stays", vocabulary_problem(stats()))

    def test_it_asks_for_replacement_not_deletion(self) -> None:
        problem = vocabulary_problem(stats())
        self.assertIn("carrying no meaning a shorter word would lose", problem)

    def test_the_separate_dials_warning_survives(self) -> None:
        """Shortening sentences was always the wrong answer to this one."""
        self.assertIn("do not shorten sentences", vocabulary_problem(stats()))

    def test_a_draft_with_no_recorded_words_still_gets_the_rule(self) -> None:
        problem = vocabulary_problem(stats(hardest_words=[]))
        self.assertIn("vocabulary is heavier", problem)
        self.assertNotIn("The heaviest words in this draft", problem)

    def test_the_list_is_bounded(self) -> None:
        many = [{"word": f"word{i}", "syllables": 4, "occurrences": 1} for i in range(30)]
        problem = vocabulary_problem(stats(hardest_words=many))
        named = re.search(r"draft: (.+?)\. Replace", problem).group(1)
        self.assertLessEqual(len(named.split(", ")), 12)


class RankingTests(unittest.TestCase):
    """Cost is length times how often the reader meets it."""

    def test_a_repeated_heavy_word_outranks_a_single_one(self) -> None:
        md = "## H\n\n" + ("depreciation is here. " * 5) + ("individually once. ")
        found = score_markdown(md)["hardest_words"]
        self.assertEqual(found[0]["word"].lower(), "depreciation")
        self.assertEqual(found[0]["occurrences"], 5)

    def test_document_order_no_longer_decides(self) -> None:
        """The old selection took the first fifteen long words as they appeared."""
        md = "## H\n\n" + "editorial. " + ("configuration " * 4)
        found = [w["word"].lower() for w in score_markdown(md)["hardest_words"]]
        self.assertEqual(found[0], "configuration")

    def test_short_words_are_never_listed(self) -> None:
        md = "## H\n\n" + "the cat sat on the mat and then it sat again. " * 4
        self.assertEqual(score_markdown(md)["hardest_words"], [])

    def test_occurrences_are_recorded_for_the_reader_of_the_stats(self) -> None:
        md = "## H\n\n" + ("configuration " * 3)
        self.assertIn("occurrences", score_markdown(md)["hardest_words"][0])

    def test_it_reproduces_the_measured_draft(self) -> None:
        draft = (
            REPO_ROOT / "outputs/t5/drafts"
            / "how-fast-can-an-arcade-machine-pay-for-itself-in-a-bar-or-ev.md"
        )
        if not draft.exists():
            self.skipTest("run output not present")
        md = draft.read_text(encoding="utf-8")
        body = md[: re.search(r"^##\s+FAQ", md, re.M | re.I).start()]
        words = [w["word"].lower() for w in score_markdown(body)["hardest_words"]]
        # Words a reader would happily lose, which the old order buried.
        self.assertTrue(
            {"depreciation", "configuration", "individually"} & set(words), words
        )


if __name__ == "__main__":
    unittest.main()
