"""Metadata Copy Agent — JVL Content Engine.

Pipeline position:
  Brief → SERP Research → Company Insight → Writer → QA → **Metadata Copy**

Purpose:
  Small downstream copy agent. Given a topic, draft, and optional brief / QA
  report, produce the final publish-support text assets (meta title, H1,
  meta description, slug, OG fields, image alt texts, excerpt).

  Deliberately narrow: text quality only. No schema design, no CMS, no
  publishing logic, no variant generation.

Auth modes (mirrors WriterAgent / QAAgent):
  1. Direct Anthropic SDK  — when ANTHROPIC_API_KEY is set
  2. Claude Agent SDK      — when running inside a Claude Code session
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

EXPECTED_KEYS = [
    "topic",
    "meta_title",
    "h1",
    "meta_description",
    "slug",
    "og_title",
    "og_description",
    "image_alt_texts",
    "excerpt",
    "notes",
    "source_inputs_used",
    "todos",
]


class MetadataCopyAgent:
    """Generates final publish-support copy for a single article."""

    def __init__(self) -> None:
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-6")
        self.repo_root = Path(__file__).parent.parent

    # ------------------------------------------------------------------
    # Prompt
    # ------------------------------------------------------------------

    def _load_file(self, path: str) -> str:
        return (self.repo_root / path).read_text(encoding="utf-8")

    def _build_system_prompt(self) -> str:
        return self._load_file("prompts/metadata_copy_agent.md")

    def _build_user_message(
        self,
        topic: str,
        draft_markdown: str,
        brief: dict | None,
        qa_report: dict | None,
        source_inputs_used: dict,
        secondary_keywords: list[str] | None = None,
    ) -> str:
        parts: list[str] = [
            f"Generate publish-support copy for topic: {topic}\n",
            "# DRAFT MARKDOWN\n\n" + draft_markdown.strip() + "\n",
        ]

        merged_secondary = list(secondary_keywords or [])
        if brief:
            for kw in brief.get("secondary_keywords", []) or []:
                if kw and kw not in merged_secondary:
                    merged_secondary.append(kw)

        if merged_secondary:
            parts.append(
                "# SECONDARY KEYWORDS (weave 1–2 naturally into meta_description "
                "where they fit — do not stuff)\n\n"
                + "\n".join(f"- {kw}" for kw in merged_secondary)
                + "\n"
            )

        if brief:
            parts.append(
                "# BRIEF (optional context — angle, audience, key questions)\n\n"
                + json.dumps(brief, indent=2, ensure_ascii=False)
                + "\n"
            )
        else:
            parts.append("# BRIEF\n\n(not provided)\n")

        if qa_report:
            slim = {
                "status": qa_report.get("status"),
                "issues": qa_report.get("issues", []),
                "severity_counts": qa_report.get("severity_counts", {}),
            }
            parts.append(
                "# QA REPORT (heed any cautions about unsupported claims)\n\n"
                + json.dumps(slim, indent=2, ensure_ascii=False)
                + "\n"
            )
        else:
            parts.append("# QA REPORT\n\n(not provided)\n")

        parts.append(
            "# SOURCE INPUTS USED (echo verbatim in source_inputs_used)\n\n"
            + json.dumps(source_inputs_used, indent=2, ensure_ascii=False)
            + "\n"
        )

        parts.append(
            f"\nTopic for the output: {topic}\n"
            "Return ONLY one flat JSON object with the exact keys specified. "
            "No markdown fences, no commentary."
        )
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # JSON extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_json(raw: str) -> dict:
        raw = raw.strip()
        raw = re.sub(r"^```(?:json)?\s*\n?", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\n?```\s*$", "", raw, flags=re.MULTILINE)
        raw = raw.strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            raw = match.group(0)
        return json.loads(raw)

    @staticmethod
    def _trim_to_limit(text: str, limit: int, min_length: int = 100) -> str:
        """Trim text to at most `limit` chars at a clean sentence or word boundary.

        Never appends an ellipsis or any other truncation marker — the result
        must look like a deliberate, complete fragment. Prefers ending at a
        sentence boundary; falls back to the last word boundary; ensures the
        result does not end on a dangling preposition or punctuation.
        """
        if len(text) <= limit:
            return text
        candidate = text[:limit].rstrip()
        # Prefer sentence boundary if it leaves enough content.
        dot_pos = max(candidate.rfind(". "), candidate.rfind("? "), candidate.rfind("! "))
        if dot_pos >= min_length:
            return candidate[: dot_pos + 1].rstrip()
        # Otherwise cut at the last whole word and remove trailing punctuation.
        space_pos = candidate.rfind(" ")
        if space_pos > 0:
            trimmed = candidate[:space_pos].rstrip(" .,;:—-")
            # Ensure we don't end on a stop word that leaves the line dangling.
            dangling = {"a", "an", "the", "and", "or", "but", "to", "of", "for", "with", "in", "on", "at"}
            words = trimmed.split()
            while words and words[-1].lower() in dangling:
                words.pop()
            trimmed = " ".join(words).rstrip(" .,;:—-")
            if trimmed and not trimmed.endswith((".", "!", "?")):
                trimmed += "."
            return trimmed
        return candidate

    @classmethod
    def _enforce_limits(cls, out: dict) -> dict:
        """Hard-enforce character limits as a deterministic post-processing step.

        The model reliably overshoots meta_description and occasionally h1.
        This mirrors the QA agent's _normalize() pattern: make the final value
        a pure function of content, not a guess. No ellipsis is ever appended —
        meta_description must read as a complete, polished fragment.
        """
        md = out.get("meta_description", "")
        if len(md) > 150:
            trimmed = cls._trim_to_limit(md, 150)
            print(
                f"Metadata Copy Agent enforcing meta_description limit: "
                f"{len(md)} → {len(trimmed)} chars",
                file=sys.stderr,
            )
            out["meta_description"] = trimmed

        h1 = out.get("h1", "")
        if len(h1) > 70:
            trimmed = cls._trim_to_limit(h1, 68)
            print(
                f"Metadata Copy Agent enforcing h1 limit: "
                f"{len(h1)} → {len(trimmed)} chars",
                file=sys.stderr,
            )
            out["h1"] = trimmed

        return out

    @staticmethod
    def _sanity_check(out: dict) -> list[str]:
        warnings: list[str] = []
        if len(out.get("meta_title", "")) > 60:
            warnings.append("meta_title exceeds 60 chars")
        if len(out.get("h1", "")) > 70:
            warnings.append("h1 exceeds 70 chars")
        md = out.get("meta_description", "")
        if not (120 <= len(md) <= 155):
            warnings.append(f"meta_description length {len(md)} outside 120–155")
        slug = out.get("slug", "")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
            warnings.append("slug not lowercase-hyphen-ascii")
        alts = out.get("image_alt_texts") or []
        if not (3 <= len(alts) <= 5):
            warnings.append(f"image_alt_texts count {len(alts)} outside 3–5")
        return warnings

    # ------------------------------------------------------------------
    # Auth mode 1: direct Anthropic SDK
    # ------------------------------------------------------------------

    def _run_via_sdk(self, system_prompt: str, user_message: str) -> dict:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        response = client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = next(
            (block.text for block in response.content if block.type == "text"), ""
        )
        if not raw:
            raise ValueError("Model returned no text content.")
        return self._extract_json(raw)

    # ------------------------------------------------------------------
    # Auth mode 2: Claude Agent SDK
    # ------------------------------------------------------------------

    def _run_via_agent_sdk(self, system_prompt: str, user_message: str) -> dict:
        import anyio
        from claude_code_sdk import (
            AssistantMessage,
            ClaudeCodeOptions,
            ResultMessage,
            TextBlock,
            query,
        )

        result_text: list[str] = []
        assistant_text: list[str] = []

        async def _run() -> None:
            try:
                async for message in query(
                    prompt=user_message,
                    options=ClaudeCodeOptions(
                        system_prompt=system_prompt,
                        allowed_tools=[],
                        model=self.model,
                        max_turns=1,
                    ),
                ):
                    if isinstance(message, ResultMessage):
                        result_text.append(message.result or "")
                    elif isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                assistant_text.append(block.text)
            except Exception as exc:
                if result_text or assistant_text:
                    print(
                        f"SDK warning (non-fatal, have content): {exc}",
                        file=sys.stderr,
                    )
                else:
                    raise

        anyio.run(_run)

        raw = "\n".join(result_text).strip() or "\n".join(assistant_text).strip()
        if not raw:
            raise ValueError("Agent SDK returned no content.")
        return self._extract_json(raw)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(
        self,
        topic: str,
        draft_markdown: str,
        brief: dict | None = None,
        qa_report: dict | None = None,
        source_inputs_used: dict | None = None,
        secondary_keywords: list[str] | None = None,
    ) -> dict:
        if not draft_markdown or not draft_markdown.strip():
            raise ValueError("draft_markdown is required and cannot be empty.")

        source_inputs_used = source_inputs_used or {
            "draft": None,
            "brief": None,
            "qa_report": None,
        }

        system_prompt = self._build_system_prompt()
        user_message = self._build_user_message(
            topic=topic,
            draft_markdown=draft_markdown,
            brief=brief,
            qa_report=qa_report,
            source_inputs_used=source_inputs_used,
            secondary_keywords=secondary_keywords,
        )

        if self.api_key:
            print(
                f"Metadata Copy Agent auth: Anthropic SDK (model: {self.model})",
                file=sys.stderr,
            )
            out = self._run_via_sdk(system_prompt, user_message)
        else:
            print(
                f"Metadata Copy Agent auth: Claude Agent SDK (model: {self.model})",
                file=sys.stderr,
            )
            out = self._run_via_agent_sdk(system_prompt, user_message)

        # Stamp echoed fields and ensure expected keys exist.
        out.setdefault("topic", topic)
        out.setdefault("source_inputs_used", source_inputs_used)
        out.setdefault("notes", [])
        out.setdefault("todos", [])
        out.setdefault("image_alt_texts", [])

        for key in EXPECTED_KEYS:
            out.setdefault(key, "" if key not in {"image_alt_texts", "notes", "todos"} else [])

        # Hard limits — deterministic post-processing, never throws.
        out = self._enforce_limits(out)

        # Soft sanity check — never throws, just logs.
        warnings = self._sanity_check(out)
        for w in warnings:
            print(f"Metadata Copy Agent sanity warning: {w}", file=sys.stderr)

        return out
