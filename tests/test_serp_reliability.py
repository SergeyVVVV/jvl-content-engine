"""The SERP call is now the one every planning step depends on.

Moving it first made it load-bearing. A run then lost it to a fifteen-second
read timeout, fell through to a default word target and a default section
allowance, wrote the article to both, and reported the fact in one line in the
middle of the log:

    SerpAPI search failed: Read timed out. (read timeout=15)
      serp_status: mock

Nothing in the run summary said the measurement was invented. Two changes: the
call gets a timeout and retries proportionate to what losing it costs, and a
run that fell back says so where the caller will see it.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.serp_providers import SerpApiProvider  # noqa: E402


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


PAYLOAD = {"organic_results": [{"title": "t", "link": "u", "snippet": "s"}]}


def provider(get):
    p = SerpApiProvider.__new__(SerpApiProvider)
    p.api_key = "x"
    p._requests = mock.Mock(get=get)
    return p


class TimeoutTests(unittest.TestCase):
    def test_the_search_waits_longer_than_a_page_fetch(self) -> None:
        """A blocked page costs a word count. A lost search costs the step."""
        self.assertGreater(
            SerpApiProvider._SEARCH_TIMEOUT, SerpApiProvider._PAGE_FETCH_TIMEOUT
        )

    def test_it_is_long_enough_for_a_live_google_query(self) -> None:
        self.assertGreaterEqual(SerpApiProvider._SEARCH_TIMEOUT, 60)


class RetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._sleep = mock.patch("src.serp_providers.time.sleep").start()
        self.addCleanup(mock.patch.stopall)

    def test_a_transient_failure_is_retried(self) -> None:
        get = mock.Mock(side_effect=[TimeoutError("read timed out"), FakeResp(PAYLOAD)])
        results = provider(get).search("k")
        self.assertEqual(get.call_count, 2)
        self.assertEqual(len(results), 1)

    def test_it_gives_up_after_the_attempt_budget(self) -> None:
        get = mock.Mock(side_effect=TimeoutError("read timed out"))
        self.assertEqual(provider(get).search("k"), [])
        self.assertEqual(get.call_count, SerpApiProvider._SEARCH_ATTEMPTS)

    def test_it_backs_off_rather_than_hammering(self) -> None:
        """A service that just timed out will not answer faster if asked at once."""
        get = mock.Mock(side_effect=TimeoutError("read timed out"))
        provider(get).search("k")
        waits = [c.args[0] for c in self._sleep.call_args_list]
        self.assertEqual(len(waits), SerpApiProvider._SEARCH_ATTEMPTS - 1)
        self.assertEqual(waits, sorted(waits))

    def test_a_first_attempt_that_works_costs_nothing_extra(self) -> None:
        get = mock.Mock(return_value=FakeResp(PAYLOAD))
        provider(get).search("k")
        self.assertEqual(get.call_count, 1)
        self._sleep.assert_not_called()

    def test_an_unreadable_response_is_not_retried_as_a_transport_failure(self) -> None:
        """Retrying a malformed body just spends another search credit."""
        get = mock.Mock(return_value=FakeResp("not a dict"))
        self.assertEqual(provider(get).search("k"), [])
        self.assertEqual(get.call_count, 1)


class StatusTests(unittest.TestCase):
    def test_the_run_records_whether_the_search_was_live(self) -> None:
        source = (REPO_ROOT / "src" / "orchestrator.py").read_text(encoding="utf-8")
        self.assertIn('results["serp_status"]', source)

    def test_a_fallback_is_reported_where_the_caller_looks(self) -> None:
        cli = (REPO_ROOT / "run_article.py").read_text(encoding="utf-8")
        self.assertIn("SERP     :", cli)
        self.assertIn("were defaults", cli)

    def test_a_live_search_is_not_announced(self) -> None:
        """Only the exception is worth a line; the normal case is silence."""
        cli = (REPO_ROOT / "run_article.py").read_text(encoding="utf-8")
        self.assertIn('serp_status != "live"', cli)


if __name__ == "__main__":
    unittest.main()
