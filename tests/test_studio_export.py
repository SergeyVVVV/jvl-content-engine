"""Tests for the studio exporter and publish client.

Run: python3 -m unittest discover -s tests -v
No third-party test runner — the repo has none, and stdlib unittest is enough.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.studio_client import PublishResult, _explain, _interpret  # noqa: E402
from src.studio_export import (  # noqa: E402
    ARTICLE_TYPES,
    BYLINES,
    lint,
    normalize_slug,
    split_markdown,
    to_studio_payload,
    validate_payload,
)

ARTICLE = """# Best Gifts for Dads

Most gift guides don't help when dad has a full house.
They offer the same safe picks.

## Why Experience Beats Stuff

A dad who has everything has a routine.

### The Finishing Touches

Small things that land.

## FAQ

### Is a bartop hard to set up?

No.

---

## Claims to Verify Before Publishing

- Warranty length
- Shipping window

## Open TODOs for Human Review

- Confirm pricing
"""


class SplitMarkdownTests(unittest.TestCase):
    def setUp(self) -> None:
        self.h1, self.intro, self.sections = split_markdown(ARTICLE)

    def test_extracts_h1(self) -> None:
        self.assertEqual(self.h1, "Best Gifts for Dads")

    def test_keeps_intro_before_first_heading(self) -> None:
        self.assertTrue(self.intro.startswith("Most gift guides"))
        self.assertIn("same safe picks.", self.intro)

    def test_h1_is_not_a_section(self) -> None:
        self.assertNotIn("Best Gifts for Dads", [s["heading"] for s in self.sections])

    def test_sections_in_document_order_with_levels(self) -> None:
        self.assertEqual(
            [(s["level"], s["heading"]) for s in self.sections],
            [
                ("h2", "Why Experience Beats Stuff"),
                ("h3", "The Finishing Touches"),
                ("h2", "FAQ"),
                ("h3", "Is a bartop hard to set up?"),
            ],
        )

    def test_drops_internal_reviewer_blocks(self) -> None:
        headings = [s["heading"] for s in self.sections]
        self.assertNotIn("Claims to Verify Before Publishing", headings)
        self.assertNotIn("Open TODOs for Human Review", headings)

    def test_drops_content_under_internal_blocks(self) -> None:
        body = " ".join(s["body_markdown"] for s in self.sections)
        self.assertNotIn("Warranty length", body)
        self.assertNotIn("Confirm pricing", body)

    def test_strips_horizontal_rule_left_by_dropped_block(self) -> None:
        last_h3 = self.sections[-1]
        self.assertEqual(last_h3["body_markdown"], "No.")

    def test_body_belongs_to_its_own_heading(self) -> None:
        by_heading = {s["heading"]: s["body_markdown"] for s in self.sections}
        self.assertEqual(by_heading["Why Experience Beats Stuff"],
                         "A dad who has everything has a routine.")
        self.assertEqual(by_heading["The Finishing Touches"], "Small things that land.")

    def test_h3_under_internal_block_is_dropped(self) -> None:
        md = "# T\n\n## Open TODOs\n\n### Sub note\n\nleak\n"
        _, _, sections = split_markdown(md)
        self.assertEqual(sections, [])

    def test_headings_inside_code_fences_are_content(self) -> None:
        md = "# T\n\n## Real\n\n```\n## Not a heading\n```\n\ntail\n"
        _, _, sections = split_markdown(md)
        self.assertEqual([s["heading"] for s in sections], ["Real"])
        self.assertIn("## Not a heading", sections[0]["body_markdown"])

    def test_article_without_intro(self) -> None:
        _, intro, _ = split_markdown("# T\n\n## First\n\nbody\n")
        self.assertEqual(intro, "")

    def test_tables_and_lists_survive_intact(self) -> None:
        md = "# T\n\n## S\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\n- one\n- two\n"
        _, _, sections = split_markdown(md)
        body = sections[0]["body_markdown"]
        self.assertIn("| a | b |", body)
        self.assertIn("- one", body)


class PayloadShapeTests(unittest.TestCase):
    METADATA = {
        "meta_title": "Best Gifts for Dads Who Have Everything",
        "h1": "Best Gifts for Dads",
        "slug": "gifts-for-dads",
        "meta_description": "x" * 140,
        "excerpt": "A gift guide for the dad who already owns the obvious.",
        "primary_keyword": "gifts for dads",
    }

    def build(self, **kwargs):
        return to_studio_payload(self.METADATA, ARTICLE, **kwargs)

    def test_meta_title_is_renamed_to_title(self) -> None:
        metadata = self.build().payload["metadata"]
        self.assertEqual(metadata["title"], self.METADATA["meta_title"])
        self.assertNotIn("meta_title", metadata)

    def test_accepts_title_if_the_agent_is_ever_renamed(self) -> None:
        result = to_studio_payload(
            {"title": "T", "slug": "s", "meta_description": "d" * 130}, ARTICLE
        )
        self.assertEqual(result.payload["metadata"]["title"], "T")

    def test_h1_comes_from_the_markdown_not_the_metadata(self) -> None:
        # The two disagree in real runs; the markdown is the article that ships.
        self.assertEqual(self.build().payload["article"]["h1"], "Best Gifts for Dads")

    def test_intro_is_carried_as_its_own_field(self) -> None:
        self.assertTrue(
            self.build().payload["article"]["intro_markdown"].startswith("Most gift guides")
        )

    def test_intro_field_omitted_when_there_is_none(self) -> None:
        result = to_studio_payload(self.METADATA, "# T\n\n## S\n\nbody\n")
        self.assertNotIn("intro_markdown", result.payload["article"])

    def test_optional_metadata_passed_through(self) -> None:
        metadata = self.build().payload["metadata"]
        self.assertEqual(metadata["excerpt"], self.METADATA["excerpt"])
        self.assertEqual(metadata["primary_keyword"], "gifts for dads")

    def test_slug_override(self) -> None:
        self.assertEqual(self.build(slug="zzz-test").payload["metadata"]["slug"], "zzz-test")

    def test_author_key_included_only_when_given(self) -> None:
        self.assertNotIn("author_key", self.build().payload["metadata"])
        self.assertEqual(
            self.build(author_key="sergey-vysotsky").payload["metadata"]["author_key"],
            "sergey-vysotsky",
        )

    def test_payload_is_json_serialisable(self) -> None:
        json.dumps(self.build().payload)

    def test_generated_payload_passes_the_site_validator(self) -> None:
        self.assertIsNone(validate_payload(self.build().payload))


class ValidatorParityTests(unittest.TestCase):
    """Mirrors jvl-next validateDraftPayload, including its error strings."""

    def valid(self) -> dict:
        return {
            "metadata": {"slug": "s", "title": "t", "meta_description": "d"},
            "article": {"h1": "h", "sections": [{"heading": "x", "body_markdown": "y"}]},
        }

    def test_accepts_a_good_payload(self) -> None:
        self.assertIsNone(validate_payload(self.valid()))

    def test_raw_engine_output_fails_on_title(self) -> None:
        # Step-1 finding A: the Metadata Copy Agent emits meta_title.
        payload = self.valid()
        payload["metadata"]["meta_title"] = payload["metadata"].pop("title")
        self.assertEqual(validate_payload(payload), "metadata.title (string) is required")

    def test_missing_h1_fails(self) -> None:
        # Step-1 finding B: the Writer output has no h1 field.
        payload = self.valid()
        del payload["article"]["h1"]
        self.assertEqual(validate_payload(payload), "article.h1 (string) is required")

    def test_missing_sections_fails(self) -> None:
        # Step-1 finding C: the Writer output has no sections at all.
        payload = self.valid()
        payload["article"]["sections"] = []
        self.assertEqual(
            validate_payload(payload), "article.sections (non-empty array) is required"
        )

    def test_malformed_section_reports_its_index(self) -> None:
        payload = self.valid()
        payload["article"]["sections"] = [{"heading": "ok", "body_markdown": "y"}, {"heading": 1}]
        self.assertEqual(
            validate_payload(payload),
            "article.sections[1] must have {heading, body_markdown} strings",
        )

    def test_slug_that_normalizes_to_nothing(self) -> None:
        payload = self.valid()
        payload["metadata"]["slug"] = "!!!"
        self.assertEqual(
            validate_payload(payload), "metadata.slug normalizes to an empty string"
        )

    def test_normalize_slug_matches_laravel_style(self) -> None:
        self.assertEqual(normalize_slug("Best Gifts, for Dads!"), "best-gifts-for-dads")
        self.assertEqual(normalize_slug("--Trim--Me--"), "trim-me")
        self.assertEqual(normalize_slug("!!!"), "")
        self.assertEqual(len(normalize_slug("a" * 300)), 180)


class LintTests(unittest.TestCase):
    def payload(self, sections, **overrides):
        article = {"h1": "H", "sections": sections}
        article.update(overrides.pop("article", {}))
        metadata = {"slug": "s", "title": "t", "meta_description": "d" * 140}
        metadata.update(overrides.pop("metadata", {}))
        return {"metadata": metadata, "article": article}

    def sec(self, heading, body="body", level="h2"):
        return {"level": level, "heading": heading, "body_markdown": body}

    # Duplicate FAQ blocks are counted in to_studio_payload, before extraction
    # merges them — see FaqExtractionTests. What lint sees is the result.

    def test_flags_an_article_with_no_faq(self) -> None:
        warnings = lint(self.payload([self.sec("Other")]))
        self.assertTrue(any("No FAQ found" in w for w in warnings))

    def test_an_article_with_an_faq_is_not_flagged(self) -> None:
        warnings = lint(self.payload(
            [self.sec("Other")], article={"faq": [{"q": "Q?", "a": "A."}]}
        ))
        self.assertFalse(any("No FAQ found" in w for w in warnings))

    def test_flags_local_image_paths(self) -> None:
        body = "![hero](images/hero-01.png)"
        warnings = lint(self.payload([self.sec("S", body)]))
        self.assertTrue(any("local paths" in w for w in warnings))

    def test_remote_images_are_fine(self) -> None:
        body = "![hero](https://www.jvl.ca/img/hero.png)"
        warnings = lint(self.payload([self.sec("S", body)]))
        self.assertFalse(any("local paths" in w for w in warnings))

    def test_flags_h1_mismatch(self) -> None:
        warnings = lint(self.payload([self.sec("S")], metadata={"h1": "Different"}))
        self.assertTrue(any("differs from the markdown H1" in w for w in warnings))

    def test_flags_empty_sections_and_missing_intro(self) -> None:
        warnings = lint(self.payload([self.sec("S", "")]))
        self.assertTrue(any("empty body" in w for w in warnings))
        self.assertTrue(any("No intro" in w for w in warnings))

    def test_flags_meta_description_length(self) -> None:
        warnings = lint(self.payload([self.sec("S")], metadata={"meta_description": "short"}))
        self.assertTrue(any("meta_description is 5 chars" in w for w in warnings))

    def test_clean_payload_has_no_warnings(self) -> None:
        payload = self.payload(
            [self.sec("S")],
            article={"intro_markdown": "Lead.", "faq": [{"q": "Q?", "a": "A."}]},
            metadata={"tags": ["Arcade"]},
        )
        self.assertEqual(lint(payload), [])


class PublishResultTests(unittest.TestCase):
    def test_201_is_success(self) -> None:
        result = _interpret(201, {"success": True, "slug": "s", "pageId": 9, "newsId": 4})
        self.assertTrue(result.ok)
        self.assertEqual((result.slug, result.page_id, result.news_id), ("s", 9, 4))
        self.assertIn("AdminLTE", result.admin_hint)

    def test_422_surfaces_the_server_message(self) -> None:
        result = _interpret(422, {"success": False, "error": "metadata.title (string) is required"})
        self.assertFalse(result.ok)
        self.assertIn("metadata.title (string) is required", result.error)
        self.assertIn("contract", result.error)

    def test_401_explains_the_token(self) -> None:
        self.assertIn("JVL_PUBLISH_TOKEN", _explain(401, {"error": "Invalid"}))

    def test_503_explains_the_server_switch(self) -> None:
        self.assertIn("CONTENT_PUBLISH_TOKEN", _explain(503, {}))

    def test_unparsable_body_still_reports_status(self) -> None:
        result = _interpret(500, None)
        self.assertFalse(result.ok)
        self.assertIn("HTTP 500", result.error)

    def test_no_admin_hint_on_failure(self) -> None:
        self.assertEqual(PublishResult(ok=False, status=422).admin_hint, "")


class RealRunRegressionTests(unittest.TestCase):
    """The July run that step 1 was diagnosed on — guards the whole path."""

    SAMPLE = "best-15-gifts-for-dads-who-have-everything-v2"

    def setUp(self) -> None:
        meta_path = REPO_ROOT / f"outputs/metadata/{self.SAMPLE}.json"
        md_path = REPO_ROOT / f"outputs/drafts/{self.SAMPLE}.md"
        if not meta_path.exists() or not md_path.exists():
            self.skipTest("sample run not present in this checkout")
        self.result = to_studio_payload(
            json.loads(meta_path.read_text()), md_path.read_text()
        )

    def test_real_run_produces_an_acceptable_payload(self) -> None:
        self.assertIsNone(validate_payload(self.result.payload))

    def test_real_run_keeps_its_lead_paragraph(self) -> None:
        intro = self.result.payload["article"]["intro_markdown"]
        self.assertTrue(intro.startswith("Most gift guides"))

    def test_real_run_drops_reviewer_blocks(self) -> None:
        headings = [s["heading"] for s in self.result.sections]
        self.assertNotIn("Claims to Verify Before Publishing", headings)
        self.assertNotIn("Open TODOs for Human Review", headings)

    def test_real_run_reports_its_duplicate_faq(self) -> None:
        self.assertTrue(any("FAQ blocks" in w for w in self.result.warnings))


if __name__ == "__main__":
    unittest.main()


class TagsTypeAndBylineTests(unittest.TestCase):
    METADATA = {
        "meta_title": "T",
        "slug": "s",
        "meta_description": "d" * 140,
    }

    def build(self, **kwargs):
        return to_studio_payload(self.METADATA, ARTICLE, **kwargs)

    def test_articles_default_to_the_blog_listing(self) -> None:
        # What this pipeline writes are guides, not company news.
        self.assertEqual(self.build().payload["metadata"]["type"], "blog")

    def test_listing_can_be_overridden(self) -> None:
        self.assertEqual(self.build(article_type="news").payload["metadata"]["type"], "news")

    def test_tags_are_passed_through_trimmed(self) -> None:
        metadata = self.build(tags=[" Arcade ", "Home Bar"]).payload["metadata"]
        self.assertEqual(metadata["tags"], ["Arcade", "Home Bar"])

    def test_blank_tags_are_dropped(self) -> None:
        metadata = self.build(tags=["Arcade", "  ", ""]).payload["metadata"]
        self.assertEqual(metadata["tags"], ["Arcade"])

    def test_tags_key_absent_when_none_given(self) -> None:
        self.assertNotIn("tags", self.build().payload["metadata"])

    def test_known_bylines_match_the_site(self) -> None:
        self.assertEqual(BYLINES, ("sergey-vysotsky", "andrei-klimovich"))

    def test_lint_flags_an_unknown_byline_before_the_server_does(self) -> None:
        warnings = self.build(author_key="someone-else").warnings
        self.assertTrue(any("not one of" in w for w in warnings))

    def test_lint_accepts_a_known_byline(self) -> None:
        warnings = self.build(author_key="sergey-vysotsky").warnings
        self.assertFalse(any("not one of" in w for w in warnings))

    def test_lint_warns_when_there_are_no_tags(self) -> None:
        self.assertTrue(any("No tags" in w for w in self.build().warnings))

    def test_lint_is_quiet_once_tags_are_picked(self) -> None:
        warnings = self.build(tags=["Arcade"]).warnings
        self.assertFalse(any("No tags" in w for w in warnings))

    def test_lint_flags_a_bad_listing_type(self) -> None:
        warnings = lint({
            "metadata": {**self.METADATA, "type": "article", "tags": ["x"]},
            "article": {"h1": "H", "intro_markdown": "i",
                        "sections": [{"level": "h2", "heading": "S", "body_markdown": "b"}]},
        })
        self.assertTrue(any("must be one of" in w for w in warnings))


class PublishTagResultTests(unittest.TestCase):
    def test_attached_and_unknown_tags_come_back(self) -> None:
        result = _interpret(201, {
            "success": True, "slug": "s", "pageId": 1, "newsId": 2,
            "tagsAttached": ["Arcade"], "tagsUnknown": ["Nope"],
        })
        self.assertEqual(result.tags_attached, ["Arcade"])
        self.assertEqual(result.tags_unknown, ["Nope"])

    def test_older_server_without_tag_fields_is_fine(self) -> None:
        result = _interpret(201, {"success": True, "slug": "s", "pageId": 1, "newsId": 2})
        self.assertEqual(result.tags_attached, [])
        self.assertEqual(result.tags_unknown, [])


class FaqExtractionTests(unittest.TestCase):
    """The FAQ must leave the body and arrive as its own list."""

    def payload(self, markdown: str = ARTICLE) -> dict:
        return to_studio_payload({"meta_title": "T", "meta_description": "D",
                                  "slug": "best-gifts"}, markdown).payload

    def test_faq_is_lifted_out_of_the_body(self) -> None:
        article = self.payload()["article"]
        self.assertEqual(article["faq"], [{"q": "Is a bartop hard to set up?", "a": "No."}])

    def test_no_faq_heading_is_left_among_the_sections(self) -> None:
        headings = [s["heading"] for s in self.payload()["article"]["sections"]]
        self.assertNotIn("FAQ", headings)
        self.assertNotIn("Is a bartop hard to set up?", headings)

    def test_the_rest_of_the_article_survives(self) -> None:
        headings = [s["heading"] for s in self.payload()["article"]["sections"]]
        self.assertEqual(headings, ["Why Experience Beats Stuff", "The Finishing Touches"])

    def test_an_h3_outside_the_faq_stays_a_section(self) -> None:
        # "The Finishing Touches" sits under a normal H2 and must not be
        # swallowed as a question just because H3s inside the FAQ are.
        sections = self.payload()["article"]["sections"]
        self.assertEqual(sections[-1]["heading"], "The Finishing Touches")
        self.assertEqual(sections[-1]["level"], "h3")

    def test_article_without_faq_omits_the_key_and_warns(self) -> None:
        plain = "# T\n\nLead.\n\n## Only Section\n\nBody.\n"
        result = to_studio_payload({"meta_title": "T", "meta_description": "D",
                                    "slug": "s"}, plain)
        self.assertNotIn("faq", result.payload["article"])
        self.assertTrue(any("No FAQ found" in w for w in result.warnings))

    def test_question_without_an_answer_is_dropped(self) -> None:
        md = "# T\n\nLead.\n\n## FAQ\n\n### Unanswered?\n\n### Answered?\n\nYes.\n"
        article = self.payload(md)["article"]
        self.assertEqual(article["faq"], [{"q": "Answered?", "a": "Yes."}])

    def test_two_faq_blocks_merge_but_are_reported(self) -> None:
        md = ("# T\n\nLead.\n\n## FAQ\n\n### One?\n\nA.\n\n"
              "## Frequently Asked Questions\n\n### Two?\n\nB.\n")
        result = to_studio_payload({"meta_title": "T", "meta_description": "D",
                                    "slug": "s"}, md)
        self.assertEqual([i["q"] for i in result.payload["article"]["faq"]], ["One?", "Two?"])
        self.assertTrue(any("2 FAQ blocks" in w for w in result.warnings))

    def test_the_site_would_accept_the_result(self) -> None:
        self.assertIsNone(validate_payload(self.payload()))

    def test_validator_rejects_the_agents_own_shape(self) -> None:
        p = self.payload()
        p["article"]["faq"] = [{"question": "Q?", "answer": "A."}]
        self.assertIn("must have {q, a} strings", validate_payload(p) or "")


class HeroExtractionTests(unittest.TestCase):
    """The hero belongs in the media library, not in the prose."""

    MD = ("# T\n\n![A bartop arcade in a basement lounge]"
          "(https://example.supabase.co/storage/v1/object/public/article-images/t/hero-01.png)\n\n"
          "Lead paragraph.\n\n## One\n\nBody.\n")

    def build(self, markdown=None):
        return to_studio_payload({"meta_title": "T", "meta_description": "D", "slug": "t"},
                                 markdown or self.MD)

    def test_hero_url_and_alt_move_into_metadata(self) -> None:
        meta = self.build().payload["metadata"]
        self.assertTrue(meta["hero_image"].endswith("hero-01.png"))
        self.assertEqual(meta["hero_image_alt"], "A bartop arcade in a basement lounge")

    def test_hero_is_gone_from_the_body(self) -> None:
        p = self.build().payload
        blob = (p["article"].get("intro_markdown", "")
                + "".join(s["body_markdown"] for s in p["article"]["sections"]))
        self.assertNotIn("hero-01.png", blob)

    def test_the_lead_survives_the_removal(self) -> None:
        self.assertIn("Lead paragraph.", self.build().payload["article"]["intro_markdown"])

    def test_only_the_first_image_is_taken(self) -> None:
        md = self.MD + "\n![inline](https://example.com/inline-01.png)\n"
        p = self.build(md).payload
        body = "".join(s["body_markdown"] for s in p["article"]["sections"])
        self.assertIn("inline-01.png", body)
        self.assertTrue(p["metadata"]["hero_image"].endswith("hero-01.png"))

    def test_an_article_without_images_carries_no_hero(self) -> None:
        meta = self.build("# T\n\nLead.\n\n## One\n\nBody.\n").payload["metadata"]
        self.assertNotIn("hero_image", meta)

    def test_a_local_path_is_not_treated_as_a_hero(self) -> None:
        # A local path means the upload failed; the site cannot fetch it.
        md = "# T\n\n![x](images/hero-01.png)\n\nLead.\n\n## One\n\nBody.\n"
        self.assertNotIn("hero_image", self.build(md).payload["metadata"])


class HeroPublishResultTests(unittest.TestCase):
    def test_hero_success_is_reported(self) -> None:
        r = _interpret(201, {"success": True, "slug": "s", "pageId": 1, "newsId": 2,
                             "heroAttached": True})
        self.assertTrue(r.hero_attached)
        self.assertIsNone(r.hero_error)

    def test_hero_failure_carries_the_reason(self) -> None:
        r = _interpret(201, {"success": True, "slug": "s", "pageId": 1, "newsId": 2,
                             "heroAttached": False,
                             "heroError": "Hero image fetch failed: HTTP 404"})
        self.assertFalse(r.hero_attached)
        self.assertIn("404", r.hero_error)

    def test_an_older_server_without_the_field_is_fine(self) -> None:
        r = _interpret(201, {"success": True, "slug": "s", "pageId": 1, "newsId": 2})
        self.assertFalse(r.hero_attached)
        self.assertIsNone(r.hero_error)
