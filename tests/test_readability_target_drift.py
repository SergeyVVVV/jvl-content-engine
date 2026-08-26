"""The readability agent was chasing a target the code had abandoned.

`src/readability_agent.py` moved from an unreachable Flesch score of 90 to a
60-75 band in August. `prompts/readability_agent.md` was not touched, then or
since, so the agent kept reading "Flesch Reading Ease score >= 90" as its goal
while the user message handed it a band of 60-75 and a list of the checks
actually out of range.

A run scored 68.12 — passing by the code, twenty-two points short by the prompt.
The agent spent its entire 16,000-token output budget deliberating and emitted
no text at all, and the rewrite loop stopped with problems still on the board.

Two fixes here: the prompt now states the band, and the step has a budget sized
for reading a whole article.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src import readability_agent  # noqa: E402
from src.readability_agent import TARGET_MAX, TARGET_MIN, max_tokens  # noqa: E402

PROMPT = (REPO_ROOT / "prompts" / "readability_agent.md").read_text(encoding="utf-8")
FLAT = re.sub(r"\s+", " ", PROMPT)


class TargetTests(unittest.TestCase):
    def test_the_prompt_states_the_band_the_code_enforces(self) -> None:
        self.assertIn(f"between {int(TARGET_MIN)} and {int(TARGET_MAX)}", FLAT)

    def test_the_unreachable_target_is_no_longer_asked_for(self) -> None:
        """90 needs ~1.24 syllables per word. "profitability" carries six."""
        self.assertNotIn("score **>= 90**", PROMPT)
        self.assertNotIn("if score < 90", PROMPT)

    def test_a_passing_draft_is_explicitly_left_alone(self) -> None:
        self.assertIn("Do not push a draft that is already inside the band", FLAT)
        self.assertIn("A score of 68 is finished", FLAT)

    def test_the_quota_that_manufactured_work_is_gone(self) -> None:
        """"At least 3 items" guaranteed instructions for a passing draft."""
        self.assertNotIn("at least 3 items", PROMPT)
        self.assertIn("An empty list is the correct output", FLAT)

    def test_the_agent_is_pointed_at_the_separate_checks(self) -> None:
        """A single score hides the tail, the vocabulary and the walls."""
        for phrase in ("long-sentence tail", "Vocabulary weight", "Unbroken prose"):
            self.assertIn(phrase, PROMPT, phrase)

    def test_it_is_warned_off_its_one_reflex(self) -> None:
        """Every problem became a reason to shorten sentences. Hence 14-word means."""
        self.assertIn("independent dials", FLAT)
        self.assertIn("treating every problem as a reason to shorten", FLAT)

    def test_the_history_is_kept_so_the_target_does_not_drift_back(self) -> None:
        self.assertIn("arithmetically unreachable", FLAT)


class DriftGuardTests(unittest.TestCase):
    """The same mistake, three times, is a pattern worth a test.

    A rule written into both a prompt and the code drifts the moment one side is
    edited alone. It has now happened with the article length ("about 3000
    words" against a measured 1,835), with the section floor against the prose
    ceiling, and here with the Flesch target. Each survived for months because
    nothing compared the two copies.
    """

    def test_no_prompt_states_a_flesch_target_outside_the_code_band(self) -> None:
        floor, ceiling = int(TARGET_MIN), int(TARGET_MAX)
        allowed = {str(n) for n in range(floor, ceiling + 1)}
        for path in (REPO_ROOT / "prompts").rglob("*.md"):
            text = re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))
            for match in re.finditer(
                r"(?:Flesch[^.]{0,60}?|reading ease[^.]{0,40}?)(\d{2,3})", text, re.I
            ):
                number = match.group(1)
                if number in allowed:
                    continue
                context = text[max(0, match.start() - 90) : match.end() + 40]
                # A number quoted while explaining a past mistake is not a target.
                if any(
                    marker in context
                    for marker in ("used to", "unreachable", "measured", "scored")
                ):
                    continue
                self.fail(
                    f"{path.name} states a Flesch figure of {number}, outside the "
                    f"code band {floor}-{ceiling}: …{context.strip()}…"
                )

    def test_the_band_reaches_the_agent_in_the_user_message_too(self) -> None:
        """Belt and braces: the prompt can drift again, this cannot."""
        source = (REPO_ROOT / "src" / "readability_agent.py").read_text(encoding="utf-8")
        self.assertIn("target band: ", source)
        self.assertIn("{TARGET_MIN}-{TARGET_MAX}", source)


class BudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = os.environ.pop("READABILITY_MAX_TOKENS", None)

    def tearDown(self) -> None:
        os.environ.pop("READABILITY_MAX_TOKENS", None)
        if self._saved is not None:
            os.environ["READABILITY_MAX_TOKENS"] = self._saved

    def test_the_step_no_longer_runs_on_the_shared_default(self) -> None:
        from src import llm_client

        self.assertGreater(max_tokens(), llm_client.default_max_tokens())

    def test_the_budget_covers_the_run_that_exhausted_sixteen_thousand(self) -> None:
        self.assertGreaterEqual(max_tokens(), 24000)

    def test_env_overrides_and_nonsense_falls_back(self) -> None:
        os.environ["READABILITY_MAX_TOKENS"] = "30000"
        self.assertEqual(max_tokens(), 30000)
        os.environ["READABILITY_MAX_TOKENS"] = "plenty"
        self.assertEqual(max_tokens(), 24000)
        os.environ["READABILITY_MAX_TOKENS"] = "0"
        self.assertEqual(max_tokens(), 24000)

    def test_the_call_passes_its_own_budget_rather_than_omitting_it(self) -> None:
        source = (REPO_ROOT / "src" / "readability_agent.py").read_text(encoding="utf-8")
        self.assertIn("max_tokens=budget or max_tokens()", source)


class RetryTests(unittest.TestCase):
    """Budget exhaustion is the one failure the caller can fix."""

    class _Agent(readability_agent.ReadabilityChecker):
        def __init__(self, failures: int) -> None:  # no super().__init__
            self.api_key = "k"
            self.tier = "standard"
            self.failures = failures
            self.budgets: list[int | None] = []

        def _build_system_prompt(self) -> str:
            return "sys"

        def _build_user_message(self, draft_markdown: str, stats: dict) -> str:
            return "user"

        def _run_via_sdk(self, system_prompt, user_message, budget=None):
            self.budgets.append(budget)
            if len(self.budgets) <= self.failures:
                raise ValueError(
                    "Model claude-sonnet-5 returned no text content, "
                    "stop_reason=max_tokens, output_tokens=16000/16000."
                )
            return {"instructions_for_writer": []}

    def test_it_retries_once_at_double_the_budget(self) -> None:
        agent = self._Agent(failures=1)
        agent.generate_instructions("draft", {})
        self.assertEqual(agent.budgets, [None, max_tokens() * 2])

    def test_it_gives_up_after_one_retry(self) -> None:
        agent = self._Agent(failures=2)
        with self.assertRaises(ValueError):
            agent.generate_instructions("draft", {})
        self.assertEqual(len(agent.budgets), 2)

    def test_other_failures_are_not_retried(self) -> None:
        """Only a budget failure is worth spending a second call on."""

        class Refusing(self._Agent):
            def _run_via_sdk(self, system_prompt, user_message, budget=None):
                self.budgets.append(budget)
                raise ValueError("stop_reason=refusal.")

        agent = Refusing(failures=0)
        with self.assertRaises(ValueError):
            agent.generate_instructions("draft", {})
        self.assertEqual(len(agent.budgets), 1)


if __name__ == "__main__":
    unittest.main()
