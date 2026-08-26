"""Writer Agent — JVL Content Engine.

Pipeline position:
  Brief Agent → SERP Research Agent → Company Insight Agent → Writer Agent

Purpose:
  Given an article brief (required) plus optional SERP research and company
  insight, generate a structured first-draft article grounded in JVL knowledge
  files. Outputs a validated JSON dict matching schemas/article_draft_schema.json
  — plus an assembled markdown string ready to save as a .md file.

Auth modes (tried in order):
  1. Anthropic (via src.llm_client) — when ANTHROPIC_API_KEY is set in env / .env
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
    (
        "firsthand_experience.md",
        "FIRSTHAND EXPERIENCE ANCHORS — use ONLY entries where consent_status is "
        "'confirmed' (or 'not_required' for JVL's own operational data) AND "
        "verified_by is filled. Never invent stories, names, dates, or quotes.",
    ),
]

#: Completion budget for the Writer, overridable with WRITER_MAX_TOKENS.
#:
#: Thinking and the answer share this allowance, so it has to hold both. At
#: 8192 a full draft left nothing for the prose, and the API returned an empty
#: message rather than an error — which surfaced in the UI as "Model returned
#: no text content". Above 16000 llm_client streams, which this exceeds.
_DEFAULT_MAX_TOKENS = 32000


def _max_tokens() -> int:
    raw = os.environ.get("WRITER_MAX_TOKENS")
    if not raw:
        return _DEFAULT_MAX_TOKENS
    try:
        value = int(raw)
    except ValueError:
        print(f"  WRITER_MAX_TOKENS={raw!r} is not a number — using "
              f"{_DEFAULT_MAX_TOKENS}", file=sys.stderr)
        return _DEFAULT_MAX_TOKENS
    return value if value > 0 else _DEFAULT_MAX_TOKENS


class WriterAgent:
    """Generates a structured first-draft article from upstream pipeline inputs.

    Outputs a validated JSON dict plus an assembled markdown string.
    All factual claims are grounded in knowledge files and upstream inputs.
    """

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

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    #: Article types whose rules differ from a plain informational piece.
    #:
    #: `article_type` has been in the brief schema since April and read by
    #: nothing. Every genre got the same instructions, so the rules for building
    #: a payback model were also being handed to gift guides — along with an
    #: aside addressed to "a bar owner", which every article was reading.
    _PROFILES: dict[str, str] = {
        "commercial_investigation": "analytical",
        "comparison": "analytical",
    }

    def _profile_for(self, article_type: str | None, has_facts: bool) -> str | None:
        """Which profile this article needs, if any.

        Two triggers, because they answer different questions. The article type
        says what genre this is. Researched facts say there are figures to
        attribute — which can happen in a genre that does not normally have
        them, and the attribution rules should follow the figures.
        """
        by_type = self._PROFILES.get((article_type or "").strip().lower())
        if by_type:
            return by_type
        return "analytical" if has_facts else None

    def _build_system_prompt(
        self,
        article_type: str | None = None,
        has_facts: bool = False,
    ) -> str:
        prompt = self._load_file("prompts/writer_agent.md")

        profile = self._profile_for(article_type, has_facts)
        if profile:
            try:
                prompt += "\n\n---\n\n" + self._load_file(f"prompts/profiles/{profile}.md")
                print(f"Writer profile: {profile}", file=sys.stderr)
            except FileNotFoundError:
                print(f"Warning: profile {profile} not found, skipping.", file=sys.stderr)
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
      "body_markdown": "string (markdown prose with lists/tables/visual placeholders where they fit)"
    }}
  ],
  "internal_links_used": ["string"],
  "suggested_visuals": [
    {{
      "section_heading": "string",
      "type": "image | video | diagram | chart | screenshot",
      "purpose": "string",
      "alt_text_proposal": "string",
      "production_note": "string"
    }}
  ],
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
- Never invent product specs, dimensions, game counts, warranty, pricing.

STRUCTURAL ENRICHMENT RULES (2026 GEO requirement):
- Use a **bulleted or numbered list** in at least one section when the topic
  logically supports one (comparisons of 3+ items, steps, checklists, pros/cons).
  Lists must have ≥ 3 items.
- Use a **markdown table** in at least one section when the article compares
  2+ items across 2+ attributes (specs, use-cases, form factors). Max 6 rows × 4 cols.
- Insert inline visual placeholders of the EXACT form
  `> **[VISUAL]** *type — short description*` where a visual would help.
  Examples of type: image / video / diagram / chart / screenshot.
- Propose 2–5 visuals per article (not after every paragraph; one per major section max).
- The `suggested_visuals` array must contain ONE ENTRY PER `[VISUAL]` placeholder
  in section bodies — counts must match.
- Never propose visuals that would require inventing JVL content (specific named
  customers, employee portraits, unbuilt prototypes). Stick to product, generic
  lifestyle contexts, diagrams, and ECHO software screenshots.

EXPERIENCE-ANCHOR RULES (E-E-A-T):
- Include AT LEAST ONE anchor from FIRSTHAND EXPERIENCE in every article.
- Only use entries where `consent_status` is `confirmed` (or `not_required`
  for JVL's own operational data) AND `verified_by` is filled.
- Skip every entry where `consent_status` is `pending` or `verified_by` is
  null — those are not yet cleared for publication.
- Never invent customer stories, names, quotes, dates, or operational
  figures. Fabricated testimonials violate Canada Competition Act s. 74.01,
  US FTC 16 CFR Part 465, and EU UCPD.
- If no relevant verified anchor exists for the topic, add the literal
  string `TODO: experience anchor needed` to the `todos` array AND inline
  in the section that would have used it. Do not fabricate.
- When using an anchor, paraphrase or quote it faithfully. Generic
  attribution is preferred ("our production team", "a JVL service
  technician"). Never expose internal IDs, ticket numbers, or private
  customer details."""

    def _build_user_message(
        self,
        topic: str,
        brief: dict,
        serp_context: str,
        insight_context: str,
        seo_structure_context: str = "",
        facts_context: str = "",
        revision_feedback: str = "",
        original_article: str = "",
        length_block: str = "",
    ) -> str:
        brief_block = (
            f"# ARTICLE BRIEF\n\n{json.dumps(brief, indent=2, ensure_ascii=False)}"
            if brief
            else "# ARTICLE BRIEF\n\n(no brief provided — write from topic and knowledge base)"
        )

        # The length target goes high in the message, in words, ahead of the
        # research payloads. Buried in the SERP JSON it lost to a hard-coded
        # figure in the system prompt; stated plainly here it is the first
        # instruction the Writer meets after the brief.
        length_section = f"\n{length_block}" if length_block else ""

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

        facts_block = (
            f"\n# RESEARCHED FIGURES — sourced, use these instead of inventing\n"
            f"# Each figure below was found by search and carries its source.\n"
            f"# Build scenarios on the bounds of a range: the pessimistic case at\n"
            f"# the low end, the base case at the typical, the optimistic at the\n"
            f"# high end. Name the source in the text where a figure carries the\n"
            f"# argument. A source of kind 'vendor' or 'own_site' is selling the\n"
            f"# product: it may set an upper bound, never the typical case, and\n"
            f"# whose number it is must be stated. Questions listed under\n"
            f"# 'unanswered' were searched and not answered — say so plainly\n"
            f"# rather than inventing a figure to fill the gap.\n\n"
            f"{facts_context}\n"
            if facts_context
            else ""
        )

        revision_block = (
            f"\n{revision_feedback}\n\n"
            "Apply every required edit above. Keep the same JSON output shape "
            "(h1, intro, sections, internal_links_used, claims_to_verify, todos). "
            "Preserve all JVL facts, brand voice, and claims discipline while "
            "simplifying language.\n"
            if revision_feedback
            else ""
        )

        if original_article:
            original_block = (
                "\n# EXISTING PUBLISHED ARTICLE — YOU ARE REVISING THIS TEXT\n"
                "# Treat this as the baseline. Preserve every section the "
                "update plan does not explicitly modify. Keep prose verbatim "
                "where possible. Output the FULL updated article as JSON — "
                "not a diff, not partial sections.\n\n"
                f"{original_article.strip()}\n"
            )
            opening = (
                "Update the existing article below according to the update "
                "instructions. Preserve everything the diagnostic flagged as "
                "still strong; only change what the plan asks for.\n\n"
                f"Topic: {topic}\n"
            )
        else:
            original_block = ""
            opening = (
                f"Write a complete first-draft article for the following topic.\n\n"
                f"Topic: {topic}\n"
            )

        return (
            f"{opening}\n"
            f"{brief_block}"
            f"{length_section}"
            f"{facts_block}"
            f"{serp_block}"
            f"{insight_block}"
            f"{seo_block}"
            f"{original_block}"
            f"{revision_block}"
            "\nReturn only a valid JSON object. No markdown fences, no commentary."
        )

    # ------------------------------------------------------------------
    # JSON extraction and validation
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_json(raw: str) -> dict:
        """Strip markdown artifacts and parse the first JSON object found.

        Falls back to json-repair when strict parsing fails — long article
        drafts often contain an unescaped quote or trailing comma inside a
        body_markdown string, which would otherwise blow up the whole step.
        """
        raw = raw.strip()
        raw = re.sub(r"^```(?:json)?\s*\n?", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\n?```\s*$", "", raw, flags=re.MULTILINE)
        raw = raw.strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            raw = match.group(0)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            try:
                from json_repair import repair_json
            except ImportError:
                raise exc
            repaired = repair_json(raw, return_objects=True)
            if not isinstance(repaired, dict):
                raise exc
            print(
                f"Writer Agent: recovered malformed JSON via json-repair ({exc}).",
                file=sys.stderr,
            )
            return repaired

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

    # Canonical host for JVL pages. Articles must link to jvl.ca, not to
    # relative paths — those break when the article is previewed anywhere
    # outside the production site (e.g. on the Streamlit app host).
    _JVL_BASE_URL = "https://jvl.ca"
    _JVL_RELATIVE_LINK_RE = re.compile(r"(?<!\w)(/(?:en|fr)/[A-Za-z0-9/_\-]+)")

    @classmethod
    def _absolutize_jvl_links(cls, text: str) -> str:
        """Rewrite any relative JVL paths (`/en/echo`, `/fr/echo`, …) to absolute URLs.

        Belt-and-braces: prompts already instruct the model to emit absolute
        URLs, but this defensive pass catches any straggling relative paths
        from older drafts, knowledge-base examples, or model lapses.
        """
        if not text:
            return text
        return cls._JVL_RELATIVE_LINK_RE.sub(lambda m: f"{cls._JVL_BASE_URL}{m.group(1)}", text)

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

        return WriterAgent._absolutize_jvl_links("\n".join(lines).strip())

    # ------------------------------------------------------------------
    # Auth mode 1: Anthropic (requires ANTHROPIC_API_KEY)
    # ------------------------------------------------------------------

    def _run_via_sdk(self, system_prompt: str, user_message: str) -> dict:
        from src import llm_client

        # This loop used to live here, and it was the only one in the codebase.
        # Ten other agents parsed once and gave up, which cost two runs their
        # whole prose-revision pass over a missing comma. It now lives in
        # llm_client so there is one implementation instead of eleven chances
        # for them to drift apart.
        return llm_client.chat_json(
            system_prompt,
            user_message,
            self._extract_json,
            max_tokens=_max_tokens(),
            tier=self.tier,
            label="Writer",
        )

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
        facts_context: str = "",
        revision_feedback: str = "",
        original_article: str = "",
        comparable_length: dict | None = None,
    ) -> dict:
        """Run the Writer Agent and return the raw LLM output dict.

        Args:
            topic:                 Article topic (plain text).
            brief:                 Optional brief dict from Brief Agent.
            serp_context:          Optional pre-formatted SERP summary string.
            insight_context:       Optional pre-formatted company insight summary string.
            seo_structure_context: Optional SEO outline JSON string from SEO Structure Agent.
            comparable_length:     Optional `comparable_length` block from SERP
                                   research. Turned into an explicit word target
                                   and handed over before the first draft.

        Returns:
            Dict with keys: h1, intro, sections, internal_links_used,
            claims_to_verify, todos.
        """
        from src import length_target

        print("Writer Agent: loading knowledge files...", file=sys.stderr)

        target = length_target.resolve(comparable_length)
        if target["measured"]:
            print(
                f"Writer length target: {target['low']}-{target['high']} words "
                f"(median {target['median']}, {target['sample_size']} article(s))",
                file=sys.stderr,
            )
        else:
            print(
                f"Writer length target: {target['low']}-{target['high']} words "
                "(no article ranked — default, not a measurement)",
                file=sys.stderr,
            )

        system_prompt = self._build_system_prompt(
            article_type=(brief or {}).get("article_type"),
            has_facts=bool(facts_context),
        )
        user_message = self._build_user_message(
            topic=topic,
            brief=brief or {},
            serp_context=serp_context,
            insight_context=insight_context,
            seo_structure_context=seo_structure_context,
            facts_context=facts_context,
            revision_feedback=revision_feedback,
            original_article=original_article,
            length_block=length_target.render(target),
        )

        if self.api_key:
            print(f"Auth: Anthropic (tier: {self.tier})", file=sys.stderr)
            result = self._run_via_sdk(system_prompt, user_message)
        else:
            print(f"Auth: Claude Agent SDK (model: {self.model})", file=sys.stderr)
            result = self._run_via_agent_sdk(system_prompt, user_message)

        self._validate(result)
        return result
