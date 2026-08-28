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

from src import length_target


#: Flesch Reading Ease band. Below the floor the prose is hard work; above the
#: ceiling it has been sanded into staccato. Plain, confident business English
#: sits between them — the measured article scored 67.0, which is where an
#: article about payback periods should land.
TARGET_MIN = 60.0
TARGET_MAX = 75.0

#: Kept for callers that pass an explicit floor.
TARGET_SCORE = TARGET_MIN

#: Output budget for this agent's own call, covering thinking and answer both.
#:
#: Ten of the eleven agents ran on the shared 16000 default. This one is the odd
#: case: its input is the entire article and its job is analysis rather than
#: generation, which is the combination that makes deliberation expensive. On a
#: 3,164-word draft it spent the whole 16000 thinking and emitted no text at
#: all — output_tokens=16000/16000, stop_reason=max_tokens — and the rewrite
#: loop stopped with problems still on the board.
#:
#: The prompt asking for an unreachable score of 90 was the larger half of that
#: and is fixed. This is the other half: a step that reads a whole article needs
#: room to think about it, and the shared default was sized for agents writing
#: short JSON from short inputs.
#:
#: Overridable with READABILITY_MAX_TOKENS.
_DEFAULT_MAX_TOKENS = 24000


def max_tokens() -> int:
    """Output budget for the instruction-generation call."""
    raw = os.environ.get("READABILITY_MAX_TOKENS")
    if not raw:
        return _DEFAULT_MAX_TOKENS
    try:
        value = int(raw)
    except ValueError:
        print(
            f"  READABILITY_MAX_TOKENS={raw!r} is not a number — using "
            f"{_DEFAULT_MAX_TOKENS}",
            file=sys.stderr,
        )
        return _DEFAULT_MAX_TOKENS
    return value if value > 0 else _DEFAULT_MAX_TOKENS

#: Sentence rhythm, in words. A mean below the floor is the checklist cadence;
#: a standard deviation below its floor means every sentence is the same length,
#: which reads as machine-made however plain each one is.
MIN_MEAN_SENTENCE = 15.0
MAX_MEAN_SENTENCE = 24.0
MIN_SENTENCE_STDEV = 6.0

#: Share of sentences under twelve words. Some are good — they land a point.
#: Most being short is the defect.
MAX_SHORT_SENTENCE_SHARE = 0.45

#: The tail, not the mean.
#:
#: A reader does not experience an average. They experience the sentence they
#: have to read twice. A draft measured 20.1 words on average and passed every
#: check while 22% of its sentences ran past thirty words and one reached 77 —
#: and the passages a reader complained about all came from that tail.
MAX_SENTENCE_WORDS = 35
MAX_LONG_SENTENCE_SHARE = 0.10

#: Word difficulty, held separately from sentence length.
#:
#: Flesch is one number over two independent things: how long sentences run and
#: how hard the words are. A band on the combination lets a draft buy length
#: with vocabulary. That is what happened — lengthening sentences from 14.6 to
#: 20.1 words also took syllables per word from 1.39 to 1.53 and difficult words
#: from 9.6% to 13.3%, because nothing was watching the second dimension. Long,
#: varied sentences made of plain words are the target; these keep the second
#: half honest while the rhythm checks work on the first.
MAX_SYLLABLES_PER_WORD = 1.45
MAX_DIFFICULT_WORD_SHARE = 0.11

#: Words of unbroken prose before something has to break it up.
#:
#: Counting tables, lists, quotes and images — not headings. A heading divides
#: the page without relieving the density beneath it, and a section that runs a
#: thousand words of paragraphs under one heading is still a wall.
#:
#: Measured across runs: an early draft's longest such run was 643 words; four
#: revisions later it was 979, with five runs past 500. That regression arrived
#: with the rules that removed a crude list quota, and nothing replaced it.
MAX_PROSE_RUN_WORDS = 350

#: Share of non-empty lines that are list items.
#:
#: Prose is measured as prose — tables and list items are excluded from the
#: readability numbers, because a five-column table row is not a 77-word
#: sentence and stripping a bullet leaves lines that merge into one. That
#: exclusion needs a counterweight, or an article made entirely of bullets
#: scores beautifully. A draft that read as a checklist had a third of its
#: lines inside lists.
MAX_LIST_LINE_SHARE = 0.25

