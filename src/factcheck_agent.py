"""Factcheck Agent — JVL Content Engine.

Pipeline position:
  QA Agent → Factcheck Agent → Metadata Copy Agent

Purpose:
  Verify that every factual claim in a draft article is grounded in repository
  knowledge files. Classifies claims as grounded, unsupported, or forbidden and
  sets a publish_blocking flag when forbidden claims are present.

  Complements the QA Agent: QA reviews overall content quality and structure;
  Factcheck focuses specifically on claim grounding.

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


# Knowledge files loaded into the Factcheck Agent's context.
# All factual claims in the draft must be verifiable against these files.
_KNOWLEDGE_FILES: list[tuple[str, str]] = [
    ("product_echo_home.md",  "PRODUCT FACTS — the only allowed source for product specs"),
    ("positioning_uvp.md",    "POSITIONING AND UVP PILLARS"),
    ("claims_constraints.md", "ALLOWED AND FORBIDDEN CLAIMS — check every claim here"),
    ("brand_voice.md",        "BRAND VOICE AND TONE RULES"),
    ("persona_echo_home.md",  "TARGET PERSONA — Mark & Linda Reynolds"),
    ("internal_links.md",     "INTERNAL LINK TARGETS"),
]


class FactcheckAgent:
    """Verifies factual claims in a draft article against knowledge files.

    Outputs a validated JSON dict matching schemas/factcheck_schema.json.
    Uses only repository knowledge — no outside knowledge.
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
        prompt = self._load_file("prompts/factcheck_agent.md")
        schema = self._load_file("schemas/factcheck_schema.json")

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

Verify every factual claim solely against the sections below.
Do not bring in outside knowledge to validate or refute claims.
Treat marketing language without facts as not a claim.

{knowledge_block}

---

# OUTPUT SCHEMA

Your response must be a single valid JSON object matching this schema exactly:

{schema}

CRITICAL OUTPUT RULES:
- Output ONLY the raw JSON object. No markdown. No code fences. No preamble. No commentary.
- The JSON must be parseable by json.loads() with no pre-processing.
- grounded_claims, unsupported_claims, forbidden_claims must be arrays (may be empty).
- publish_blocking must be true if forbidden_claims is non-empty.
- Flag every spec, number, comparison, warranty, pricing, or legal statement.
- Never bring in outside knowledge to validate or refute claims."""

    def _build_user_message(self, topic: str, draft_markdown: str) -> str:
        return (
            f"Fact-check the following draft article for topic: {topic}\n\n"
            f"# DRAFT ARTICLE\n\n{draft_markdown.strip()}\n\n"
            "For every factual claim, classify it as grounded, unsupported, or forbidden "
            "using only the knowledge files in your system prompt.\n"
            "Return only a valid JSON object. No markdown, no commentary."
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

    @staticmethod
    def _normalize(result: dict) -> dict:
        """Deterministic override: publish_blocking is true iff forbidden_claims is non-empty.

        This ensures the flag is always a reliable function of the data,
        not just whatever the LLM returned.
        """
        if result.get("forbidden_claims"):
            result["publish_blocking"] = True
        result.setdefault("todos", [])
        return result

    def _validate(self, result: dict) -> None:
        schema = json.loads(self._load_file("schemas/factcheck_schema.json"))
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
        draft_markdown: str,
    ) -> dict:
        """Run the Factcheck Agent and return a validated claim report.

        Args:
            topic:          Article topic (plain text description).
            draft_markdown: Full article draft as markdown string.

        Returns:
            Validated dict matching factcheck_schema.json with fields:
            grounded_claims, unsupported_claims, forbidden_claims, todos,
            publish_blocking.
        """
        print("Factcheck Agent: loading knowledge files...", file=sys.stderr)

        system_prompt = self._build_system_prompt()
        user_message = self._build_user_message(topic, draft_markdown)

        if self.api_key:
            print(f"Auth: Anthropic SDK (model: {self.model})", file=sys.stderr)
            result = self._run_via_sdk(system_prompt, user_message)
        else:
            print(f"Auth: Claude Agent SDK (model: {self.model})", file=sys.stderr)
            result = self._run_via_agent_sdk(system_prompt, user_message)

        result = self._normalize(result)
        self._validate(result)
        return result
