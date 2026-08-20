"""An article may need no images, and the pipeline has to survive saying so.

The visual schema demanded exactly three assets while seo_rules.md asked that
"media should support content, not just fill space". Obeying the second was
impossible: three pictures had to be produced whether or not there was anything
to show. A run duly produced three decorative photographs of a subject the
reader had already understood, at roughly $0.13 and a minute apiece.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.visual_agent import VisualAgent  # noqa: E402


def schema() -> dict:
    return json.loads(
        (REPO_ROOT / "schemas" / "visual_schema.json").read_text(encoding="utf-8")
    )


class SchemaTests(unittest.TestCase):
    def test_zero_images_validate(self) -> None:
        import jsonschema

        s = schema()
        payload = {
            key: ([] if key == "assets" else "x")
            for key in s.get("required", ["assets"])
        }
        payload["assets"] = []
        try:
            jsonschema.validate(payload, s)
        except jsonschema.ValidationError as exc:
            if "assets" in str(exc.path) or "minItems" in str(exc):
                self.fail(f"an empty asset list must validate: {exc.message}")

    def test_the_ceiling_of_three_stays(self) -> None:
        self.assertEqual(schema()["properties"]["assets"]["maxItems"], 3)

    def test_the_floor_is_gone(self) -> None:
        self.assertEqual(schema()["properties"]["assets"]["minItems"], 0)


class PromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.prompt = VisualAgent()._build_system_prompt()

    def test_the_exact_quota_is_gone(self) -> None:
        self.assertNotIn("EXACTLY 3 items", self.prompt)

    def test_zero_is_named_as_a_valid_answer(self) -> None:
        self.assertIn("ZERO to THREE", self.prompt)
        self.assertIn("Do not pad", self.prompt)

    def test_the_criterion_is_the_open_question(self) -> None:
        self.assertIn("answering a question the text leaves open", self.prompt)


class InjectionTests(unittest.TestCase):
    """No assets must leave the draft untouched rather than raise."""

    DRAFT = (
        "# Title\n\nIntro paragraph.\n\n## First\n\nBody.\n\n## Second\n\nMore body.\n"
    )

    def test_no_assets_returns_the_draft_unchanged(self) -> None:
        self.assertEqual(VisualAgent._insert_images(self.DRAFT, []), self.DRAFT)

    def test_one_asset_still_lands(self) -> None:
        assets = [{"type": "hero", "url": "https://x/h.png", "alt_text": "a machine"}]
        out = VisualAgent._insert_images(self.DRAFT, assets)
        self.assertIn("![a machine](https://x/h.png)", out)

    def test_a_hero_only_article_gets_no_phantom_inlines(self) -> None:
        assets = [{"type": "hero", "url": "https://x/h.png", "alt_text": "a machine"}]
        out = VisualAgent._insert_images(self.DRAFT, assets)
        self.assertEqual(out.count("!["), 1)


if __name__ == "__main__":
    unittest.main()
