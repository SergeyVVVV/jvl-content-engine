"""What the readability loop earns has to survive the step after it.

A measured run ended its loop at three problems, none of them a wall, having
spent an iteration getting the Writer to say why the article ran long:

    Iteration 3: reading ease 67.3 — 3 out of range
    Length: 3619 words, past the band and justified — accepted.

The file on disk held 3,312 words, a 502-word wall, and no justification at all.
Between those two states sits one QA revision, and it took away both.

Two holes, both here:

  * the gate compared problem *counts*, so trading a fixable sentence for a wall
    passed at three against three;
  * the revision returns a fresh Writer result, and nothing carried the earned
    justification onto it.

And one consequence: the length verdict was the loop's parting word, so the run
reported a figure for a draft nobody would read.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.readability_agent import (  # noqa: E402
    prose_problem_kinds,
    prose_problems,
    score_markdown,
)

SOURCE = (REPO_ROOT / "src" / "orchestrator.py").read_text(encoding="utf-8")


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


class KindTests(unittest.TestCase):
    def test_a_clean_draft_has_no_kinds(self) -> None:
        self.assertEqual(prose_problem_kinds(stats()), set())

    def test_each_defect_has_its_own_name(self) -> None:
        self.assertEqual(
            prose_problem_kinds(stats(longest_prose_run=900)), {"prose_wall"}
        )
        self.assertEqual(
            prose_problem_kinds(stats(longest_sentence_words=63)), {"sentence_tail"}
        )

    def test_the_same_count_can_be_a_different_article(self) -> None:
        """The exact confusion the old gate fell into."""
        before = stats(longest_sentence_words=63, long_share=0.16, difficult_word_share=0.16)
        after = stats(longest_sentence_words=63, long_share=0.16, longest_prose_run=502)
        self.assertEqual(len(prose_problems(before)), len(prose_problems(after)))
        self.assertNotEqual(prose_problem_kinds(before), prose_problem_kinds(after))
        self.assertEqual(
            prose_problem_kinds(after) - prose_problem_kinds(before), {"prose_wall"}
        )

    def test_kinds_do_not_leak_between_calls(self) -> None:
        prose_problem_kinds(stats(longest_prose_run=900))
        self.assertEqual(prose_problem_kinds(stats()), set())

    def test_the_measured_pair_differs_by_the_wall(self) -> None:
        drafts = {}
        for name in ("t1", "t2"):
            path = (
                REPO_ROOT / f"outputs/{name}/drafts"
                / "how-fast-can-an-arcade-machine-pay-for-itself-in-a-bar-or-ev.md"
            )
            if not path.exists():
                self.skipTest("run output not present")
            md = path.read_text(encoding="utf-8")
            body = md[: re.search(r"^##\s+FAQ", md, re.M | re.I).start()]
            drafts[name] = prose_problem_kinds(score_markdown(body))
        self.assertIn("prose_wall", drafts["t2"])
        self.assertNotIn("prose_wall", drafts["t1"])


class GateTests(unittest.TestCase):
    def test_the_gate_rejects_only_newly_introduced_kinds(self) -> None:
        self.assertIn("introduced = after_kinds - before_kinds", SOURCE)

    def test_it_names_what_it_rejected_for(self) -> None:
        """"Prose got worse" is not something a reader of the log can act on."""
        self.assertIn("but introduced ", SOURCE)
        self.assertIn("', '.join(sorted(introduced))", SOURCE)


class JustificationTests(unittest.TestCase):
    def test_an_earned_justification_survives_a_silent_revision(self) -> None:
        self.assertIn('if not (revised_result.get("length_justification") or "").strip():', SOURCE)
        self.assertIn('revised_result["length_justification"] = carried', SOURCE)

    def test_a_revision_with_its_own_reason_keeps_it(self) -> None:
        """Carrying forward must not overwrite what the revision itself said."""
        block = SOURCE[SOURCE.index("carrying the length justification") - 900 :][:1400]
        self.assertIn("if not (", block)
        self.assertNotIn("revised_result.pop", block)

    def test_it_reaches_the_companion_the_site_reads(self) -> None:
        self.assertIn('companion["length_justification"]', SOURCE)


class FinalVerdictTests(unittest.TestCase):
    def test_the_length_verdict_is_measured_after_qa(self) -> None:
        """It used to be the readability loop's parting word, and QA runs later."""
        qa_done = SOURCE.index('yield _event(steps, "QA Review", "done")')
        recompute = SOURCE.index("final_length = length_target.assess(")
        self.assertLess(recompute, qa_done)
        self.assertIn('results["length_check"] = final_length', SOURCE)

    def test_it_measures_the_markdown_that_ships(self) -> None:
        block = SOURCE[SOURCE.index("final_length = length_target.assess(") :][:400]
        self.assertIn("article_word_count(draft_markdown)", block)
        self.assertIn('draft_result.get("length_justification")', block)


if __name__ == "__main__":
    unittest.main()
