"""Article Diagnostic Agent v1 — JVL Content Engine.

Pipeline position (Article Update workflow):
  SERP Research (fresh) → Company Insight (fresh) → **Article Diagnostic** →
  Writer (update mode) → Readability → FAQ → QA → Metadata

Purpose:
  Audit an existing published article against current SERP data, current
  knowledge base, and a requested scope (light / medium / heavy). Return
  a structured update plan that the Writer Agent applies surgically —
  preserving most of the original prose, fixing only what the diagnostic
  identifies as broken or stale.

Auth modes (mirrors WriterAgent / QAAgent):
  1. Anthropic (via src.llm_client) — when ANTHROPIC_API_KEY is set
  2. Claude Agent SDK      — when running inside a Claude Code session
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


_KNOWLEDGE_FILES: list[tuple[str, str]] = [
    ("product_echo_home.md", "PRODUCT FACTS — current source of truth"),
    ("persona_echo_home.md", "TARGET PERSONA — current"),
    ("brand_voice.md", "BRAND VOICE — current rules"),
    ("positioning_uvp.md", "POSITIONING AND UVP — current"),
    ("claims_constraints.md", "ALLOWED AND FORBIDDEN CLAIMS — current"),
    ("internal_links.md", "INTERNAL LINK TARGETS — current"),
]


VALID_SCOPES = {"light", "medium", "heavy"}


class ArticleDiagnosticAgent:
    """Audits an existing article and returns a scoped update plan dict."""

    def __init__(self) -> None:
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.tier = "heavy"
        self.model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")  # agent-SDK fallback only
        self.repo_root = Path(__file__).parent.parent

    def _load_file(self, path: str) -> str:
        return (self.repo_root / path).read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        prompt = self._load_file("prompts/article_diagnostic_agent.md")

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
            f"# CURRENT KNOWLEDGE BASE — THE SOURCE OF TRUTH FOR THIS AUDIT\n\n"
            f"Anything in the original article that contradicts this knowledge "
            f"base is stale and must be flagged.\n\n{knowledge_block}\n"
        )

    def _build_user_message(
        self,
        topic: str,
        original_article: str,
        scope: str,
        serp_data: dict | None,
        insight_data: dict | None,
        previous_brief: dict | None,
        secondary_keywords: list[str] | None = None,
    ) -> str:
        parts: list[str] = [
            f"Audit the following existing article for topic: {topic}\n",
            f"Requested update scope: **{scope}** — stay strictly within this scope.\n",
            "# ORIGINAL ARTICLE MARKDOWN (the live published text)\n\n"
            + original_article.strip()
            + "\n",
        ]

        if secondary_keywords:
            parts.append(
                "# SECONDARY KEYWORDS TO COVER\n\n"
                "These lower-priority keywords should be woven naturally into "
                "the updated article. If the original article does not cover "
                "any of them, flag the gap in `serp_gaps_to_close` and propose "
                "where to add coverage.\n\n"
                + "\n".join(f"- {kw}" for kw in secondary_keywords)
                + "\n"
            )

        if previous_brief:
            parts.append(
                "# ORIGINAL BRIEF (when the article was first written — for context only)\n\n"
                + json.dumps(previous_brief, indent=2, ensure_ascii=False)
                + "\n"
            )

        if serp_data:
            parts.append(
                "# FRESH SERP RESEARCH (current state of the SERP — use to find new gaps)\n\n"
                + json.dumps(serp_data, indent=2, ensure_ascii=False)
                + "\n"
            )
        else:
            parts.append("# FRESH SERP RESEARCH\n\n(not provided — note in todos)\n")

        if insight_data:
            parts.append(
                "# FRESH COMPANY INSIGHT (current angles, claims, forbidden lines)\n\n"
                + json.dumps(insight_data, indent=2, ensure_ascii=False)
                + "\n"
            )
        else:
            parts.append(
                "# FRESH COMPANY INSIGHT\n\n(not provided — note in todos)\n"
            )

        parts.append(
            "\nReturn ONLY a single valid JSON object matching the schema in "
            "the system prompt. No markdown fences, no commentary."
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

    # ------------------------------------------------------------------
    # Render diagnostic output as a Writer-facing feedback block
    # ------------------------------------------------------------------

    @staticmethod
    def format_for_writer(
        plan: dict,
        scope: str,
        secondary_keywords: list[str] | None = None,
    ) -> str:
        """Render the update plan as a structured instruction block that
        WriterAgent.run() consumes via the `revision_feedback` parameter."""
        lines: list[str] = [
            "# ARTICLE UPDATE INSTRUCTIONS (scope: " + scope + ")",
            "",
            "You are revising an EXISTING article, not writing from scratch. "
            "Preserve the prose that the diagnostic flagged as still strong. "
            "Apply only the edits listed below.",
            "",
        ]

        diag = plan.get("diagnosis", {})
        if diag.get("summary"):
            lines += ["## Diagnostic summary", "", diag["summary"], ""]

        def _bullet_block(title: str, items: list) -> None:
            items = items or []
            if items:
                lines.append(f"### {title}")
                lines.extend(f"- {x}" for x in items)
                lines.append("")

        _bullet_block("Freshness issues", diag.get("freshness_issues"))
        _bullet_block("SERP gaps to close", diag.get("serp_gaps_to_close"))
        _bullet_block("Brand alignment issues", diag.get("brand_alignment_issues"))
        _bullet_block("Experience anchor gaps", diag.get("experience_anchor_gaps"))
        _bullet_block("Structural issues", diag.get("structural_issues"))
        _bullet_block(
            "Structural enrichment gaps (lists, tables, visuals)",
            diag.get("structural_enrichment_gaps"),
        )

        preserve = plan.get("sections_to_preserve") or []
        if preserve:
            lines += ["## Sections to PRESERVE verbatim", ""]
            for p in preserve:
                lines.append(
                    f"- **{p.get('section_heading', '?')}** — {p.get('reason', '')}"
                )
            lines.append("")

        instructions = plan.get("update_instructions") or []
        if instructions:
            lines += ["## Update instructions (apply in order)", ""]
            for i, item in enumerate(instructions, 1):
                lines.append(
                    f"{i}. **{item.get('section_heading', '?')}** "
                    f"[{item.get('action', 'edit')}] — {item.get('guidance', '')}"
                )
                excerpt = (item.get("target_excerpt") or "").strip()
                if excerpt:
                    lines.append(f"   Target span: > {excerpt}")
            lines.append("")

        broken = plan.get("broken_links_to_replace") or []
        if broken:
            lines += ["## Broken links to replace", ""]
            for b in broken:
                lines.append(f"- `{b.get('old', '')}` → `{b.get('new', '')}`")
            lines.append("")

        new_links = plan.get("new_internal_links_to_add") or []
        if new_links:
            lines += ["## New internal links to weave in", ""]
            lines.extend(f"- {l}" for l in new_links)
            lines.append("")

        if secondary_keywords:
            lines += [
                "## Secondary keywords to weave naturally",
                "",
                "Use these lower-priority keywords in body prose where they fit "
                "the topic. Do not stuff them — natural mentions only.",
                "",
            ]
            lines.extend(f"- {kw}" for kw in secondary_keywords)
            lines.append("")

        lines += [
            "## Output reminder",
            "",
            "Return the same JSON shape as a new article "
            "(h1, intro, sections, internal_links_used, claims_to_verify, "
            "todos). The result must read like a polished article — not a "
            "diff. Preserve the original h1 unless the diagnostic explicitly "
            "asks you to change it.",
        ]

        return "\n".join(lines).strip()

    # ------------------------------------------------------------------
    # Auth mode 1: Anthropic (requires ANTHROPIC_API_KEY)
    # ------------------------------------------------------------------

    def _run_via_sdk(self, system_prompt: str, user_message: str) -> dict:
        from src import llm_client

        raw = llm_client.chat(system_prompt, user_message, tier=self.tier)
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
        original_article: str,
        scope: str = "medium",
        serp_data: dict | None = None,
        insight_data: dict | None = None,
        previous_brief: dict | None = None,
        secondary_keywords: list[str] | None = None,
    ) -> dict:
        """Audit an existing article and return a scoped update plan.

        Args:
            topic:             Article topic.
            original_article:  The full markdown text of the published article.
            scope:             "light" | "medium" | "heavy".
            serp_data:         Fresh SERP research dict (optional but recommended).
            insight_data:      Fresh company insight dict (optional).
            previous_brief:    Original brief, if available (context only).

        Returns:
            Dict matching the schema in prompts/article_diagnostic_agent.md.
        """
        if scope not in VALID_SCOPES:
            raise ValueError(
                f"Invalid scope {scope!r}. Must be one of {sorted(VALID_SCOPES)}."
            )

        print(
            f"Article Diagnostic Agent: scope={scope}, "
            f"article length={len(original_article)} chars",
            file=sys.stderr,
        )

        system_prompt = self._build_system_prompt()
        user_message = self._build_user_message(
            topic=topic,
            original_article=original_article,
            scope=scope,
            serp_data=serp_data,
            insight_data=insight_data,
            previous_brief=previous_brief,
            secondary_keywords=secondary_keywords,
        )

        if self.api_key:
            print(f"Auth: Anthropic (tier: {self.tier})", file=sys.stderr)
            result = self._run_via_sdk(system_prompt, user_message)
        else:
            print(f"Auth: Claude Agent SDK (model: {self.model})", file=sys.stderr)
            result = self._run_via_agent_sdk(system_prompt, user_message)

        if "scope_used" not in result:
            result["scope_used"] = scope
        return result
