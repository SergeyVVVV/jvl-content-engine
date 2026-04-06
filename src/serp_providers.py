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
from abc import ABC, abstractmethod


class SerpProvider(ABC):
    """Minimal interface for SERP retrieval."""

    @abstractmethod
    def search(
        self,
        keyword: str,
        country: str = "us",
        language: str = "en",
        top_n: int = 5,
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
        top_n: int = 5,
    ) -> list[dict]:
        return []

    def fetch_page(self, url: str) -> str:
        return ""


class SerpApiProvider(SerpProvider):
    """Live SERP provider using SerpAPI (https://serpapi.com).

    Requires:
      - SERPAPI_KEY env var set to a valid key
      - `requests` package installed (pip install requests)
    """

    _BASE_URL = "https://serpapi.com/search.json"
    _PAGE_FETCH_TIMEOUT = 15
    _SEARCH_TIMEOUT = 15
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
        top_n: int = 5,
    ) -> list[dict]:
        """Call SerpAPI and return top_n organic results."""
        params = {
            "q": keyword,
            "gl": country.lower(),
            "hl": language.lower(),
            "num": top_n,
            "api_key": self.api_key,
            "engine": "google",
        }
        try:
            resp = self._requests.get(
                self._BASE_URL, params=params, timeout=self._SEARCH_TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
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
            print(f"SerpAPI search failed: {exc}", file=sys.stderr)
            return []

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
