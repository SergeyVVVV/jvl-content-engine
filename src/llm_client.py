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


#: Completion budget when a caller does not ask for a specific one.
#:
#: This is a ceiling, not a spend: the API bills what the call actually uses,
#: so a generous one costs nothing. It has to cover the reasoning as well as
#: the answer — on a gpt-5 tier both come out of the same allowance, and at
#: 4096 a high reasoning effort consumed the whole budget before a single
#: token of prose, which the API reports as an empty message rather than an
#: error. Overridable with OPENAI_MAX_TOKENS.
_DEFAULT_MAX_TOKENS = 16000


def default_max_tokens() -> int:
    raw = os.environ.get("OPENAI_MAX_TOKENS")
    if not raw:
        return _DEFAULT_MAX_TOKENS
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_MAX_TOKENS
    return value if value > 0 else _DEFAULT_MAX_TOKENS


def empty_response_error(response: object, model: str, max_tokens: int) -> str:
    """Explain an empty completion using what the response itself reports.

    The gpt-5 tiers are reasoning models: their thinking is billed as
    completion tokens and drawn from the same `max_completion_tokens` budget as
    the prose. A budget large enough for the article but not for the thinking
    in front of it returns `finish_reason="length"` and an empty message — no
    error, no partial text. Repeating the call unchanged reproduces it exactly,
    so the message has to say what to change.
    """
    choice = getattr(response, "choices", [None])[0]
    finish = getattr(choice, "finish_reason", None)
    usage = getattr(response, "usage", None)
    details = getattr(usage, "completion_tokens_details", None)
    reasoning = getattr(details, "reasoning_tokens", None)

    parts = [f"Model {model} returned no text content"]
    if finish:
        parts.append(f"finish_reason={finish}")
    if usage is not None:
        spent = getattr(usage, "completion_tokens", None)
        parts.append(f"completion_tokens={spent}/{max_tokens}")
    if reasoning is not None:
        parts.append(f"reasoning_tokens={reasoning}")

    message = ", ".join(parts) + "."
    if finish == "length":
        message += (
            " The completion budget ran out before any prose was emitted"
            f" — raise max_tokens above {max_tokens}, or lower"
            " OPENAI_REASONING_EFFORT so less of it goes to thinking."
        )
    return message


def chat(
    system: str,
    user: str,
    max_tokens: int | None = None,
    tier: str = "standard",
    reasoning_effort: str | None = None,
) -> str:
    """Call OpenAI chat completions and return the raw text response.

    `reasoning_effort` is forwarded only when set, here or via
    OPENAI_REASONING_EFFORT, so the default behaviour is the model's own.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY is required for llm_client.chat().")
    model = resolve_model(tier)
    max_tokens = max_tokens or default_max_tokens()
    client = OpenAI(api_key=api_key)

    kwargs = {}
    effort = reasoning_effort or os.environ.get("OPENAI_REASONING_EFFORT")
    if effort:
        kwargs["reasoning_effort"] = effort

    response = client.chat.completions.create(
        model=model,
        max_completion_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        **kwargs,
    )
    text = response.choices[0].message.content
    if not text:
        raise ValueError(empty_response_error(response, model, max_tokens))
    return text
