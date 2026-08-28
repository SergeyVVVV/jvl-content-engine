"""SERP provider abstraction — JVL Content Engine.

Supports:
  - mock mode   : returns empty results; agent generates a clearly-labeled stub
  - serpapi mode: uses SerpAPI (https://serpapi.com) for live results

Environment variables:
  SERP_PROVIDER    = mock | serpapi   (default: mock)
  SERPAPI_KEY      = <api-key>        (required only for SERP_PROVIDER=serpapi)
  SERP_FETCH_PAGES = true | false     (default: false; fetch page content in live mode)

When SERP_PROVIDER is not set or is "mock", the SERP Research Agent runs in
offline mode and produces a clearly-labeled stub output.
"""

from __future__ import annotations

import os
import re
import sys
import time
from abc import ABC, abstractmethod


class SerpProvider(ABC):
    #: Questions from the SERP's own People-also-ask box, filled by search().
    #: Empty when the provider cannot supply them or the query has no box —
    #: which is a fact about the query, not a failure to paper over.
    _last_paa: list[str] = []

    def people_also_ask(self) -> list[str]:
        """PAA questions from the most recent search()."""
        return list(self._last_paa)


    """Minimal interface for SERP retrieval."""

    @abstractmethod
    def search(
        self,
        keyword: str,
        country: str = "us",
        language: str = "en",
        top_n: int = 10,
    ) -> list[dict]:
        """Return a list of search result dicts.

        Each dict has keys: position (int), title (str), url (str), snippet (str).
        Returns an empty list if no results are available.
        """

    @abstractmethod
    def fetch_page(self, url: str) -> str:
        """Return extracted plain text from a URL.

        Returns an empty string on failure or when not supported.
        Callers must handle empty string gracefully.
        """

    def fetch_page_detail(self, url: str) -> tuple[str, int]:
        """Return (text, full word count).

        The text is truncated so a competitor's page cannot swamp the context.
        The word count is not: it is measured before the cut, because the
        question "how long is the article ranking above us" cannot be answered
        from the first three thousand characters of it.
        """
        text = self.fetch_page(url)
        return text, len(text.split())


class MockSerpProvider(SerpProvider):
    """Offline mock provider — returns no real results.

    The SERP Research Agent receives an empty result list and sets
    serp_status='mock', generating a clearly-labeled category-pattern stub.
    """

    def search(
        self,
        keyword: str,
        country: str = "us",
        language: str = "en",
        top_n: int = 10,
    ) -> list[dict]:
        return []

    def fetch_page(self, url: str) -> str:
        return ""

    def fetch_page_detail(self, url: str) -> tuple[str, int]:
        return "", 0


