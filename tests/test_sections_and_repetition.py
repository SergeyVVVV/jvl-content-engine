"""Three drafts overshot their target by half without adding a single section.

The first diagnosis was that the Writer invented sections — 10, 13 and 12
against outlines offering 7, 9 and 8. That count was wrong: it included the FAQ,
the sources block and the editorial appendices, none of which the Writer chose.
Counting only the body, the drafts held to 6, 9 and 8. They kept their outlines.

What they did was write 723, 421 and 522 words per section, because PR #73
rewrote the section-length rule as "at least 250 words of prose" and dropped the
"aiming at 250-350" that had bounded it. A floor with no ceiling only ever
pushes one way.

Separately and independently: two sections of one draft argued the same point to
the same conclusion, their headings ending in the same nine words. The
anti-repetition rule in the prompt covers four product claims and nothing about
the article's own arguments.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src import length_target as lt  # noqa: E402

PROMPT = re.sub(
    r"\s+", " ", (REPO_ROOT / "prompts" / "writer_agent.md").read_text(encoding="utf-8")
)
TARGET = lt.resolve({"median_words": 2424, "sample_size": 2, "positions": [6, 8]})


RATIONALE = re.sub(
    r"\s+", " ",
    (REPO_ROOT / "prompts" / "writer_agent.rationale.md").read_text(encoding="utf-8"),
)


def kept_in_rationale(case: unittest.TestCase, phrase: str) -> None:
    """Evidence lives in the rationale file; the prompt keeps the rule.

    A rule whose reason has been forgotten is a rule the next refactor
    deletes — that is how the section ceiling and the Flesch target were
    lost. The reason has to survive somewhere; it does not have to spend
    the Writer's attention.
    """
    case.assertTrue(phrase in RATIONALE, f"rationale does not record: {phrase!r}")


def says(case: unittest.TestCase, phrase: str) -> None:
    case.assertTrue(phrase in PROMPT, f"prompt does not say: {phrase!r}")


class SectionBudgetTests(unittest.TestCase):
    def test_the_allowance_is_computed_not_left_as_a_division(self) -> None:
        """"Divide the target by roughly 350" asks for arithmetic it will not do."""
        self.assertEqual(TARGET["sections"], 7)
        self.assertNotIn("Divide the word target you were given", PROMPT)

    def test_it_scales_with_the_target(self) -> None:
        small = lt.resolve({"median_words": 1400, "sample_size": 1})
        large = lt.resolve({"median_words": 3500, "sample_size": 3})
        self.assertLess(small["sections"], TARGET["sections"])
        self.assertGreater(large["sections"], TARGET["sections"])

    def test_it_never_collapses_to_nothing(self) -> None:
        self.assertGreaterEqual(lt.resolve({"median_words": 300})["sections"], 3)

    def test_the_block_states_it_as_a_cap(self) -> None:
        text = lt.render(TARGET)
        self.assertIn("affords 7 H2 sections", text)
        self.assertIn("cap, not a suggestion", text)

    def test_requested_sections_come_out_of_the_allowance(self) -> None:
        """The gap that made a requirement read as an extra section."""
        text = lt.render(TARGET)
        self.assertIn("never on top of it", text)
        says(self, "is not an extra section")


class SectionCountTests(unittest.TestCase):
    def test_appended_blocks_are_not_sections_the_writer_chose(self) -> None:
        body = "## One\n\ntext\n\n## Two\n\ntext\n"
        tail = "## FAQ\n\n### q\n\n## Sources\n\n- a\n"
        self.assertEqual(lt.count_sections(body + tail), 2)

    def test_editorial_appendices_do_not_count_either(self) -> None:
        md = "## One\n\nt\n\n## Claims to Verify Before Publishing\n\nt\n\n## Open TODOs for Human Review\n\nt\n"
        self.assertEqual(lt.count_sections(md), 1)

    def test_h3_does_not_earn_its_own_slot(self) -> None:
        md = "## One\n\nt\n\n### Sub\n\nt\n\n### Sub two\n\nt\n"
        self.assertEqual(lt.count_sections(md), 1)

    def test_the_measured_drafts_kept_to_their_outlines(self) -> None:
        """The correction: they did not add sections. 6, 9, 8 against 7, 9, 8."""
        expected = {"t1": 6, "t2": 9, "t3": 8}
        for name, count in expected.items():
            path = (
                REPO_ROOT / f"outputs/{name}/drafts"
                / "how-fast-can-an-arcade-machine-pay-for-itself-in-a-bar-or-ev.md"
            )
            if not path.exists():
                self.skipTest("run output not present")
            self.assertEqual(
                lt.count_sections(path.read_text(encoding="utf-8")), count, name
            )

    def test_an_over_budget_draft_is_told_to_merge_not_to_shorten(self) -> None:
        md = "".join(f"## Section {i}\n\nbody\n\n" for i in range(12))
        problem = lt.section_problem(TARGET, md)
        self.assertIn("12 H2 sections against the 7", problem)
        self.assertIn("Merge 5", problem)
        self.assertIn("rather than shortening", problem)

    def test_a_draft_inside_its_allowance_is_left_alone(self) -> None:
        md = "".join(f"## Section {i}\n\nbody\n\n" for i in range(7))
        self.assertIsNone(lt.section_problem(TARGET, md))


class SectionCeilingTests(unittest.TestCase):
    """The rule that was dropped, and the reason it existed."""

    def test_the_section_length_rule_has_both_ends_again(self) -> None:
        says(self, "250 to 350 words of prose, and both ends are real")

    def test_the_floor_alone_is_named_as_the_cause(self) -> None:
        """The prompt keeps the reason in one clause; the file keeps the evidence."""
        says(self, "A floor alone only ever pushes one way")
        kept_in_rationale(self, "A floor alone only ever pushes one way")

    def test_the_evidence_is_the_per_section_word_count(self) -> None:
        kept_in_rationale(self, "723, 421 and 522 words")

    def test_the_prompt_no_longer_claims_sections_were_added(self) -> None:
        """The first diagnosis was wrong and must not survive as folklore."""
        self.assertNotIn("ran 10, 13 and 12", PROMPT)


class RepetitionTests(unittest.TestCase):
    def test_the_rule_reaches_past_the_four_product_claims(self) -> None:
        says(self, "that is not where the damage is")

    def test_every_claim_has_one_home(self) -> None:
        says(self, "Every claim the article makes has one home")
        says(self, "never a second argument for the same conclusion")

    def test_the_writer_is_told_what_to_ask_before_a_section(self) -> None:
        says(self, "what it settles that no earlier section settled")

    def test_the_seam_between_outline_and_requirements_is_named(self) -> None:
        """The measured duplicate was one section from each, saying one thing."""
        says(self, "the same section wearing two names")
        says(self, "they ask for it to be said")

    def test_the_measured_duplicate_is_kept_as_evidence(self) -> None:
        kept_in_rationale(self, "the step every ranking guide skips")


class LoopTests(unittest.TestCase):
    def test_the_section_count_is_checked_every_iteration(self) -> None:
        source = (REPO_ROOT / "src" / "readability_agent.py").read_text(encoding="utf-8")
        self.assertIn("length_target.section_problem(", source)

    def test_it_is_a_separate_problem_from_the_word_count(self) -> None:
        """Opposite fixes: one asks to merge, the other to cut. Do not conflate."""
        source = (REPO_ROOT / "src" / "readability_agent.py").read_text(encoding="utf-8")
        self.assertIn('stats["section_check"] = section_note', source)

    def test_the_feedback_the_writer_reads_carries_it(self) -> None:
        source = (REPO_ROOT / "src" / "readability_agent.py").read_text(encoding="utf-8")
        formatter = source[source.index("def format_writer_feedback") :]
        self.assertIn('stats.get("section_check")', formatter)


if __name__ == "__main__":
    unittest.main()
