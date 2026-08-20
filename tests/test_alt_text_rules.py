"""Alt text is a description, and the codebase has to say so in one voice.

Three files gave instructions about alt text and they did not agree:
visual_agent said "not keywords", seo_rules said "for accessibility", and
writer_agent asked for "SEO-friendly alt text" — an invitation to the exact
keyword stuffing the other two forbid. A live run produced alt strings of 196,
160 and 193 characters, each restating its own caption.

Screen readers and search engines want the same thing here, which is why there
is no separate SEO alt to write. These tests pin that the rules say so and stay
consistent with the unbranded-image rule from the visual style file.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


class AltTextRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.visual_prompt = read("prompts/visual_agent.md")
        self.writer_prompt = read("prompts/writer_agent.md")
        self.agent_source = read("src/visual_agent.py")

    def test_no_file_still_asks_for_seo_alt_text(self) -> None:
        for name, text in (
            ("prompts/writer_agent.md", self.writer_prompt),
            ("prompts/visual_agent.md", self.visual_prompt),
            ("src/visual_agent.py", self.agent_source),
        ):
            self.assertNotIn("SEO-friendly alt", text, name)

    def test_the_length_range_is_stated_where_the_agent_reads_it(self) -> None:
        self.assertIn("60 to 150 characters", self.visual_prompt)
        self.assertIn("60-150", self.agent_source)

    def test_image_of_openers_are_banned(self) -> None:
        self.assertIn('"image of"', self.visual_prompt)

    def test_alt_may_not_duplicate_the_caption(self) -> None:
        self.assertIn("Do not repeat the caption word for word", self.visual_prompt)

    def test_decorative_images_take_empty_alt(self) -> None:
        self.assertIn('alt=""', self.visual_prompt)

    def test_charts_put_their_figures_in_the_text(self) -> None:
        lowered = self.visual_prompt.lower()
        self.assertIn("charts and diagrams", lowered)
        self.assertIn("readable on the page", lowered)


class BrandConsistencyTests(unittest.TestCase):
    """Alt must not name a product the picture does not contain.

    #51 requires unbranded machines above the closing product section. An alt
    rule that said "always write JVL ECHO HD3 for our own imagery" would
    contradict it and put a brand claim on a generic photograph.
    """

    def test_the_brand_is_conditional_on_the_machine_being_shown(self) -> None:
        prompt = read("prompts/visual_agent.md")
        self.assertIn("only when our machine is actually shown", prompt)

    def test_the_unbranded_rule_still_stands(self) -> None:
        rules = read("knowledge/visual_style_rules.md")
        self.assertIn("unbranded", rules.lower())


if __name__ == "__main__":
    unittest.main()
