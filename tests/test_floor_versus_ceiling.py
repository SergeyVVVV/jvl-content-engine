"""Two rules in one prompt that could not both be obeyed.

The Writer was told each H2 section carries at least 250 words of prose, with
tables and lists explicitly not counting toward that floor. It was also told
never to let prose run more than 350 words unbroken, with headings explicitly
not breaking a run.

Those meet head-on. A section written to its own target sits at the ceiling with
no margin; two sections at the floor, back to back and unbroken, make a 500-word
wall with a subtitle in the middle. A measured draft produced four consecutive
sections with no break at all and a 1,261-word run spanning three headings.

The prompt now says which rule wins and what that means in practice.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.readability_agent import (  # noqa: E402
    MAX_PROSE_RUN_WORDS,
    MAX_SENTENCE_WORDS,
    longest_prose_run,
    prose_problems,
    score_markdown,
)

import re

RAW = (REPO_ROOT / "prompts" / "writer_agent.md").read_text(encoding="utf-8")
#: Line wrapping is not part of the rule. Assert on the sentence, not the fill.
PROMPT = re.sub(r"\s+", " ", RAW)


def assert_says(case: unittest.TestCase, phrase: str) -> None:
    """assertIn without dumping the whole prompt into the failure message."""
    case.assertTrue(phrase in PROMPT, f"prompt does not say: {phrase!r}")


class ContradictionTests(unittest.TestCase):
    def test_the_prompt_names_the_conflict_rather_than_leaving_it_implicit(self) -> None:
        assert_says(self, "meet head-on")

    def test_the_ceiling_is_declared_the_winner(self) -> None:
        assert_says(self, "The ceiling wins")

    def test_a_section_at_the_floor_must_carry_a_break_inside_it(self) -> None:
        """"After it" is not enough — headings do not break a run."""
        assert_says(self, "not merely after it")

    def test_the_floor_is_not_a_licence_to_pad(self) -> None:
        assert_says(self, "should be shorter, not padded to the floor")

    def test_the_ceiling_still_states_that_headings_do_not_break_a_run(self) -> None:
        assert_says(self, "It does not count headings")


class ArithmeticTests(unittest.TestCase):
    """The failure the prompt change is meant to prevent, measured directly."""

    def _wall(self, sections: int, words_each: int) -> str:
        para = " ".join(["word"] * words_each)
        return "\n\n".join(f"## Section {i}\n\n{para}" for i in range(sections))

    def test_two_floor_sections_in_a_row_already_break_the_ceiling(self) -> None:
        run = longest_prose_run(self._wall(2, 250))
        self.assertGreater(run, MAX_PROSE_RUN_WORDS)

    def test_a_break_inside_each_section_keeps_the_run_legal(self) -> None:
        para = " ".join(["word"] * 250)
        md = "\n\n".join(
            f"## Section {i}\n\n{para}\n\n| a | b |\n| - | - |\n| 1 | 2 |"
            for i in range(4)
        )
        self.assertLessEqual(longest_prose_run(md), MAX_PROSE_RUN_WORDS)


class SelfCheckTests(unittest.TestCase):
    """The sentence rule was present and simply not followed.

    Its only enforcement was the readability loop, which ran after the fact and
    on the failing run did not run at all. The prompt now asks for a count
    rather than a feel.
    """

    def test_the_prompt_asks_the_writer_to_count_before_returning(self) -> None:
        assert_says(self, "Before you return the draft")
        assert_says(self, "Not estimate — count")

    def test_it_shows_why_the_average_cannot_be_trusted(self) -> None:
        assert_says(self, "63-word sentence")
        assert_says(self, "Averages hide their own tails")

    def test_the_prompt_and_the_checker_agree_on_the_number(self) -> None:
        self.assertEqual(MAX_SENTENCE_WORDS, 35)
        assert_says(self, f"No sentence past {MAX_SENTENCE_WORDS} words")
        assert_says(self, f"more than {MAX_PROSE_RUN_WORDS} words unbroken")

    def test_the_checker_still_catches_a_long_sentence_in_healthy_prose(self) -> None:
        """Belt and braces: the self-check is advice, this is the measurement."""
        long_one = " ".join(["word"] * 63) + "."
        short = " ".join(["word"] * 12) + "."
        md = "## H\n\n" + (short + " ") * 20 + long_one
        problems = prose_problems(score_markdown(md))
        self.assertTrue(any("63 words" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
