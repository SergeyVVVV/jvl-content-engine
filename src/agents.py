"""Brief Agent — JVL Content Engine.

Auth modes (tried in order):
  1. Direct Anthropic SDK — when ANTHROPIC_API_KEY is set in env / .env
  2. Claude Agent SDK    — when running inside a Claude Code session
                          (no API key needed; uses Claude Code CLI auth)
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import jsonschema


# Priority-ordered knowledge files loaded into every Brief Agent call.
KNOWLEDGE_FILES: list[tuple[str, str]] = [
    ("product_echo_home.md", "PRODUCT FACTS — only use these facts about the JVL ECHO product"),
    ("persona_echo_home.md", "TARGET PERSONA"),
    ("brand_voice.md", "BRAND VOICE AND TONE RULES"),
    ("seo_rules.md", "SEO RULES"),
    ("internal_links.md", "INTERNAL LINK TARGETS"),
    ("metadata_rules.md", "METADATA RULES"),
    ("visual_style_rules.md", "VISUAL STYLE RULES"),
]


class BriefAgent:
    """Generates a structured article brief grounded in JVL repository knowledge."""

    def __init__(self) -> None:
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-6")
        self.repo_root = Path(__file__).parent.parent

    def _load_file(self, path: str) -> str:
        return (self.repo_root / path).read_text(encoding="utf-8")

    def _build_system_prompt(self) -> str:
        prompt = self._load_file("prompts/brief_agent.md")
        schema = self._load_file("schemas/brief_schema.json")

        knowledge_sections: list[str] = []
        for filename, label in KNOWLEDGE_FILES:
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

Everything you write must be grounded in the sections below.
Do not introduce facts, specs, comparisons, or claims not present here.
If a fact is missing, write "TODO: source not confirmed" as the value.

{knowledge_block}

---

# OUTPUT SCHEMA

Your response must be a single valid JSON object matching this schema:

{schema}

CRITICAL OUTPUT RULES:
- Output ONLY the raw JSON object. No markdown. No code fences. No preamble. No commentary.
- Do not wrap the output in ```json ... ``` or any other delimiters.
- The JSON must be parseable by json.loads() with no pre-processing.
- All required fields must be present.
- working_title must be a strong, specific, publication-ready article title — not a placeholder.
- questions_to_answer must contain at least 5 real questions a reader would type into Google.
- claims_to_verify must list any product claims needing business confirmation; write ["none required"] only if there are genuinely none.
- Never invent product specs, dimensions, pricing, warranty details, or comparison data."""

    def _build_user_message(self, **kwargs: str) -> str:
        return (
            f"Create an article brief for the following input.\n\n"
            f"Topic: {kwargs['topic']}\n"
            f"Primary keyword: {kwargs['primary_keyword']}\n"
            f"Content goal: {kwargs['content_goal']}\n"
            f"Funnel stage: {kwargs['funnel_stage']}\n"
            f"Audience: {kwargs['audience']}\n"
            f"Country: {kwargs['country']}\n"
            f"Language: {kwargs['language']}\n\n"
            "Return only a valid JSON object. No markdown, no code fences, no commentary."
        )

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
        schema = json.loads(self._load_file("schemas/brief_schema.json"))
        try:
            jsonschema.validate(instance=result, schema=schema)
            print("Schema validation: PASSED", file=sys.stderr)
        except jsonschema.ValidationError as exc:
            print(f"Schema validation WARNING: {exc.message}", file=sys.stderr)
            print("Output was saved anyway — review the warnings above.", file=sys.stderr)

    # ------------------------------------------------------------------
    # Auth mode 1: direct Anthropic SDK (requires ANTHROPIC_API_KEY)
    # ------------------------------------------------------------------

    def _run_via_sdk(self, system_prompt: str, user_message: str) -> dict:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        response = client.messages.create(
            model=self.model,
            max_tokens=4096,
            thinking={"type": "enabled", "budget_tokens": 4000},
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
    # Auth mode 2: Claude Agent SDK (Claude Code environment, no key needed)
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
        primary_keyword: str,
        content_goal: str,
        funnel_stage: str,
        audience: str,
        country: str,
        language: str,
    ) -> dict:
        """Run the Brief Agent and return a validated brief dict."""
        system_prompt = self._build_system_prompt()
        user_message = self._build_user_message(
            topic=topic,
            primary_keyword=primary_keyword,
            content_goal=content_goal,
            funnel_stage=funnel_stage,
            audience=audience,
            country=country,
            language=language,
        )

        if self.api_key:
            print(f"Auth: Anthropic SDK (model: {self.model})", file=sys.stderr)
            result = self._run_via_sdk(system_prompt, user_message)
        else:
            print(f"Auth: Claude Agent SDK (model: {self.model})", file=sys.stderr)
            result = self._run_via_agent_sdk(system_prompt, user_message)

        self._validate(result)
        return result
