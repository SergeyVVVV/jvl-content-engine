"""Thin OpenAI wrapper used by all content-engine agents.

Tiers (env-configurable):
  OPENAI_MODEL_HEAVY    — complex generation  (default: gpt-5)
  OPENAI_MODEL_STANDARD — balanced tasks      (default: gpt-5-mini)
  OPENAI_MODEL_LIGHT    — cheap/fast tasks    (default: gpt-5-nano)
"""

from __future__ import annotations

import os

from openai import OpenAI


def resolve_model(tier: str = "standard") -> str:
    """Return the configured OpenAI model id for a tier."""
    models = {
        "heavy":    os.environ.get("OPENAI_MODEL_HEAVY", "gpt-5"),
        "standard": os.environ.get("OPENAI_MODEL_STANDARD", "gpt-5-mini"),
        "light":    os.environ.get("OPENAI_MODEL_LIGHT", "gpt-5-nano"),
    }
    return models.get(tier, models["standard"])


def chat(system: str, user: str, max_tokens: int = 4096, tier: str = "standard") -> str:
    """Call OpenAI chat completions and return the raw text response."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY is required for llm_client.chat().")
    model = resolve_model(tier)
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        max_completion_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    text = response.choices[0].message.content
    if not text:
        raise ValueError("Model returned no text content.")
    return text
