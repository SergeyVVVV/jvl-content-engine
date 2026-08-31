"""Four lines the site prints above the article, which the engine never wrote.

The site has rendered a HIGHLIGHTS box on 46 articles, and every one of them was
typed by hand into `src/data/articleHighlights.ts` at merge time. The engine had
no field for it, so every published article needed a manual step nobody had
written down.

The constraints here are the site's, measured from what is already live: exactly
four points, 69-120 characters each and 99 on average, none of the 184 ending in
a full stop, and plain text throughout — React escapes the string, so a bullet
or a `**bold**` ships as literal characters on the page.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.metadata_copy_agent import MetadataCopyAgent as Meta  # noqa: E402
from src.studio_export import to_studio_payload  # noqa: E402

GOOD = [
    "A $4,250 machine at $170 a week pays for itself in about six months before costs",
    "Published arcade figures come from venues where guests arrived intending to play",
    "After payback the base case nets roughly $671 a month once running costs are named",
    "The ECHO HD3 Commercial Edition is the machine this article's price anchor describes",
]


class CleaningTests(unittest.TestCase):
    def test_a_clean_set_passes_through(self) -> None:
        self.assertEqual(Meta._clean_highlights(GOOD), GOOD)

    def test_markdown_is_stripped_because_the_site_escapes_it(self) -> None:
        dirty = ["**Merit Industries** closed in 2014, ending an era for bars everywhere"] + GOOD[1:]
        self.assertNotIn("**", Meta._clean_highlights(dirty)[0])

    def test_a_link_becomes_its_own_text(self) -> None:
        dirty = ["[Merit Industries](https://x.com) closed in 2014, ending an era for bars"] + GOOD[1:]
        out = Meta._clean_highlights(dirty)[0]
        self.assertTrue(out.startswith("Merit Industries closed"))
        self.assertNotIn("http", out)

    def test_leading_bullets_and_numbering_go(self) -> None:
        for prefix in ("- ", "* ", "• ", "✓ ", "1. ", "2) "):
            dirty = [prefix + GOOD[0]] + GOOD[1:]
            self.assertEqual(Meta._clean_highlights(dirty)[0], GOOD[0])

    def test_the_trailing_full_stop_is_removed(self) -> None:
        """None of the 184 lines already on the site has one."""
        dirty = [GOOD[0] + "."] + GOOD[1:]
        self.assertFalse(Meta._clean_highlights(dirty)[0].endswith("."))

    def test_a_question_mark_survives(self) -> None:
        """Only the habitual full stop is removed, not real punctuation."""
        asked = ["Does a second machine double the takings? Rarely, and it can lower the average"]
        self.assertIn("?", Meta._clean_highlights(asked + GOOD[1:])[0])


class CountTests(unittest.TestCase):
    def test_four_is_the_only_acceptable_number(self) -> None:
        self.assertEqual(len(Meta._clean_highlights(GOOD)), 4)

    def test_too_few_drops_the_block_rather_than_shipping_a_stub(self) -> None:
        """A box of two reads as a bug; an absent box renders nothing at all."""
        self.assertEqual(Meta._clean_highlights(GOOD[:2]), [])

    def test_too_many_are_trimmed_to_four(self) -> None:
        extra = GOOD + ["A fifth line the site has no room for in its four-item block layout"]
        self.assertEqual(len(Meta._clean_highlights(extra)), 4)

    def test_junk_types_do_not_reach_the_site(self) -> None:
        self.assertEqual(Meta._clean_highlights(None), [])
        self.assertEqual(Meta._clean_highlights("not a list"), [])
        self.assertEqual(Meta._clean_highlights([1, 2, 3, 4]), [])

    def test_blank_entries_do_not_count_toward_the_four(self) -> None:
        self.assertEqual(Meta._clean_highlights(["", "  ", *GOOD[:2]]), [])


class PayloadTests(unittest.TestCase):
    MD = "# T\n\nIntro paragraph that the site needs above the first heading.\n\n## One\n\nBody.\n"

    def _payload(self, **meta):
        base = {"slug": "s", "meta_title": "T", "meta_description": "D"}
        base.update(meta)
        return to_studio_payload(base, self.MD, slug="s").payload

    def test_highlights_reach_the_article_object(self) -> None:
        article = self._payload(highlights=GOOD)["article"]
        self.assertEqual(article["highlights"], GOOD)

    def test_they_sit_beside_faq_not_inside_metadata(self) -> None:
        """The site reads article.highlights, mirroring article.faq."""
        payload = self._payload(highlights=GOOD)
        self.assertIn("highlights", payload["article"])
        self.assertNotIn("highlights", payload["metadata"])

    def test_an_article_without_them_omits_the_key(self) -> None:
        """The site falls back to its own map, then renders nothing."""
        self.assertNotIn("highlights", self._payload()["article"])
        self.assertNotIn("highlights", self._payload(highlights=[])["article"])


class PromptTests(unittest.TestCase):
    PROMPT = re.sub(
        r"\s+", " ",
        (REPO_ROOT / "prompts" / "metadata_copy_agent.md").read_text(encoding="utf-8"),
    )

    def test_the_field_is_in_the_output_contract(self) -> None:
        self.assertIn('"highlights"', self.PROMPT)

    def test_the_site_s_hard_constraints_are_stated(self) -> None:
        for rule in ("Exactly four", "69 to 120 characters", "Plain text only",
                     "No full stop at the end"):
            self.assertIn(rule, self.PROMPT, rule)

    def test_it_asks_for_findings_rather_than_a_contents_list(self) -> None:
        self.assertIn("not its table of contents", self.PROMPT)
        self.assertIn("is a contents line and fails", self.PROMPT)

    def test_the_product_line_is_conditional(self) -> None:
        """A box of four facts with an advert bolted on is worse than three."""
        self.assertIn("never as an advert bolted onto four facts", self.PROMPT)


if __name__ == "__main__":
    unittest.main()
