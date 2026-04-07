"""Company Insight Agent — JVL Content Engine.

Pipeline position:
  Brief Agent → SERP Research Agent → Company Insight Agent → Writer Agent

Purpose:
  Given an article topic and brief, read internal knowledge files and surface
  the JVL-specific insight layer that competitors cannot copy. Outputs a
  structured package for the Writer Agent.

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


# Knowledge files loaded into the Company Insight Agent's context.
# Order matters: most specific product/persona facts first.
_KNOWLEDGE_FILES: list[tuple[str, str]] = [
    ("product_echo_home.md", "PRODUCT FACTS — use only these facts about the JVL ECHO product"),
    ("persona_echo_home.md", "TARGET PERSONA — Mark & Linda Reynolds"),
    ("brand_voice.md", "BRAND VOICE AND TONE RULES"),
    ("positioning_uvp.md", "POSITIONING AND UVP PILLARS"),
    ("claims_constraints.md", "ALLOWED AND FORBIDDEN CLAIMS"),
    ("internal_links.md", "INTERNAL LINK TARGETS"),
]


class CompanyInsightAgent:
    """Extracts JVL-specific insight for a given topic from internal knowledge files.

    Outputs a validated JSON dict matching schemas/company_insight_schema.json.
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
        prompt = self._load_file("prompts/company_insight_agent.md")
        schema = self._load_file("schemas/company_insight_schema.json")

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

Everything you output must be grounded in the sections below.
Do not introduce facts, specs, comparisons, stories, or proof points not present here.
If a fact is missing, write "TODO: source not confirmed" as the value.
If a claim needs business input, write "TODO: requires business confirmation".

{knowledge_block}

---

# OUTPUT SCHEMA

Your response must be a single valid JSON object matching this schema exactly:

{schema}

CRITICAL OUTPUT RULES:
- Output ONLY the raw JSON object. No markdown. No code fences. No preamble. No commentary.
- The JSON must be parseable by json.loads() with no pre-processing.
- All required fields must be present.
- Never invent product specs, dimensions, pricing, game titles, or warranty details.
- Never invent customer stories, founder anecdotes, or company history.
- Never use "best", "#1", or "leading" without grounded evidence.
- Mark anything missing as TODO: source not confirmed or TODO: requires business confirmation."""

    def _build_user_message(
        self,
        topic: str,
        brief: dict,
        extra_context: str,
    ) -> str:
        brief_summary = json.dumps(brief, indent=2, ensure_ascii=False) if brief else "{}"
        context_block = (
            f"\n# SERP CONTEXT — FOR EMPHASIS AND PRIORITISATION ONLY\n"
            f"# This tells you which content gaps and opportunities matter most for this topic.\n"
            f"# It does NOT add JVL facts. All JVL facts must come from the KNOWLEDGE BASE above.\n"
            f"# Do not treat anything in this block as a factual claim about JVL or its products.\n\n"
            f"{extra_context}\n"
            if extra_context
            else ""
        )
        return (
            f"Extract company insights for the following topic and brief.\n\n"
            f"Topic: {topic}\n"
            f"{context_block}"
            f"\nArticle brief:\n{brief_summary}\n\n"
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
        schema = json.loads(self._load_file("schemas/company_insight_schema.json"))
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
        extra_context: str = "",
    ) -> dict:
        """Run the Company Insight Agent and return a validated insight package.

        Args:
            topic: Article topic (plain text description).
            brief: Optional brief dict from Brief Agent output.
            extra_context: Optional free-text context (e.g. SERP research summary).

        Returns:
            Validated dict matching company_insight_schema.json.
        """
        print("Company Insight Agent: loading knowledge files...", file=sys.stderr)

        system_prompt = self._build_system_prompt()
        user_message = self._build_user_message(topic, brief or {}, extra_context)

        if self.api_key:
            print(f"Auth: Anthropic SDK (model: {self.model})", file=sys.stderr)
            result = self._run_via_sdk(system_prompt, user_message)
        else:
            print(f"Auth: Claude Agent SDK (model: {self.model})", file=sys.stderr)
            result = self._run_via_agent_sdk(system_prompt, user_message)

        self._validate(result)
        return result
