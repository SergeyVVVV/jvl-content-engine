"""The last step must not undo the work of the careful one.

The readability loop spends up to three Writer passes getting prose into range.
Then the Visual, FAQ and QA steps run, and a QA revision rewrites the whole
article with no prose constraint at all. Observed: the loop finished on three
problems, QA asked for one factual correction, and the revision came back with
four. A careful contour followed by a step that overwrites its result is not a
contour.

Separately, the FAQ. Six answers averaged 92 words with none under 84 — 554
words of prose wearing question marks, and the largest single stretch in the
article. It now has a length rule of its own, and the wall measurement stops at
the FAQ heading, because a question heading every ninety words is a visual
anchor on every screen and does not read as a wall however the arithmetic adds
up.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.readability_agent import longest_prose_run  # noqa: E402


def read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


class RevisionGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = read("src/orchestrator.py")

    def test_the_revision_is_measured_for_prose_before_it_is_accepted(self) -> None:
        loop = self.source[self.source.index("revision_damage(draft_markdown") - 2500 :]
        self.assertIn("prose_problem_kinds(score_markdown(draft_markdown))", loop)
        self.assertIn("prose_problem_kinds(score_markdown(revised_markdown))", loop)

    def test_a_revision_that_introduces_a_new_defect_is_rejected(self) -> None:
        self.assertIn("introduced = after_kinds - before_kinds", self.source)
        self.assertIn("if introduced:", self.source)

    def test_the_gate_no_longer_compares_counts(self) -> None:
        """Counting let a fixable sentence be traded for a 502-word wall.

        Three problems before, three after, and the wall shipped. What the
        readability loop earns is the absence of particular defects, so that is
        what survives the revision.
        """
        self.assertNotIn("after_prose > before_prose", self.source)
        self.assertNotIn("len(prose_problems(score_markdown(revised_markdown)))", self.source)

    def test_a_revision_that_fixes_without_introducing_is_allowed_through(self) -> None:
        # Only *new* kinds are rejected. A revision that clears a finding and
        # leaves the prose where it was is exactly what we asked for.
        self.assertNotIn("if after_kinds != before_kinds", self.source)

    def test_the_writer_is_warned_rather_than_only_judged(self) -> None:
        qa = read("src/qa_agent.py")
        self.assertIn("Keep the prose as readable as you found it", qa)
        self.assertIn("rejected whole", qa)


class FAQLengthTests(unittest.TestCase):
    def test_the_answer_length_rule_is_where_the_agent_reads_it(self) -> None:
        for rel in ("prompts/faq_agent.md", "src/faq_agent.py"):
            text = read(rel).lower()
            self.assertIn("60", text, rel)
            self.assertIn("40", text, rel)

    def test_the_first_sentence_must_answer_the_question(self) -> None:
        self.assertIn("First sentence answers the question", read("prompts/faq_agent.md"))

    def test_a_required_caveat_is_compressed_rather_than_dropped(self) -> None:
        # The ceiling is tight enough that the hedge is the obvious thing to
        # cut, and the hedge is the part that must not go.
        prompt = read("prompts/faq_agent.md")
        self.assertIn("never more than 60", prompt)
        self.assertIn("never a reason to leave it out", prompt)


class WallMeasurementTests(unittest.TestCase):
    def test_the_faq_does_not_count_toward_the_wall(self) -> None:
        body = "word " * 200
        faq = "\n\n## FAQ\n\n" + "\n\n".join(
            f"### Question {i}\n\n" + ("word " * 90) for i in range(6)
        )
        self.assertLess(longest_prose_run(body + faq), 300)

    def test_a_wall_before_the_faq_is_still_counted(self) -> None:
        md = ("word " * 900) + "\n\n## FAQ\n\n### Q\n\nA short answer."
        self.assertGreater(longest_prose_run(md), 800)

    def test_an_article_with_no_faq_is_unaffected(self) -> None:
        md = "word " * 500
        self.assertGreater(longest_prose_run(md), 450)


if __name__ == "__main__":
    unittest.main()
