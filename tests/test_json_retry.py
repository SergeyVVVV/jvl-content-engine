"""A dropped comma should cost one call, not a pipeline step.

Two runs in a row lost their entire prose-revision pass to a single malformed
reply — "Expecting ',' delimiter: line 51 column 6" — and the same call, made by
hand afterwards against the same draft, returned valid JSON on the first try
(stop_reason=end_turn, 19,092 tokens of a 24,000 budget). Nothing was wrong
except that nobody asked twice.

The Writer already retried and was the only agent that did. Ten others parsed
once and gave up. The loop now lives in llm_client, so there is one
implementation rather than eleven chances for them to drift apart.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src import llm_client  # noqa: E402

GOOD = '{"ok": true}'
BAD = '{"ok": true,}'


def parse(raw: str) -> dict:
    return json.loads(raw)


class RetryTests(unittest.TestCase):
    def test_a_first_reply_that_parses_costs_one_call(self) -> None:
        with mock.patch.object(llm_client, "chat", return_value=GOOD) as chat:
            self.assertEqual(llm_client.chat_json("s", "u", parse), {"ok": True})
        self.assertEqual(chat.call_count, 1)

    def test_a_malformed_reply_is_asked_again(self) -> None:
        with mock.patch.object(llm_client, "chat", side_effect=[BAD, GOOD]) as chat:
            self.assertEqual(llm_client.chat_json("s", "u", parse), {"ok": True})
        self.assertEqual(chat.call_count, 2)

    def test_it_gives_up_after_the_attempt_budget(self) -> None:
        with mock.patch.object(llm_client, "chat", return_value=BAD) as chat:
            with self.assertRaises(ValueError) as caught:
                llm_client.chat_json("s", "u", parse, attempts=3, label="Readability")
        self.assertEqual(chat.call_count, 3)
        self.assertIn("Readability", str(caught.exception))
        self.assertIn("3 replies in a row", str(caught.exception))

    def test_the_retry_says_what_broke_instead_of_repeating_itself(self) -> None:
        """Re-rolling the same words is a worse bet than naming the fault."""
        seen: list[str] = []

        def fake(system, user, **kw):
            seen.append(user)
            return GOOD if len(seen) > 1 else BAD

        with mock.patch.object(llm_client, "chat", side_effect=fake):
            llm_client.chat_json("s", "original request", parse)

        self.assertEqual(seen[0], "original request")
        self.assertIn("original request", seen[1])
        self.assertIn("COULD NOT BE PARSED", seen[1])
        self.assertIn("trailing comma", seen[1])  # the parser's own words

    def test_a_value_error_from_the_parser_also_retries(self) -> None:
        """Schema extraction raises ValueError, not only JSONDecodeError."""
        calls = {"n": 0}

        def picky(raw: str) -> dict:
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("no JSON object found in reply")
            return {"ok": True}

        with mock.patch.object(llm_client, "chat", return_value=GOOD) as chat:
            self.assertEqual(llm_client.chat_json("s", "u", picky), {"ok": True})
        self.assertEqual(chat.call_count, 2)

    def test_the_budget_and_tier_reach_the_call(self) -> None:
        with mock.patch.object(llm_client, "chat", return_value=GOOD) as chat:
            llm_client.chat_json("s", "u", parse, max_tokens=24000, tier="heavy")
        self.assertEqual(chat.call_args.kwargs["max_tokens"], 24000)
        self.assertEqual(chat.call_args.kwargs["tier"], "heavy")


class CoverageTests(unittest.TestCase):
    """Every agent, not just the one that broke."""

    AGENTS = [
        "article_diagnostic_agent",
        "company_insight_agent",
        "faq_agent",
        "metadata_copy_agent",
        "qa_agent",
        "readability_agent",
        "seo_structure_agent",
        "serp_research_agent",
        "visual_agent",
        "writer_agent",
    ]

    def test_no_agent_parses_a_reply_without_a_retry(self) -> None:
        for name in self.AGENTS:
            source = (REPO_ROOT / "src" / f"{name}.py").read_text(encoding="utf-8")
            block = source[source.index("def _run_via_sdk") :][:900]
            self.assertIn("chat_json", block, f"{name} still parses once")

    def test_the_writers_private_copy_is_gone(self) -> None:
        """Two implementations are two things to keep in step. There is one."""
        source = (REPO_ROOT / "src" / "writer_agent.py").read_text(encoding="utf-8")
        self.assertNotIn("Writer JSON parse failed", source)

    def test_each_agent_names_itself_in_the_log(self) -> None:
        """"Agent: reply was not valid JSON" from an unnamed step helps nobody."""
        for name in self.AGENTS:
            source = (REPO_ROOT / "src" / f"{name}.py").read_text(encoding="utf-8")
            block = source[source.index("def _run_via_sdk") :][:900]
            self.assertIn("label=", block, f"{name} retries anonymously")


class ProviderLabelTests(unittest.TestCase):
    """The log said OpenAI for two agents that call Anthropic."""

    def test_no_agent_claims_a_provider_it_does_not_use(self) -> None:
        for path in (REPO_ROOT / "src").glob("*_agent.py"):
            source = path.read_text(encoding="utf-8")
            if "OpenAI" not in source:
                continue
            self.assertNotIn(
                "auth: OpenAI", source, f"{path.name} still reports the wrong provider"
            )


if __name__ == "__main__":
    unittest.main()
