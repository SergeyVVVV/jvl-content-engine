"""Read ten results, not five.

Two runs of the same keyword, days apart. The first put one article in the top
five and the measurement came back at 1,835 words. The second put none there at
all — five shop pages and a blocked forum thread — and `comparable_length` came
back null, so the Writer fell through to a default.

That is the shape of a commercial query: merchants hold the first positions and
the guides sit behind them. A window of five leaves the field unanswerable
whenever that happens, which on this kind of keyword is often.

Reading to ten costs the same SerpAPI credit — the `num` parameter, not extra
searches — and buys the sample. What it must not do is quietly pass off a
position-nine article as though it ranked second.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src import length_target  # noqa: E402


def read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


class WindowTests(unittest.TestCase):
    def test_the_pipeline_asks_for_ten(self) -> None:
        source = read("src/orchestrator.py")
        self.assertIn("top_n=10", source)
        self.assertNotIn("top_n=5", source)

    def test_both_pipelines_ask_for_ten(self) -> None:
        """The Update pipeline runs its own SERP step and was missed once."""
        self.assertEqual(read("src/orchestrator.py").count("top_n=10"), 2)

    def test_the_defaults_agree_with_the_call_sites(self) -> None:
        for rel in ("src/serp_research_agent.py", "src/serp_providers.py"):
            self.assertIn("top_n: int = 10", read(rel), rel)
            self.assertNotIn("top_n: int = 5", read(rel), rel)

    def test_one_search_still_covers_it(self) -> None:
        """`num` widens a single query; it does not buy a second one."""
        source = read("src/serp_providers.py")
        self.assertIn('"num": top_n', source)


class PositionTests(unittest.TestCase):
    def test_the_schema_records_where_the_sample_came_from(self) -> None:
        import json

        schema = json.loads(read("schemas/serp_research_schema.json"))
        block = schema["properties"]["comparable_length"]["properties"]
        self.assertIn("positions", block)

    def test_a_back_half_sample_is_flagged_to_the_writer(self) -> None:
        text = length_target.render(
            length_target.resolve(
                {"median_words": 1900, "sample_size": 2, "positions": [7, 9]}
            )
        )
        self.assertIn("below position 5", text)
        self.assertIn("weaker signal", text)

    def test_a_top_five_sample_is_not_hedged(self) -> None:
        text = length_target.render(
            length_target.resolve(
                {"median_words": 1835, "sample_size": 1, "positions": [3]}
            )
        )
        self.assertNotIn("weaker signal", text)
        self.assertIn("Ranked at 3", text)

    def test_a_mixed_sample_is_not_hedged_either(self) -> None:
        """One article at 2 and one at 9 is still evidence from the top five."""
        text = length_target.render(
            length_target.resolve(
                {"median_words": 1900, "sample_size": 2, "positions": [2, 9]}
            )
        )
        self.assertNotIn("weaker signal", text)

    def test_missing_positions_are_simply_absent(self) -> None:
        """Older runs and the mock provider carry no ranks. That is not an error."""
        text = length_target.render(
            length_target.resolve({"median_words": 1835, "sample_size": 1})
        )
        self.assertIn("1835", text)
        self.assertNotIn("Ranked at", text)

    def test_junk_positions_do_not_reach_the_prompt(self) -> None:
        target = length_target.resolve(
            {"median_words": 1835, "sample_size": 1, "positions": [None, "3", 4]}
        )
        self.assertEqual(target["positions"], [4])

    def test_the_median_is_never_adjusted_for_rank(self) -> None:
        """The caveat goes in prose; the number stays the number."""
        low = length_target.resolve(
            {"median_words": 1900, "sample_size": 1, "positions": [9]}
        )
        high = length_target.resolve(
            {"median_words": 1900, "sample_size": 1, "positions": [1]}
        )
        self.assertEqual(low["median"], high["median"])
        self.assertEqual((low["low"], low["high"]), (high["low"], high["high"]))


class PromptTests(unittest.TestCase):
    def test_the_agent_is_told_why_the_window_widened(self) -> None:
        prompt = read("prompts/serp_research_agent.md")
        self.assertIn("You are given the top ten", prompt)
        self.assertIn("six through ten", prompt)

    def test_it_is_asked_to_record_ranks_rather_than_weight_them(self) -> None:
        prompt = read("prompts/serp_research_agent.md")
        self.assertIn("`positions`", prompt)
        self.assertIn("Do not weight or adjust the median for position", prompt)

    def test_an_empty_sample_is_still_reported_as_empty(self) -> None:
        """Widening the window must not turn a null into a guess."""
        prompt = read("prompts/serp_research_agent.md")
        self.assertIn("no article ranked anywhere in the ten", prompt)
        self.assertIn("A guess here is worse than an absence", prompt)


if __name__ == "__main__":
    unittest.main()
