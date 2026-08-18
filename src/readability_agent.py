"""Readability Checker Agent — JVL Content Engine.

Pipeline position:
  Brief → SERP Research → Company Insight → SEO Structure → Writer →
  **Readability Checker** ↔ Writer (feedback loop, up to 3 iterations) →
  QA → Metadata

Purpose:
  Score a draft article with Flesch Reading Ease (textstat). If the score is
  below the target (default 90), call an LLM to produce surgical rewrite
  instructions, then ask the Writer Agent to regenerate the draft. Repeat
  until the target is met or max_iterations is reached. Returns the best
  draft seen plus a full iteration report.

Auth modes (mirrors WriterAgent):
  1. OpenAI (via src.llm_client) — when OPENAI_API_KEY is set
  2. Claude Agent SDK      — when running inside a Claude Code session
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable


TARGET_SCORE = 90.0
MAX_ITERATIONS = 3


def _strip_markdown(md: str) -> str:
    """Return plain prose suitable for readability scoring.

    Removes headings, list bullets, fenced code, inline code, links → text,
    and the trailing 'Claims to Verify' / 'Open TODOs' review block that the
    Writer Agent appends to assembled markdown.
    """
    text = md

    # Drop everything after the trailing review block separator.
    parts = re.split(r"\n---\s*\n+##\s+(?:Claims to Verify|Open TODOs)", text, maxsplit=1)
    if len(parts) > 1:
        text = parts[0]

    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]+`", " ", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s+.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_]{1,3}([^*_]+)[*_]{1,3}", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def score_markdown(md: str) -> dict[str, Any]:
    """Compute Flesch Reading Ease and supporting stats for an article."""
    import textstat

    prose = _strip_markdown(md)
    if not prose:
        return {
            "flesch_reading_ease": 0.0,
            "flesch_kincaid_grade": 0.0,
            "avg_sentence_length": 0.0,
            "avg_syllables_per_word": 0.0,
            "word_count": 0,
            "sentence_count": 0,
            "longest_sentences": [],
            "hardest_words": [],
        }

    flesch = float(textstat.flesch_reading_ease(prose))
    fk_grade = float(textstat.flesch_kincaid_grade(prose))
    avg_sent_len = float(textstat.avg_sentence_length(prose))
    avg_syll = float(textstat.avg_syllables_per_word(prose))
    word_count = int(textstat.lexicon_count(prose, removepunct=True))
    sentence_count = int(textstat.sentence_count(prose))

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", prose) if s.strip()]
    sentences_sorted = sorted(sentences, key=lambda s: len(s.split()), reverse=True)
    longest = [
        {"length_words": len(s.split()), "text": s[:240]}
        for s in sentences_sorted[:5]
        if len(s.split()) >= 20
    ]

    words = re.findall(r"[A-Za-z][A-Za-z'-]+", prose)
    seen: set[str] = set()
    hardest: list[dict[str, Any]] = []
    for w in words:
        wl = w.lower()
        if wl in seen:
            continue
        syll = textstat.syllable_count(w)
        if syll >= 4:
            hardest.append({"word": w, "syllables": int(syll)})
            seen.add(wl)
        if len(hardest) >= 15:
            break

    return {
        "flesch_reading_ease": round(flesch, 2),
        "flesch_kincaid_grade": round(fk_grade, 2),
        "avg_sentence_length": round(avg_sent_len, 2),
        "avg_syllables_per_word": round(avg_syll, 3),
        "word_count": word_count,
        "sentence_count": sentence_count,
        "longest_sentences": longest,
        "hardest_words": hardest,
    }


class ReadabilityChecker:
    """Score a draft, generate rewrite instructions, loop Writer until target."""

    def __init__(
        self,
        target_score: float = TARGET_SCORE,
        max_iterations: int = MAX_ITERATIONS,
    ) -> None:
        self.api_key = os.environ.get("OPENAI_API_KEY")
        self.tier = "standard"
        self.model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-6")  # agent-SDK fallback only
        self.repo_root = Path(__file__).parent.parent
        self.target_score = float(target_score)
        self.max_iterations = int(max_iterations)

    # ------------------------------------------------------------------
    # File loading
    # ------------------------------------------------------------------

    def _load_file(self, path: str) -> str:
        return (self.repo_root / path).read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        return self._load_file("prompts/readability_agent.md")

    def _build_user_message(self, draft_markdown: str, stats: dict) -> str:
        stats_block = json.dumps(stats, indent=2, ensure_ascii=False)
        return (
            f"Analyse the following article draft. Flesch Reading Ease is "
            f"{stats['flesch_reading_ease']} (target: >= {self.target_score}).\n\n"
            f"# READABILITY STATS\n\n{stats_block}\n\n"
            f"# DRAFT MARKDOWN\n\n{draft_markdown}\n\n"
            "Return only a valid JSON object matching the schema in the system "
            "prompt. No markdown fences, no commentary."
        )

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
    # Auth mode 1: OpenAI (requires OPENAI_API_KEY)
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

        anyio.run(_run)
        raw = "\n".join(result_text).strip() or "\n".join(assistant_text).strip()
        if not raw:
            raise ValueError("Agent SDK returned no content.")
        return self._extract_json(raw)

    # ------------------------------------------------------------------
    # Instruction generation
    # ------------------------------------------------------------------

    def generate_instructions(self, draft_markdown: str, stats: dict) -> dict:
        system_prompt = self._build_system_prompt()
        user_message = self._build_user_message(draft_markdown, stats)
        if self.api_key:
            return self._run_via_sdk(system_prompt, user_message)
        return self._run_via_agent_sdk(system_prompt, user_message)

    # ------------------------------------------------------------------
    # Feedback-loop instruction formatting for WriterAgent
    # ------------------------------------------------------------------

    @staticmethod
    def format_writer_feedback(instructions: dict, stats: dict, target: float) -> str:
        """Render ReadabilityChecker output into a user-message addendum
        that the Writer Agent will receive on its next pass."""
        lines: list[str] = [
            "# READABILITY REVISION REQUEST",
            "",
            f"The previous draft scored {stats['flesch_reading_ease']} on Flesch "
            f"Reading Ease. Target is >= {target}.",
            "",
            "Rewrite the draft so the score reaches the target. Keep the same "
            "structure (H1, sections, internal links), the same facts, and the "
            "same brand voice. Simplify language: shorter sentences, fewer "
            "polysyllabic words, active voice.",
            "",
        ]

        diagnosis = instructions.get("diagnosis", {})
        if diagnosis.get("summary"):
            lines += ["## Diagnosis", "", diagnosis["summary"], ""]

        problems = diagnosis.get("primary_problems") or []
        if problems:
            lines.append("**Primary problems:**")
            lines.extend(f"- {p}" for p in problems)
            lines.append("")

        offenders = diagnosis.get("worst_offenders") or []
        if offenders:
            lines += ["## Worst offenders", ""]
            for o in offenders:
                lines.append(
                    f"- **{o.get('section', '?')}** — {o.get('why', '')}\n"
                    f"  > {o.get('excerpt', '')}"
                )
            lines.append("")

        items = instructions.get("instructions_for_writer") or []
        if items:
            lines += ["## Required edits", ""]
            for i, item in enumerate(items, 1):
                lines.append(
                    f"{i}. **{item.get('section', '?')}** "
                    f"[{item.get('action', 'other')}] — {item.get('guidance', '')}\n"
                    f"   Target span: > {item.get('target_excerpt', '')}"
                )
            lines.append("")

        tradeoffs = instructions.get("tradeoff_notes") or []
        if tradeoffs:
            lines += ["## Tradeoff notes (preserve brand voice over raw score)", ""]
            lines.extend(f"- {t}" for t in tradeoffs)
            lines.append("")

        return "\n".join(lines).strip()

    # ------------------------------------------------------------------
    # Public interface: full feedback loop
    # ------------------------------------------------------------------

    def run(
        self,
        draft_result: dict,
        draft_markdown: str,
        rewrite_fn: Callable[[str], dict],
        assemble_markdown_fn: Callable[[dict], str],
    ) -> dict:
        """Run the readability feedback loop.

        Args:
            draft_result:          The Writer Agent's structured JSON output.
            draft_markdown:        Assembled markdown of that draft.
            rewrite_fn:            Callable taking a feedback string and
                                   returning a new Writer Agent result dict.
                                   Caller is responsible for wiring it to
                                   WriterAgent.run(...) with the original
                                   topic, brief, serp_context, etc.
            assemble_markdown_fn:  Callable that turns a Writer result dict
                                   into assembled markdown.

        Returns:
            {
              "final_result":   dict,    # Writer result for the best draft
              "final_markdown": str,
              "final_score":    float,
              "target_score":   float,
              "passed":         bool,
              "iterations":     [
                  {"iteration": int, "stats": {...},
                   "instructions": {...} | None, "used": bool},
                  ...
              ],
              "best_iteration": int,
            }
        """
        print(
            f"ReadabilityChecker: target Flesch Reading Ease >= "
            f"{self.target_score}, max iterations = {self.max_iterations}",
            file=sys.stderr,
        )

        iterations: list[dict] = []
        best_score = -1.0
        best_idx = 0
        best_result = draft_result
        best_markdown = draft_markdown

        current_result = draft_result
        current_markdown = draft_markdown

        for i in range(self.max_iterations + 1):
            stats = score_markdown(current_markdown)
            score = stats["flesch_reading_ease"]
            print(
                f"  Iteration {i}: Flesch Reading Ease = {score} "
                f"(words: {stats['word_count']}, sentences: {stats['sentence_count']})",
                file=sys.stderr,
            )

            if score > best_score:
                best_score = score
                best_idx = i
                best_result = current_result
                best_markdown = current_markdown

            if score >= self.target_score:
                iterations.append(
                    {"iteration": i, "stats": stats, "instructions": None, "used": False}
                )
                return {
                    "final_result": current_result,
                    "final_markdown": current_markdown,
                    "final_score": score,
                    "target_score": self.target_score,
                    "passed": True,
                    "iterations": iterations,
                    "best_iteration": i,
                }

            if i == self.max_iterations:
                iterations.append(
                    {"iteration": i, "stats": stats, "instructions": None, "used": False}
                )
                break

            try:
                instructions = self.generate_instructions(current_markdown, stats)
            except Exception as exc:
                print(
                    f"  Instruction generation failed: {exc}. Stopping loop.",
                    file=sys.stderr,
                )
                iterations.append(
                    {
                        "iteration": i,
                        "stats": stats,
                        "instructions": None,
                        "used": False,
                        "error": str(exc),
                    }
                )
                break

            feedback = self.format_writer_feedback(instructions, stats, self.target_score)
            iterations.append(
                {"iteration": i, "stats": stats, "instructions": instructions, "used": True}
            )

            try:
                current_result = rewrite_fn(feedback)
            except Exception as exc:
                print(
                    f"  Writer rewrite failed on iteration {i + 1}: {exc}. "
                    "Returning best-so-far.",
                    file=sys.stderr,
                )
                break

            current_markdown = assemble_markdown_fn(current_result)

        return {
            "final_result": best_result,
            "final_markdown": best_markdown,
            "final_score": best_score,
            "target_score": self.target_score,
            "passed": best_score >= self.target_score,
            "iterations": iterations,
            "best_iteration": best_idx,
        }
