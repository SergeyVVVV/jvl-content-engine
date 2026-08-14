"""FAQ Agent v1 — JVL Content Engine.

Pipeline position:
  Brief → SERP Research → Company Insight → SEO Structure → Writer →
  Readability Checker → **FAQ** → QA → Metadata

Purpose:
  Generate the FAQ block for an article. Reads the already-assembled draft
  (to avoid duplicating section content), the brief, SERP data (for PAA
  questions), and company insight (for persona hooks). Returns a validated
  JSON dict matching schemas/faq_schema.json plus a ready-to-append markdown
  block. Grounded in knowledge files — never invents specs, pricing, warranty.

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

import jsonschema


_KNOWLEDGE_FILES: list[tuple[str, str]] = [
    ("product_echo_home.md", "PRODUCT FACTS — use ONLY these facts about the JVL ECHO product"),
    ("persona_echo_home.md", "TARGET PERSONA — Mark & Linda Reynolds"),
    ("claims_constraints.md", "ALLOWED AND FORBIDDEN CLAIMS"),
    ("metadata_rules.md", "METADATA AND FAQ BLOCK REQUIREMENTS"),
    ("keyword_intent.md", "KEYWORD INTENT MAP"),
]


class FAQAgent:
    """Generates a structured FAQ block grounded in the knowledge base."""

    def __init__(self) -> None:
        self.api_key = os.environ.get("OPENAI_API_KEY")
        self.tier = "standard"
        self.model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-6")  # agent-SDK fallback only
        self.repo_root = Path(__file__).parent.parent

    # ------------------------------------------------------------------
    # File loading
    # ------------------------------------------------------------------

    def _load_file(self, path: str) -> str:
        return (self.repo_root / path).read_text(encoding="utf-8")

    def _load_schema(self) -> dict:
        return json.loads(self._load_file("schemas/faq_schema.json"))

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        prompt = self._load_file("prompts/faq_agent.md")
        schema = self._load_file("schemas/faq_schema.json")

        knowledge_sections: list[str] = []
        for filename, label in _KNOWLEDGE_FILES:
            filepath = f"knowledge/{filename}"
            try:
                content = self._load_file(filepath)
                knowledge_sections.append(f"## {label}\n\n{content}")
            except FileNotFoundError:
                print(f"Warning: {filepath} not found, skipping.", file=sys.stderr)

        knowledge_block = "\n\n---\n\n".join(knowledge_sections)

        return (
            f"{prompt}\n\n---\n\n"
            f"# KNOWLEDGE BASE — YOUR ONLY SOURCE OF TRUTH FOR JVL FACTS\n\n"
            f"{knowledge_block}\n\n---\n\n"
            f"# FAQ JSON SCHEMA\n\n{schema}\n\n"
            "CRITICAL OUTPUT RULES:\n"
            "- Output ONLY the raw JSON object. No markdown fences. No commentary.\n"
            "- At least 5 items.\n"
            "- Each answer 2–4 sentences, concrete, no marketing fluff.\n"
            "- Do not repeat questions already answered in the draft's H2/H3 sections.\n"
            "- If an answer requires unconfirmed data, write `TODO: source not confirmed`.\n"
        )

    def _build_user_message(
        self,
        topic: str,
        draft_markdown: str,
        brief: dict | None,
        serp_data: dict | None,
        insight_data: dict | None,
    ) -> str:
        parts: list[str] = [
            f"Produce the FAQ block for the article on topic: {topic}\n",
            "# CURRENT DRAFT MARKDOWN (do NOT duplicate questions already covered here)\n\n"
            + draft_markdown.strip()
            + "\n",
        ]

        if brief:
            slim_brief = {
                "primary_keyword": brief.get("primary_keyword"),
                "secondary_keywords": brief.get("secondary_keywords", []),
                "search_intent": brief.get("search_intent"),
                "funnel_stage": brief.get("funnel_stage"),
                "questions_to_answer": brief.get("questions_to_answer", []),
                "audience": brief.get("audience"),
                "product_fit": brief.get("product_fit"),
            }
            parts.append(
                "# BRIEF\n\n"
                + json.dumps(slim_brief, indent=2, ensure_ascii=False)
                + "\n"
            )

        if serp_data:
            paa_block = {
                "paa_questions": serp_data.get("paa_questions", []),
                "related_searches": serp_data.get("related_searches", []),
                "content_gaps": serp_data.get("content_gaps", []),
            }
            parts.append(
                "# SERP SIGNALS (use PAA + related searches as FAQ seeds)\n\n"
                + json.dumps(paa_block, indent=2, ensure_ascii=False)
                + "\n"
            )

        if insight_data:
            slim_insight = {
                "persona_hooks": insight_data.get("persona_hooks", []),
                "relevant_product_facts": insight_data.get("relevant_product_facts", []),
                "forbidden_claims": insight_data.get("forbidden_claims", []),
                "claims_to_verify": insight_data.get("claims_to_verify", []),
            }
            parts.append(
                "# COMPANY INSIGHT (respect forbidden claims, use persona hooks)\n\n"
                + json.dumps(slim_insight, indent=2, ensure_ascii=False)
                + "\n"
            )

        parts.append(
            "\nReturn ONLY a single valid JSON object matching the FAQ schema. "
            "No markdown fences, no commentary."
        )

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # JSON extraction and validation
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

    def _validate(self, result: dict) -> None:
        schema = self._load_schema()
        try:
            jsonschema.validate(instance=result, schema=schema)
            print("FAQ schema validation: PASSED", file=sys.stderr)
        except jsonschema.ValidationError as exc:
            print(
                f"FAQ schema validation WARNING: {exc.message}",
                file=sys.stderr,
            )

    # ------------------------------------------------------------------
    # Markdown assembly
    # ------------------------------------------------------------------

    @staticmethod
    def assemble_markdown(result: dict, heading: str = "FAQ") -> str:
        """Render the FAQ JSON into a markdown block ready to append to an article."""
        items = result.get("items") or []
        if not items:
            return ""

        lines: list[str] = [f"## {heading}", ""]
        for item in items:
            q = (item.get("question") or "").strip()
            a = (item.get("answer") or "").strip()
            if not q or not a:
                continue
            lines.append(f"### {q}")
            lines.append("")
            lines.append(a)
            lines.append("")
        from src.writer_agent import WriterAgent
        return WriterAgent._absolutize_jvl_links("\n".join(lines).strip())

    @staticmethod
    def append_to_article(draft_markdown: str, faq_markdown: str) -> str:
        """Insert the FAQ block, replacing any existing `## FAQ*` sections.

        The Writer Agent is instructed to skip FAQ, but defensively we strip
        any FAQ-like H2 sections it (or a previous update-mode revision) may
        have emitted, then insert this FAQ block before any trailing
        Claims/TODOs review block.
        """
        if not faq_markdown:
            return draft_markdown

        # Strip every existing `## FAQ*` or `## Frequently Asked Questions*`
        # section, from its H2 up to (but not including) the next H2 of the
        # same level, the trailing review block, or end-of-document.
        faq_section_re = re.compile(
            r"(?ms)^##\s+(?:FAQ|Frequently\s+Asked\s+Questions)\b.*?"
            r"(?=^##\s|\n---\s*\n+##\s+(?:Claims to Verify|Open TODOs)|\Z)"
        )
        stripped = faq_section_re.sub("", draft_markdown).rstrip() + "\n"

        marker = re.search(
            r"\n---\s*\n+##\s+(?:Claims to Verify|Open TODOs)",
            stripped,
        )
        if marker:
            head = stripped[: marker.start()].rstrip()
            tail = stripped[marker.start():]
            return f"{head}\n\n{faq_markdown}\n{tail}"

        return f"{stripped.rstrip()}\n\n{faq_markdown}\n"

    # ------------------------------------------------------------------
    # JSON-LD (schema.org FAQPage) — for AI search engines / GEO
    # ------------------------------------------------------------------

    @staticmethod
    def assemble_json_ld(
        result: dict,
        page_url: str | None = None,
        wrap_in_script_tag: bool = True,
    ) -> str:
        """Render FAQ items as schema.org FAQPage JSON-LD.

        Aimed at AI search engines (Perplexity, ChatGPT Search, Google AI
        Overviews) which use structured data to extract atomic Q/A pairs for
        citation. Not aimed at Google FAQ rich snippets — those were
        restricted to gov/health sites in August 2023.

        Args:
            result:              FAQAgent.run() output dict.
            page_url:            Optional canonical URL of the article page.
                                 Adds @id / mainEntityOfPage when provided.
            wrap_in_script_tag:  True (default) returns the ready-to-paste
                                 <script type="application/ld+json"> block.
                                 False returns raw JSON only.

        Returns:
            String — either a <script> block or raw JSON. Empty string if
            no items present.
        """
        items = result.get("items") or []
        valid_items = [
            it for it in items
            if (it.get("question") or "").strip() and (it.get("answer") or "").strip()
        ]
        if not valid_items:
            return ""

        ld: dict = {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": (it.get("question") or "").strip(),
                    "acceptedAnswer": {
                        "@type": "Answer",
                        "text": (it.get("answer") or "").strip(),
                    },
                }
                for it in valid_items
            ],
        }
        if page_url:
            ld["@id"] = f"{page_url}#faq"
            ld["mainEntityOfPage"] = {
                "@type": "WebPage",
                "@id": page_url,
            }

        raw_json = json.dumps(ld, indent=2, ensure_ascii=False)
        if not wrap_in_script_tag:
            return raw_json
        return f'<script type="application/ld+json">\n{raw_json}\n</script>'

    # ------------------------------------------------------------------
    # Auth mode 1: direct Anthropic SDK
    # ------------------------------------------------------------------

    def _run_via_sdk(self, system_prompt: str, user_message: str) -> dict:
        from src import llm_client

        raw = llm_client.chat(system_prompt, user_message, max_tokens=4096, tier=self.tier)
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
        serp_data: dict | None = None,
        insight_data: dict | None = None,
    ) -> dict:
        """Run the FAQ Agent and return the validated JSON dict.

        Args:
            topic:          Article topic (plain text).
            draft_markdown: Assembled article markdown (FAQ-free), used to
                            avoid duplicating questions already answered.
            brief:          Optional brief dict.
            serp_data:      Optional SERP data; PAA + related_searches seed
                            the FAQ question set.
            insight_data:   Optional company insight dict.

        Returns:
            Dict matching faq_schema.json (items[], optional todos[]).
        """
        print("FAQ Agent: loading knowledge files...", file=sys.stderr)

        system_prompt = self._build_system_prompt()
        user_message = self._build_user_message(
            topic=topic,
            draft_markdown=draft_markdown,
            brief=brief,
            serp_data=serp_data,
            insight_data=insight_data,
        )

        if self.api_key:
            print(f"Auth: OpenAI (tier: {self.tier})", file=sys.stderr)
            result = self._run_via_sdk(system_prompt, user_message)
        else:
            print(f"Auth: Claude Agent SDK (model: {self.model})", file=sys.stderr)
            result = self._run_via_agent_sdk(system_prompt, user_message)

        self._validate(result)
        return result
