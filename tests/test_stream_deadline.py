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


def factory_for(*streams: FakeStream):
    """A client factory handing out one client per attempt.

    It records the `timeout` each attempt was built with, which is how the
    shared-budget behaviour is observed: later attempts must be given less.
    """
    made: list[dict] = []
    queue = list(streams)

    def factory(**kwargs):
        made.append(kwargs)
        stream = queue.pop(0) if len(queue) > 1 else queue[0]
        return FakeClient(stream)

    factory.made = made  # type: ignore[attr-defined]
    return factory


class ExplodingStream(FakeStream):
    """A stream whose transport dies part-way through, as a dropped TLS read does."""

    def __init__(self, after: int = 1, burn: float = 0.0) -> None:
        super().__init__(chunk_delay=0.0, chunks=10_000)
        self.after, self.burn = after, burn

    def __iter__(self):
        for _ in range(self.after):
            self.consumed += 1
            yield object()
        time.sleep(self.burn)
        raise ConnectionError("connection reset by peer")


class DeadlineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = os.environ.pop("ANTHROPIC_STREAM_DEADLINE", None)

    def tearDown(self) -> None:
        os.environ.pop("ANTHROPIC_STREAM_DEADLINE", None)
        if self._saved is not None:
            os.environ["ANTHROPIC_STREAM_DEADLINE"] = self._saved

    def test_a_trickling_stream_is_abandoned(self) -> None:
        os.environ["ANTHROPIC_STREAM_DEADLINE"] = "0.05"
        with self.assertRaises(StreamDeadlineExceeded):
            _stream_within_deadline({}, "k", factory_for(FakeStream(chunk_delay=0.01)))

    def test_the_error_says_why_the_read_timeout_did_not_save_us(self) -> None:
        os.environ["ANTHROPIC_STREAM_DEADLINE"] = "0.05"
        try:
            _stream_within_deadline({}, "k", factory_for(FakeStream(chunk_delay=0.01)))
        except StreamDeadlineExceeded as exc:
            self.assertIn("Chunks kept", str(exc))
            self.assertIn("ANTHROPIC_STREAM_DEADLINE", str(exc))

    def test_a_stream_that_finishes_in_time_returns_its_message(self) -> None:
        factory = factory_for(FakeStream(chunk_delay=0.0, chunks=5))
        self.assertEqual(_stream_within_deadline({}, "k", factory), "finished")

    def test_it_is_a_timeout_error_so_callers_can_treat_it_as_one(self) -> None:
        self.assertTrue(issubclass(StreamDeadlineExceeded, TimeoutError))

    def test_the_ceiling_is_longer_than_the_read_timeout_but_not_by_much(self) -> None:
        # It has to allow a real 32000-token generation, and stop well short of
        # the thirty-five minutes that prompted it.
        self.assertGreater(stream_deadline(), default_timeout())
        self.assertLess(stream_deadline(), 20 * 60)

    def test_retries_share_one_budget_instead_of_resetting_the_clock(self) -> None:
        """The 75-minute hang, in miniature.

        The old code let the SDK retry, and each retry started a fresh clock. A
        run spent 75 minutes inside a nominally 900-second call and gave up on a
        readability rewrite it had already paid for. Every attempt now draws on
        the same budget.
        """
        os.environ["ANTHROPIC_STREAM_DEADLINE"] = "0.3"
        factory = factory_for(ExplodingStream())
        started = time.monotonic()
        with self.assertRaises(StreamDeadlineExceeded):
            _stream_within_deadline({}, "k", factory)
        self.assertLess(time.monotonic() - started, 2.0)

    def test_each_attempt_is_clipped_to_what_is_left_of_the_budget(self) -> None:
        """A silent socket must not outlive the ceiling waiting on a read."""
        os.environ["ANTHROPIC_STREAM_DEADLINE"] = "5"
        # Each attempt burns real time, so the budget visibly shrinks.
        factory = factory_for(ExplodingStream(burn=0.2))
        with self.assertRaises(StreamDeadlineExceeded):
            _stream_within_deadline({}, "k", factory)
        timeouts = [call["timeout"] for call in factory.made]
        self.assertGreaterEqual(len(timeouts), 2)
        self.assertTrue(all(t <= 5 for t in timeouts), timeouts)
        self.assertLess(timeouts[-1], timeouts[0], timeouts)

    def test_the_sdk_is_never_allowed_to_retry_on_this_path(self) -> None:
        """SDK retries are per-attempt and reset the clock. Ours do not."""
        factory = factory_for(FakeStream(chunk_delay=0.0, chunks=2))
        _stream_within_deadline({}, "k", factory)
        self.assertEqual([call["max_retries"] for call in factory.made], [0])

    def test_a_transport_failure_is_retried_rather_than_surfaced(self) -> None:
        """A dropped connection with budget left should be tried again."""
        os.environ["ANTHROPIC_STREAM_DEADLINE"] = "10"
        factory = factory_for(ExplodingStream(), FakeStream(chunk_delay=0.0, chunks=2))
        self.assertEqual(_stream_within_deadline({}, "k", factory), "finished")
        self.assertEqual(len(factory.made), 2)

    def test_env_overrides_and_nonsense_falls_back(self) -> None:
        os.environ["ANTHROPIC_STREAM_DEADLINE"] = "42"
        self.assertEqual(stream_deadline(), 42.0)
        os.environ["ANTHROPIC_STREAM_DEADLINE"] = "eventually"
        self.assertEqual(stream_deadline(), 900.0)


class DraftPersistenceTests(unittest.TestCase):
    """The Writer's output must land on disk before anything else runs.

    It used to be held in memory through readability, images, the FAQ and the
    sources block, and written only at the end. A run hung in the readability
    rewrite for 75 minutes; the draft it had already generated was nowhere, and
    --resume — built for exactly this — had nothing to resume from.
    """

    def test_the_draft_is_written_before_the_readability_step(self) -> None:
        source = (REPO_ROOT / "src" / "orchestrator.py").read_text(encoding="utf-8")
        write = source.index("raw_md_path.write_text(draft_markdown")
        readability = source.index('yield _event(steps, "Readability Checker", "running")')
        self.assertLess(write, readability)

    def test_the_raw_writer_output_is_kept_too(self) -> None:
        """Markdown alone loses the companion fields a rerun would want."""
        source = (REPO_ROOT / "src" / "orchestrator.py").read_text(encoding="utf-8")
        self.assertIn('f"{topic_slug}.raw.json"', source)


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
