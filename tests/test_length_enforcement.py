"""The length rule could not be obeyed where it was written.

The Writer was told to fill `length_justification` whenever it ran past the
target band. It never does, and the reason is not disobedience: it never learns
its own word count. The number does not exist until it has stopped writing, and
nothing hands it back. A measured draft landed 6% over the band with the field
empty — an impossible instruction reading as a broken one.

So the trigger moves to where the number is known: measured after the draft
exists, and fed to the Writer through the rewrite loop it already runs.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src import length_target as lt  # noqa: E402

TARGET = lt.resolve({"median_words": 2605, "sample_size": 2, "positions": [6, 8]})


class CountingTests(unittest.TestCase):
    def test_the_count_matches_the_article_as_a_reader_meets_it(self) -> None:
        """Tables and lists count: the competitor pages were measured the same way."""
        md = "# T\n\nOne two three.\n\n| a | b |\n| - | - |\n| four | five |\n\n- six seven\n"
        self.assertEqual(lt.article_word_count(md), 10)

    def test_the_faq_does_not_count(self) -> None:
        """A later agent writes it and it ships as its own block."""
        body = "# T\n\n" + " ".join(["word"] * 100)
        self.assertEqual(lt.article_word_count(body), 101)
        self.assertEqual(
            lt.article_word_count(body + "\n\n## FAQ\n\n" + " ".join(["q"] * 300)),
            101,
        )

    def test_the_sources_block_does_not_count_either(self) -> None:
        body = "# T\n\n" + " ".join(["word"] * 50)
        with_sources = body + "\n\n## Sources\n\n" + " ".join(["s"] * 200)
        self.assertEqual(lt.article_word_count(with_sources), 51)

    def test_it_reproduces_the_measured_run(self) -> None:
        """The run that prompted this: 3,164 words against a 2,214-2,995 band."""
        draft = (
            REPO_ROOT
            / "outputs/v8/drafts"
            / "how-fast-can-an-arcade-machine-pay-for-itself-in-a-bar-or-ev.md"
        )
        if not draft.exists():
            self.skipTest("run output not present")
        self.assertEqual(lt.article_word_count(draft.read_text(encoding="utf-8")), 3164)


class VerdictTests(unittest.TestCase):
    def test_inside_the_band_asks_for_nothing(self) -> None:
        self.assertIsNone(lt.assess(TARGET, 2600)["problem"])
        self.assertEqual(lt.assess(TARGET, 2600)["verdict"], "inside")

    def test_the_edges_of_the_band_are_inside_it(self) -> None:
        for words in (TARGET["low"], TARGET["high"]):
            self.assertEqual(lt.assess(TARGET, words)["verdict"], "inside", words)

    def test_over_the_band_without_a_reason_is_asked_for_one(self) -> None:
        verdict = lt.assess(TARGET, 3164)
        self.assertEqual(verdict["verdict"], "over_band")
        self.assertIn("6% past", verdict["problem"])
        self.assertIn("length_justification", verdict["problem"])

    def test_over_the_band_with_a_reason_is_accepted(self) -> None:
        """The permission to write longer is real, and this is where it lands."""
        verdict = lt.assess(TARGET, 3164, "models three scenarios none of them do")
        self.assertEqual(verdict["verdict"], "over_band_justified")
        self.assertIsNone(verdict["problem"])

    def test_whitespace_is_not_a_justification(self) -> None:
        self.assertEqual(lt.assess(TARGET, 3164, "   ")["verdict"], "over_band")

    def test_a_reason_does_not_buy_past_the_ceiling(self) -> None:
        """5,340 against 1,835 was 2.9x. No sentence justifies that."""
        verdict = lt.assess(TARGET, 5000, "a scenario none of them models")
        self.assertEqual(verdict["verdict"], "over_ceiling")
        self.assertIn("Cut a whole section", verdict["problem"])

    def test_the_ceiling_advice_is_to_cut_a_section_not_to_compress(self) -> None:
        """Compressing every explanation is how a 5,000-word draft got dense."""
        problem = lt.assess(TARGET, 5000)["problem"]
        self.assertIn("rather than compressing every explanation", problem)

    def test_a_thin_draft_is_caught_as_well(self) -> None:
        verdict = lt.assess(TARGET, 1500)
        self.assertEqual(verdict["verdict"], "thin")
        self.assertIn("Do not pad", verdict["problem"])

    def test_the_advice_never_asks_for_padding_or_hand_waving(self) -> None:
        for words in (1500, 3164, 5000):
            problem = lt.assess(TARGET, words)["problem"] or ""
            self.assertNotIn("add more detail", problem.lower())


class LoopTests(unittest.TestCase):
    """Measured every iteration, on the call the loop already makes."""

    def test_the_loop_takes_the_target(self) -> None:
        source = (REPO_ROOT / "src" / "readability_agent.py").read_text(encoding="utf-8")
        self.assertIn("word_target: dict | None = None", source)
        self.assertIn("length_target.assess(", source)

    def test_the_verdict_counts_toward_convergence(self) -> None:
        """Otherwise a length-only failure would look like a clean pass."""
        source = (REPO_ROOT / "src" / "readability_agent.py").read_text(encoding="utf-8")
        self.assertIn('problems = problems + [length["problem"]]', source)

    def test_the_feedback_the_writer_reads_carries_it_too(self) -> None:
        """The loop's own list and the rendered feedback are built separately."""
        source = (REPO_ROOT / "src" / "readability_agent.py").read_text(encoding="utf-8")
        formatter = source[source.index("def format_writer_feedback") :]
        self.assertIn('stats.get("length_check")', formatter)

    def test_it_costs_no_extra_model_call(self) -> None:
        """Length rides the rewrite the loop was already going to make."""
        source = (REPO_ROOT / "src" / "readability_agent.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("rewrite_fn("), 1)

    def test_the_orchestrator_hands_the_target_over(self) -> None:
        source = (REPO_ROOT / "src" / "orchestrator.py").read_text(encoding="utf-8")
        self.assertIn("word_target=length_target.resolve(comparable_length)", source)

    def test_the_verdict_reaches_the_run_summary(self) -> None:
        """A draft ending over target used to be visible only by counting the file."""
        self.assertIn("length_check", (REPO_ROOT / "src" / "orchestrator.py").read_text(encoding="utf-8"))
        self.assertIn("length   :", (REPO_ROOT / "run_article.py").read_text(encoding="utf-8"))


class PromptTests(unittest.TestCase):
    def test_the_writer_is_no_longer_asked_to_notice_its_own_overshoot(self) -> None:
        """It cannot. The prompt should say what the field is for, not when to fire it."""
        prompt = re.sub(
            r"\s+", " ", (REPO_ROOT / "prompts" / "writer_agent.md").read_text(encoding="utf-8")
        )
        phrase = "You will not know your own word count"
        self.assertTrue(phrase in prompt, f"prompt does not say: {phrase!r}")

    def test_the_field_still_exists_and_still_means_the_same_thing(self) -> None:
        schema = json.loads(
            (REPO_ROOT / "schemas" / "article_draft_schema.json").read_text(encoding="utf-8")
        )
        self.assertIn("length_justification", schema["properties"])


if __name__ == "__main__":
    unittest.main()
