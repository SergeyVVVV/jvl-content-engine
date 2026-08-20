"""A stream that trickles must still end.

#43 gave the client a 300-second timeout and moved every agent onto the
streaming path. Those two changes fight each other: the HTTP timeout is a *read*
timeout — the longest gap between two chunks — so a stream that keeps sending
something never trips it. A Writer call ran thirty-five minutes before anything
stopped it, and the run died with a traceback that discarded twelve paid
searches and five completed steps.

Two fixes, tested here: a wall-clock ceiling on the whole streaming call, and a
Writer failure that reports instead of crashing.
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.llm_client import (  # noqa: E402
    StreamDeadlineExceeded,
    _stream_within_deadline,
    default_timeout,
    stream_deadline,
)


class FakeStream:
    """A stream that keeps producing chunks forever, slowly."""

    def __init__(self, chunk_delay: float = 0.01, chunks: int = 10_000) -> None:
        self.chunk_delay, self.chunks = chunk_delay, chunks
        self.consumed = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        for _ in range(self.chunks):
            time.sleep(self.chunk_delay)
            self.consumed += 1
            yield object()

    def get_final_message(self):
        return "finished"


class FakeClient:
    def __init__(self, stream: FakeStream) -> None:
        self._stream = stream
        self.messages = self

    def stream(self, **kwargs):
        return self._stream


class DeadlineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = os.environ.pop("ANTHROPIC_STREAM_DEADLINE", None)

    def tearDown(self) -> None:
        os.environ.pop("ANTHROPIC_STREAM_DEADLINE", None)
        if self._saved is not None:
            os.environ["ANTHROPIC_STREAM_DEADLINE"] = self._saved

    def test_a_trickling_stream_is_abandoned(self) -> None:
        os.environ["ANTHROPIC_STREAM_DEADLINE"] = "0.05"
        client = FakeClient(FakeStream(chunk_delay=0.01))
        with self.assertRaises(StreamDeadlineExceeded):
            _stream_within_deadline(client, {})

    def test_the_error_says_why_the_read_timeout_did_not_save_us(self) -> None:
        os.environ["ANTHROPIC_STREAM_DEADLINE"] = "0.05"
        client = FakeClient(FakeStream(chunk_delay=0.01))
        try:
            _stream_within_deadline(client, {})
        except StreamDeadlineExceeded as exc:
            self.assertIn("Chunks kept", str(exc))
            self.assertIn("ANTHROPIC_STREAM_DEADLINE", str(exc))

    def test_a_stream_that_finishes_in_time_returns_its_message(self) -> None:
        client = FakeClient(FakeStream(chunk_delay=0.0, chunks=5))
        self.assertEqual(_stream_within_deadline(client, {}), "finished")

    def test_it_is_a_timeout_error_so_callers_can_treat_it_as_one(self) -> None:
        self.assertTrue(issubclass(StreamDeadlineExceeded, TimeoutError))

    def test_the_ceiling_is_longer_than_the_read_timeout_but_not_by_much(self) -> None:
        # It has to allow a real 32000-token generation, and stop well short of
        # the thirty-five minutes that prompted it.
        self.assertGreater(stream_deadline(), default_timeout())
        self.assertLess(stream_deadline(), 20 * 60)

    def test_env_overrides_and_nonsense_falls_back(self) -> None:
        os.environ["ANTHROPIC_STREAM_DEADLINE"] = "42"
        self.assertEqual(stream_deadline(), 42.0)
        os.environ["ANTHROPIC_STREAM_DEADLINE"] = "eventually"
        self.assertEqual(stream_deadline(), 600.0)


class WriterFailureTests(unittest.TestCase):
    """A Writer failure must report, not throw away the run.

    Everything expensive happens before the Writer: the research step spends
    real money on searches, and four more steps run after it.
    """

    def test_the_writer_step_is_wrapped(self) -> None:
        source = (REPO_ROOT / "src" / "orchestrator.py").read_text(encoding="utf-8")
        writer_call = source.index("writer_agent = WriterAgent()")
        after = source[writer_call : writer_call + 1200]
        self.assertIn("except Exception as exc:", after)
        self.assertIn('results["failed_step"] = "Writer"', after)

    def test_the_failure_event_is_terminal_and_labelled(self) -> None:
        source = (REPO_ROOT / "src" / "orchestrator.py").read_text(encoding="utf-8")
        self.assertIn('"status": "failed", "results": results', source)

    def test_the_cli_names_what_survived(self) -> None:
        cli = (REPO_ROOT / "run_article.py").read_text(encoding="utf-8")
        for key in ("facts_path", "serp_path", "brief_path"):
            self.assertIn(key, cli)


if __name__ == "__main__":
    unittest.main()
