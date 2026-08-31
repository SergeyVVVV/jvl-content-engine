"""Revises an article that already exists, and nothing else.

The readability loop used to send its faults to the Writer. The Writer's system
prompt is 12,000 words of "you produce first-draft articles from a brief", with
the brief, the outline, the SERP research and seven knowledge files attached —
and it did what the bulk of its input asked for. Measured on one draft: of 109
sentences, 2 survived a revision pass verbatim. The loop was not improving prose,
it was generating a new article each iteration and keeping the best-scoring one.

A three-line prompt with the same output contract kept 93% on the first try. So
the fix is not more instructions telling the Writer to hold still; it is not
asking a writer to edit.

This agent carries ~470 words of prompt and no knowledge base. What it must not
break is stated as a rule rather than supplied as seven thousand words of
reference — the Writer had all of it and still misused a verified figure, so
volume was never the protection.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

#: Output budget. The whole article comes back every time, so this scales with
#: the article rather than with the size of the edit.
_DEFAULT_MAX_TOKENS = 32000


def max_tokens() -> int:
    raw = os.environ.get("EDITOR_MAX_TOKENS")
    if not raw:
        return _DEFAULT_MAX_TOKENS
    try:
        value = int(raw)
    except ValueError:
        print(
            f"  EDITOR_MAX_TOKENS={raw!r} is not a number — using {_DEFAULT_MAX_TOKENS}",
            file=sys.stderr,
        )
        return _DEFAULT_MAX_TOKENS
    return value if value > 0 else _DEFAULT_MAX_TOKENS


class EditorAgent:
    """Applies named fixes to an existing article without rewriting it."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.repo_root = repo_root or Path(__file__).resolve().parent.parent
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.tier = "heavy"

    def _load_file(self, path: str) -> str:
        return (self.repo_root / path).read_text(encoding="utf-8")

    def _build_system_prompt(self) -> str:
        return self._load_file("prompts/editor_agent.md")

    @staticmethod
    def _build_user_message(article_markdown: str, feedback: str) -> str:
        return (
            "# THE ARTICLE\n\n"
            f"{article_markdown.strip()}\n\n"
            f"{feedback.strip()}\n\n"
            "Return the full article as JSON, with only the faults above fixed."
        )

    @staticmethod
    def _extract_json(raw: str) -> dict:
        raw = raw.strip()
        raw = re.sub(r"^```(?:json)?\s*\n?", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\n?```\s*$", "", raw, flags=re.MULTILINE)
        match = re.search(r"\{.*\}", raw.strip(), re.DOTALL)
        if not match:
            raise ValueError("no JSON object found in the editor's reply")
        return json.loads(match.group(0))

    @staticmethod
    def _validate(result: dict) -> None:
        if not isinstance(result.get("sections"), list) or not result["sections"]:
            raise ValueError("editor returned no sections")
        if not str(result.get("h1", "")).strip():
            raise ValueError("editor returned no h1")

    def run(self, article_markdown: str, feedback: str, previous: dict | None = None) -> dict:
        """Return the revised article in the Writer's result shape.

        Fields the editor does not produce — suggested_visuals, claims_to_verify,
        length_justification — are carried over from `previous`, because losing
        them is how a revision quietly drops what an earlier step established.
        """
        from src import llm_client

        if not self.api_key:
            raise EnvironmentError("ANTHROPIC_API_KEY is required for the Editor Agent.")

        print("Editor Agent: revising in place", file=sys.stderr)
        result = llm_client.chat_json(
            self._build_system_prompt(),
            self._build_user_message(article_markdown, feedback),
            self._extract_json,
            max_tokens=max_tokens(),
            tier=self.tier,
            label="Editor",
        )
        self._validate(result)

        carried: dict[str, Any] = dict(previous or {})
        carried.update({k: v for k, v in result.items() if v not in (None, [], "")})
        for field in ("suggested_visuals", "claims_to_verify", "length_justification",
                      "internal_links_used", "source_inputs_used"):
            if field in (previous or {}) and field not in result:
                carried[field] = previous[field]
        return carried
