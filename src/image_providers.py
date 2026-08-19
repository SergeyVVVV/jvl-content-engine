"""Image providers for the Visual Agent — JVL Content Engine.

Two providers:
  MockImageProvider  — returns None (no API calls); used when OPENAI_API_KEY is absent.
  DalleProvider      — generates images via DALL-E 3 (requires OPENAI_API_KEY).

Factory:
  get_image_provider() → DalleProvider if key set, else MockImageProvider.

Shared utility:
  download_image(url, dest) → downloads any image URL to a local path.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

class MockImageProvider:
    """No-op provider. Returns None for every generate() call."""

    def generate(self, prompt: str, size: str) -> str | None:
        print("  [mock] Image generation skipped (no OPENAI_API_KEY).", file=sys.stderr)
        return None


class DalleProvider:
    """Generates images via OpenAI DALL-E 3."""

    def __init__(self) -> None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError("OPENAI_API_KEY is required for DalleProvider.")
        import openai
        self.client = openai.OpenAI(api_key=api_key)

    def generate(self, prompt: str, size: str) -> str | None:
        """Generate an image and return its temporary URL.

        Args:
            prompt: DALL-E 3 generation prompt.
            size:   "1792x1024" for hero, "1024x1024" for inline.

        Returns:
            Temporary image URL string, or None on failure.
        """
        try:
            response = self.client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size=size,
                quality="standard",
                n=1,
            )
            return response.data[0].url
        except Exception as exc:
            print(f"  DALL-E 3 generation failed: {exc}", file=sys.stderr)
            return None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_image_provider() -> MockImageProvider | DalleProvider:
    """Return DalleProvider if OPENAI_API_KEY is set, else MockImageProvider."""
    if os.environ.get("OPENAI_API_KEY"):
        print("Image provider: DALL-E 3 (OpenAI)", file=sys.stderr)
        return DalleProvider()
    print("Image provider: mock (set OPENAI_API_KEY for real generation)", file=sys.stderr)
    return MockImageProvider()


# ---------------------------------------------------------------------------
# Shared download utility
# ---------------------------------------------------------------------------

def download_image(url: str, dest: Path) -> Path:
    """Download an image from url and save it to dest.

    Args:
        url:  HTTP(S) URL of the image.
        dest: Local destination path (parent directories created automatically).

    Returns:
        The dest path after successful download.

    Raises:
        requests.HTTPError: On non-2xx response.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, timeout=30, stream=True)
    response.raise_for_status()
    with open(dest, "wb") as fh:
        for chunk in response.iter_content(chunk_size=8192):
            fh.write(chunk)
    return dest