#: How far outside a boundary still counts as inside it.
#:
#: Every threshold here is a judgement dressed as a number, and enforcing them
#: exactly costs more than it buys. A draft once sat at 14.29 words against a
#: floor of 15 — seven tenths of a word — with its reading ease already in band,
#: and paid for a full Writer pass on the heavy tier to close the gap. The pass
#: overshot to 26.66 and made things worse. Ten percent of the boundary is the
#: width of the doubt in the boundary itself.
#:
#: It applies to every check, and for a while it did not. The longest-sentence
#: and unbroken-prose counters were added later and compared hard, so a run
#: reporting a 372-word wall against a 350-word ceiling — six percent, inside
#: the doubt every other check is granted — spent two full Writer calls chasing
#: twenty-two words. Worse, the loop's "not converging" verdict is a count of
#: these problems, so noise did not merely reach the report: it decided when to
#: stop. Every threshold here is a judgement, and none is sharp enough to
#: justify an exception.
_TOLERANCE = 0.10

MAX_ITERATIONS = 3


def _below(value: float, floor: float) -> bool:
    """Meaningfully below a floor, not merely under it."""
    return value < floor * (1 - _TOLERANCE)


def _above(value: float, ceiling: float) -> bool:
    """Meaningfully above a ceiling."""
    return value > ceiling * (1 + _TOLERANCE)


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
    # Table rows are not prose. Left in, a five-column row reads as one
    # 77-word sentence, so adding the table an article needed would make its
    # readability numbers worse — the opposite of what the rules ask for.
    text = re.sub(r"^\s*\|.*$", "", text, flags=re.MULTILINE)
    # List items are not prose either, and stripping only the marker leaves
    # lines with no terminal punctuation that merge into one 104-word
    # "sentence". Structure is measured separately, by longest_prose_run and
    # list_line_share; this function measures prose.
    text = re.sub(r"^\s*(?:[-*+]|\d+\.)\s+.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_]{1,3}([^*_]+)[*_]{1,3}", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_STRUCTURE_RE = re.compile(r"^(\||[-*]\s|\d+\.\s|>|!\[)")


_FAQ_HEADING_RE = re.compile(r"^##\s+(?:FAQ|Frequently\s+Asked)", re.IGNORECASE)


def longest_prose_run(md: str) -> int:
    """Words of unbroken prose between structural elements.

    Headings do not count. A heading divides the page without relieving the
    density beneath it — a thousand words of paragraphs under one heading is
    still a wall, and that is the thing a reader complains about.

    The FAQ is the exception and stops the count. A question heading every
    ninety words is a visual anchor on every screen, so a Q&A block does not
    read as a wall however the arithmetic adds up; measuring it as one made the
    number say something about the article that a reader would not recognise.
    Its length is governed instead by a ceiling on each answer.
    """
    run = 0
    longest = 0
    for line in md.splitlines():
        if _FAQ_HEADING_RE.match(line.strip()):
            break
        stripped = line.strip()
        if not stripped:
            continue
        if _STRUCTURE_RE.match(stripped):
            longest = max(longest, run)
            run = 0
        else:
            run += len(stripped.split())
    return max(longest, run)


def list_line_share(md: str) -> float:
    """Share of non-empty lines that are list items."""
    lines = [l.strip() for l in md.splitlines() if l.strip()]
    if not lines:
        return 0.0
    items = sum(1 for l in lines if re.match(r"^(?:[-*+]|\d+\.)\s", l))
    return items / len(lines)


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
            "long_sentence_share": 0.0,
            "longest_sentence_words": 0,
            "difficult_word_share": 0.0,
            "longest_prose_run": 0,
            "list_line_share": 0.0,
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
    long_share = sum(1 for n in lengths if n > 30) / len(lengths)
    longest_sentence = max(lengths)
    difficult_share = (
        textstat.difficult_words(prose) / word_count if word_count else 0.0
    )

    sentences_sorted = sorted(sentences, key=lambda s: len(s.split()), reverse=True)
    longest = [
        {"length_words": len(s.split()), "text": s[:240]}
        for s in sentences_sorted[:5]
        if len(s.split()) >= 20
    ]

    # Ranked by what each word actually costs the reader — its length times how
    # often they meet it. This used to take the first fifteen long words in
    # document order, which was harmless while nothing read the list and wrong
    # once the Writer started being handed it: a four-syllable word used once in
    # the intro outranked one used ten times throughout.
    words = re.findall(r"[A-Za-z][A-Za-z'-]+", prose)
    counts: dict[str, int] = {}
    forms: dict[str, str] = {}
    for w in words:
        wl = w.lower()
        counts[wl] = counts.get(wl, 0) + 1
        forms.setdefault(wl, w)

    scored = []
    for wl, n in counts.items():
        syll = textstat.syllable_count(wl)
        if syll >= 4:
            scored.append((syll * n, syll, n, forms[wl]))
    scored.sort(key=lambda t: (-t[0], -t[1], t[3]))
    hardest: list[dict[str, Any]] = [
        {"word": word, "syllables": int(syll), "occurrences": n}
        for _, syll, n, word in scored[:15]
    ]

    return {
        "flesch_reading_ease": round(flesch, 2),
        "flesch_kincaid_grade": round(fk_grade, 2),
        "avg_sentence_length": round(avg_sent_len, 2),
        "avg_syllables_per_word": round(avg_syll, 3),
        "word_count": word_count,
        "sentence_count": sentence_count,
        "sentence_length_stdev": round(stdev, 2),
        "short_sentence_share": round(short_share, 3),
        "long_sentence_share": round(long_share, 3),
        "longest_sentence_words": int(longest_sentence),
        "difficult_word_share": round(difficult_share, 3),
        "longest_prose_run": longest_prose_run(md),
        "list_line_share": round(list_line_share(md), 3),
        "longest_sentences": longest,
        "hardest_words": hardest,
    }


def prose_problems(stats: dict[str, Any]) -> list[str]:
    """Everything out of range in a draft, phrased as an instruction.

    Empty means the prose is fine. Each entry is written to be handed straight
    to the Writer, which is why they say what to do rather than what is wrong.
    """
    problems: list[str] = []
    kinds: list[str] = []
    score = stats.get("flesch_reading_ease", 0.0)
    mean = stats.get("avg_sentence_length", 0.0)
    stdev = stats.get("sentence_length_stdev", 0.0)
    short_share = stats.get("short_sentence_share", 0.0)

    if _below(score, TARGET_MIN):
        kinds.append("reading_ease_low")
        problems.append(
            f"Reading ease is {score}, below {TARGET_MIN}. Touch only the densest "
            f"sentences — those over {int(MAX_MEAN_SENTENCE)} words — and split each "
            "at its natural joint, or replace a piece of jargon where a plain word "
            "carries the same meaning. Leave every other sentence exactly as it is. "
            "Flattening the whole article to move a number is the failure this "
            "check exists to catch, not the fix for it."
        )
    elif _above(score, TARGET_MAX):
        kinds.append("reading_ease_high")
        problems.append(
            f"Reading ease is {score}, above {TARGET_MAX}. The prose has been "
            "simplified past plain into choppy. Rejoin adjacent short sentences "
            f"— those under {int(MIN_MEAN_SENTENCE) - 3} words — that carry one "
            "idea between them, and restore the connective words an argument needs "
            "(because, which, even though). Do not lengthen a sentence that is "
            "already comfortable."
        )

    if _below(mean, MIN_MEAN_SENTENCE):
        kinds.append("sentences_short")
        problems.append(
            f"Sentences average {mean} words, under {MIN_MEAN_SENTENCE}. That is "
            "checklist cadence: a paragraph of short declaratives reads as a list "
            "with the bullets removed. Combine adjacent sentences that carry one "
            f"idea between them — the ones under {int(MIN_MEAN_SENTENCE) - 3} words "
            "— so the reasoning between them becomes visible instead of implied. "
            f"Leave anything already over {int(MIN_MEAN_SENTENCE)} words alone; the "
            "goal is a mixture, not a uniformly longer article."
        )
    elif _above(mean, MAX_MEAN_SENTENCE):
        kinds.append("sentences_long")
        problems.append(
            f"Sentences average {mean} words, over {MAX_MEAN_SENTENCE}. Split only "
            f"the sentences over {int(MAX_MEAN_SENTENCE) + 6} words, at their "
            "natural joints. Leave the rest untouched — splitting everything "
            "trades one failure for its opposite."
        )

    if _below(stdev, MIN_SENTENCE_STDEV):
        kinds.append("rhythm_flat")
        problems.append(
            f"Sentence length barely varies (spread {stdev}, floor "
            f"{MIN_SENTENCE_STDEV}). Every sentence being the same size reads as "
            "machine-made however plain each one is. Vary the gear: a long "
            "sentence that develops a point, then a short one that lands it."
        )

    longest = stats.get("longest_sentence_words", 0)
    long_share = stats.get("long_sentence_share", 0.0)
    syllables = stats.get("avg_syllables_per_word", 0.0)
    difficult = stats.get("difficult_word_share", 0.0)
    prose_run = stats.get("longest_prose_run", 0)

    if _above(longest, MAX_SENTENCE_WORDS):
        kinds.append("sentence_tail")
        problems.append(
            f"One sentence runs {longest} words against a {MAX_SENTENCE_WORDS}-word "
            "ceiling. Find the sentences past that length and split each at its "
            "natural joint. A reader does not experience your average sentence, "
            "they experience the one they have to read twice."
        )

    if _above(long_share, MAX_LONG_SENTENCE_SHARE):
        kinds.append("long_share")
        problems.append(
            f"{round(long_share * 100)}% of sentences run over thirty words, above "
            f"the {round(MAX_LONG_SENTENCE_SHARE * 100)}% ceiling. Long sentences "
            "are for developing a point and should be the exception. Split the "
            "worst offenders; leave the rest alone."
        )

    if _above(syllables, MAX_SYLLABLES_PER_WORD) or _above(difficult, MAX_DIFFICULT_WORD_SHARE):
        kinds.append("vocabulary")
        # Name the words. Every other check points at something the Writer can
        # find — "one sentence runs 44 words", "379 words without a break". This
        # one used to hand over two ratios and a generic example while the list
        # of actual offenders sat unused in the same stats dict, and it was the
        # check drafts failed most often and fixed least.
        offenders = [
            w.get("word", "")
            for w in (stats.get("hardest_words") or [])
            if w.get("word")
        ][:12]
        pointer = (
            f" The heaviest words in this draft: {', '.join(offenders)}. Replace "
            "the ones carrying no meaning a shorter word would lose. A term the "
            "brief asked for stays."
            if offenders
            else ""
        )
        problems.append(
            f"The vocabulary is heavier than it needs to be ({syllables} syllables "
            f"per word, {round(difficult * 100)}% difficult words, against "
            f"{MAX_SYLLABLES_PER_WORD} and {round(MAX_DIFFICULT_WORD_SHARE * 100)}%). "
            "This is separate from sentence length — do not shorten sentences to "
            "fix it. Replace abstract nouns with the verbs they were made from: "
            "\"quantified a dollar lift attributable to a machine\" becomes "
            "\"measured what one machine adds\". Keep the sentences long and the "
            f"words plain.{pointer}"
        )

    if _above(prose_run, MAX_PROSE_RUN_WORDS):
        kinds.append("prose_wall")
        problems.append(
            f"{prose_run} words run without a table, list, quote or image to break "
            f"them, against a {MAX_PROSE_RUN_WORDS}-word ceiling. Headings do not "
            "count: a section that runs a thousand words of paragraphs under one "
            "heading is still a wall. Find the longest stretch and give it what it "
            "was already asking for — a comparison becomes a table, a set of "
            "conditions becomes a list, a figure that carries the argument becomes "
            "a pulled quote."
        )

    if _above(stats.get("list_line_share", 0.0), MAX_LIST_LINE_SHARE):
        kinds.append("list_heavy")
        problems.append(
            f"{round(stats['list_line_share'] * 100)}% of lines are list items, "
            f"above the {round(MAX_LIST_LINE_SHARE * 100)}% ceiling. Lists carry "
            "items; they cannot carry reasoning. Turn the ones whose entries need "
            "a \"because\" back into sentences."
        )

    if _above(short_share, MAX_SHORT_SENTENCE_SHARE):
        kinds.append("too_choppy")
        problems.append(
            f"{round(short_share * 100)}% of sentences are under twelve words, over "
            f"the {round(MAX_SHORT_SENTENCE_SHARE * 100)}% ceiling. Short sentences "
            "are for emphasis. When most of them are short, none of them are "
            "emphatic and the article reads as a series of assertions rather than "
            "an argument."
        )

    _LAST_KINDS[:] = kinds
    return problems


#: The kind of each problem the last prose_problems() call reported.
#:
#: The QA revision step used to compare problem *counts* before and after, and
#: let a revision through when the count held. A measured run traded a fixable
#: sentence for a 502-word wall and passed the gate at three problems against
#: three: the count was identical, the article was worse. Composition is what
#: matters, so the gate compares kinds.
_LAST_KINDS: list[str] = []


def prose_problem_kinds(stats: dict[str, Any]) -> set[str]:
    """Which kinds of problem a draft has, ignoring how bad each one is.

    Two drafts with three problems each are not interchangeable. This is what a
    gate should compare when it asks whether a rewrite made things worse.
    """
    prose_problems(stats)
    return set(_LAST_KINDS)


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

    def _run_via_sdk(
        self, system_prompt: str, user_message: str, budget: int | None = None
    ) -> dict:
        from src import llm_client

        return llm_client.chat_json(
            system_prompt,
            user_message,
            self._extract_json,
            max_tokens=budget or max_tokens(),
            tier=self.tier,
            label="Readability Checker",
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
        if not self.api_key:
            return self._run_via_agent_sdk(system_prompt, user_message)

        try:
            return self._run_via_sdk(system_prompt, user_message)
        except ValueError as exc:
            # Running out of output budget is the one failure the caller can
            # actually fix, and abandoning the loop over it is expensive: the
            # draft in hand still carries problems the next pass would clear.
            # A measured run lost its third iteration this way. One retry at
            # double, then it is a real failure.
            if "max_tokens" not in str(exc):
                raise
            raised = max_tokens() * 2
            print(
                f"  Instruction generation exhausted its {max_tokens()}-token "
                f"budget without emitting text. Retrying once at {raised}.",
                file=sys.stderr,
            )
            return self._run_via_sdk(system_prompt, user_message, budget=raised)

    # ------------------------------------------------------------------
    # Feedback-loop instruction formatting for WriterAgent
    # ------------------------------------------------------------------

    @staticmethod
    def format_writer_feedback(instructions: dict, stats: dict, target: float) -> str:
        """Render ReadabilityChecker output into a user-message addendum
        that the Writer Agent will receive on its next pass."""
        problems = prose_problems(stats)
        # The loop appended the length verdict to its own problem list; the
        # feedback the Writer actually reads has to carry it as well, or the
        # rewrite fixes the prose and leaves the article the same length.
        length = stats.get("length_check") or {}
        if length.get("problem"):
            problems = problems + [length["problem"]]
        if stats.get("section_check"):
            problems = problems + [stats["section_check"]]
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
        word_target: dict | None = None,
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
        previous_problems: int | None = None
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

            # Length is measured here rather than trusted to the Writer, which
            # never learns its own word count — the number does not exist until
            # it has stopped writing. Asking it to notice it had overshot was
            # asking for a measurement it cannot take. It rides the same loop as
            # the prose problems so it costs no extra call, and it counts toward
            # convergence like everything else.
            length = None
            if word_target:
                length = length_target.assess(
                    word_target,
                    length_target.article_word_count(current_markdown),
                    (current_result or {}).get("length_justification"),
                )
                stats["length_check"] = length
                if length["problem"]:
                    problems = problems + [length["problem"]]
                # Counted separately from the words. A draft can hold its
                # section count and still overshoot by writing each one long,
                # and it can keep the length while splitting the argument into
                # too many places — the two fail independently and the fixes
                # are opposite, so telling the Writer "too long" when the fault
                # is "too many places" sends it to compress prose that is fine.
                section_note = length_target.section_problem(
                    word_target, current_markdown
                )
                if section_note:
                    problems = problems + [section_note]
                    stats["section_check"] = section_note
                    print(f"  Sections: {section_note.split('.')[0]}.", file=sys.stderr)
                    print(
                        f"  Length: {length['word_count']} words against "
                        f"{word_target['low']}-{word_target['high']} "
                        f"({length['verdict']})",
                        file=sys.stderr,
                    )
                elif length["verdict"] == "over_band_justified":
                    print(
                        f"  Length: {length['word_count']} words, past the band "
                        "and justified — accepted.",
                        file=sys.stderr,
                    )
            print(
                f"  Iteration {i}: reading ease {score}, sentences avg "
                f"{stats['avg_sentence_length']} words (spread "
                f"{stats['sentence_length_stdev']}, "
                f"{round(stats['short_sentence_share'] * 100)}% short) — "
                f"{len(problems)} out of range",
                file=sys.stderr,
            )

            # A pass that does not reduce the problem count is not converging,
            # and the next one has no better prospects. Observed: 22.97 words ->
            # 14.29 -> 26.66, each correction overshooting harder than the last,
            # the third draft worse than the first, and the whole budget spent.
            # The rule is "fewer than before or stop" rather than "worse than
            # before", because standing still is how an oscillation looks when it
            # happens to trade one problem for another.
            if previous_problems is not None and len(problems) >= previous_problems:
                verdict = (
                    "worse than" if len(problems) > previous_problems else "no better than"
                )
                print(
                    f"  Iteration {i} is {verdict} the last "
                    f"({len(problems)} problems against {previous_problems}) — "
                    "the loop is not converging. Stopping and keeping the best draft.",
                    file=sys.stderr,
                )
                iterations.append(
                    {"iteration": i, "stats": stats, "instructions": None,
                     "used": False, "diverged": True}
                )
                break
            previous_problems = len(problems)

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
                    "length_check": length,
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
            # The best draft's verdict, not the last one's — the loop can end on
            # an iteration it then discards.
            "length_check": (
                (iterations[best_idx].get("stats") or {}).get("length_check")
                if best_idx < len(iterations)
                else None
            ),
        }
