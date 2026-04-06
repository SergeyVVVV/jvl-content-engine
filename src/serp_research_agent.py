"""SERP / Competitor Research Agent — JVL Content Engine.

Pipeline position:
  Brief Agent → SERP Research Agent → Company Insight Agent → Writer Agent

Purpose:
  Given a primary keyword and article brief, collect competitive intelligence
  from top-ranking articles and return a structured research package for
  downstream writing.

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

# Allow both `from src.serp_research_agent import ...` (from repo root)
# and `python src/serp_research_agent.py` (direct execution).
_SRC_DIR = Path(__file__).parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from serp_providers import MockSerpProvider, SerpProvider, get_provider  # noqa: E402


# Knowledge files injected into the SERP agent's context.
# These inform analysis of content direction and search intent without
# loading product specs (those belong to Company Insight Agent).
_KNOWLEDGE_FILES: list[tuple[str, str]] = [
    ("keyword_intent.md", "KEYWORD INTENT — CATEGORIES AND PRIORITY SIGNALS"),
    ("content_directions.md", "CONTENT DIRECTIONS — EDITORIAL THEMES AND ARTICLE TYPES"),
    ("seo_rules.md", "SEO RULES — WHAT GOOGLE EVALUATES IN 2026"),
]


class SerpResearchAgent:
    """Generates a structured competitive research package for a keyword and topic.

    Outputs a validated JSON dict matching schemas/serp_research_schema.json.
    Works in mock mode (no live SERP) or live mode (SerpAPI configured).
    """

    def __init__(self, provider: SerpProvider | None = None) -> None:
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-6")
        self.repo_root = Path(__file__).parent.parent
        self.provider = provider or get_provider()

    # ------------------------------------------------------------------
    # File loading
    # ------------------------------------------------------------------

    def _load_file(self, path: str) -> str:
        return (self.repo_root / path).read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_system_prompt(
        self,
        serp_results: list[dict],
        serp_status: str,
    ) -> str:
        prompt = self._load_file("prompts/serp_research_agent.md")
        schema = self._load_file("schemas/serp_research_schema.json")

        knowledge_sections: list[str] = []
        for filename, label in _KNOWLEDGE_FILES:
            filepath = f"knowledge/{filename}"
            try:
                content = self._load_file(filepath)
                knowledge_sections.append(f"## {label}\n\n{content}")
            except FileNotFoundError:
                print(f"Warning: {filepath} not found, skipping.", file=sys.stderr)

        knowledge_block = "\n\n---\n\n".join(knowledge_sections)

        if serp_results:
            serp_block = json.dumps(serp_results, indent=2, ensure_ascii=False)
        else:
            serp_block = "[] — No live SERP results. Generate a mock/pattern-based stub."

        return f"""{prompt}

---

# SERP STATUS: {serp_status.upper()}

# SERP RESULTS

{serp_block}

---

# CONTENT KNOWLEDGE

{knowledge_block}

---

# OUTPUT SCHEMA

Your response must be a single valid JSON object matching this schema exactly:

{schema}

CRITICAL OUTPUT RULES:
- Output ONLY the raw JSON object. No markdown. No code fences. No preamble. No commentary.
- The JSON must be parseable by json.loads() with no pre-processing.
- "serp_status" MUST be set to "{serp_status}".
- In mock mode: set "top_results" to [] and prefix every analysis string with "[MOCK]".
- Never invent competitor names, domain names, URLs, or positions.
- Never invent statistics, rankings, or factual competitor claims.
- All required fields must be present."""

    def _build_user_message(
        self,
        primary_keyword: str,
        topic: str,
        brief: dict,
        country: str,
        language: str,
        top_n: int,
        paa_questions: list[str],
    ) -> str:
        brief_summary = json.dumps(brief, indent=2, ensure_ascii=False) if brief else "{}"
        paa_block = (
            "\n".join(f"- {q}" for q in paa_questions)
            if paa_questions
            else "None provided."
        )
        return (
            f"Run competitor research for the following input.\n\n"
            f"Primary keyword: {primary_keyword}\n"
            f"Topic: {topic}\n"
            f"Country: {country}\n"
            f"Language: {language}\n"
            f"Top N: {top_n}\n\n"
            f"PAA questions already available from Brief Agent:\n{paa_block}\n\n"
            f"Article brief:\n{brief_summary}\n\n"
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
        schema = json.loads(self._load_file("schemas/serp_research_schema.json"))
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
        primary_keyword: str,
        topic: str,
        brief: dict | None = None,
        country: str = "us",
        language: str = "en",
        top_n: int = 5,
        paa_questions: list[str] | None = None,
    ) -> dict:
        """Run the SERP Research Agent and return a validated research package.

        Args:
            primary_keyword: The SEO keyword to research.
            topic: Article topic (plain text description).
            brief: Optional brief dict from Brief Agent output.
            country: Target country code (default: "us").
            language: Target language code (default: "en").
            top_n: Number of top results to fetch (default: 5).
            paa_questions: Optional list of PAA questions from the brief.

        Returns:
            Validated dict matching serp_research_schema.json.
        """
        if paa_questions is None:
            paa_questions = []

        # Step 1: Fetch SERP results (live or empty for mock)
        print(
            f"SERP Research Agent: fetching via {type(self.provider).__name__}...",
            file=sys.stderr,
        )
        serp_results = self.provider.search(primary_keyword, country, language, top_n)

        # Step 2: Determine status and optionally fetch page content
        if serp_results:
            serp_status = "live"
            if os.environ.get("SERP_FETCH_PAGES", "false").lower() == "true":
                for result in serp_results:
                    url = result.get("url", "")
                    if url:
                        print(f"  Fetching page: {url}", file=sys.stderr)
                        result["page_text"] = self.provider.fetch_page(url)
        else:
            serp_status = "mock"

        print(f"  serp_status: {serp_status}", file=sys.stderr)

        # Step 3: Build prompts and call LLM
        system_prompt = self._build_system_prompt(serp_results, serp_status)
        user_message = self._build_user_message(
            primary_keyword, topic, brief or {}, country, language, top_n, paa_questions
        )

        if self.api_key:
            print(f"Auth: Anthropic SDK (model: {self.model})", file=sys.stderr)
            result = self._run_via_sdk(system_prompt, user_message)
        else:
            print(f"Auth: Claude Agent SDK (model: {self.model})", file=sys.stderr)
            result = self._run_via_agent_sdk(system_prompt, user_message)

        # Step 4: Enforce serp_status from our determination (not the model's guess)
        result["serp_status"] = serp_status

        # Step 5: Validate and return
        self._validate(result)
        return result
