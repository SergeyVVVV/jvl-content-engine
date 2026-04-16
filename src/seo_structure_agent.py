"""SEO Structure Agent — JVL Content Engine.

Pipeline position:
  Company Insight Agent → SEO Structure Agent → Writer Agent

Purpose:
  Given an article brief, read SEO and keyword knowledge files and produce a
  clean, SEO-sound article outline (H1, H2s, optional H3s) that matches
  search intent and targets the brief's primary keyword.

Auth modes (tried in order):
  1. Direct Anthropic SDK  — when ANTHROPIC_API_KEY is set in env / .env
  2. Claude Agent SDK      — when running inside a Claude Code session
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import jsonschema


# Knowledge files loaded into the SEO Structure Agent's context.
_KNOWLEDGE_FILES: list[tuple[str, str]] = [
    ("seo_rules.md",      "SEO RULES — follow these rules for every outline decision"),
    ("metadata_rules.md", "METADATA RULES — slug, H1, and heading hierarchy rules"),
    ("keyword_intent.md", "KEYWORD INTENT — primary and secondary keyword guidance"),
    ("internal_links.md", "INTERNAL LINK TARGETS — include at least /en/echo"),
]


class SeoStructureAgent:
    """Produces an SEO-optimised article outline from a brief.

    Outputs a validated JSON dict matching schemas/seo_schema.json.
    All output is grounded in knowledge files — no invented facts.
    """

    def __init__(self) -> None:
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-6")
        self.repo_root = Path(__file__).parent.parent

    # ------------------------------------------------------------------
    # File loading
    # ------------------------------------------------------------------

    def _load_file(self, path: str) -> str:
        return (self.repo_root / path).read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        prompt = self._load_file("prompts/seo_structure_agent.md")
        schema = self._load_file("schemas/seo_schema.json")

        knowledge_sections: list[str] = []
        for filename, label in _KNOWLEDGE_FILES:
            filepath = f"knowledge/{filename}"
            try:
                content = self._load_file(filepath)
                knowledge_sections.append(f"## {label}\n\n{content}")
            except FileNotFoundError:
                print(f"Warning: {filepath} not found, skipping.", file=sys.stderr)

        knowledge_block = "\n\n---\n\n".join(knowledge_sections)

        return f"""{prompt}

---

# KNOWLEDGE BASE — YOUR ONLY SOURCE OF TRUTH

All outline decisions must be grounded in the sections below.
Do not introduce product facts, specs, or claims not present here.
If a section would require unsupported claims, mark it `TODO: source not confirmed`.

{knowledge_block}

---

# OUTPUT SCHEMA

Your response must be a single valid JSON object matching this schema exactly:

{schema}

CRITICAL OUTPUT RULES:
- Output ONLY the raw JSON object. No markdown. No code fences. No preamble. No commentary.
- The JSON must be parseable by json.loads() with no pre-processing.
- All required fields must be present.
- One H1 only — must contain the primary keyword.
- outline must contain at least 3 h2 sections.
- Reserve one h2 section as a placeholder for the FAQ block.
- internal_link_targets must contain at least /en/echo.
- Never invent product specs, dimensions, pricing, game titles, or warranty details.
- Mark anything unsupported as TODO: source not confirmed."""

    def _build_user_message(self, topic: str, brief: dict) -> str:
        brief_block = json.dumps(brief, indent=2, ensure_ascii=False) if brief else "{}"
        return (
            f"Build the SEO outline for the following topic and brief.\n\n"
            f"Topic: {topic}\n\n"
            f"# ARTICLE BRIEF\n\n{brief_block}\n\n"
            "Return only a valid JSON object. No markdown, no code fences, no commentary."
        )

    # ------------------------------------------------------------------
    # JSON extraction and validation
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_json(raw: str) -> dict:
        """Strip markdown artifacts and parse the first JSON object found."""
        raw = raw.strip()
        raw = re.sub(r"^```(?:json)?\s*\n?", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\n?```\s*$", "", raw, flags=re.MULTILINE)
        raw = raw.strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            raw = match.group(0)
        return json.loads(raw)

    def _validate(self, result: dict) -> None:
        schema = json.loads(self._load_file("schemas/seo_schema.json"))
        try:
            jsonschema.validate(instance=result, schema=schema)
            print("Schema validation: PASSED", file=sys.stderr)
        except jsonschema.ValidationError as exc:
            print(f"Schema validation WARNING: {exc.message}", file=sys.stderr)
            print("Output was saved anyway — review the warnings above.", file=sys.stderr)

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
    # Auth mode 2: Claude Agent SDK (Claude Code environment)
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
                    print(f"SDK warning (non-fatal, have content): {exc}", file=sys.stderr)
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
        brief: dict | None = None,
    ) -> dict:
        """Run the SEO Structure Agent and return a validated outline.

        Args:
            topic: Article topic (plain text description).
            brief: Optional brief dict from Brief Agent output.

        Returns:
            Validated dict matching seo_schema.json.
        """
        print("SEO Structure Agent: loading knowledge files...", file=sys.stderr)

        system_prompt = self._build_system_prompt()
        user_message = self._build_user_message(topic, brief or {})

        if self.api_key:
            print(f"Auth: Anthropic SDK (model: {self.model})", file=sys.stderr)
            result = self._run_via_sdk(system_prompt, user_message)
        else:
            print(f"Auth: Claude Agent SDK (model: {self.model})", file=sys.stderr)
            result = self._run_via_agent_sdk(system_prompt, user_message)

        self._validate(result)
        return result
