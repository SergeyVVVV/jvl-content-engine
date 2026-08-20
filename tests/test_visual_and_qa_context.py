"""Guards for two failures that reached a finished article.

* QA judged the draft against the files it had been given and called confirmed
  facts inventions. It got claims_constraints.md, then flagged the 1995
  founding year and the seven-day production cycle as unsourced — both are
  entries in firsthand_experience.md, which it could not see. Same defect as
  before, one file over.
* The Visual Agent branded every image in an editorial ROI article, and an
  earlier run drew a competitor's cabinet running licensed game titles. A
  per-run instruction in the brief did not hold; the rule has to live in the
  style file the agent always loads.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.qa_agent import QAAgent  # noqa: E402
from src.visual_agent import _KNOWLEDGE_FILES as VISUAL_KNOWLEDGE  # noqa: E402


class QAContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.prompt = QAAgent()._build_system_prompt()

    def test_the_experience_anchors_reach_qa(self) -> None:
        # The two it wrongly flagged as unsourced on the last run.
        self.assertIn("seven working days", self.prompt)
        self.assertIn("eleventh generation", self.prompt)

    def test_the_claims_rules_still_reach_qa(self) -> None:
        self.assertIn("Forbidden", self.prompt)
        self.assertIn("22 inches", self.prompt)

    def test_qa_is_told_the_knowledge_base_is_the_authority(self) -> None:
        self.assertIn("source of truth", self.prompt)


class VisualRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = (REPO_ROOT / "knowledge" / "visual_style_rules.md").read_text(
            encoding="utf-8"
        )

    def test_the_visual_agent_loads_the_style_rules(self) -> None:
        self.assertIn(
            "visual_style_rules.md", [name for name, _ in VISUAL_KNOWLEDGE]
        )

    def test_third_party_ip_is_forbidden(self) -> None:
        lowered = self.rules.lower()
        self.assertIn("no third-party brands", lowered)
        for word in ("logo", "poster", "cabinet art"):
            self.assertIn(word, lowered)

    def test_editorial_images_must_be_unbranded(self) -> None:
        self.assertIn("unbranded", self.rules.lower())

    def test_captions_may_not_assert_specifications(self) -> None:
        lowered = self.rules.lower()
        self.assertIn("caption", lowered)
        self.assertIn("do not assert specifications", lowered.replace(
            "does not assert specifications", "do not assert specifications"))


if __name__ == "__main__":
    unittest.main()
