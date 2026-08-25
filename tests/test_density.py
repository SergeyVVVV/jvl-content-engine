"""Readability is three independent things, and averages hide the worst of them.

A reader complained about passages a passing article contained. Every check
agreed the article was fine, because every check measured a mean: 20.1 words per
sentence on average, while 22% of sentences ran past thirty and one reached
sixty-four. The complaint was about the tail.

Two more blind spots came out of the same look. Flesch is one number over two
independent dials — sentence length and word difficulty — so a band on the
combination let the draft buy length with vocabulary: lengthening sentences from
14.6 to 20.1 words also took syllables per word from 1.39 to 1.53 and difficult
words from 9.6% to 13.3%. And nothing counted how far prose ran before something
broke it up, which had gone from 643 words to 979.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.readability_agent import (  # noqa: E402
    MAX_DIFFICULT_WORD_SHARE,
    MAX_LIST_LINE_SHARE,
    MAX_LONG_SENTENCE_SHARE,
    MAX_PROSE_RUN_WORDS,
    MAX_SENTENCE_WORDS,
    MAX_SYLLABLES_PER_WORD,
    list_line_share,
    longest_prose_run,
    prose_problems,
    score_markdown,
)


def stats(**over) -> dict:
    base = {
        "flesch_reading_ease": 65.0,
        "avg_sentence_length": 18.0,
        "sentence_length_stdev": 9.0,
        "short_sentence_share": 0.30,
        "long_sentence_share": 0.05,
        "longest_sentence_words": 28,
        "difficult_word_share": 0.09,
        "avg_syllables_per_word": 1.40,
        "longest_prose_run": 200,
        "list_line_share": 0.15,
    }
    base.update(over)
    return base


class TailTests(unittest.TestCase):
    def test_a_clean_draft_has_no_problems(self) -> None:
        self.assertEqual(prose_problems(stats()), [])

    def test_a_single_monster_sentence_is_flagged(self) -> None:
        problems = prose_problems(stats(longest_sentence_words=64))
        self.assertTrue(any("read twice" in p for p in problems))

    def test_a_long_tail_is_flagged_even_when_the_mean_is_fine(self) -> None:
        # 20.1 words on average, 22% past thirty: the article that passed.
        problems = prose_problems(stats(avg_sentence_length=20.1, long_sentence_share=0.22))
        self.assertTrue(any("over thirty words" in p for p in problems))

    def test_the_ceiling_leaves_room_for_a_developed_sentence(self) -> None:
        self.assertGreater(MAX_SENTENCE_WORDS, 30)
        self.assertLess(MAX_SENTENCE_WORDS, 45)


class VocabularyTests(unittest.TestCase):
    def test_heavy_words_are_flagged_independently_of_length(self) -> None:
        problems = prose_problems(stats(avg_syllables_per_word=1.53, difficult_word_share=0.133))
        self.assertEqual(len(problems), 1)
        self.assertIn("separate from sentence length", problems[0])

    def test_the_fix_asks_for_verbs_not_shorter_sentences(self) -> None:
        problems = prose_problems(stats(difficult_word_share=0.20))
        self.assertIn("do not shorten sentences", problems[0])
        self.assertIn("Keep the sentences long", problems[0])

    def test_the_ceilings_sit_below_what_the_bad_draft_measured(self) -> None:
        self.assertLess(MAX_SYLLABLES_PER_WORD, 1.53)
        self.assertLess(MAX_DIFFICULT_WORD_SHARE, 0.133)


class ProseRunTests(unittest.TestCase):
    def test_headings_do_not_count_as_a_break(self) -> None:
        # A thousand words of paragraphs under one heading is still a wall.
        md = "## A heading\n\n" + ("word " * 400) + "\n\n## Another\n\n" + ("word " * 400)
        self.assertGreater(longest_prose_run(md), MAX_PROSE_RUN_WORDS)

    def test_a_table_breaks_it(self) -> None:
        md = ("word " * 300) + "\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n" + ("word " * 300)
        self.assertLessEqual(longest_prose_run(md), MAX_PROSE_RUN_WORDS)

    def test_a_list_and_a_quote_and_an_image_break_it_too(self) -> None:
        for breaker in ("- an item", "> a quote", "![alt](https://x/y.png)"):
            md = ("word " * 300) + f"\n\n{breaker}\n\n" + ("word " * 300)
            self.assertLessEqual(longest_prose_run(md), MAX_PROSE_RUN_WORDS, breaker)

    def test_a_wall_is_flagged_with_advice_not_just_a_number(self) -> None:
        problems = prose_problems(stats(longest_prose_run=979))
        self.assertTrue(problems)
        self.assertIn("Headings do not", problems[0])
        self.assertIn("becomes a table", problems[0])


class MeasurementHygieneTests(unittest.TestCase):
    """Tables and lists are not prose, and counting them punished good structure."""

    def test_a_table_row_is_not_a_sentence(self) -> None:
        # Five columns read as one 77-word sentence, so adding the table the
        # article needed made its readability numbers worse.
        md = "Some prose here.\n\n| a | b | c | d | e |\n|---|---|---|---|---|\n" + (
            "| " + " | ".join(["twelve word cell here now"] * 5) + " |\n"
        )
        self.assertLess(score_markdown(md)["longest_sentence_words"], 20)

    def test_bullets_do_not_merge_into_one_sentence(self) -> None:
        # Stripping the marker left lines with no terminal punctuation, which
        # merged into a single 104-word "sentence".
        md = "Prose sentence.\n\n" + "\n".join(f"- item number {i} with several words" for i in range(12))
        self.assertLess(score_markdown(md)["longest_sentence_words"], 20)

    def test_an_article_of_bullets_does_not_score_beautifully(self) -> None:
        # The counterweight to excluding lists from the prose measurement.
        md = "Intro.\n\n" + "\n".join(f"- item {i}" for i in range(40))
        self.assertGreater(list_line_share(md), MAX_LIST_LINE_SHARE)
        self.assertTrue(any("list items" in p for p in prose_problems(score_markdown(md))))


if __name__ == "__main__":
    unittest.main()
