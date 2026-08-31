"""Two styles, one switch, and a default that changes nothing.

The request that produced this was "не хочу чтобы мы опять все поломали" — keep
what works, put the new idea beside it, make the switch a small commit. So
STYLE_1 is the engine exactly as it shipped and is the default, and the tests
below exist mostly to prove that selecting it changes nothing at all.

STYLE_2 is the shorter-block style. Everything in it is a ceiling: paragraphs
get one, sections get a lower one so more of them fit inside the same word
target. Nothing in it is a floor, deliberately — a rule that compels a heading
produces headings whether or not the material wanted one, and today's session
found two rules that pushed one way because only one end was bounded.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.editorial_style import ACTIVE, STYLE_1, STYLE_2, active  # noqa: E402
from src.readability_agent import longest_paragraph, prose_problems  # noqa: E402


def stats(**over) -> dict:
    base = {
        "flesch_reading_ease": 67.0, "avg_sentence_length": 18.0,
        "sentence_length_stdev": 8.0, "short_sentence_share": 0.25,
        "long_sentence_share": 0.05, "longest_sentence_words": 20,
        "avg_syllables_per_word": 1.40, "difficult_word_share": 0.09,
        "longest_prose_run": 200, "list_line_share": 0.10,
        "longest_paragraph": 90, "hardest_words": [],
    }
    base.update(over)
    return base


class DefaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = os.environ.pop("EDITORIAL_STYLE", None)

    def tearDown(self) -> None:
        os.environ.pop("EDITORIAL_STYLE", None)
        if self._saved is not None:
            os.environ["EDITORIAL_STYLE"] = self._saved

    def test_the_default_is_what_shipped(self) -> None:
        self.assertIs(ACTIVE, STYLE_1)
        self.assertIs(active(), STYLE_1)

    def test_style_one_holds_the_values_the_engine_had(self) -> None:
        """Copied across unchanged; selecting it must be a no-op."""
        self.assertIsNone(STYLE_1.max_paragraph_words)
        self.assertEqual(STYLE_1.section_prose_min, 250)
        self.assertEqual(STYLE_1.section_prose_max, 350)
        self.assertEqual(STYLE_1.words_per_section, 350)

    def test_style_one_adds_no_new_problem(self) -> None:
        self.assertEqual(prose_problems(stats(longest_paragraph=153)), [])


class SwitchTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("EDITORIAL_STYLE", None)

    def test_the_environment_selects_a_style(self) -> None:
        os.environ["EDITORIAL_STYLE"] = "Editorial_Style_2"
        self.assertIs(active(), STYLE_2)

    def test_an_unknown_name_falls_back_rather_than_failing(self) -> None:
        """A typo in a variable must not take down an eleven-step pipeline."""
        os.environ["EDITORIAL_STYLE"] = "Editorial_Style_9"
        self.assertIs(active(), ACTIVE)

    def test_the_switch_is_one_line(self) -> None:
        source = (REPO_ROOT / "src" / "editorial_style.py").read_text(encoding="utf-8")
        self.assertIn("ACTIVE = STYLE_1", source)
        self.assertEqual(len(re.findall(r"^ACTIVE = ", source, re.M)), 1)


class ParagraphCeilingTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("EDITORIAL_STYLE", None)

    def test_it_is_measured_separately_from_the_prose_run(self) -> None:
        """A page can break often and still hand over a 153-word block."""
        md = "## H\n\n" + " ".join(["word"] * 150) + "\n\n| a | b |\n| - | - |\n"
        self.assertEqual(longest_paragraph(md), 150)

    def test_tables_lists_quotes_and_headings_are_not_paragraphs(self) -> None:
        md = ("## A heading that is quite long but is still a heading\n\n"
              "| " + " | ".join(["cell"] * 40) + " |\n\n"
              "- " + " ".join(["item"] * 40) + "\n\n"
              "> " + " ".join(["quoted"] * 40) + "\n\n"
              "Short real paragraph here.\n")
        self.assertEqual(longest_paragraph(md), 4)

    def test_style_two_flags_the_long_paragraph(self) -> None:
        os.environ["EDITORIAL_STYLE"] = "Editorial_Style_2"
        problems = prose_problems(stats(longest_paragraph=153))
        self.assertTrue(any("153 words against a 110-word" in p for p in problems))

    def test_it_asks_for_a_break_not_a_rewrite(self) -> None:
        os.environ["EDITORIAL_STYLE"] = "Editorial_Style_2"
        problem = next(p for p in prose_problems(stats(longest_paragraph=153))
                       if "paragraph runs" in p)
        self.assertIn("the fix is a paragraph break, not a rewrite", problem)

    def test_a_paragraph_inside_the_ceiling_passes(self) -> None:
        os.environ["EDITORIAL_STYLE"] = "Editorial_Style_2"
        self.assertEqual(prose_problems(stats(longest_paragraph=100)), [])

    def test_the_tolerance_applies_here_too(self) -> None:
        """Every other check gets 10%; a new one must not be the exception."""
        os.environ["EDITORIAL_STYLE"] = "Editorial_Style_2"
        self.assertEqual(prose_problems(stats(longest_paragraph=118)), [])


class SectionBudgetTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("EDITORIAL_STYLE", None)

    def _sections(self, median: int = 2424) -> int:
        import importlib
        from src import length_target

        importlib.reload(length_target)
        return length_target.resolve({"median_words": median})["sections"]

    def test_style_two_affords_more_sections_for_the_same_target(self) -> None:
        """More headings without ever requiring one — shorter sections, not a floor."""
        one = self._sections()
        os.environ["EDITORIAL_STYLE"] = "Editorial_Style_2"
        self.assertGreater(self._sections(), one)


class NoFloorTests(unittest.TestCase):
    """Style 2 must not compel structure anywhere."""

    def test_nothing_in_style_two_is_a_minimum_count(self) -> None:
        self.assertGreater(STYLE_2.section_prose_min, 0)  # a floor on length, not count
        source = (REPO_ROOT / "src" / "editorial_style.py").read_text(encoding="utf-8")
        self.assertIn("Nothing in it is a\nfloor", source)

    def test_the_heading_hint_is_guidance_not_a_check(self) -> None:
        source = (REPO_ROOT / "src" / "readability_agent.py").read_text(encoding="utf-8")
        self.assertNotIn("heading_hint", source)
        self.assertIn("around ten is the comfortable number", STYLE_2.heading_hint)


class PromptTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("EDITORIAL_STYLE", None)

    def _prompt(self) -> str:
        from src.writer_agent import WriterAgent

        agent = WriterAgent.__new__(WriterAgent)
        agent.repo_root = REPO_ROOT
        return WriterAgent._build_system_prompt(agent, article_type=None, has_facts=False)

    def test_every_placeholder_is_filled(self) -> None:
        """An unreplaced {SECTION_MAX} would ship to the model as literal text."""
        for style in ("Editorial_Style_1", "Editorial_Style_2"):
            os.environ["EDITORIAL_STYLE"] = style
            self.assertEqual(re.findall(r"\{[A-Z_]+\}", self._prompt()), [], style)

    def test_style_one_prints_the_numbers_it_always_had(self) -> None:
        os.environ["EDITORIAL_STYLE"] = "Editorial_Style_1"
        prompt = self._prompt()
        self.assertIn("250 to 350 words of prose", prompt)
        self.assertIn("three to six sentences", prompt)
        self.assertNotIn("No paragraph past", prompt)

    def test_style_two_prints_its_own(self) -> None:
        os.environ["EDITORIAL_STYLE"] = "Editorial_Style_2"
        prompt = self._prompt()
        self.assertIn("200 to 300 words of prose", prompt)
        self.assertIn("two to five sentences", prompt)
        self.assertIn("No paragraph past 110 words", prompt)


if __name__ == "__main__":
    unittest.main()
