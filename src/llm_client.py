"""Thin OpenAI wrapper used by all content-engine agents.

Configuration is read from Streamlit secrets first, then the environment, so
the same code works from `.env` locally and from the secrets editor on
Streamlit Cloud. Reading only `os.environ` would depend on the platform
exporting secrets as environment variables, which the Streamlit library does
not do — a dependency worth not having in the one place that makes every agent
work.

Settings:
  OPENAI_API_KEY        — required
  OPENAI_MODEL_HEAVY    — complex generation  (default: gpt-5)
  OPENAI_MODEL_STANDARD — balanced tasks      (default: gpt-5-mini)
  OPENAI_MODEL_LIGHT    — cheap/fast tasks    (default: gpt-5-nano)
"""

from __future__ import annotations

import os

from openai import OpenAI


def setting(name: str, default: str | None = None) -> str | None:
    """Read a setting from Streamlit secrets, then the environment."""
    try:
        import streamlit as st

        value = st.secrets.get(name)
        if value:
            return str(value)
    except Exception:
        # No Streamlit, no secrets file, or running outside a session.
        pass
    return os.environ.get(name, default)


def resolve_model(tier: str = "standard") -> str:
    """Return the configured OpenAI model id for a tier."""
    models = {
        "heavy":    setting("OPENAI_MODEL_HEAVY", "gpt-5"),
        "standard": setting("OPENAI_MODEL_STANDARD", "gpt-5-mini"),
        "light":    setting("OPENAI_MODEL_LIGHT", "gpt-5-nano"),
    }
    return models.get(tier, models["standard"])


def chat(system: str, user: str, max_tokens: int = 4096, tier: str = "standard") -> str:
    """Call OpenAI chat completions and return the raw text response."""
    api_key = setting("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY is not set. Add it to Streamlit secrets "
            "(App settings → Secrets) or to the environment / .env file."
        )
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
