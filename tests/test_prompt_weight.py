"""The shared prompt grew 45% in one session, and nobody was watching.

    2,977 words  before the run of fixes
    3,767        after the length fix
    4,309        after the section fix
    4,592        after the plain-language fix

Every addition was justified where it was made: a rule fixed a defect, and the
defect went in beside it so a later refactor would not delete the rule without
knowing what it cost. Twice that instinct was right — the section-length ceiling
was dropped while fixing length, and the Flesch target drifted three months
behind the code.

But the sum is a document where one instruction competes with four thousand
words of others, and where a contradiction between two rules can live for months
because nothing compares them. `# LENGTH TARGET` lost to a hard-coded 3000
partly on mass.

So the rule and its provenance are separated. The rule stays in the prompt. The
evidence moves to writer_agent.rationale.md, which no agent reads and which
protects against reverts exactly as well.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

PROMPT_PATH = REPO_ROOT / "prompts" / "writer_agent.md"
RATIONALE_PATH = REPO_ROOT / "prompts" / "writer_agent.rationale.md"
PROMPT = PROMPT_PATH.read_text(encoding="utf-8")
RATIONALE = RATIONALE_PATH.read_text(encoding="utf-8")

#: What the prompt may weigh. Set just above where the split left it, so a
#: genuine new rule fits and another accumulation of war stories does not.
MAX_PROMPT_WORDS = 4300


class WeightTests(unittest.TestCase):
    def test_the_prompt_stays_under_its_ceiling(self) -> None:
        words = len(PROMPT.split())
        self.assertLessEqual(
            words,
            MAX_PROMPT_WORDS,
            f"{words} words. Add the rule; put the story that justifies it in "
            f"{RATIONALE_PATH.name}.",
        )

    def test_it_is_smaller_than_before_the_split(self) -> None:
        self.assertLess(len(PROMPT.split()), 4592)


class SplitTests(unittest.TestCase):
    def test_the_rationale_file_exists_and_says_nobody_reads_it(self) -> None:
        self.assertIn("No agent reads this file", RATIONALE)

    def test_no_agent_loads_it(self) -> None:
        """A rationale that reaches a model is just more prompt."""
        for path in (REPO_ROOT / "src").glob("*.py"):
            self.assertNotIn(
                "writer_agent.rationale", path.read_text(encoding="utf-8"), path.name
            )

    def test_every_rule_it_explains_still_exists(self) -> None:
        """The file documents rules; it must not outlive them."""
        for rule in ("250 to 350 words", "35 words", "350 words unbroken",
                     "LENGTH TARGET", "length_justification", "one home"):
            self.assertIn(rule, PROMPT, rule)

    def test_the_evidence_that_was_moved_survived(self) -> None:
        for evidence in ("723, 421 and 522", "5,340", "1,835",
                         "the step every ranking guide skips", "63-word sentence"):
            self.assertIn(evidence, RATIONALE, evidence)

    def test_it_records_why_provenance_is_kept_at_all(self) -> None:
        flat = re.sub(r"\s+", " ", RATIONALE)
        self.assertIn("a rule the next refactor deletes", flat)


class LeakageTests(unittest.TestCase):
    """One article's numbers must not reach the prompt every article reads."""

    def test_no_dollar_figures_in_the_shared_prompt(self) -> None:
        """"at the $170 planned earlier" was in it until the split."""
        found = re.findall(r"\$\s?\d[\d,]*", PROMPT)
        self.assertEqual(found, [], f"topic figures in the shared prompt: {found}")

    def test_the_rationale_may_carry_them(self) -> None:
        """It is written for people, and the numbers are the evidence."""
        self.assertTrue(re.search(r"\d,\d{3}", RATIONALE))


if __name__ == "__main__":
    unittest.main()
