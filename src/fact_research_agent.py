"""Fact Research Agent — JVL Content Engine.

Pipeline position:
  Brief → **Fact Research** → SERP Research → Company Insight → SEO Structure → Writer

Purpose:
  Establish what is actually known about the quantities an article will state,
  with sources, using Anthropic's server-side web search.

  This is not SERP research. That step studies what competitors publish; this
  one asks what the numbers really are. The distinction matters because an
  article modelled three payback scenarios on $30, $75 and $160 a week, every
  figure invented and honestly labelled illustrative, while a single search
  found published ranges of $50-$150, "a minimum of $200 per week", and an
  operator running two thousand machines reporting EUR 45-60 on weekend days.
  The data existed. No step in the pipeline was looking for it.

  Search runs on Anthropic's infrastructure rather than ours, which is the
  point: our own fetcher gets 6 characters back from Reddit and 82 from
  Facebook, and those are exactly where operators discuss takings instead of
  selling machines.

Auth modes (mirrors the other agents):
  1. Anthropic (via src.llm_client) — when ANTHROPIC_API_KEY is set
  2. Disabled — without a key there is no search, and the step is skipped
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import jsonschema

#: Domains that sell what the article discusses. Their figures are still worth
#: having — they are often the only public numbers — but they are marked so the
#: Writer cannot mistake a sales page for a survey.
_OWN_DOMAINS = ("jvl.ca", "jvl.com")


class FactResearchAgent:
    """Finds sourced figures for the quantities an article will assert."""

    def __init__(self) -> None:
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.tier = "standard"
        self.max_searches = 12
        self.repo_root = Path(__file__).parent.parent

    # ------------------------------------------------------------------
    # File loading
    # ------------------------------------------------------------------

    def _load_file(self, path: str) -> str:
        return (self.repo_root / path).read_text(encoding="utf-8")

    def _load_schema(self) -> dict:
        return json.loads(self._load_file("schemas/fact_research_schema.json"))

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        prompt = self._load_file("prompts/fact_research_agent.md")
        schema = self._load_file("schemas/fact_research_schema.json")
        return f"{prompt}\n\n---\n\n# OUTPUT JSON SCHEMA\n\n{schema}\n"

    def _build_user_message(
        self,
        topic: str,
        brief: dict | None,
        country: str,
        language: str,
        budget: int,
    ) -> str:
        parts = [
            f"Establish the figures this article will need.\n\nTopic: {topic}\n",
            f"Market: {country.upper()}; language: {language}.\n",
            "Report every figure in the currency and period a reader of that "
            "market expects, and say in caveats when you converted.\n",
        ]
        if brief:
            parts.append(
                "\n# ARTICLE BRIEF — derive the research questions from what "
                "this article will have to assert\n\n"
                + json.dumps(brief, indent=2, ensure_ascii=False)
                + "\n"
            )
        parts.append(
            f"\nYou have at most {budget} searches. Plan your queries to fit "
            "them, and if you hit the limit, write up what you already found "
            "rather than reporting nothing.\n"
            "\nSearch the questions, not the article keyword. Return only a "
            "valid JSON object matching the schema. No markdown, no commentary."
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
        match = re.search(r"\{.*\}", raw.strip(), re.DOTALL)
        if match:
            raw = match.group(0)
        return json.loads(raw)

    @staticmethod
    def _normalise(result: dict) -> dict:
        """Fill the holes a model leaves so the schema check has less to reject.

        A 14-search run was thrown away because one finding came back with
        ``"range": null``: the schema wants an object there, validation raised,
        and nothing was written or returned. Every search had already been
        paid for. Missing or malformed fields get a placeholder the Writer can
        recognise ("n/a", "unknown", an empty string) rather than costing the
        whole result.
        """
        findings = result.get("findings")
        if not isinstance(findings, list):
            findings = []
        result["findings"] = [f for f in findings if isinstance(f, dict)]
        for finding in result["findings"]:
            if not isinstance(finding.get("range"), dict):
                finding["range"] = {
                    "low": "n/a", "typical": "n/a", "high": "n/a", "unit": "n/a"
                }
            for key in ("low", "typical", "high", "unit"):
                finding["range"].setdefault(key, "n/a")
            finding.setdefault("confidence", "medium")
            if not isinstance(finding.get("sources"), list):
                finding["sources"] = []
            finding["sources"] = [s for s in finding["sources"] if isinstance(s, dict)]
            for source in finding["sources"]:
                source.setdefault("kind", "unknown")
                source.setdefault("figure", "")
                source.setdefault("url", "")
        if not isinstance(result.get("unanswered"), list):
            result["unanswered"] = []
        return result

    def _validate(self, result: dict) -> dict:
        """Check the result against the schema, but never discard it.

        Normalisation handles the shapes we have seen go wrong. Whatever it
        could not fix is logged, like the FAQ agent does, and the findings are
        still returned: a run with one odd field is worth far more than no run.
        """
        try:
            jsonschema.validate(result, self._load_schema())
            print("Fact Research schema validation: PASSED", file=sys.stderr)
        except jsonschema.ValidationError as exc:
            path = "/".join(str(p) for p in exc.absolute_path) or "<root>"
            print(
                f"Fact Research schema validation WARNING at {path}: {exc.message}",
                file=sys.stderr,
            )
        return result

    # ------------------------------------------------------------------
    # Source classification
    # ------------------------------------------------------------------

    @staticmethod
    def _mark_own_sources(result: dict) -> dict:
        """Relabel our own site whatever the model called it.

        Citing jvl.ca as independent evidence for how much a machine earns is
        circular, and a reader who follows the link and lands on our own blog
        stops believing the rest of the article. A live search returned exactly
        that page among its results.
        """
        for finding in result.get("findings", []) or []:
            for source in finding.get("sources", []) or []:
                url = (source.get("url") or "").lower()
                if any(domain in url for domain in _OWN_DOMAINS):
                    source["kind"] = "own_site"
        return result

    @staticmethod
    def _demote_vendor_only_findings(result: dict) -> dict:
        """Flag a finding whose every source is selling something.

        Such a figure is not evidence of what a machine earns; it is evidence of
        what sellers say it earns. It stays in the output — often it is the only
        public number — but the Writer is told what it is.
        """
        interested = {"vendor", "own_site"}
        for finding in result.get("findings", []) or []:
            kinds = {
                (s.get("kind") or "unknown") for s in finding.get("sources", []) or []
            }
            if kinds and kinds <= interested:
                finding["confidence"] = "low"
                note = (
                    "Every source for this figure sells the product. Treat it as "
                    "an upper bound and say whose number it is; it may not be the "
                    "typical case."
                )
                existing = finding.get("caveats") or ""
                finding["caveats"] = f"{existing} {note}".strip()
        return result

    # ------------------------------------------------------------------
    # Debug dump
    # ------------------------------------------------------------------

    @staticmethod
    def _dump_raw(raw: str, sources: list, debug_dir: str | Path | None) -> None:
        """Write the model's text before anything can go wrong with it."""
        target = debug_dir or os.environ.get("FACT_RESEARCH_DEBUG_DIR")
        if not target:
            return
        try:
            directory = Path(target)
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "facts-raw.txt").write_text(raw, encoding="utf-8")
            (directory / "facts-pages-seen.json").write_text(
                json.dumps(sources, indent=1, ensure_ascii=False), encoding="utf-8"
            )
            print(f"  raw model text saved to {directory}", file=sys.stderr)
        except OSError as exc:
            print(f"  could not save raw model text: {exc}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(
        self,
        topic: str,
        brief: dict | None = None,
        country: str = "US",
        language: str = "en",
        max_searches: int | None = None,
        debug_dir: str | Path | None = None,
    ) -> dict:
        """Search for the article's figures and return a validated result.

        ``debug_dir`` (or the FACT_RESEARCH_DEBUG_DIR environment variable)
        names a directory where the raw model text is written before parsing,
        so a run that fails later can still be recovered by hand.
        """
        if not self.api_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY is required for fact research — web search "
                "runs server-side."
            )

        from src import llm_client

        system_prompt = self._build_system_prompt()
        budget = max_searches or self.max_searches
        user_message = self._build_user_message(topic, brief, country, language, budget)

        print(f"Fact Research Agent: searching (tier: {self.tier})", file=sys.stderr)
        raw, sources, searches = llm_client.chat_with_search(
            system_prompt,
            user_message,
            tier=self.tier,
            max_searches=budget,
        )
        print(
            f"  {searches} searches, {len(sources)} distinct pages seen",
            file=sys.stderr,
        )

        self._dump_raw(raw, sources, debug_dir)

        result = self._extract_json(raw)
        result.setdefault("topic", topic)
        result.setdefault("findings", [])
        result.setdefault("unanswered", [])
        result["searches_performed"] = searches

        result = self._normalise(result)
        result = self._mark_own_sources(result)
        result = self._demote_vendor_only_findings(result)

        result = self._validate(result)
        print(
            f"  {len(result['findings'])} figures sourced, "
            f"{len(result['unanswered'])} questions left open",
            file=sys.stderr,
        )
        return result
