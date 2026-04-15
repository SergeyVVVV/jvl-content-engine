"""Writer Agent — JVL Content Engine.

Pipeline position:
  Brief Agent → SERP Research Agent → Company Insight Agent → Writer Agent

Purpose:
  Given an article brief (required) plus optional SERP research and company
  insight, generate a structured first-draft article grounded in JVL knowledge
  files. Outputs a validated JSON dict matching schemas/article_draft_schema.json
  — plus an assembled markdown string ready to save as a .md file.

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


# Knowledge files injected into the Writer Agent's system prompt.
# Ordered most-specific-first so the model encounters hard constraints early.
_KNOWLEDGE_FILES: list[tuple[str, str]] = [
    ("product_echo_home.md", "PRODUCT FACTS — use ONLY these facts about the JVL ECHO product"),
    ("persona_echo_home.md", "TARGET PERSONA — Mark & Linda Reynolds"),
    ("brand_voice.md", "BRAND VOICE AND TONE RULES"),
    ("positioning_uvp.md", "POSITIONING AND UVP PILLARS"),
    ("claims_constraints.md", "ALLOWED AND FORBIDDEN CLAIMS"),
    ("internal_links.md", "INTERNAL LINK TARGETS"),
]


class WriterAgent:
    """Generates a structured first-draft article from upstream pipeline inputs.

    Outputs a validated JSON dict plus an assembled markdown string.
    All factual claims are grounded in knowledge files and upstream inputs.
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
        prompt = self._load_file("prompts/writer_agent.md")
        schema = self._load_file("schemas/article_draft_schema.json")

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

# KNOWLEDGE BASE — YOUR ONLY SOURCE OF TRUTH FOR JVL FACTS

Everything you write about JVL, its products, brand, and persona must come from
the sections below. Do not introduce product specs, comparisons, stories, or
proof points not present here.
If a JVL fact is missing, write `TODO: source not confirmed` inline.

{knowledge_block}

---

# LLM OUTPUT SCHEMA

Your response must be a single valid JSON object with these fields:

{{
  "h1": "string",
  "intro": "string (markdown, 2–4 paragraphs, no heading)",
  "sections": [
    {{
      "level": "h2 or h3",
      "heading": "string",
      "body_markdown": "string (markdown prose, at least 2–3 paragraphs)"
    }}
  ],
  "internal_links_used": ["string"],
  "claims_to_verify": ["string"],
  "todos": ["string"]
}}

CRITICAL OUTPUT RULES:
- Output ONLY the raw JSON object. No markdown fences. No preamble. No commentary.
- The JSON must be parseable by json.loads() with no pre-processing.
- h1 must be specific and publication-ready — not a placeholder.
- intro must be real prose, minimum 2 paragraphs.
- sections must cover all required_sections from the brief (except FAQ).
- Each body_markdown must be substantive real content — not filler.
- claims_to_verify must list every claim not 100% confirmed by source inputs.
  Write ["none identified"] only if truly none require verification.
