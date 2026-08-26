"""The length target has to reach the Writer before the first draft.

A run whose competitors measured 1,835 words produced 5,340. The measurement was
present the whole time — it sat inside the SERP JSON handed to the Writer — but
the shared prompt also said "an article runs about 3000 words across 10-14 H2
sections", and a hard-coded number beats a field in a payload every time.

So the target is computed, stated in words, and placed ahead of the research.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src import length_target  # noqa: E402


class ResolveTests(unittest.TestCase):
    def test_the_band_brackets_the_measured_median(self) -> None:
        t = length_target.resolve({"median_words": 1835, "sample_size": 1})
        self.assertLess(t["low"], 1835)
        self.assertGreater(t["high"], 1835)
        self.assertTrue(t["measured"])

    def test_the_band_is_fifteen_percent_either_side(self) -> None:
        t = length_target.resolve({"median_words": 2000, "sample_size": 3})
        self.assertEqual((t["low"], t["high"]), (1700, 2300))

    def test_a_missing_measurement_falls_back_and_admits_it(self) -> None:
        for value in (None, {}, {"median_words": None}, {"median_words": 0}):
            t = length_target.resolve(value)
            self.assertFalse(t["measured"], value)
            self.assertEqual(t["median"], length_target.FALLBACK_WORDS)

    def test_the_ceiling_sits_above_the_band_but_well_under_the_failure(self) -> None:
        """5,340 against 1,835 is 2.9x. The ceiling has to call that out."""
        t = length_target.resolve({"median_words": 1835, "sample_size": 1})
        self.assertGreater(t["ceiling"], t["high"])
        self.assertLess(t["ceiling"], 5340)


class RenderTests(unittest.TestCase):
    def test_it_states_the_band_in_words(self) -> None:
        text = length_target.render(
            length_target.resolve({"median_words": 1835, "sample_size": 1})
        )
        self.assertIn("1559", text)
        self.assertIn("2110", text)

    def test_it_permits_going_longer_and_asks_what_for(self) -> None:
        text = length_target.render(
            length_target.resolve({"median_words": 1835, "sample_size": 1})
        )
        self.assertIn("You may exceed the band", text)
        self.assertIn("length_justification", text)

    def test_an_unmeasured_target_does_not_pose_as_evidence(self) -> None:
        text = length_target.render(length_target.resolve(None))
        self.assertIn("default, not a finding", text)

    def test_the_faq_is_excluded_from_the_count(self) -> None:
        """The FAQ is written by a later agent and shipped as its own block."""
        text = length_target.render(
            length_target.resolve({"median_words": 1835, "sample_size": 1})
        )
        self.assertIn("FAQ", text)
        self.assertIn("does not count toward this target", text)


class HandoffTests(unittest.TestCase):
    def test_the_writer_takes_the_measurement(self) -> None:
        source = (REPO_ROOT / "src" / "writer_agent.py").read_text(encoding="utf-8")
        self.assertIn("comparable_length: dict | None = None", source)
        self.assertIn("length_target.render(target)", source)

    def test_the_block_lands_before_the_research_payloads(self) -> None:
        """Buried under the SERP JSON it lost to the prompt. Order is the fix."""
        source = (REPO_ROOT / "src" / "writer_agent.py").read_text(encoding="utf-8")
        body = source[source.index('f"{brief_block}"') :]
        self.assertLess(
            body.index('f"{length_section}"'), body.index('f"{serp_block}"')
        )

    def test_every_writer_call_gets_it_including_the_rewrites(self) -> None:
        """A rewrite blind to the target drifts straight back off it."""
        source = (REPO_ROOT / "src" / "orchestrator.py").read_text(encoding="utf-8")
        calls = source.count("writer_agent.run(")
        passed = source.count("comparable_length=comparable_length")
        self.assertGreaterEqual(passed, 3, f"{passed} of {calls} calls carry it")

    def test_it_is_resolved_before_the_writer_step(self) -> None:
        source = (REPO_ROOT / "src" / "orchestrator.py").read_text(encoding="utf-8")
        self.assertLess(
            source.index("comparable_length = (serp_data or {})"),
            source.index("draft_result = writer_agent.run("),
        )


if __name__ == "__main__":
    unittest.main()
