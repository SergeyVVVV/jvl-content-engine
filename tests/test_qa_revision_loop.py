"""QA has to reach the Writer, and it has to judge against the real rules.

Two failures this file guards, both found on a live run:

* A report said `status: fail` and nothing happened. The Writer never saw it —
  the report was saved, shown, and dropped — so an arithmetic error and a raw
  TODO string shipped in the finished article.
* Two findings marked `high` were wrong. QA was judging the draft against the
  ten-item extract Company Insight passes downstream and called the 22-inch
  display and the box contents inventions, when both are confirmed claims in
  claims_constraints.md. The same blind spot meant it could not have caught a
  trademarked game title or a forbidden comparison either.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.orchestrator import qa_max_revisions, revision_damage  # noqa: E402
from src.qa_agent import QAAgent  # noqa: E402


def issue(severity="medium", location="Payback section", problem="p", fix="f") -> dict:
    return {
        "severity": severity,
        "category": "factual",
        "location": location,
        "problem": problem,
        "recommended_fix": fix,
    }


class OwnershipTests(unittest.TestCase):
    """The Writer owns the article body. Nothing else."""

    def test_a_body_section_is_the_writers(self) -> None:
        self.assertTrue(QAAgent.writer_can_fix(issue(location="Net Monthly Profit section")))

    def test_an_faq_answer_is_not(self) -> None:
        self.assertFalse(QAAgent.writer_can_fix(issue(location="FAQ — used machines answer")))

    def test_an_image_caption_is_not(self) -> None:
        self.assertFalse(QAAgent.writer_can_fix(issue(location="Hero image caption")))
        self.assertFalse(QAAgent.writer_can_fix(issue(location="inline-01 alt text")))

    def test_wrapper_metadata_is_not(self) -> None:
        self.assertFalse(QAAgent.writer_can_fix(issue(location="Wrapper metadata todos")))

    def test_a_missing_location_defaults_to_the_writer(self) -> None:
        # Better to hand over an edit the Writer cannot make than to drop a
        # finding because the reviewer left the field vague.
        self.assertTrue(QAAgent.writer_can_fix({"severity": "high", "problem": "x"}))


class FormatForWriterTests(unittest.TestCase):
    def test_nothing_actionable_returns_empty(self) -> None:
        report = {"issues": [issue(location="FAQ answer 2"), issue(location="Hero image")]}
        self.assertEqual(QAAgent.format_for_writer(report), "")

    def test_no_issues_at_all_returns_empty(self) -> None:
        self.assertEqual(QAAgent.format_for_writer({"issues": []}), "")

    def test_the_problem_and_the_fix_both_reach_the_writer(self) -> None:
        report = {"issues": [issue(problem="52 weeks vs 46", fix="Recompute at 46")]}
        out = QAAgent.format_for_writer(report)
        self.assertIn("52 weeks vs 46", out)
        self.assertIn("Recompute at 46", out)

    def test_high_severity_is_listed_first(self) -> None:
        report = {"issues": [
            issue(severity="low", problem="LOW ITEM"),
            issue(severity="high", problem="HIGH ITEM"),
        ]}
        out = QAAgent.format_for_writer(report)
        self.assertLess(out.index("HIGH ITEM"), out.index("LOW ITEM"))

    def test_out_of_scope_issues_are_named_but_not_assigned(self) -> None:
        report = {"issues": [
            issue(problem="BODY ITEM"),
            issue(location="FAQ — second answer", problem="FAQ ITEM"),
        ]}
        out = QAAgent.format_for_writer(report)
        self.assertIn("Not yours to fix", out)
        self.assertIn("FAQ — second answer", out)
        # The FAQ problem text must not appear as a required edit.
        self.assertNotIn("FAQ ITEM", out)

    def test_it_asks_for_a_revision_not_a_rewrite(self) -> None:
        out = QAAgent.format_for_writer({"issues": [issue()]})
        self.assertIn("correcting an existing article", out)
        self.assertIn("FULL article", out)

    def test_the_two_recurring_defects_are_named_every_time(self) -> None:
        out = QAAgent.format_for_writer({"issues": [issue()]})
        self.assertIn("Recompute", out)   # arithmetic that contradicts its inputs
        self.assertIn("TODO:", out)       # editorial notes leaking into prose


class RevisionBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = os.environ.pop("QA_MAX_REVISIONS", None)

    def tearDown(self) -> None:
        if self._saved is None:
            os.environ.pop("QA_MAX_REVISIONS", None)
        else:
            os.environ["QA_MAX_REVISIONS"] = self._saved

    def test_one_pass_by_default(self) -> None:
        self.assertEqual(qa_max_revisions(), 1)

    def test_zero_restores_the_old_report_only_behaviour(self) -> None:
        os.environ["QA_MAX_REVISIONS"] = "0"
        self.assertEqual(qa_max_revisions(), 0)

    def test_nonsense_falls_back_instead_of_crashing_a_nine_step_run(self) -> None:
        os.environ["QA_MAX_REVISIONS"] = "as many as it takes"
        self.assertEqual(qa_max_revisions(), 1)
        os.environ["QA_MAX_REVISIONS"] = "-3"
        self.assertEqual(qa_max_revisions(), 1)


ARTICLE = (
    "# Payback\n\n"
    "![hero](https://cdn.example/hero-01.png)\n\n"
    + ("The machine costs $4,250 and the split is even. " * 60)
    + "\n\n![chart](https://cdn.example/inline-02.png)\n\n"
    + ("Recurring costs are power and repairs. " * 60)
    + "\n\n## FAQ\n\n### Is it worth it?\n\nThat depends on the room.\n"
)


class RevisionDamageTests(unittest.TestCase):
    """A revision must prove it kept what it was handed.

    The Writer receives the finished article — images injected, FAQ appended —
    and is asked to change only what QA named. It can return clean prose that
    quietly lost the pictures, and a silent loss is worse than the defect.
    """

    def test_an_untouched_article_is_accepted(self) -> None:
        self.assertIsNone(revision_damage(ARTICLE, ARTICLE))

    def test_a_real_edit_is_accepted(self) -> None:
        edited = ARTICLE.replace("$4,250", "$4,250 USD")
        self.assertIsNone(revision_damage(ARTICLE, edited))

    def test_a_dropped_image_is_rejected(self) -> None:
        lost = ARTICLE.replace("![chart](https://cdn.example/inline-02.png)", "")
        self.assertIn("image", revision_damage(ARTICLE, lost) or "")

    def test_a_dropped_faq_is_rejected(self) -> None:
        lost = ARTICLE.replace("## FAQ", "## Closing")
        self.assertIn("FAQ", revision_damage(ARTICLE, lost) or "")

    def test_a_truncated_article_is_rejected(self) -> None:
        self.assertIsNotNone(revision_damage(ARTICLE, ARTICLE[:200]))

    def test_an_empty_revision_is_rejected(self) -> None:
        self.assertIsNotNone(revision_damage(ARTICLE, "   "))

    def test_an_article_that_never_had_an_faq_is_not_faulted_for_lacking_one(self) -> None:
        plain = "# T\n\n" + ("body text " * 200)
        self.assertIsNone(revision_damage(plain, plain + "\n\nOne more sentence."))


class QAKnowledgeTests(unittest.TestCase):
    """QA must judge against claims_constraints.md, not a downstream extract."""

    def setUp(self) -> None:
        self.prompt = QAAgent()._build_system_prompt()

    def test_the_allowed_claims_reach_qa(self) -> None:
        # The two findings it got wrong on the live run.
        self.assertIn("22 inches", self.prompt)
        self.assertIn("What's in the box", self.prompt)

    def test_the_forbidden_claims_reach_qa(self) -> None:
        self.assertIn("Forbidden", self.prompt)
        self.assertIn("B2C / B2B separation", self.prompt)

    def test_the_trademark_rule_reaches_qa(self) -> None:
        # It could not have caught a trademarked game title before.
        self.assertIn("Pac-Man", self.prompt)

    def test_the_schema_still_reaches_qa(self) -> None:
        self.assertIn("QA REPORT JSON SCHEMA", self.prompt)
        self.assertIn("severity", self.prompt)


if __name__ == "__main__":
    unittest.main()


class FAQSurvivalTests(unittest.TestCase):
    """A QA revision must not cost the article its FAQ.

    Observed on a live run: QA returned `fail`, the loop asked the Writer to
    fix it, the Writer came back without the FAQ block, `revision_damage`
    rejected the whole revision, and every fix was lost with it. The Writer
    behaves that way by instruction — its own system prompt says a separate
    agent owns the FAQ and to leave a placeholder — so hoping is not a
    strategy. The block is re-attached deterministically instead.
    """

    FAQ = "## FAQ\n\n### Is it worth it?\n\nThat depends on the room.\n"

    def test_a_revision_without_an_faq_gets_one_back(self) -> None:
        from src.faq_agent import FAQAgent

        revised = "# T\n\n" + ("Body prose that survived the revision. " * 40)
        restored = FAQAgent.append_to_article(revised, self.FAQ)
        self.assertIn("## FAQ", restored)
        self.assertIn("That depends on the room.", restored)

    def test_restoring_does_not_duplicate_an_faq_the_writer_kept(self) -> None:
        from src.faq_agent import FAQAgent

        revised = "# T\n\n" + ("Body prose. " * 40) + "\n\n" + self.FAQ
        restored = FAQAgent.append_to_article(revised, self.FAQ)
        self.assertEqual(restored.count("## FAQ"), 1)

    def test_a_restored_revision_passes_the_damage_check(self) -> None:
        from src.faq_agent import FAQAgent

        before = "# T\n\n" + ("Original prose here. " * 60) + "\n\n" + self.FAQ
        revised = "# T\n\n" + ("Corrected prose here. " * 60)
        self.assertIsNotNone(revision_damage(before, revised))  # without the FAQ
        restored = FAQAgent.append_to_article(revised, self.FAQ)
        self.assertIsNone(revision_damage(before, restored))    # with it
