"""How long the articles already ranking are — and only the articles.

A live top five for one keyword was four commerce pages and a forum thread. The
shop category page measured 1,349 words and the product page 3,343, but those
numbers count product grids, review blocks, menus and footers; matching them
would mean nothing. The single article among them measured 1,835 words, and that
figure means something — it ranked alongside shop listings, so Google judged it
worth the place.

Nothing in the pipeline knew any of this. The engine wrote 5,842 words with no
idea what it was competing against.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.orchestrator import _build_serp_context  # noqa: E402
from src.serp_providers import MockSerpProvider  # noqa: E402


def read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


class SchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = json.loads(read("schemas/serp_research_schema.json"))

    def test_each_result_carries_a_type_and_a_length(self) -> None:
        item = self.schema["properties"]["top_results"]["items"]["properties"]
        self.assertIn("page_type", item)
        self.assertIn("word_count", item)

    def test_commerce_is_a_distinct_type_from_article(self) -> None:
        kinds = self.schema["properties"]["top_results"]["items"]["properties"]["page_type"]["enum"]
        self.assertIn("article", kinds)
        self.assertIn("commerce", kinds)

    def test_a_blocked_fetch_is_null_rather_than_zero(self) -> None:
        # Reddit and Facebook routinely refuse; zero would read as an empty page.
        wc = self.schema["properties"]["top_results"]["items"]["properties"]["word_count"]
        self.assertIn("null", wc["type"])

    def test_comparable_length_can_be_absent(self) -> None:
        block = self.schema["properties"]["comparable_length"]["properties"]
        self.assertIn("null", block["median_words"]["type"])
        self.assertIn("sample_size", block)


class MeasurementTests(unittest.TestCase):
    def test_the_word_count_is_taken_before_truncation(self) -> None:
        # Page text is capped at 3000 characters so one competitor cannot swamp
        # the context; counting after the cap would report every page as ~500
        # words.
        source = read("src/serp_providers.py")
        self.assertIn("self._last_word_count = len(text.split())", source)
        cut = source.index("self._last_word_count")
        self.assertLess(cut, source.index("return text[: self._MAX_PAGE_CHARS]"))

    def test_the_mock_provider_reports_nothing_rather_than_guessing(self) -> None:
        self.assertEqual(MockSerpProvider().fetch_page_detail("https://x"), ("", 0))


class HandoffTests(unittest.TestCase):
    def test_the_writer_receives_it(self) -> None:
        context = _build_serp_context({"comparable_length": {"median_words": 1835}})
        self.assertIn("comparable_length", context)
        self.assertIn("1835", context)

    def test_the_writer_is_pointed_at_the_length_target_block(self) -> None:
        prompt = read("prompts/writer_agent.md")
        self.assertIn("# LENGTH TARGET", prompt)
        self.assertIn("before you write", prompt)

    def test_going_longer_is_allowed_and_has_to_be_named(self) -> None:
        """Both halves matter and the rule is useless without either.

        A ceiling alone would forbid the article that genuinely answers what the
        ranking pages leave open; permission alone is what produced a
        5,340-word draft against an 1,835-word measurement.
        """
        prompt = read("prompts/writer_agent.md")
        self.assertIn("Writing longer is allowed", prompt)
        self.assertIn("length_justification", prompt)
        self.assertIn("padding", prompt)

    def test_the_justification_field_exists_in_the_draft_schema(self) -> None:
        import json

        schema = json.loads(read("schemas/article_draft_schema.json"))
        self.assertIn("length_justification", schema["properties"])

    def test_no_hard_coded_article_length_survives_in_the_prompt(self) -> None:
        """The 3000 outranked the measurement, because it was more concrete.

        A run measuring 1,835 words produced 5,340. Any bare word count written
        into the shared prompt competes with the figure the SERP actually
        measured, and wins.
        """
        prompt = read("prompts/writer_agent.md")
        self.assertNotIn("about 3000 words", prompt)
        self.assertNotIn("3000-word article", prompt)

    def test_a_null_target_is_not_invented(self) -> None:
        for rel in ("prompts/writer_agent.md", "prompts/serp_research_agent.md"):
            self.assertIn("invent", read(rel).lower(), rel)


if __name__ == "__main__":
    unittest.main()
