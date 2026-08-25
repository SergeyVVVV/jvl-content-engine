"""Genre rules belong to the genres that have them.

`article_type` has been in the brief schema since April and read by nothing.
Every article got one set of instructions, so the rules for building a payback
model were also handed to gift guides — along with an aside addressed to "a bar
owner" that every article was reading, whoever it was written for.

The rules themselves were not wrong. They were in the wrong place, and the
Writer prompt grew from 137 lines in April to 450 partly because each fix for
one article was written into the prompt every article reads.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.writer_agent import WriterAgent  # noqa: E402


def read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


class SelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.writer = WriterAgent()

    def test_an_analysis_gets_the_analytical_profile(self) -> None:
        self.assertEqual(
            self.writer._profile_for("commercial_investigation", False), "analytical"
        )

    def test_a_gift_guide_gets_none(self) -> None:
        # It has no scenarios to build and no sources to attribute.
        self.assertIsNone(self.writer._profile_for("lifestyle_inspiration", False))
        self.assertIsNone(self.writer._profile_for("buyer_guide", False))

    def test_researched_facts_pull_the_profile_in_regardless_of_genre(self) -> None:
        # Two triggers answering different questions: the type says what genre
        # this is, facts say there are figures that need attributing.
        self.assertEqual(self.writer._profile_for("buyer_guide", True), "analytical")

    def test_an_unknown_or_missing_type_is_not_a_crash(self) -> None:
        self.assertIsNone(self.writer._profile_for(None, False))
        self.assertIsNone(self.writer._profile_for("something_new", False))

    def test_the_types_are_ones_the_brief_actually_emits(self) -> None:
        emitted = read("prompts/brief_agent.md")
        for article_type in self.writer._PROFILES:
            self.assertIn(article_type, emitted, article_type)


class SharedPromptTests(unittest.TestCase):
    """Nothing in the shared prompt may be about one article."""

    def setUp(self) -> None:
        self.prompt = read("prompts/writer_agent.md")

    def test_no_scenario_rules_for_articles_without_scenarios(self) -> None:
        self.assertNotIn("pessimistic", self.prompt.lower())

    def test_no_reader_from_one_topic(self) -> None:
        # "You are writing for a bar owner, not a committee" was being read by
        # every article, including guides for people buying one for a basement.
        self.assertNotIn("bar owner", self.prompt.lower())

    def test_no_figures_from_one_topic(self) -> None:
        for fragment in ("$200-485", "$200–485", "coin drop"):
            self.assertNotIn(fragment, self.prompt, fragment)

    def test_the_craft_rules_stayed(self) -> None:
        # Sentence length, walls, structure and voice apply to everything.
        for rule in ("35 words", "350 words", "Vary sentence length"):
            self.assertIn(rule, self.prompt, rule)


class ProfileContentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = read("prompts/profiles/analytical.md")

    def test_scenarios_are_derived_from_the_base_case(self) -> None:
        # The bug this profile was written to fix: the low/typical/high fields
        # of a research range were mapped straight onto three scenario rows,
        # producing a two-months-to-two-years spread.
        self.assertIn("Build the base case first", self.profile)
        self.assertIn("never from the ends of the sample", self.profile)

    def test_it_explains_why_the_endpoints_are_wrong(self) -> None:
        self.assertIn("spread between **different businesses**", self.profile)

    def test_the_endpoints_still_appear_in_the_article(self) -> None:
        # Discarded from the scenarios, kept in the methodology.
        self.assertIn("methodology", self.profile)

    def test_the_attribution_rules_came_with_it(self) -> None:
        self.assertIn("Do not put external links in the body", self.profile)
        self.assertIn("At most three named sources", self.profile)

    def test_it_says_why_it_is_not_in_the_main_prompt(self) -> None:
        self.assertIn("a gift guide has", self.profile)


class AssemblyTests(unittest.TestCase):
    def test_the_profile_is_appended_when_it_applies(self) -> None:
        writer = WriterAgent()
        without = writer._build_system_prompt("buyer_guide", False)
        with_profile = writer._build_system_prompt("commercial_investigation", False)
        self.assertGreater(len(with_profile), len(without))
        self.assertIn("Build the base case first", with_profile)
        self.assertNotIn("Build the base case first", without)

    def test_a_missing_profile_file_does_not_stop_the_run(self) -> None:
        writer = WriterAgent()
        writer._PROFILES = {"commercial_investigation": "nonexistent"}
        self.assertIn("Role", writer._build_system_prompt("commercial_investigation"))


if __name__ == "__main__":
    unittest.main()
