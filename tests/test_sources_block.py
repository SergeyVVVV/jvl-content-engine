"""The list of sources that closes an article.

Citing sources is not a ranking factor — Google documents none, and the 2026
reading is that outbound links support E-E-A-T, which reaches ranking only
indirectly. So the block is built for the reader, and two things follow: a short
chosen list reads as editorial judgement where a long one reads as an automated
dump, and a bare URL demonstrates nothing that a title, publisher and date do
not demonstrate better.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.sources_block import (  # noqa: E402
    MAX_SOURCES,
    append_to_article,
    render,
    select_sources,
)


def facts(*sources) -> dict:
    return {"findings": [{"sources": list(sources)}]}


def src(url, kind="industry", title="A title", date="2025") -> dict:
    return {"url": url, "kind": kind, "title": title, "date": date, "figure": "said"}


class SelectionTests(unittest.TestCase):
    def test_our_own_site_is_never_a_source(self) -> None:
        # A live search returned jvl.ca. Citing ourselves for what a machine
        # earns is circular, and a reader who follows the link sees that.
        chosen = select_sources(facts(
            src("https://www.jvl.ca/en/blog", kind="own_site"),
            src("https://a.com"), src("https://b.com"),
        ))
        self.assertNotIn("jvl.ca", [s["publisher"] for s in chosen])

    def test_one_entry_per_publisher(self) -> None:
        # The same site three times is one voice, not three.
        chosen = select_sources(facts(
            src("https://x.com/one"), src("https://x.com/two"), src("https://y.com"),
        ))
        self.assertEqual([s["publisher"] for s in chosen], ["x.com", "y.com"])

    def test_operators_outrank_industry_blogs_which_outrank_sellers(self) -> None:
        chosen = select_sources(facts(
            src("https://seller.com", kind="vendor"),
            src("https://blog.com", kind="industry"),
            src("https://ops.com", kind="operator"),
        ))
        self.assertEqual(
            [s["publisher"] for s in chosen], ["ops.com", "blog.com", "seller.com"]
        )

    def test_a_dated_source_wins_a_tie(self) -> None:
        chosen = select_sources(facts(
            src("https://undated.com", date=""), src("https://dated.com", date="2026"),
        ))
        self.assertEqual(chosen[0]["publisher"], "dated.com")

    def test_the_list_stays_short_enough_to_look_chosen(self) -> None:
        many = facts(*[src(f"https://s{i}.com") for i in range(20)])
        self.assertLessEqual(len(select_sources(many)), MAX_SOURCES)


class RenderTests(unittest.TestCase):
    def test_one_source_still_gets_a_block(self) -> None:
        # If the article leaned on something, the reader gets to see what.
        out = render(facts(src("https://a.com", title="The one source")))
        self.assertIn("## Sources", out)
        self.assertIn("The one source", out)

    def test_no_research_gets_no_block(self) -> None:
        self.assertEqual(render({}), "")
        self.assertEqual(render({"findings": []}), "")

    def test_entries_carry_title_publisher_and_date_not_a_bare_url(self) -> None:
        out = render(facts(
            src("https://www.partycentersoftware.com/blog/x",
                title="Average Arcade Revenue and Budget", date="2025"),
            src("https://ops.com", kind="operator", title="Operator notes", date="2026-01"),
        ))
        self.assertIn("[Average Arcade Revenue and Budget](", out)
        self.assertIn("partycentersoftware.com", out)
        self.assertIn("2025", out)

    def test_a_seller_is_labelled_as_one(self) -> None:
        out = render(facts(
            src("https://betson.com", kind="vendor", title="How Profitable are Arcades?"),
            src("https://ops.com", kind="operator"),
        ))
        self.assertIn("(supplier)", out)

    def test_the_heading_is_an_h2_so_the_exporter_treats_it_as_a_section(self) -> None:
        out = render(facts(src("https://a.com"), src("https://b.com")))
        self.assertTrue(out.startswith("## Sources"))


class PlacementTests(unittest.TestCase):
    BLOCK = "## Sources\n\n- [A](https://a.com) — a.com"

    def test_it_lands_at_the_end_after_the_faq(self) -> None:
        article = "# T\n\nBody.\n\n## FAQ\n\n### Q\n\nA.\n"
        out = append_to_article(article, self.BLOCK)
        self.assertLess(out.index("## FAQ"), out.index("## Sources"))

    def test_it_goes_before_the_internal_review_block(self) -> None:
        article = "# T\n\nBody.\n\n---\n\n## Claims to Verify Before Publishing\n\n- x\n"
        out = append_to_article(article, self.BLOCK)
        self.assertLess(out.index("## Sources"), out.index("## Claims to Verify"))

    def test_re_appending_does_not_duplicate(self) -> None:
        article = "# T\n\nBody.\n"
        once = append_to_article(article, self.BLOCK)
        twice = append_to_article(once, self.BLOCK)
        self.assertEqual(twice.count("## Sources"), 1)

    def test_an_empty_block_leaves_the_article_alone(self) -> None:
        article = "# T\n\nBody.\n"
        self.assertEqual(append_to_article(article, ""), article)


class WriterRuleTests(unittest.TestCase):
    """Attribution belongs in the prose; links belong at the end.

    A sentence followed by a link is the signature of a search assistant —
    Perplexity and ChatGPT Search append a footnote to every fact — and a reader
    who has seen that output recognises the machine immediately.
    """

    def setUp(self) -> None:
        self.prompt = (REPO_ROOT / "prompts" / "writer_agent.md").read_text(
            encoding="utf-8"
        )

    def test_external_links_are_kept_out_of_the_body(self) -> None:
        self.assertIn("Do not put external links in the body", self.prompt)

    def test_named_attribution_is_capped(self) -> None:
        self.assertIn("At most three named sources", self.prompt)

    def test_a_departure_from_the_researched_typical_must_be_explained(self) -> None:
        self.assertIn("say why in the article", self.prompt)

    def test_the_threshold_needs_both_conditions(self) -> None:
        self.assertIn("Both conditions, not either", self.prompt)

    def test_our_own_facts_are_never_attributed(self) -> None:
        self.assertIn("citing ourselves as independent evidence is circular", self.prompt)


if __name__ == "__main__":
    unittest.main()


class SurvivesRevisionTests(unittest.TestCase):
    """A QA revision must not be able to replace the chosen list with its own.

    Observed on a live run: the selector produced seven entries, QA asked for a
    fix, the Writer rewrote the article including its own sources list, and the
    published block had ten entries with four from a single publisher. The
    selection rules live in this module; the Writer has never seen them.
    """

    BLOCK = (
        "## Sources\n\n"
        "- [Chosen one](https://a.com) — a.com, 2025\n"
        "- [Chosen two](https://b.com) — b.com, 2026"
    )

    WRITERS_OWN = (
        "## Sources\n\n"
        "- [Something](https://dojobusiness.com/one)\n"
        "- [Something else](https://dojobusiness.com/two)\n"
        "- [A third](https://dojobusiness.com/three)\n"
    )

    def test_a_rewritten_block_is_replaced_not_joined(self) -> None:
        article = "# T\n\nBody.\n\n" + self.WRITERS_OWN
        out = append_to_article(article, self.BLOCK)
        self.assertEqual(out.count("## Sources"), 1)
        self.assertNotIn("dojobusiness.com", out)
        self.assertIn("Chosen one", out)

    def test_it_is_replaced_under_another_name_too(self) -> None:
        # A revision may call it References or Further reading.
        for heading in ("References", "Further reading", "Citations"):
            article = f"# T\n\nBody.\n\n## {heading}\n\n- [x](https://x.com)\n"
            out = append_to_article(article, self.BLOCK)
            self.assertNotIn(heading, out, heading)
            self.assertIn("Chosen one", out)

    def test_the_orchestrator_restores_it_after_a_revision(self) -> None:
        source = (REPO_ROOT / "src" / "orchestrator.py").read_text(encoding="utf-8")
        loop = source[source.index("revision_damage(draft_markdown") - 2000 :]
        self.assertIn("sources_block.append_to_article", loop)