class SerpApiProvider(SerpProvider):
    """Live SERP provider using SerpAPI (https://serpapi.com).

    Requires:
      - SERPAPI_KEY env var set to a valid key
      - `requests` package installed (pip install requests)
    """

    _BASE_URL = "https://serpapi.com/search.json"

    #: A page that will not load in fifteen seconds is not worth waiting for —
    #: there are nine others, and one blocked fetch costs a word count, not the
    #: step.
    _PAGE_FETCH_TIMEOUT = 15

    #: The search is different: it is the only call in the step, and losing it
    #: loses the measurement every planning step below now depends on. A run
    #: timed out at fifteen seconds and the whole pipeline fell back to a
    #: default word target, with nothing in the summary to say so.
    #:
    #: SerpAPI itself is doing a live Google query, so seconds of latency are
    #: normal and a slow one is not a broken one.
    _SEARCH_TIMEOUT = 60

    #: Transient failures are worth another go for the same reason: this call is
    #: not one of ten, it is the one. Retried with a short backoff, because a
    #: service that just timed out will not answer faster if asked immediately.
    _SEARCH_ATTEMPTS = 3
    _SEARCH_BACKOFF = 2.0

    _MAX_PAGE_CHARS = 3000  # limit per-page text to avoid overloading context

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        try:
            import requests as _r
            self._requests = _r
        except ImportError as exc:
            raise ImportError(
                "'requests' package is required for live SERP mode. "
                "Install it with: pip install requests"
            ) from exc

    def search(
        self,
        keyword: str,
        country: str = "us",
        language: str = "en",
        top_n: int = 10,
    ) -> list[dict]:
        """Call SerpAPI and return top_n organic results.

        Also records the SERP's own People-also-ask questions, readable through
        `people_also_ask()`.
        """
        params = {
            "q": keyword,
            "gl": country.lower(),
            "hl": language.lower(),
            "num": top_n,
            "api_key": self.api_key,
            "engine": "google",
        }
        data = None
        for attempt in range(1, self._SEARCH_ATTEMPTS + 1):
            try:
                resp = self._requests.get(
                    self._BASE_URL, params=params, timeout=self._SEARCH_TIMEOUT
                )
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as exc:
                if attempt == self._SEARCH_ATTEMPTS:
                    print(
                        f"SerpAPI search failed after {attempt} attempts: {exc}",
                        file=sys.stderr,
                    )
                    return []
                wait = self._SEARCH_BACKOFF * attempt
                print(
                    f"SerpAPI search attempt {attempt}/{self._SEARCH_ATTEMPTS} "
                    f"failed ({exc}); retrying in {wait:.0f}s.",
                    file=sys.stderr,
                )
                time.sleep(wait)

        try:
            # Google's own "People also ask", when the query has one. The brief
            # used to supply these as guesses, written before anyone had looked
            # at the SERP, and the SERP agent was asked to check guesses against
            # what ranks. These are the real questions.
            self._last_paa = [
                q.get("question", "")
                for q in (data.get("related_questions") or [])
                if q.get("question")
            ]
            results = []
            for i, item in enumerate(
                data.get("organic_results", [])[:top_n], start=1
            ):
                results.append(
                    {
                        "position": i,
                        "title": item.get("title", ""),
                        "url": item.get("link", ""),
                        "snippet": item.get("snippet", ""),
                    }
                )
            return results
        except Exception as exc:
            print(f"SerpAPI response could not be read: {exc}", file=sys.stderr)
            return []

    def fetch_page_detail(self, url: str) -> tuple[str, int]:
        """Return (truncated text, full word count of the page)."""
        self._last_word_count = 0
        text = self.fetch_page(url)
        return text, self._last_word_count

    def fetch_page(self, url: str) -> str:
        """Fetch a URL and return plain text (basic HTML stripping)."""
        try:
            resp = self._requests.get(
                url,
                timeout=self._PAGE_FETCH_TIMEOUT,
                headers={"User-Agent": "Mozilla/5.0 (compatible; JVLBot/1.0)"},
            )
            resp.raise_for_status()
            html = resp.text
            # Strip style and script blocks first
            html = re.sub(
                r"<style[^>]*>.*?</style>",
                " ",
                html,
                flags=re.DOTALL | re.IGNORECASE,
            )
            html = re.sub(
                r"<script[^>]*>.*?</script>",
                " ",
                html,
                flags=re.DOTALL | re.IGNORECASE,
            )
            # Strip remaining tags
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()
            self._last_word_count = len(text.split())
            return text[: self._MAX_PAGE_CHARS]
        except Exception as exc:
            print(f"fetch_page failed for {url}: {exc}", file=sys.stderr)
            return ""


def get_provider() -> SerpProvider:
    """Factory: return the configured SERP provider based on env vars.

    Reads SERP_PROVIDER env var (default: "mock").
    Falls back to MockSerpProvider if live provider cannot be initialised.
    """
    mode = os.environ.get("SERP_PROVIDER", "mock").lower().strip()

    if mode == "serpapi":
        key = os.environ.get("SERPAPI_KEY", "").strip()
        if not key:
            print(
                "Warning: SERP_PROVIDER=serpapi but SERPAPI_KEY is not set. "
                "Falling back to mock mode.",
                file=sys.stderr,
            )
            return MockSerpProvider()
        try:
            provider = SerpApiProvider(key)
            print("SERP provider: SerpAPI (live mode)", file=sys.stderr)
            return provider
        except ImportError as exc:
            print(f"Warning: {exc} — falling back to mock mode.", file=sys.stderr)
            return MockSerpProvider()

    print("SERP provider: Mock (offline mode)", file=sys.stderr)
    return MockSerpProvider()
