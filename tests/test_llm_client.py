"""Tests for the Anthropic wrapper's failure reporting and the Writer's budget.

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

from src.llm_client import (  # noqa: E402
    _DEFAULT_MAX_RETRIES,
    _DEFAULT_TIMEOUT,
    _STREAM_AT_OR_ABOVE,
    default_max_retries,
    default_max_tokens,
    default_timeout,
    empty_response_error,
    resolve_model,
)
from src.writer_agent import _DEFAULT_MAX_TOKENS, _max_tokens  # noqa: E402


def response(stop="max_tokens", output=8192, content=()):
    """A stand-in shaped like an Anthropic Message."""
    return SimpleNamespace(
        stop_reason=stop,
        stop_details=None,
        content=list(content),
        usage=SimpleNamespace(output_tokens=output),
    )


class EmptyResponseErrorTests(unittest.TestCase):
    def test_names_the_model_and_the_budget_that_ran_out(self) -> None:
        msg = empty_response_error(response(), "claude-opus-5", 8192)
        self.assertIn("claude-opus-5", msg)
        self.assertIn("stop_reason=max_tokens", msg)
        self.assertIn("output_tokens=8192/8192", msg)

    def test_says_what_to_change_when_the_budget_ran_out(self) -> None:
        msg = empty_response_error(response(), "claude-opus-5", 8192)
        self.assertIn("max_tokens above 8192", msg)
        self.assertIn("ANTHROPIC_EFFORT", msg)

    def test_explains_a_refusal_instead_of_blaming_the_budget(self) -> None:
        refused = response(stop="refusal")
        refused.stop_details = SimpleNamespace(category="cyber")
        msg = empty_response_error(refused, "claude-opus-5", 8192)
        self.assertIn("declined", msg)
        self.assertIn("cyber", msg)
        self.assertNotIn("raise max_tokens", msg)

    def test_survives_a_response_carrying_no_usage(self) -> None:
        bare = SimpleNamespace(stop_reason=None, stop_details=None, content=[], usage=None)
        self.assertIn("returned no text content", empty_response_error(bare, "claude-opus-5", 4096))


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
        os.environ.pop("ANTHROPIC_MODEL_HEAVY", None)
        self.assertEqual(resolve_model("heavy"), "claude-opus-5")

    def test_each_tier_maps_to_a_distinct_model(self) -> None:
        for tier in ("heavy", "standard", "light"):
            os.environ.pop(f"ANTHROPIC_MODEL_{tier.upper()}", None)
        picked = [resolve_model(t) for t in ("heavy", "standard", "light")]
        self.assertEqual(len(set(picked)), 3, picked)


class DefaultBudgetTests(unittest.TestCase):
    """Every agent now inherits one ceiling; it must clear a full reasoning pass."""

    def setUp(self) -> None:
        self._saved = os.environ.pop("ANTHROPIC_MAX_TOKENS", None)

    def tearDown(self) -> None:
        os.environ.pop("ANTHROPIC_MAX_TOKENS", None)
        if self._saved is not None:
            os.environ["ANTHROPIC_MAX_TOKENS"] = self._saved

    def test_default_clears_the_budget_that_starved_the_brief_agent(self) -> None:
        from src.llm_client import default_max_tokens

        # The Brief Agent died at 4096 with reasoning_tokens=4096 — the whole
        # allowance spent thinking, nothing left to answer with.
        self.assertGreater(default_max_tokens(), 4096)

    def test_env_override_wins(self) -> None:
        from src.llm_client import default_max_tokens

        os.environ["ANTHROPIC_MAX_TOKENS"] = "24000"
        self.assertEqual(default_max_tokens(), 24000)

    def test_nonsense_override_falls_back(self) -> None:
        from src.llm_client import _DEFAULT_MAX_TOKENS, default_max_tokens

        for bad in ("lots", "0", "-1"):
            os.environ["ANTHROPIC_MAX_TOKENS"] = bad
            self.assertEqual(default_max_tokens(), _DEFAULT_MAX_TOKENS, bad)

    def test_no_agent_pins_a_budget_that_cannot_fit_reasoning(self) -> None:
        # A hardcoded 4096/8192 at a call site would silently opt that agent
        # out of the shared ceiling, which is how this failure spread.
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent / "src"
        pinned = [
            p.name for p in root.glob("*.py")
            if re.search(r"max_tokens=(?:4096|8192)\b", p.read_text(encoding="utf-8"))
        ]
        self.assertEqual(pinned, [])


class TimeoutAndRetryTests(unittest.TestCase):
    """A wedged request must end by itself.

    Without a timeout the client inherits the SDK's generous defaults, so a
    request that never completes is never abandoned: one held a nine-step
    pipeline for 47 minutes at 0% CPU, and the retries queued behind it made it
    worse. These pin the bound and the env escape hatch.
    """

    def setUp(self) -> None:
        self._saved = {
            name: os.environ.pop(name, None)
            for name in ("ANTHROPIC_TIMEOUT", "ANTHROPIC_MAX_RETRIES")
        }

    def tearDown(self) -> None:
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def test_a_request_cannot_wait_forever(self) -> None:
        # A read timeout, not a ceiling: it has to outlast a legitimate
        # thinking pause — 152 seconds was measured mid-generation — while
        # still noticing a connection that has actually died.
        self.assertGreater(default_timeout(), 3 * 152)
        self.assertLessEqual(default_timeout(), 900)

    def test_retries_are_bounded(self) -> None:
        self.assertLessEqual(default_max_retries(), 3)

    def test_the_wall_clock_is_what_bounds_a_call_not_the_retries(self) -> None:
        # Retries multiply the read timeout, so that product is not the real
        # bound. The stream deadline is, and it applies per attempt regardless.
        from src.llm_client import stream_deadline

        self.assertLess(stream_deadline(), 20 * 60)
        self.assertGreater(stream_deadline(), default_timeout())

    def test_env_overrides_win(self) -> None:
        os.environ["ANTHROPIC_TIMEOUT"] = "45"
        os.environ["ANTHROPIC_MAX_RETRIES"] = "0"
        self.assertEqual(default_timeout(), 45.0)
        self.assertEqual(default_max_retries(), 0)

    def test_nonsense_overrides_fall_back_instead_of_crashing_the_run(self) -> None:
        os.environ["ANTHROPIC_TIMEOUT"] = "soon"
        os.environ["ANTHROPIC_MAX_RETRIES"] = "-1"
        self.assertEqual(default_timeout(), _DEFAULT_TIMEOUT)
        self.assertEqual(default_max_retries(), _DEFAULT_MAX_RETRIES)


class StreamingThresholdTests(unittest.TestCase):
    def test_the_default_budget_streams(self) -> None:
        # The hang landed on a call at exactly the default budget, which the old
        # strictly-greater comparison sent down the non-streaming path.
        self.assertGreaterEqual(default_max_tokens(), _STREAM_AT_OR_ABOVE)

    def test_the_writers_budget_streams(self) -> None:
        self.assertGreaterEqual(_DEFAULT_MAX_TOKENS, _STREAM_AT_OR_ABOVE)
