"""A third style, built from a measurement rather than from the other two.

Ten articles on a site that ranks well for questions of this kind, measured the
same way we measure our own. The sample spans conditions, drugs and
how-to-get-prescribed pages, so the numbers are a house style rather than one
article's shape:

    words per heading      107-129   (ours: 338)
    paragraph, mean          33-51   (ours: 52-58)
    paragraph, 90th          59-84
    paragraph, longest      94-129   (ours: 90-116)
    sentences per paragraph 1.5-2.6

Everything is the 25th-75th percentile of the ten, loosened by 15% because our
subjects argue where theirs enumerate, and expressed as a band. A single figure
would be false precision: no two of the ten agree to within 15% on anything.

STYLE_3 replaces the shared prompt rather than adjusting it. The shared prompt is
3,700 words written for long developed sections; reaching a different shape by
editing it would have produced neither shape cleanly.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.editorial_style import STYLE_1, STYLE_2, STYLE_3, active  # noqa: E402

PROMPT = (REPO_ROOT / "prompts" / "writer_agent_style3.md").read_text(encoding="utf-8")
FLAT = re.sub(r"\s+", " ", PROMPT)

#: The sample the numbers came from, so a later edit can be checked against it.
SAMPLE_WORDS_PER_HEADING = (107, 129)
SAMPLE_PARAGRAPH_MAX = (94, 129)


class MeasurementTests(unittest.TestCase):
    def test_the_paragraph_ceiling_sits_above_the_sample(self) -> None:
        """+15% on the sample's upper quartile, not on its single worst case."""
        self.assertGreater(STYLE_3.max_paragraph_words, SAMPLE_PARAGRAPH_MAX[1])
        self.assertLess(STYLE_3.max_paragraph_words, 160)

    def test_sections_are_shorter_than_either_earlier_style(self) -> None:
        self.assertLess(STYLE_3.section_prose_max, STYLE_1.section_prose_max)
        self.assertLess(STYLE_3.section_prose_max, STYLE_2.section_prose_max)

    def test_the_section_budget_follows_the_section_length(self) -> None:
        """A cheaper section means more of them fit the same word target."""
        self.assertLess(STYLE_3.words_per_section, STYLE_2.words_per_section)
        self.assertLessEqual(STYLE_3.words_per_section, STYLE_3.section_prose_max)

    def test_it_affords_more_sections_than_the_others(self) -> None:
        import importlib
        from src import length_target

        counts = {}
        for name in ("Editorial_Style_1", "Editorial_Style_2", "Editorial_Style_3"):
            os.environ["EDITORIAL_STYLE"] = name
            importlib.reload(length_target)
            counts[name] = length_target.resolve({"median_words": 2423})["sections"]
        os.environ.pop("EDITORIAL_STYLE", None)
        importlib.reload(length_target)
        self.assertGreater(counts["Editorial_Style_3"], counts["Editorial_Style_2"])
        self.assertGreater(counts["Editorial_Style_2"], counts["Editorial_Style_1"])


class BandTests(unittest.TestCase):
    """Ranges, not points. No two of the ten agree to within 15% on anything."""

    def test_the_prompt_states_ranges_for_every_shape_rule(self) -> None:
        for band in ("120–150 words", "150–280 words", "2–4 sentences",
                     "30–60 words typical"):
            self.assertIn(band, PROMPT, band)

    def test_the_only_hard_number_is_a_ceiling(self) -> None:
        """A ceiling is permissive; a target would compel."""
        self.assertIn("never past 140", FLAT)
        self.assertIn("That is a ceiling and not a target", FLAT)

    def test_it_says_where_the_numbers_came_from(self) -> None:
        self.assertIn("Measured across ten articles", FLAT)
        self.assertIn("then loosened for a subject that argues", FLAT)

    def test_it_does_not_read_as_write_less(self) -> None:
        """The sample runs 2,300-4,000 words. The change is breaks, not length."""
        self.assertIn("Nothing about it says write less", FLAT)
        self.assertIn("It says break more", FLAT)


class PromptTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("EDITORIAL_STYLE", None)

    def test_it_is_a_replacement_not_an_overlay(self) -> None:
        self.assertEqual(STYLE_3.prompt_file, "prompts/writer_agent_style3.md")
        self.assertIsNone(STYLE_1.prompt_file)
        self.assertIsNone(STYLE_2.prompt_file)

    def test_the_writer_loads_it(self) -> None:
        from src.writer_agent import WriterAgent

        os.environ["EDITORIAL_STYLE"] = "Editorial_Style_3"
        agent = WriterAgent.__new__(WriterAgent)
        agent.repo_root = REPO_ROOT
        built = WriterAgent._build_system_prompt(agent, article_type=None, has_facts=False)
        self.assertIn("A heading every", built)
        self.assertNotIn("Write as an author, not as a reference sheet", built)

    def test_it_is_shorter_than_the_prompt_it_replaces(self) -> None:
        shared = (REPO_ROOT / "prompts" / "writer_agent.md").read_text(encoding="utf-8")
        self.assertLess(len(PROMPT.split()), len(shared.split()) / 2)

    def test_the_h3_cap_is_lifted_without_a_quota_replacing_it(self) -> None:
        """The shared prompt forbids H3s outnumbering H2s, and that ban is what
        held earlier drafts to one or two sub-headings.

        The first draft of this file replaced the ban with its mirror — "H3s
        outnumber H2s, and that is correct" — on a sample where that held in
        seven of ten. A majority is not a rule, and a rule in the opposite
        direction is the same mistake twice.
        """
        self.assertIn("There is no cap on how many", FLAT)
        self.assertIn("in two there were fewer", FLAT)
        self.assertIn("not to hit a ratio", FLAT)
        self.assertNotIn("and that is correct", FLAT)

    def test_headings_are_written_to_be_searched_for(self) -> None:
        self.assertIn("someone might actually search for", FLAT)


class CarriedOverTests(unittest.TestCase):
    """A style changes rhythm. It does not change what may be said."""

    def test_the_claim_rules_survive(self) -> None:
        for rule in ("Never invent", "warranty terms", "TODO: source not confirmed"):
            self.assertIn(rule, PROMPT, rule)

    def test_the_product_caps_survive(self) -> None:
        self.assertIn("product_fit", PROMPT)
        self.assertIn("fifteen mentions", FLAT)
        self.assertIn("An H3 shares its parent H2's allowance", FLAT)

    def test_the_sentence_rules_survive(self) -> None:
        self.assertIn("No sentence past 35 words", PROMPT)
        self.assertIn("fewer than one in ten past 30", PROMPT)

    def test_the_length_target_is_still_the_authority(self) -> None:
        self.assertIn("# LENGTH TARGET", PROMPT)
        self.assertIn("spends from it rather than adding", FLAT)

    def test_the_faq_still_belongs_to_another_agent(self) -> None:
        self.assertIn("Do not write an FAQ section yourself", FLAT)

    def test_the_output_contract_is_unchanged(self) -> None:
        for field in ("h1", "intro", "sections", "suggested_visuals",
                      "claims_to_verify", "length_justification", "todos"):
            self.assertIn(f'"{field}"', PROMPT, field)


class DefaultTests(unittest.TestCase):
    def test_style_one_is_still_the_default(self) -> None:
        os.environ.pop("EDITORIAL_STYLE", None)
        self.assertIs(active(), STYLE_1)


if __name__ == "__main__":
    unittest.main()
