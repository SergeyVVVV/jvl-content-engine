"""Readability Checker Agent — JVL Content Engine.

Pipeline position:
  Brief → SERP Research → Company Insight → SEO Structure → Writer →
  **Readability Checker** ↔ Writer (feedback loop, up to 3 iterations) →
  QA → Metadata

Purpose:
  Score a draft article for readability AND for rhythm, then ask the Writer to
  fix whichever is off. Repeat until both are in range or max_iterations is
  reached. Returns the best draft seen plus a full iteration report.

  Readability is a band, not a floor. The target used to be Flesch Reading Ease
  >= 90, which is a fifth-grade reading level and — for this subject matter —
  arithmetically out of reach: at 90 the text may average about 1.24 syllables
  per word, and "payback" is 2, "maintenance" 3, "optimistic" 4, "electricity"
  5, "profitability" 6. A measured article came in at 1.47 and 67.0. So the
  target could never be met, the loop never terminated satisfied, and every
  iteration told the Writer to cut again. What came back read like a checklist
  with the bullets removed: 13.2 words per sentence, 64% of them under fifteen,
  44-word paragraphs. Narrative voice lives in subordinate clauses and varying
  sentence length, and neither survives that pressure.

  So too simple now fails the same way too dense does, and sentence rhythm is
  measured alongside the score.

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
from typing import Any, Callable


#: Flesch Reading Ease band. Below the floor the prose is hard work; above the
#: ceiling it has been sanded into staccato. Plain, confident business English
#: sits between them — the measured article scored 67.0, which is where an
#: article about payback periods should land.
TARGET_MIN = 55.0
TARGET_MAX = 70.0

#: Kept for callers that pass an explicit floor.
TARGET_SCORE = TARGET_MIN

#: Sentence rhythm, in words. A mean below the floor is the checklist cadence;
#: a standard deviation below its floor means every sentence is the same length,
#: which reads as machine-made however plain each one is.
MIN_MEAN_SENTENCE = 15.0
MAX_MEAN_SENTENCE = 24.0
MIN_SENTENCE_STDEV = 6.0

#: Share of sentences under twelve words. Some are good — they land a point.
#: Most being short is the defect.
MAX_SHORT_SENTENCE_SHARE = 0.45

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
            "sentence_length_stdev": 0.0,
            "short_sentence_share": 0.0,
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

    # Rhythm. The mean says how long a sentence runs; the spread says whether
    # the writer ever changes gear. Prose can be plain and still varied, and it
    # is the variation a reader hears as a voice.
    lengths = [len(s.split()) for s in sentences] or [0]
    mean_len = sum(lengths) / len(lengths)
    variance = sum((n - mean_len) ** 2 for n in lengths) / len(lengths)
    stdev = variance ** 0.5
    short_share = sum(1 for n in lengths if n < 12) / len(lengths)

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
        "sentence_length_stdev": round(stdev, 2),
        "short_sentence_share": round(short_share, 3),
        "longest_sentences": longest,
        "hardest_words": hardest,
    }


def prose_problems(stats: dict[str, Any]) -> list[str]:
    """Everything out of range in a draft, phrased as an instruction.

    Empty means the prose is fine. Each entry is written to be handed straight
    to the Writer, which is why they say what to do rather than what is wrong.
    """
    problems: list[str] = []
    score = stats.get("flesch_reading_ease", 0.0)
    mean = stats.get("avg_sentence_length", 0.0)
    stdev = stats.get("sentence_length_stdev", 0.0)
    short_share = stats.get("short_sentence_share", 0.0)

    if score < TARGET_MIN:
        problems.append(
            f"Reading ease is {score}, below {TARGET_MIN}. The prose is harder work "
            "than it needs to be. Break the densest sentences and replace jargon "
            "where a plain word carries the same meaning — do not flatten the whole "
            "article to reach a number."
        )
    elif score > TARGET_MAX:
        problems.append(
            f"Reading ease is {score}, above {TARGET_MAX}. The prose has been "
            "simplified past plain into choppy. Rejoin sentences that belong "
            "together, restore the connective words that carry an argument "
            "(because, which, even though), and let the reasoning run."
        )

    if mean < MIN_MEAN_SENTENCE:
        problems.append(
            f"Sentences average {mean} words, under {MIN_MEAN_SENTENCE}. That is "
            "checklist cadence: a paragraph of short declaratives reads as a list "
            "with the bullets removed. Combine related sentences so the reasoning "
            "between them is visible instead of implied."
        )
    elif mean > MAX_MEAN_SENTENCE:
        problems.append(
            f"Sentences average {mean} words, over {MAX_MEAN_SENTENCE}. Split the "
            "longest ones at their natural joints."
        )

    if stdev < MIN_SENTENCE_STDEV:
        problems.append(
            f"Sentence length barely varies (spread {stdev}, floor "
            f"{MIN_SENTENCE_STDEV}). Every sentence being the same size reads as "
            "machine-made however plain each one is. Vary the gear: a long "
            "sentence that develops a point, then a short one that lands it."
        )

    if short_share > MAX_SHORT_SENTENCE_SHARE:
        problems.append(
            f"{round(short_share * 100)}% of sentences are under twelve words, over "
            f"the {round(MAX_SHORT_SENTENCE_SHARE * 100)}% ceiling. Short sentences "
            "are for emphasis. When most of them are short, none of them are "
            "emphatic and the article reads as a series of assertions rather than "
            "an argument."
        )

    return problems


def prose_is_in_range(stats: dict[str, Any]) -> bool:
    """Whether the draft needs no rewrite on readability or rhythm grounds."""
    return not prose_problems(stats)


class ReadabilityChecker:
    """Score a draft, generate rewrite instructions, loop Writer until target."""

    def __init__(
        self,
        target_score: float = TARGET_SCORE,
        max_iterations: int = MAX_ITERATIONS,
    ) -> None:
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.tier = "standard"
        self.model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")  # agent-SDK fallback only
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
            f"{stats['flesch_reading_ease']} (target band: "
            f"{TARGET_MIN}-{TARGET_MAX}). Out of range now: "
            f"{'; '.join(prose_problems(stats)) or 'nothing'}.\n\n"
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
        problems = prose_problems(stats)
        lines: list[str] = [
            "# PROSE REVISION REQUEST",
            "",
            f"Reading ease {stats['flesch_reading_ease']} (target band "
            f"{TARGET_MIN}-{TARGET_MAX}); sentences average "
            f"{stats.get('avg_sentence_length')} words, spread "
            f"{stats.get('sentence_length_stdev')}, "
            f"{round(stats.get('short_sentence_share', 0) * 100)}% under twelve.",
            "",
            "Keep the same structure (H1, sections, internal links), the same "
            "facts, and the same brand voice. Fix only what is listed below — "
            "and note the direction of each item. Simplifying further when the "
            "text is already plain is what produced the problem being fixed.",
            "",
        ]

        if problems:
            lines += ["## What is out of range", ""]
            lines += [f"- {p}" for p in problems]
            lines.append("")

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
            f"ReadabilityChecker: reading-ease band {TARGET_MIN}-{TARGET_MAX}, "
            f"sentence mean {MIN_MEAN_SENTENCE}-{MAX_MEAN_SENTENCE} words, "
            f"max iterations = {self.max_iterations}",
            file=sys.stderr,
        )

        iterations: list[dict] = []
        best_rank: tuple[int, float] = (10**6, 0.0)
        best_score = -1.0
        best_idx = 0
        best_result = draft_result
        best_markdown = draft_markdown

        current_result = draft_result
        current_markdown = draft_markdown

        for i in range(self.max_iterations + 1):
            stats = score_markdown(current_markdown)
            score = stats["flesch_reading_ease"]
            problems = prose_problems(stats)
            print(
                f"  Iteration {i}: reading ease {score}, sentences avg "
                f"{stats['avg_sentence_length']} words (spread "
                f"{stats['sentence_length_stdev']}, "
                f"{round(stats['short_sentence_share'] * 100)}% short) — "
                f"{len(problems)} out of range",
                file=sys.stderr,
            )

            rank = (len(problems), -score)
            if rank < best_rank:
                best_rank = rank
                best_score = score
                best_idx = i
                best_result = current_result
                best_markdown = current_markdown

            if not problems:
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
            "passed": best_rank[0] == 0,
            "iterations": iterations,
            "best_iteration": best_idx,
        }
