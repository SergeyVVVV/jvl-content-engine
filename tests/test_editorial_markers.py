"""Notes written for the team must not reach the reader.

A finished payload bound for jvl.ca carried five internal markers: three
`> **[VISUAL]** *chart — …*` blockquotes, which the Writer emits to tell whoever
makes the picture what to draw and which nothing removed, and two
`TODO: source not confirmed` strings sitting inside customer-facing FAQ answers.

The TODOs were not a lapse. `prompts/faq_agent.md` instructed the agent to write
exactly that string when an answer needed data nobody had confirmed, so it did.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.studio_export import strip_editorial_markers  # noqa: E402


class StripTests(unittest.TestCase):
    def test_a_visual_placeholder_goes(self) -> None:
        md = (
            "Some prose here.\n\n"
            "> **[VISUAL]** *chart — three-line payback curve over 36 months*\n\n"
            "More prose.\n"
        )
        out = strip_editorial_markers(md)
        self.assertNotIn("[VISUAL]", out)
        self.assertIn("Some prose here.", out)
        self.assertIn("More prose.", out)

    def test_a_todo_sentence_goes_and_the_answer_survives(self) -> None:
        md = (
            "Most occasional-event venues get more value treating it as part of "
            "the guest experience rather than as a revenue line. TODO: source not "
            "confirmed for typical event-venue drop rates.\n"
        )
        out = strip_editorial_markers(md).strip()
        self.assertNotIn("TODO", out)
        self.assertTrue(out.endswith("rather than as a revenue line."), out[-60:])

    def test_ordinary_prose_is_untouched(self) -> None:
        md = "# Heading\n\nA paragraph with a [link](https://x) and **bold**.\n"
        self.assertEqual(strip_editorial_markers(md), md)

    def test_a_quote_that_is_not_a_placeholder_survives(self) -> None:
        md = "> A real block quote from a source.\n"
        self.assertEqual(strip_editorial_markers(md).strip(), md.strip())

    def test_the_published_payload_carries_neither(self) -> None:
        from src.studio_export import to_studio_payload
        import dataclasses
        import json

        draft = REPO_ROOT / "outputs" / "v4" / "drafts" / (
            "how-fast-can-an-arcade-machine-pay-for-itself-in-a-bar-or-ev.md"
        )
        if not draft.exists():
            self.skipTest("sample draft not present")
        payload = to_studio_payload(
            {"slug": "x", "h1": "X", "meta_title": "X", "meta_description": "X"},
            draft.read_text(encoding="utf-8"),
        )
        blob = json.dumps(dataclasses.asdict(payload), ensure_ascii=False, default=str)
        self.assertNotIn("TODO", blob)
        self.assertNotIn("VISUAL", blob)


class SourceRuleTests(unittest.TestCase):
    """Fix the instruction, not only the symptom."""

    def test_the_faq_agent_is_no_longer_told_to_write_todos_into_answers(self) -> None:
        for rel in ("prompts/faq_agent.md", "src/faq_agent.py"):
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("NEVER write `TODO:` inside an answer".lower(), text.lower(), rel)

    def test_generated_images_of_tables_and_charts_are_forbidden(self) -> None:
        rules = (REPO_ROOT / "knowledge" / "visual_style_rules.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Never generate an image of a table", rules)
        self.assertIn("Tables belong in markdown", rules)


if __name__ == "__main__":
    unittest.main()
