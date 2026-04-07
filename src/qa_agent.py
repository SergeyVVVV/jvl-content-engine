"""QA Agent v1 — JVL Content Engine.

Pipeline position:
  Brief → SERP Research → Company Insight → Writer → **QA**

Purpose:
  Inspect a generated article draft (markdown or Writer JSON wrapper) plus
  optional upstream context (brief, SERP research, company insight) and return
  a structured JSON QA report. Review-only — never rewrites the article.

Auth modes (mirrors WriterAgent):
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


class QAAgent:
    """Reviews a draft article and returns a structured QA report dict."""

    def __init__(self) -> None:
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-6")
        self.repo_root = Path(__file__).parent.parent

    # ------------------------------------------------------------------
    # File loading
    # ------------------------------------------------------------------

    def _load_file(self, path: str) -> str:
        return (self.repo_root / path).read_text(encoding="utf-8")

    def _load_schema(self) -> dict:
        return json.loads(self._load_file("schemas/qa_report_schema.json"))

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        prompt = self._load_file("prompts/qa_agent.md")
        schema = self._load_file("schemas/qa_report_schema.json")
        return f"{prompt}\n\n---\n\n# QA REPORT JSON SCHEMA\n\n{schema}\n"

    def _build_user_message(
        self,
        topic: str,
        draft_markdown: str,
        draft_wrapper: dict | None,
        brief: dict | None,
        serp_data: dict | None,
        insight_data: dict | None,
        source_inputs_used: dict,
    ) -> str:
        parts: list[str] = [
            f"Review the following article draft for topic: {topic}\n"
        ]

        parts.append("# DRAFT MARKDOWN\n\n" + draft_markdown.strip() + "\n")

        if draft_wrapper:
            slim = {
                "claims_to_verify": draft_wrapper.get("claims_to_verify", []),
                "internal_links_used": draft_wrapper.get("internal_links_used", []),
                "risks_to_review": draft_wrapper.get("risks_to_review", []),
                "todos": draft_wrapper.get("todos", []),
                "primary_keyword": draft_wrapper.get("primary_keyword", ""),
                "search_intent": draft_wrapper.get("search_intent", ""),
                "funnel_stage": draft_wrapper.get("funnel_stage", ""),
                "product_fit": draft_wrapper.get("product_fit", ""),
            }
            parts.append(
                "# WRITER WRAPPER METADATA\n\n"
                + json.dumps(slim, indent=2, ensure_ascii=False)
                + "\n"
            )

        if brief:
            parts.append(
                "# BRIEF (use as benchmark for angle, intent, audience, key questions)\n\n"
                + json.dumps(brief, indent=2, ensure_ascii=False)
                + "\n"
            )
        else:
            parts.append("# BRIEF\n\n(not provided — note in todos)\n")

        if serp_data:
            parts.append(
                "# SERP RESEARCH (use to evaluate coverage and differentiation)\n\n"
                + json.dumps(serp_data, indent=2, ensure_ascii=False)
                + "\n"
            )
        else:
            parts.append("# SERP RESEARCH\n\n(not provided — note in todos)\n")

        if insight_data:
            parts.append(
                "# COMPANY INSIGHT (use to evaluate JVL grounding and forbidden claims)\n\n"
                + json.dumps(insight_data, indent=2, ensure_ascii=False)
                + "\n"
            )
        else:
            parts.append("# COMPANY INSIGHT\n\n(not provided — note in todos)\n")

        parts.append(
            "# SOURCE INPUTS USED (echo back verbatim in source_inputs_used)\n\n"
            + json.dumps(source_inputs_used, indent=2, ensure_ascii=False)
            + "\n"
        )

        parts.append(
            f"\nTopic for the report: {topic}\n"
            "Return ONLY a single valid JSON object matching the QA report schema. "
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

    def _validate(self, report: dict) -> None:
        schema = self._load_schema()
        try:
            jsonschema.validate(instance=report, schema=schema)
            print("QA report schema validation: PASSED", file=sys.stderr)
        except jsonschema.ValidationError as exc:
            print(
                f"QA report schema validation WARNING: {exc.message}",
                file=sys.stderr,
            )

    # ------------------------------------------------------------------
    # Deterministic normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(report: dict) -> dict:
        """Recompute severity_counts and status from issues[] deterministically.

        The LLM produces issues; this function makes the final verdict a pure
        function of the issue list, so the gate can never contradict the data.
        """
        issues = report.get("issues") or []

        counts = {"high": 0, "medium": 0, "low": 0}
        for issue in issues:
            sev = (issue.get("severity") or "").lower()
            if sev in counts:
                counts[sev] += 1

        if counts["high"] > 0:
            status = "fail"
        elif counts["medium"] > 0:
            status = "revise"
        else:
            status = "pass"

        report["severity_counts"] = counts
        report["status"] = status
        return report

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
        draft_wrapper: dict | None = None,
        brief: dict | None = None,
        serp_data: dict | None = None,
        insight_data: dict | None = None,
        source_inputs_used: dict | None = None,
    ) -> dict:
        """Run the QA Agent and return a validated QA report dict."""
        if not draft_markdown or not draft_markdown.strip():
            raise ValueError("draft_markdown is required and cannot be empty.")

        source_inputs_used = source_inputs_used or {
            "draft": None,
            "brief": None,
            "serp_research": None,
            "company_insight": None,
        }

        system_prompt = self._build_system_prompt()
        user_message = self._build_user_message(
            topic=topic,
            draft_markdown=draft_markdown,
            draft_wrapper=draft_wrapper,
            brief=brief,
            serp_data=serp_data,
            insight_data=insight_data,
            source_inputs_used=source_inputs_used,
        )

        if self.api_key:
            print(f"QA Agent auth: Anthropic SDK (model: {self.model})", file=sys.stderr)
            report = self._run_via_sdk(system_prompt, user_message)
        else:
            print(f"QA Agent auth: Claude Agent SDK (model: {self.model})", file=sys.stderr)
            report = self._run_via_agent_sdk(system_prompt, user_message)

        # Ensure topic + source_inputs_used are stamped even if model omitted them.
        report.setdefault("topic", topic)
        report.setdefault("source_inputs_used", source_inputs_used)
        report.setdefault("issues", [])

        # Deterministic normalization: verdict is a pure function of issues[].
        report = self._normalize(report)

        self._validate(report)
        return report
