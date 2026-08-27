"""Writing plainly was one bullet and one example.

The prompt said "Prefer clarity over cleverness" and gave a single before/after
pair. Against four thousand words of instructions — most of which ask for
something to be added, explained or demonstrated — one example does not
generalise. Meanwhile the checker measured vocabulary on two dials and drafts
kept failing them: 1.487 syllables per word and 13% difficult words in one run,
1.514 and 14% in two others, against ceilings of 1.45 and 11%.

So the rule is now a presumption rather than a preference, with the three habits
that cause the damage named and three worked pairs taken from drafts this
pipeline actually produced.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.readability_agent import (  # noqa: E402
    MAX_DIFFICULT_WORD_SHARE,
    MAX_SYLLABLES_PER_WORD,
    prose_problem_kinds,
)

RAW = (REPO_ROOT / "prompts" / "writer_agent.md").read_text(encoding="utf-8")
PROMPT = re.sub(r"\s+", " ", RAW)


def says(case: unittest.TestCase, phrase: str) -> None:
    case.assertTrue(phrase in PROMPT, f"prompt does not say: {phrase!r}")


class PresumptionTests(unittest.TestCase):
    def test_plainness_is_the_default_not_a_preference(self) -> None:
        says(self, "Write plainly by default")
        says(self, "the burden of proof is on the complicated one")

    def test_the_three_habits_are_named(self) -> None:
        for habit in (
            "the noun made from a verb",
            "the longer synonym for no reason",
            "the term nobody asked for",
        ):
            says(self, habit)

    def test_the_common_offenders_are_listed_by_name(self) -> None:
        """A model generalises from a list better than from one example."""
        for word in ("utilise", "commence", "sufficient", "approximately", "prior to"):
            says(self, word)

    def test_a_term_used_once_is_called_out(self) -> None:
        says(self, "a term you use once was showing off")


class NotBrevityTests(unittest.TestCase):
    """The trap this rule could create, closed in the rule itself."""

    def test_the_worked_pair_that_gets_longer_is_kept(self) -> None:
        says(self, "The last plain version is **longer**, and still the better sentence")

    def test_plainness_is_distinguished_from_brevity(self) -> None:
        says(self, "Plainness is not brevity")
        says(self, "Never compress an explanation in its name")

    def test_terms_of_art_survive(self) -> None:
        """A reader who cannot recognise the term next time was not helped.

        Stated without naming any — the shared prompt is read by every article,
        and examples from one topic leak into all of them. A guard in
        test_article_profiles enforces that, and caught this rule using
        arcade vocabulary on the first draft of it.
        """
        says(self, "A term of art stays as it is")
        says(self, "unable to spot them next time")
        for topic_word in ("payback period", "coin drop", "revenue split"):
            self.assertNotIn(topic_word, PROMPT, topic_word)


class DialTests(unittest.TestCase):
    """Vocabulary and sentence length fail independently and are fixed differently."""

    def test_the_writer_is_told_not_to_shorten_sentences_for_vocabulary(self) -> None:
        says(self, "do not shorten sentences — that is the wrong dial")

    def test_the_checker_agrees_they_are_separate(self) -> None:
        heavy_words = {
            "flesch_reading_ease": 67.0, "avg_sentence_length": 18.0,
            "sentence_length_stdev": 8.0, "short_sentence_share": 0.25,
            "long_sentence_share": 0.05, "longest_sentence_words": 20,
            "avg_syllables_per_word": 1.60, "difficult_word_share": 0.16,
            "longest_prose_run": 200, "list_line_share": 0.10,
        }
        self.assertEqual(prose_problem_kinds(heavy_words), {"vocabulary"})

    def test_the_ceilings_the_prompt_is_written_against(self) -> None:
        self.assertEqual(MAX_SYLLABLES_PER_WORD, 1.45)
        self.assertEqual(MAX_DIFFICULT_WORD_SHARE, 0.11)


class EvidenceTests(unittest.TestCase):
    def test_the_pairs_come_from_real_drafts(self) -> None:
        says(self, "From drafts this pipeline has already produced")

    def test_the_heavy_side_of_each_pair_is_quoted_verbatim(self) -> None:
        """Invented examples drift; these are greppable in the outputs."""
        for phrase in (
            "applicable taxes",
            "attributable to a single machine",
            "from stated assumptions",
        ):
            says(self, phrase)

    def test_there_are_three_pairs_not_one(self) -> None:
        table = RAW[RAW.index("| as written |") :]
        rows = [r for r in table.splitlines() if r.startswith("|")]
        self.assertGreaterEqual(len(rows) - 2, 3)


if __name__ == "__main__":
    unittest.main()
