"""QA Agent v1 — JVL Content Engine.

Pipeline position:
  Brief → SERP Research → Company Insight → Writer → **QA**

Purpose:
  Inspect a generated article draft (markdown or Writer JSON wrapper) plus
  optional upstream context (brief, SERP research, company insight) and return
  a structured JSON QA report. The agent never edits the article itself, but
  `format_for_writer()` renders its findings as revision instructions the
  Writer consumes through `revision_feedback` — so a failing report now causes
  a fix instead of only recording one.

Auth modes (mirrors WriterAgent):
  1. Anthropic (via src.llm_client) — when ANTHROPIC_API_KEY is set
  2. Claude Agent SDK      — when running inside a Claude Code session
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import jsonschema


#: Knowledge loaded into the QA system prompt.
#:
#: The claims rules have to come from the source file, not from the Company
#: Insight agent's extract of it. That extract is a per-topic shortlist — ten
#: or so facts — and QA was judging the article against it as if it were the
#: whole truth. Both directions were wrong: it called the 22-inch display and
#: the box contents inventions when both are confirmed claims, and it could not
#: have caught a trademarked game title, a competitor comparison, or a B2B
#: framing on B2C copy, because none of those rules were in front of it.
_KNOWLEDGE_FILES: list[tuple[str, str]] = [
    ("claims_constraints.md", "ALLOWED AND FORBIDDEN CLAIMS — the authority on what may be said"),
    ("firsthand_experience.md", "VERIFIED EXPERIENCE ANCHORS — confirmed operational and process facts"),
]

#: Issues the Writer cannot act on, matched against the issue's `location`.
#:
#: The Writer owns the article body and nothing else. An image caption belongs
#: to the Visual Agent, an FAQ answer to the FAQ Agent, wrapper metadata to the
#: pipeline. Handing it those anyway would invite it to invent an edit it has
#: no way to make, and to report success.
_NOT_WRITERS_TO_FIX = (
    "faq", "image", "caption", "hero", "inline-", "visual", "alt text",
    "wrapper metadata", "metadata /",
)


class QAAgent:
    """Reviews a draft article and returns a structured QA report dict."""

    def __init__(self) -> None:
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.tier = "heavy"
        self.model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")  # agent-SDK fallback only
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

        knowledge_sections: list[str] = []
        for filename, label in _KNOWLEDGE_FILES:
            try:
                content = self._load_file(f"knowledge/{filename}")
            except FileNotFoundError:
                print(f"QA Agent: knowledge/{filename} not found", file=sys.stderr)
                continue
            knowledge_sections.append(f"## {label}\n\n{content}")

        knowledge_block = ""
        if knowledge_sections:
            knowledge_block = (
                "\n\n---\n\n# KNOWLEDGE BASE\n\n"
                "This is the source of truth for what the article may claim. A fact\n"
                "listed here as allowed is not an invention, however it reached the\n"
                "draft, and a rule listed here as forbidden holds even when no\n"
                "upstream agent repeated it.\n\n"
                + "\n\n".join(knowledge_sections)
            )

        return (
            f"{prompt}{knowledge_block}\n\n---\n\n"
            f"# QA REPORT JSON SCHEMA\n\n{schema}\n"
        )

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
    # Feedback for the Writer
    # ------------------------------------------------------------------

    @staticmethod
    def writer_can_fix(issue: dict) -> bool:
        """Whether the Writer is the agent that owns this issue.

        Ownership is read off the issue's `location`, which the schema requires
        and which QA fills with the section or element it is talking about.
        """
        location = (issue.get("location") or "").lower()
        return not any(marker in location for marker in _NOT_WRITERS_TO_FIX)

    @staticmethod
    def format_for_writer(report: dict) -> str:
        """Render a QA report as an instruction block for `revision_feedback`.

        Returns an empty string when there is nothing the Writer can act on,
        which the caller reads as "do not spend a rewrite on this".
        """
        issues = report.get("issues", []) or []
        actionable = [i for i in issues if QAAgent.writer_can_fix(i)]
        if not actionable:
            return ""

        rank = {"high": 0, "medium": 1, "low": 2}
        actionable.sort(key=lambda i: rank.get(i.get("severity", "low"), 3))

        # A list, not a report. This block used to open with the reviewer's
        # 250-word summary and then give every issue a heading, a "Problem"
        # paragraph and a "Required fix" paragraph — 1,048 words on a measured
        # run, telling a model to make small corrections at the length of a
        # commission. The full report is saved as JSON and read by people; the
        # agent doing the fixing gets only the part it can act on.
        lines: list[str] = ["# FIX THESE, AND CHANGE NOTHING ELSE", ""]
        for n, issue in enumerate(actionable, 1):
            where = issue.get("location", "unspecified location")
            what = str(issue.get("problem", "(not described)")).rstrip(". ")
            fix = issue.get("recommended_fix") or "correct it in place"
            lines.append(f"{n}. **{where}** — {what}. Fix: {fix}")
        lines.append("")

        skipped = [i for i in issues if not QAAgent.writer_can_fix(i)]
        if skipped:
            lines += [
                "Not yours, do not touch: "
                + "; ".join(i.get("location", "unspecified") for i in skipped),
                "",
            ]

        lines += [
            "Recompute any figure you touch against the numbers it comes from. "
            "Do not add claims while fixing old ones. No `TODO:` may survive in "
            "reader-facing prose. Return the full article as JSON.",
        ]
        return "\n".join(lines)

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
    # Auth mode 1: Anthropic (requires ANTHROPIC_API_KEY)
    # ------------------------------------------------------------------

    def _run_via_sdk(self, system_prompt: str, user_message: str) -> dict:
        from src import llm_client

        return llm_client.chat_json(
            system_prompt,
            user_message,
            self._extract_json,
            tier=self.tier,
            label="QA Agent",
        )

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
            print(f"QA Agent auth: Anthropic (tier: {self.tier})", file=sys.stderr)
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