- Never invent product specs, dimensions, game counts, warranty, pricing."""

    def _build_user_message(
        self,
        topic: str,
        brief: dict,
        serp_context: str,
        insight_context: str,
        seo_structure_context: str = "",
    ) -> str:
        brief_block = (
            f"# ARTICLE BRIEF\n\n{json.dumps(brief, indent=2, ensure_ascii=False)}"
            if brief
            else "# ARTICLE BRIEF\n\n(no brief provided — write from topic and knowledge base)"
        )

        serp_block = (
            f"\n# SERP RESEARCH — COMPETITOR PATTERNS AND CONTENT GAPS\n"
            f"# Use this to avoid repeating what competitors already cover well\n"
            f"# and to exploit identified content gaps. Do not treat this as a\n"
            f"# source of JVL facts.\n\n{serp_context}\n"
            if serp_context
            else ""
        )

        insight_block = (
            f"\n# COMPANY INSIGHT — JVL-SPECIFIC ANGLES AND CONSTRAINTS\n"
            f"# Use the angles, product facts, and injection points provided here.\n"
            f"# Respect the forbidden claims and risks listed. Do not embellish.\n\n"
            f"{insight_context}\n"
            if insight_context
            else ""
        )

        seo_block = (
            f"\n# SEO OUTLINE — FOLLOW THIS STRUCTURE\n"
            f"# Use the H1, headings, and section order provided below.\n"
            f"# The FAQ section will be produced by a separate agent — write a placeholder.\n\n"
            f"{seo_structure_context}\n"
            if seo_structure_context
            else ""
        )

        return (
            f"Write a complete first-draft article for the following topic.\n\n"
            f"Topic: {topic}\n\n"
            f"{brief_block}"
            f"{serp_block}"
            f"{insight_block}"
            f"{seo_block}"
            "\nReturn only a valid JSON object. No markdown fences, no commentary."
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
        """Validate the LLM output has the expected shape."""
        required = {"h1", "intro", "sections", "internal_links_used", "claims_to_verify"}
        missing = required - set(result.keys())
        if missing:
            print(
                f"Schema validation WARNING: missing fields: {missing}",
                file=sys.stderr,
            )
            print("Output was saved anyway — review the warnings above.", file=sys.stderr)
        else:
            print("Schema validation: PASSED", file=sys.stderr)

    # ------------------------------------------------------------------
    # Markdown assembly
    # ------------------------------------------------------------------

    @staticmethod
    def assemble_markdown(result: dict) -> str:
        """Assemble h1 + intro + sections into a single markdown string."""
        lines: list[str] = []

        h1 = result.get("h1", "").strip()
        if h1:
            lines.append(f"# {h1}")
            lines.append("")

        intro = result.get("intro", "").strip()
        if intro:
            lines.append(intro)
            lines.append("")

        for section in result.get("sections", []):
            level = section.get("level", "h2")
            heading = section.get("heading", "").strip()
            body = section.get("body_markdown", "").strip()

            prefix = "##" if level == "h2" else "###"
            if heading:
                lines.append(f"{prefix} {heading}")
                lines.append("")
            if body:
                lines.append(body)
                lines.append("")

        # Append claims-to-verify and todos as a review block
        claims = result.get("claims_to_verify", [])
        todos = result.get("todos", [])

        if claims or todos:
            lines.append("---")
            lines.append("")

        if claims and claims != ["none identified"]:
            lines.append("## Claims to Verify Before Publishing")
            lines.append("")
            for claim in claims:
                lines.append(f"- {claim}")
            lines.append("")

        if todos:
            lines.append("## Open TODOs for Human Review")
            lines.append("")
            for todo in todos:
                lines.append(f"- {todo}")
            lines.append("")

        return "\n".join(lines).strip()

    # ------------------------------------------------------------------
    # Auth mode 1: direct Anthropic SDK
    # ------------------------------------------------------------------

    def _run_via_sdk(self, system_prompt: str, user_message: str) -> dict:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        response = client.messages.create(
            model=self.model,
            max_tokens=8192,
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
        import time
        import anyio
        from claude_code_sdk import (
            AssistantMessage,
            ClaudeCodeOptions,
            ResultMessage,
            TextBlock,
            query,
        )

        # The Writer Agent generates a large response; rate_limit_event can fire
        # before content arrives. Retry up to 3 times with backoff.
        max_attempts = 3
        for attempt in range(max_attempts):
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
                    # If we already have usable content, treat as non-fatal warning.
                    if result_text or assistant_text:
                        print(
                            f"SDK warning (non-fatal, have content): {exc}",
                            file=sys.stderr,
                        )
                    else:
                        raise

            try:
                anyio.run(_run)
            except Exception as exc:
                is_rate_limit = "rate_limit" in str(exc).lower()
                if is_rate_limit and attempt < max_attempts - 1:
                    wait = [30, 60, 120][attempt]
                    print(
                        f"  Rate limit (attempt {attempt + 1}/{max_attempts}) — "
                        f"retrying in {wait}s…",
                        file=sys.stderr,
                    )
                    time.sleep(wait)
                    continue
                raise

            # Prefer ResultMessage; fall back to assembled AssistantMessage text.
            raw = "\n".join(result_text).strip()
            if not raw:
                raw = "\n".join(assistant_text).strip()

            if raw:
                try:
                    return self._extract_json(raw)
                except (json.JSONDecodeError, ValueError) as parse_exc:
                    # Truncated JSON — rate_limit interrupted mid-stream.
                    if attempt < max_attempts - 1:
                        wait = [30, 60, 120][attempt]
                        print(
                            f"  Truncated JSON (attempt {attempt + 1}) — "
                            f"retrying in {wait}s…",
                            file=sys.stderr,
                        )
                        time.sleep(wait)
                        continue
                    raise

            # No content — retry if attempts remain.
            if attempt < max_attempts - 1:
                wait = [30, 60, 120][attempt]
                print(
                    f"  No content returned (attempt {attempt + 1}) — "
                    f"retrying in {wait}s…",
                    file=sys.stderr,
                )
                time.sleep(wait)

        raise ValueError("Agent SDK returned no content after all retries.")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(
        self,
        topic: str,
        brief: dict | None = None,
        serp_context: str = "",
        insight_context: str = "",
        seo_structure_context: str = "",
    ) -> dict:
        """Run the Writer Agent and return the raw LLM output dict.

        Args:
            topic:                 Article topic (plain text).
            brief:                 Optional brief dict from Brief Agent.
            serp_context:          Optional pre-formatted SERP summary string.
            insight_context:       Optional pre-formatted company insight summary string.
            seo_structure_context: Optional SEO outline JSON string from SEO Structure Agent.

        Returns:
            Dict with keys: h1, intro, sections, internal_links_used,
            claims_to_verify, todos.
        """
        print("Writer Agent: loading knowledge files...", file=sys.stderr)

        system_prompt = self._build_system_prompt()
        user_message = self._build_user_message(
            topic=topic,
            brief=brief or {},
            serp_context=serp_context,
            insight_context=insight_context,
            seo_structure_context=seo_structure_context,
        )

        if self.api_key:
            print(f"Auth: Anthropic SDK (model: {self.model})", file=sys.stderr)
            result = self._run_via_sdk(system_prompt, user_message)
        else:
            print(f"Auth: Claude Agent SDK (model: {self.model})", file=sys.stderr)
            result = self._run_via_agent_sdk(system_prompt, user_message)

        self._validate(result)
        return result
