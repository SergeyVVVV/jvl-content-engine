"""The readability loop rewrote the article instead of revising it.

Measured on one draft: of 109 sentences, 2 survived a pass verbatim. The loop
was not improving prose, it was generating a fresh article each iteration and
keeping whichever scored best — which is why a "correction" could go 22.97 ->
14.29 -> 26.66 words per sentence, and why the article the user approved came
back with a different H1 and a different opening.

Three causes, isolated one at a time on the same draft and the same feedback:

    as it was                                        2%
    without the generated edit plan                 44%
    ...and one fault per pass instead of five       71%
    ...and no brief/outline/SERP attached           87%
    all three, through the real loop path           95%

The largest single one was the instruction agent's own output: a diagnosis, a
list of worst offenders and fourteen numbered "rewrite this span" edits, 525
words of plan covering the whole article. The step meant to make revision
precise was the main reason it was not a revision.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.readability_agent import (  # noqa: E402
    _FAULTS_PER_PASS,
    ReadabilityChecker,
    prose_problem_kinds,
    prose_problems,
    score_markdown,
)
from src.writer_agent import WriterAgent  # noqa: E402

FULL = {
    "diagnosis": {
        "summary": "the prose is heavy",
        "primary_problems": ["long sentences", "abstract nouns"],
        "worst_offenders": [{"section": "S", "excerpt": "e", "why": "w"}] * 6,
    },
    "instructions_for_writer": [
        {"section": "S", "action": "split", "target_excerpt": "…", "guidance": "…"}
    ] * 14,
    "tradeoff_notes": ["keep the brand voice"],
}


def stats(**over) -> dict:
    base = {
        "flesch_reading_ease": 63.0, "avg_sentence_length": 18.0,
        "sentence_length_stdev": 8.0, "short_sentence_share": 0.25,
        "long_sentence_share": 0.13, "longest_sentence_words": 69,
        "avg_syllables_per_word": 1.47, "difficult_word_share": 0.14,
        "longest_prose_run": 424, "list_line_share": 0.29,
        "hardest_words": [{"word": "attributable", "syllables": 5, "occurrences": 2}],
    }
    base.update(over)
    return base


class FeedbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.feedback = ReadabilityChecker.format_writer_feedback(FULL, stats(), 60.0)

    def test_the_generated_edit_plan_is_gone(self) -> None:
        """4% of sentences survived with it, 44% without."""
        self.assertNotIn("Required edits", self.feedback)
        self.assertNotIn("Worst offenders", self.feedback)
        self.assertNotIn("Diagnosis", self.feedback)

    def test_what_not_to_change_survives(self) -> None:
        """tradeoff_notes is the one field that restrains rather than directs."""
        self.assertIn("Leave these alone", self.feedback)
        self.assertIn("keep the brand voice", self.feedback)

    def test_it_carries_only_the_faults_it_should(self) -> None:
        body = self.feedback[self.feedback.index("Fix these") : self.feedback.index("other measurements")]
        self.assertEqual(body.count("\n- "), _FAULTS_PER_PASS)

    def test_the_rest_are_named_as_not_this_pass_s_business(self) -> None:
        self.assertIn("not your problem on this pass", self.feedback)
        self.assertIn("how a revision turns into a rewrite", self.feedback)

    def test_it_is_a_fraction_of_what_it_was(self) -> None:
        self.assertLess(len(self.feedback.split()), 250)


class OrderTests(unittest.TestCase):
    """Severity decides, not the order the checks happen to run in."""

    def test_the_worst_overshoot_comes_first(self) -> None:
        problems = prose_problems(stats())
        self.assertIn("69 words", problems[0])

    def test_hand_ranking_is_gone(self) -> None:
        """It put a 21%-over wall ahead of a sentence 97% past its ceiling."""
        source = (REPO_ROOT / "src" / "readability_agent.py").read_text(encoding="utf-8")
        self.assertNotIn("_PRIORITY", source)

    def test_vocabulary_is_reachable_within_the_budget(self) -> None:
        """Ranked by hand it sat fourth of five, so three passes never got to it."""
        kinds = list(prose_problem_kinds(stats()))
        ordered = [k for k in kinds]
        problems = prose_problems(stats())
        self.assertLess(
            next(i for i, p in enumerate(problems) if "vocabulary is heavier" in p),
            3,
            ordered,
        )

    def test_severity_compares_across_different_measurements(self) -> None:
        """A ratio to each check's own limit is the only comparable number."""
        gentle = stats(longest_sentence_words=40, difficult_word_share=0.20)
        self.assertIn("vocabulary is heavier", prose_problems(gentle)[0])


class ContextTests(unittest.TestCase):
    def test_a_revision_is_not_handed_a_commission_for_a_new_article(self) -> None:
        agent = WriterAgent.__new__(WriterAgent)
        kw = dict(
            topic="T", brief={"required_sections": ["a", "b"]},
            serp_context='{"gaps": 1}', insight_context='{"angle": 2}',
            seo_structure_context='{"outline": 3}', facts_context='{"figure": 4}',
            revision_feedback="- fix the vocabulary",
        )
        revision = WriterAgent._build_user_message(agent, **kw, original_article="# T\n\nBody.")
        for block in ("ARTICLE BRIEF", "SERP RESEARCH", "SEO", "FACT"):
            self.assertNotIn(block, revision, block)

    def test_the_first_draft_still_gets_everything(self) -> None:
        agent = WriterAgent.__new__(WriterAgent)
        first = WriterAgent._build_user_message(
            agent, topic="T", brief={"required_sections": ["a"]},
            serp_context='{"gaps": 1}', insight_context="", seo_structure_context="",
            facts_context="",
        )
        self.assertIn("ARTICLE BRIEF", first)
        self.assertIn("SERP RESEARCH", first)

    def test_the_draft_reaches_the_writer_at_all(self) -> None:
        """The loop used to send the faults and not the article they were in."""
        source = (REPO_ROOT / "src" / "orchestrator.py").read_text(encoding="utf-8")
        self.assertIn("original_article=current_markdown", source)

    def test_the_loop_passes_the_draft_as_it_stands(self) -> None:
        """Not the article the run started from, or each pass reverts the last."""
        source = (REPO_ROOT / "src" / "readability_agent.py").read_text(encoding="utf-8")
        self.assertIn("rewrite_fn(feedback, current_markdown)", source)


class DefaultTests(unittest.TestCase):
    def test_the_shipped_default_is_the_measured_one(self) -> None:
        """Two is the obvious next step and has no number against it yet."""
        self.assertEqual(_FAULTS_PER_PASS, 1)

    def test_it_can_be_raised_without_a_code_change(self) -> None:
        source = (REPO_ROOT / "src" / "readability_agent.py").read_text(encoding="utf-8")
        self.assertIn("READABILITY_FAULTS_PER_PASS", source)


class EvidenceTests(unittest.TestCase):
    def test_the_measured_draft_is_still_here_to_check_against(self) -> None:
        draft = REPO_ROOT / "outputs/t5/drafts"
        if not draft.exists():
            self.skipTest("run output not present")
        self.assertTrue(any(draft.glob("*.raw.json")))


if __name__ == "__main__":
    unittest.main()
