"""Tests for the OpenAI wrapper's failure reporting and the Writer's budget.

Run: python3 -m unittest discover -s tests
No network: the response objects are stand-ins shaped like the SDK's.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.llm_client import empty_response_error, resolve_model  # noqa: E402
from src.writer_agent import _DEFAULT_MAX_TOKENS, _max_tokens  # noqa: E402


def response(finish="length", completion=8192, reasoning=8192):
    return SimpleNamespace(
        choices=[SimpleNamespace(finish_reason=finish)],
        usage=SimpleNamespace(
            completion_tokens=completion,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=reasoning),
        ),
    )


class EmptyResponseErrorTests(unittest.TestCase):
    def test_names_the_model_and_the_budget_that_ran_out(self) -> None:
        msg = empty_response_error(response(), "gpt-5", 8192)
        self.assertIn("gpt-5", msg)
        self.assertIn("finish_reason=length", msg)
        self.assertIn("completion_tokens=8192/8192", msg)
        self.assertIn("reasoning_tokens=8192", msg)

    def test_says_what_to_change_when_the_budget_ran_out(self) -> None:
        msg = empty_response_error(response(), "gpt-5", 8192)
        self.assertIn("raise max_tokens above 8192", msg)
        self.assertIn("OPENAI_REASONING_EFFORT", msg)

    def test_does_not_blame_the_budget_for_other_finish_reasons(self) -> None:
        msg = empty_response_error(response(finish="content_filter"), "gpt-5", 8192)
        self.assertIn("finish_reason=content_filter", msg)
        self.assertNotIn("raise max_tokens", msg)

    def test_survives_a_response_carrying_no_usage(self) -> None:
        bare = SimpleNamespace(choices=[SimpleNamespace(finish_reason=None)], usage=None)
        self.assertIn("returned no text content", empty_response_error(bare, "gpt-5", 4096))


class WriterBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = os.environ.pop("WRITER_MAX_TOKENS", None)

    def tearDown(self) -> None:
        os.environ.pop("WRITER_MAX_TOKENS", None)
        if self._saved is not None:
            os.environ["WRITER_MAX_TOKENS"] = self._saved

    def test_default_leaves_room_for_reasoning_and_a_full_draft(self) -> None:
        self.assertEqual(_max_tokens(), _DEFAULT_MAX_TOKENS)
        self.assertGreater(_DEFAULT_MAX_TOKENS, 8192)

    def test_env_override_wins(self) -> None:
        os.environ["WRITER_MAX_TOKENS"] = "12000"
        self.assertEqual(_max_tokens(), 12000)

    def test_nonsense_override_falls_back_instead_of_crashing_the_run(self) -> None:
        for bad in ("plenty", "0", "-5"):
            os.environ["WRITER_MAX_TOKENS"] = bad
            self.assertEqual(_max_tokens(), _DEFAULT_MAX_TOKENS, bad)


class ModelTierTests(unittest.TestCase):
    def test_writer_runs_on_the_heavy_tier_by_default(self) -> None:
        os.environ.pop("OPENAI_MODEL_HEAVY", None)
        self.assertEqual(resolve_model("heavy"), "gpt-5")
