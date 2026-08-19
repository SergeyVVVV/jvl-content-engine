"""Thin Anthropic wrapper used by all content-engine agents.

Tiers (env-configurable):
  ANTHROPIC_MODEL_HEAVY    — complex generation  (default: claude-opus-5)
  ANTHROPIC_MODEL_STANDARD — balanced tasks      (default: claude-sonnet-5)
  ANTHROPIC_MODEL_LIGHT    — cheap/fast tasks    (default: claude-haiku-4-5)

Three shape differences from the OpenAI wrapper this replaces, none of which
the agents have to know about — they still call chat(system, user, ...):

* The system prompt is a top-level parameter, not a message with role="system".
* Thinking depth is output_config.effort, not a token budget. These models
  reject budget_tokens outright, and thinking is on by default.
* The response is a list of content blocks. Thinking arrives as its own block
  type and must be skipped — concatenating it would corrupt the JSON every
  agent parses.
"""

from __future__ import annotations

import os

from anthropic import Anthropic

#: Tier → default model. Opus for the Writer and QA, Sonnet through the middle
#: of the pipeline, Haiku for the metadata copy pass.
_DEFAULT_MODELS = {
    "heavy": "claude-opus-5",
    "standard": "claude-sonnet-5",
    "light": "claude-haiku-4-5",
}

#: Output budget when a caller does not ask for a specific one.
#:
#: A ceiling, not a spend: the API bills what a call actually uses, so a
#: generous one costs nothing. It has to cover the thinking as well as the
#: answer — both come out of this same allowance — and at 4096 a deep think
#: consumed the whole budget before a single token of prose.
#: Overridable with ANTHROPIC_MAX_TOKENS.
_DEFAULT_MAX_TOKENS = 16000

#: At or above this, stream.
#:
#: A non-streaming call has to deliver its whole response inside one timeout
#: window, and while it waits there is nothing to see: the socket stays open and
#: a wedged request is indistinguishable from a slow one. Streaming resets the
#: read timeout on every chunk, so a live generation is never mistaken for a
#: hang and a dead one trips the timeout instead of holding the line.
#:
#: The old threshold was 16000 and the comparison was strictly greater, which
#: put the default budget — also 16000 — on the non-streaming path. The common
#: call was the exposed one.
_STREAM_AT_OR_ABOVE = 8000

#: Per-request timeout in seconds, and how many times the SDK may retry.
#:
#: Without these the client runs on the SDK's own generous defaults, so a
#: request that never completes is never abandoned either. That is not
#: hypothetical: one wedged call held a nine-step pipeline for 47 minutes with
#: no output and half a second of CPU burnt, and the retries queued up behind it
#: made it worse rather than better. Bounded, the same failure costs at most
#: three windows and then says so.
#:
#: Overridable with ANTHROPIC_TIMEOUT and ANTHROPIC_MAX_RETRIES.
_DEFAULT_TIMEOUT = 300.0
_DEFAULT_MAX_RETRIES = 2

_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")


def resolve_model(tier: str = "standard") -> str:
    """Return the configured model id for a tier."""
    default = _DEFAULT_MODELS.get(tier, _DEFAULT_MODELS["standard"])
    return os.environ.get(f"ANTHROPIC_MODEL_{tier.upper()}", default)


def default_max_tokens() -> int:
    raw = os.environ.get("ANTHROPIC_MAX_TOKENS")
    if not raw:
        return _DEFAULT_MAX_TOKENS
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_MAX_TOKENS
    return value if value > 0 else _DEFAULT_MAX_TOKENS


def default_timeout() -> float:
    """Seconds to wait on one request before giving up."""
    raw = os.environ.get("ANTHROPIC_TIMEOUT")
    if not raw:
        return _DEFAULT_TIMEOUT
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_TIMEOUT
    return value if value > 0 else _DEFAULT_TIMEOUT


def default_max_retries() -> int:
    """How many times the SDK may retry a failed request."""
    raw = os.environ.get("ANTHROPIC_MAX_RETRIES")
    if not raw:
        return _DEFAULT_MAX_RETRIES
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_MAX_RETRIES
    return value if value >= 0 else _DEFAULT_MAX_RETRIES


def resolve_effort(explicit: str | None = None) -> str | None:
    """Resolve the effort level, ignoring a value the API would reject.

    Returning None simply omits the parameter, which runs the model at its own
    default — better than failing a nine-step pipeline over a typo in a secret.
    """
    value = explicit or os.environ.get("ANTHROPIC_EFFORT")
    if not value:
        return None
    value = value.strip().lower()
    return value if value in _EFFORT_LEVELS else None


def extract_text(message: object) -> str:
    """Join the text blocks of a response, skipping thinking blocks."""
    parts = []
    for block in getattr(message, "content", None) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", "") or "")
    return "".join(parts)


def empty_response_error(message: object, model: str, max_tokens: int) -> str:
    """Explain a response that carried no usable text, using what it reports.

    Repeating the call unchanged reproduces it exactly, so the message has to
    say what to change rather than what happened.
    """
    stop = getattr(message, "stop_reason", None)
    usage = getattr(message, "usage", None)

    parts = [f"Model {model} returned no text content"]
    if stop:
        parts.append(f"stop_reason={stop}")
    if usage is not None:
        parts.append(f"output_tokens={getattr(usage, 'output_tokens', None)}/{max_tokens}")

    text = ", ".join(parts) + "."
    if stop == "max_tokens":
        text += (
            " The output budget ran out before any prose was emitted — thinking"
            " and the answer share it. Raise max_tokens above"
            f" {max_tokens}, or lower ANTHROPIC_EFFORT."
        )
    elif stop == "refusal":
        category = getattr(getattr(message, "stop_details", None), "category", None)
        text += (
            " The request was declined by the model's safety classifiers"
            + (f" (category: {category})." if category else ".")
            + " Rewording the brief is likelier to help than retrying."
        )
    return text


def chat(
    system: str,
    user: str,
    max_tokens: int | None = None,
    tier: str = "standard",
    effort: str | None = None,
) -> str:
    """Call the Messages API and return the raw text response."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY is required for llm_client.chat().")

    model = resolve_model(tier)
    max_tokens = max_tokens or default_max_tokens()
    client = Anthropic(
        api_key=api_key,
        timeout=default_timeout(),
        max_retries=default_max_retries(),
    )

    request = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    level = resolve_effort(effort)
    if level:
        request["output_config"] = {"effort": level}

    if max_tokens >= _STREAM_AT_OR_ABOVE:
        with client.messages.stream(**request) as stream:
            message = stream.get_final_message()
    else:
        message = client.messages.create(**request)

    text = extract_text(message)
    if not text:
        raise ValueError(empty_response_error(message, model, max_tokens))
    return text
