"""Pipeline orchestration — the one path every entry point runs.

Extracted from `app.py`, where it used to live. Streamlit was not the only
caller: `run_article.py` had its own copy of the wiring, and the two drifted —
the CLI never gained the Readability, FAQ or Diagnostic agents added in May,
and the Streamlit path never gained the Visual Agent. Whichever entry point
you used silently changed which agents ran.

Both pipelines are generators that yield progress events:

    {"step": 3, "label": "Company Insight", "status": "running"}
    {"step": 0, "label": "done", "status": "done", "results": {...}}

so a caller renders progress however it likes — `st.status()`, a print, or
nothing at all — without this module knowing anything about a UI.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from src.agents import BriefAgent
from src.fact_research_agent import FactResearchAgent
from src.serp_research_agent import SerpResearchAgent
from src.company_insight_agent import CompanyInsightAgent
from src.seo_structure_agent import SeoStructureAgent
from src.writer_agent import WriterAgent
from src.readability_agent import ReadabilityChecker, prose_problems, score_markdown
from src.faq_agent import FAQAgent
from src import length_target, sources_block
from src.qa_agent import QAAgent
from src.metadata_copy_agent import MetadataCopyAgent
from src.article_diagnostic_agent import ArticleDiagnosticAgent
from src.history_store import HistoryUnavailable, save_to_history

OUTPUT_ROOT = Path("outputs")

#: How many times a failing QA report may send the article back to the Writer.
#:
#: One is the useful setting. The first pass fixes the concrete defects — an
#: arithmetic slip, a leaked TODO, an unhedged claim. Past that the reviewer
#: starts trading one wording for another, and each round costs a full Writer
#: and QA call on the heavy tier. Set QA_MAX_REVISIONS=0 to record the verdict
#: without acting on it, which is how the pipeline behaved before.
_DEFAULT_QA_MAX_REVISIONS = 1

#: A revision that returns less than this share of the original is treated as
#: damage, not an edit.
_MIN_REVISION_LENGTH_RATIO = 0.75

_IMAGE_URL_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _reuse(path: Path, label: str, reuse: bool) -> dict | None:
    """Return a previous run's output for a step, if we are allowed to.

    The steps before the Writer are the expensive half — Fact Research pays for
    web searches, and four more agents run before a single word is written. When
    the Writer then times out, the whole run is thrown away and paid for again
    from the top. This lets an attempt pick up what the last one already
    established.

    Deliberately narrow: only the steps whose output is a function of the topic
    and keyword, nothing downstream of the draft. A stale brief for the same
    topic is the same brief; a stale draft is a different article.
    """
    if not reuse or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  {label}: could not reuse {path.name} ({exc}) — running it", file=sys.stderr)
        return None
    print(f"  {label}: reusing {path}", file=sys.stderr)
    return data


def fact_research_enabled() -> bool:
    """Whether to spend searches establishing the article's figures.

    Off unless asked. Search is billed per query on top of tokens, and a caller
    writing a piece with no quantities in it should not pay for research it will
    not use.
    """
    return os.environ.get("FACT_RESEARCH", "false").strip().lower() == "true"


def qa_max_revisions() -> int:
    """How many Writer passes a failing QA report may trigger."""
    raw = os.environ.get("QA_MAX_REVISIONS")
    if not raw:
        return _DEFAULT_QA_MAX_REVISIONS
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_QA_MAX_REVISIONS
    return value if value >= 0 else _DEFAULT_QA_MAX_REVISIONS


def revision_damage(before: str, after: str) -> str | None:
    """Return why a revision must be rejected, or None if it is safe to accept.

    The Writer is handed the finished article — images injected, FAQ appended —
    and asked to change only what QA named. It is capable of returning a clean
    article that quietly dropped the pictures or the Q&A block along the way,
    and a silent loss is worse than the defect being fixed. So the revision has
    to prove it kept what it was given before it replaces anything.
    """
    if not after or not after.strip():
        return "the revision came back empty"

    if len(after) < len(before) * _MIN_REVISION_LENGTH_RATIO:
        return (
            f"the revision is {len(after)} characters against {len(before)} — "
            "too much of the article went missing to call it an edit"
        )

    lost_images = [
        url for url in _IMAGE_URL_RE.findall(before) if url not in after
    ]
    if lost_images:
        return f"{len(lost_images)} image(s) dropped, first was {lost_images[0]}"

    if "## FAQ" in before and "## FAQ" not in after:
        return "the FAQ section was dropped"

    return None


#: Canonical step order. Callers render progress from this list, so a step can
#: never be added to the pipeline without appearing in the UI, or vice versa.
PIPELINE_STEPS = [
    "Brief",
    "Fact Research",
    "SERP Research",
    "Company Insight",
    "SEO Structure",
    "Writer",
    "Readability Checker",
    "FAQ Agent",
    "QA Review",
    "Metadata",
]

#: Steps a caller may skip. Everything else always runs.
SKIPPABLE = {"Fact Research", "SERP Research", "Company Insight", "SEO Structure",
             "Readability Checker", "Visual Agent", "FAQ Agent",
             "QA Review", "Metadata"}


def pipeline_steps(with_visuals: bool = False) -> list[str]:
    """Step labels in order, for a caller that wants to render progress."""
    steps = list(PIPELINE_STEPS)
    if with_visuals:
        # Images are placed among the body headings, so they go in before the
        # FAQ block is appended to the end.
        steps.insert(steps.index("FAQ Agent"), "Visual Agent")
    return steps


#: Step order for the Article Update pipeline (Update tab / `--update`).
UPDATE_STEPS = [
    "SERP Research (fresh)",
    "Company Insight (fresh)",
    "Article Diagnostic",
    "Writer (update mode)",
    "Readability Checker",
    "FAQ Agent (refresh)",
    "QA Review",
    "Metadata (refresh)",
]


def _event(steps: list[str], label: str, status: str) -> dict:
    return {"step": steps.index(label) + 1, "label": label, "status": status}


class _StepSkipped(Exception):
    """Raised at the top of a step body when the caller asked to skip it.

    Every optional step already runs inside `try/except`, so raising here
    lands in the same handler as a failure and leaves the step's results at
    their defaults — which is exactly what skipping means.
    """


def _guard(skip: set[str], label: str) -> None:
    if label in skip:
        raise _StepSkipped(label)


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text)
    return text.strip("-")[:60]


def _save_json(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


# ─── Pipeline helpers ─────────────────────────────────────────────────────────

def _build_facts_context(facts: dict) -> str:
    """Render researched figures for the Writer.

    Kept narrow on purpose. The Writer needs the number, its bounds, where it
    came from and how far to trust it — not the whole record.
    """
    findings = []
    for f in facts.get("findings", []) or []:
        findings.append({
            "question": f.get("question"),
            "range": f.get("range"),
            "confidence": f.get("confidence"),
            "caveats": f.get("caveats"),
            "sources": [
                {
                    "kind": s.get("kind"),
                    "url": s.get("url"),
                    "said": s.get("figure"),
                    "date": s.get("date"),
                }
                for s in (f.get("sources") or [])
            ],
        })
    payload = {
        "findings": findings,
        "unanswered": facts.get("unanswered", []),
        "notes_for_writer": facts.get("notes_for_writer", []),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _build_serp_context(serp_data: dict) -> str:
    fields = {
        "serp_status": serp_data.get("serp_status"),
        "dominant_search_intent": serp_data.get("dominant_search_intent"),
        "content_gaps": serp_data.get("content_gaps", []),
        "differentiation_opportunities": serp_data.get("differentiation_opportunities", []),
        "competitor_weaknesses": serp_data.get("competitor_weaknesses", []),
        "risks_to_avoid": serp_data.get("risks_to_avoid", []),
        "notes_for_writer": serp_data.get("notes_for_writer", []),
        "comparable_length": serp_data.get("comparable_length"),
    }
    return json.dumps(fields, indent=2, ensure_ascii=False)


def _build_insight_context(insight_data: dict) -> str:
    fields = {
        "relevant_jvl_angles": insight_data.get("relevant_jvl_angles", []),
        "relevant_product_facts": insight_data.get("relevant_product_facts", []),
        "natural_product_injection_points": insight_data.get("natural_product_injection_points", []),
        "unique_brand_perspective": insight_data.get("unique_brand_perspective"),
        "eeat_signals": insight_data.get("eeat_signals", []),
        "persona_hooks": insight_data.get("persona_hooks", []),
        "trust_signals": insight_data.get("trust_signals", []),
        "claims_to_verify": insight_data.get("claims_to_verify", []),
        "forbidden_claims": insight_data.get("forbidden_claims", []),
        "risks_to_avoid": insight_data.get("risks_to_avoid", []),
        "notes_for_writer": insight_data.get("notes_for_writer", []),
    }
    return json.dumps(fields, indent=2, ensure_ascii=False)


def _build_risks(brief: dict, insight_data: dict | None) -> list[str]:
    risks: list[str] = list(brief.get("risks_to_avoid", []))
    if insight_data:
        for r in insight_data.get("risks_to_avoid", []):
            if r not in risks:
                risks.append(r)
    return risks


def run_pipeline(
    topic: str,
    primary_keyword: str,
    funnel_stage: str,
    secondary_keywords: list[str],
    custom_requirements: str,
    *,
    output_root: Path | None = None,
    skip: set[str] | None = None,
    with_visuals: bool = False,
    reuse: bool = False,
    country: str = "US",
    language: str = "en",
):
    """Run the article pipeline; yields progress events, ends with a results dict.

    `skip` takes labels from `SKIPPABLE`; `with_visuals` adds the Visual Agent.
    Both default to the Streamlit behaviour, so existing callers are unchanged.
    """
    root = output_root or OUTPUT_ROOT
    skip = skip or set()
    steps = pipeline_steps(with_visuals)
    results: dict = {}

    content_goal = "drive product consideration and support organic search traffic"
    if secondary_keywords:
        content_goal += f". Also incorporate these secondary keywords naturally: {', '.join(secondary_keywords)}"
    if custom_requirements:
        content_goal += f". Additional requirements from editor: {custom_requirements}"

    # Step 1 — Brief
    yield _event(steps, "Brief", "running")
    brief_agent = BriefAgent()
    brief_path = root / "briefs" / f"{slugify(primary_keyword)}.json"
    brief = _reuse(brief_path, "Brief", reuse)
    if brief is None:
        brief = brief_agent.run(
            topic=topic,
            primary_keyword=primary_keyword,
            content_goal=content_goal,
            funnel_stage=funnel_stage,
            audience="Mark & Linda Reynolds",
            country=country,
            language=language,
        )
        brief_slug = slugify(brief.get("primary_keyword", primary_keyword))
        brief_path = root / "briefs" / f"{brief_slug}.json"
        _save_json(brief, brief_path)
    results["brief"] = brief
    results["brief_path"] = brief_path
    yield _event(steps, "Brief", "done")

    topic_slug = slugify(topic)

    # Step 2 — Fact Research
    #
    # What the article's numbers actually are, with sources. Distinct from SERP
    # research, which is about what competitors published. Off by default: it
    # costs a cent a search on top of tokens, and a caller who does not need
    # sourced figures should not pay for them.
    yield _event(steps, "Fact Research", "running")
    facts: dict | None = None
    facts_path: Path | None = None
    try:
        _guard(skip, "Fact Research")
        facts_path = root / "facts" / f"{topic_slug}.json"
        facts = _reuse(facts_path, "Fact Research", reuse)
        if facts is None:
            if not fact_research_enabled():
                facts_path = None
                raise _StepSkipped("Fact Research")
            facts = FactResearchAgent().run(
                topic=topic, brief=brief, country=country, language=language
            )
            _save_json(facts, facts_path)
    except _StepSkipped:
        pass
    except Exception as exc:
        print(f"Fact Research failed: {exc}", file=sys.stderr)
    results["facts"] = facts
    results["facts_path"] = facts_path
    yield _event(steps, "Fact Research", "done")

    # Step 3 — SERP Research
    yield _event(steps, "SERP Research", "running")
    serp_data: dict | None = None
    serp_path: Path | None = None
    try:
        _guard(skip, "SERP Research")
        serp_path = root / "serp_research" / f"{slugify(primary_keyword)}.json"
        serp_data = _reuse(serp_path, "SERP Research", reuse)
        if serp_data is None:
            serp_agent = SerpResearchAgent()
            serp_data = serp_agent.run(
                primary_keyword=primary_keyword,
                topic=topic,
                brief=brief,
                country="us",
                language="en",
                top_n=10,
                paa_questions=brief.get("questions_to_answer", []),
            )
            _save_json(serp_data, serp_path)
    except Exception:
        pass
    results["serp_data"] = serp_data
    results["serp_path"] = serp_path

    # Pulled out here, ahead of the Writer, because it is the one SERP field the
    # Writer needs before it writes a word rather than after. It stays a plain
    # measurement; length_target.resolve turns it into a band.
    comparable_length = (serp_data or {}).get("comparable_length")
    yield _event(steps, "SERP Research", "done")

    # Step 3 — Company Insight
    yield _event(steps, "Company Insight", "running")
    insight_data: dict | None = None
    insight_path: Path | None = None
    extra_context = ""
    if serp_data:
        context_fields = {
            "serp_status": serp_data.get("serp_status"),
            "dominant_search_intent": serp_data.get("dominant_search_intent"),
            "content_gaps": serp_data.get("content_gaps", []),
            "differentiation_opportunities": serp_data.get("differentiation_opportunities", []),
            "competitor_weaknesses": serp_data.get("competitor_weaknesses", []),
            "notes_for_writer": serp_data.get("notes_for_writer", []),
        }
        extra_context = (
            "SERP research summary (from SERP Research Agent):\n"
            + json.dumps(context_fields, indent=2, ensure_ascii=False)
        )
    try:
        _guard(skip, "Company Insight")
        insight_path = root / "company_insight" / f"{topic_slug}.json"
        insight_data = _reuse(insight_path, "Company Insight", reuse)
        if insight_data is None:
            insight_agent = CompanyInsightAgent()
            insight_data = insight_agent.run(
                topic=topic,
                brief=brief,
                extra_context=extra_context,
            )
            _save_json(insight_data, insight_path)
    except Exception:
        pass
    results["insight_data"] = insight_data
    results["insight_path"] = insight_path
    yield _event(steps, "Company Insight", "done")

    # Step 4 — SEO Structure
    yield _event(steps, "SEO Structure", "running")
    seo_data: dict | None = None
    seo_path: Path | None = None
    try:
        _guard(skip, "SEO Structure")
        seo_path = root / "seo_structure" / f"{topic_slug}.json"
        seo_data = _reuse(seo_path, "SEO Structure", reuse)
        if seo_data is None:
            seo_agent = SeoStructureAgent()
            seo_data = seo_agent.run(topic=topic, brief=brief)
            _save_json(seo_data, seo_path)
    except Exception:
        pass
    results["seo_data"] = seo_data
    yield _event(steps, "SEO Structure", "done")

    # Step 5 — Writer
    yield _event(steps, "Writer", "running")
    serp_context = _build_serp_context(serp_data) if serp_data else ""
    insight_context = _build_insight_context(insight_data) if insight_data else ""
    facts_context = _build_facts_context(facts) if facts else ""
    seo_structure_context = json.dumps(seo_data, indent=2, ensure_ascii=False) if seo_data else ""
    writer_agent = WriterAgent()
    try:
        draft_result = writer_agent.run(
            topic=topic,
            brief=brief,
            serp_context=serp_context,
            insight_context=insight_context,
            seo_structure_context=seo_structure_context,
            facts_context=facts_context,
            comparable_length=comparable_length,
        )
    except Exception as exc:
        # Every other step catches its own failure and lets the run continue;
        # this one could not, and a Writer timeout therefore threw a traceback
        # and discarded the whole run — twelve paid searches, five completed
        # steps, and half an hour, with the intermediate files left on disk in
        # a state nothing could resume from.
        #
        # There is still no article without a draft, so the pipeline stops. But
        # it stops by reporting, with the research it already has attached, so
        # the next attempt can reuse the expensive part.
        print(f"Writer failed: {exc}", file=sys.stderr)
        results["error"] = f"Writer failed: {exc}"
        results["failed_step"] = "Writer"
        results["draft_markdown"] = ""
        yield _event(steps, "Writer", "done")
        yield {"step": 0, "label": "failed", "status": "failed", "results": results}
        return
    draft_markdown = writer_agent.assemble_markdown(draft_result)

    # Land the Writer's output on disk before anything else touches it.
    #
    # It used to be held in memory through readability, images, the FAQ and the
    # sources block, and only written at the end. So any hang in those four
    # steps threw away the single most expensive call in the pipeline, and
    # --resume — built for exactly this — had nothing to resume from. The raw
    # draft is written here and overwritten in place once the later steps have
    # enriched it.
    raw_md_path = root / "drafts" / f"{topic_slug}.md"
    raw_md_path.parent.mkdir(parents=True, exist_ok=True)
    raw_md_path.write_text(draft_markdown, encoding="utf-8")
    _save_json(draft_result, root / "drafts" / f"{topic_slug}.raw.json")

    yield _event(steps, "Writer", "done")

    # Step 6 — Readability Checker (Flesch Reading Ease >= 90, up to 3 rewrites)
    yield _event(steps, "Readability Checker", "running")
    readability_report: dict | None = None
    readability_path: Path | None = None
    try:
        _guard(skip, "Readability Checker")
        readability = ReadabilityChecker()

        def _rewrite(feedback: str) -> dict:
            return writer_agent.run(
                topic=topic,
                brief=brief,
                serp_context=serp_context,
                insight_context=insight_context,
                seo_structure_context=seo_structure_context,
                facts_context=facts_context,
                revision_feedback=feedback,
                comparable_length=comparable_length,
            )

        readability_report = readability.run(
            draft_result=draft_result,
            draft_markdown=draft_markdown,
            rewrite_fn=_rewrite,
            assemble_markdown_fn=writer_agent.assemble_markdown,
            word_target=length_target.resolve(comparable_length),
        )
        draft_result = readability_report["final_result"]
        draft_markdown = readability_report["final_markdown"]
        readability_path = root / "readability" / f"{topic_slug}.json"
        _save_json(readability_report, readability_path)
    except _StepSkipped:
        pass
    except Exception as exc:
        print(f"Readability Checker failed: {exc}", file=sys.stderr)
    results["readability_report"] = readability_report
    results["readability_path"] = readability_path
    yield _event(steps, "Readability Checker", "done")

    companion = {
        "topic": topic,
        "working_title": brief.get("working_title", draft_result.get("h1", "")),
        "primary_keyword": brief.get("primary_keyword", ""),
        "search_intent": brief.get("search_intent", ""),
        "funnel_stage": brief.get("funnel_stage", ""),
        "product_fit": brief.get("product_fit", ""),
        "draft_markdown": draft_markdown,
        "claims_to_verify": draft_result.get("claims_to_verify", []),
        "source_inputs_used": {
            "brief": str(brief_path),
            "serp_research": str(serp_path) if serp_path else None,
            "company_insight": str(insight_path) if insight_path else None,
            "seo_structure": str(seo_path) if seo_path else None,
            "readability_report": str(readability_path) if readability_path else None,
        },
        "risks_to_review": _build_risks(brief, insight_data),
        "internal_links_used": draft_result.get("internal_links_used", []),
        "suggested_visuals": draft_result.get("suggested_visuals", []),
        "todos": draft_result.get("todos", []),
        "readability": {
            "final_score": readability_report["final_score"],
            "target_score": readability_report["target_score"],
            "passed": readability_report["passed"],
            "iterations_run": len(readability_report["iterations"]),
        }
        if readability_report
        else None,
        "length_check": (readability_report or {}).get("length_check"),
    }
    results["length_check"] = (readability_report or {}).get("length_check")
    # Visual Agent — generates images and inserts them among the body
    # headings. Runs before the FAQ block is appended so images land in the
    # article, not in the Q&A.
    if with_visuals:
        yield _event(steps, "Visual Agent", "running")
        visual_result: dict | None = None
        visual_path: Path | None = None
        try:
            _guard(skip, "Visual Agent")
            from src.visual_agent import VisualAgent

            visual_agent = VisualAgent()
            visual_result = visual_agent.run(
                topic=topic,
                brief=brief,
                draft_markdown=draft_markdown,
                output_dir=root / "images" / topic_slug,
            )
            draft_markdown = visual_result.get("enriched_markdown", draft_markdown)
            visual_path = root / "visuals" / f"{topic_slug}.json"
            _save_json(visual_result, visual_path)
        except _StepSkipped:
            pass
        except Exception as exc:
            print(f"Visual Agent failed: {exc}", file=sys.stderr)
        results["visual_result"] = visual_result
        results["visual_path"] = visual_path
        companion["draft_markdown"] = draft_markdown
        yield _event(steps, "Visual Agent", "done")

    # Step — FAQ
    yield _event(steps, "FAQ Agent", "running")
    faq_result: dict | None = None
    faq_markdown: str = ""
    faq_json_ld: str = ""
    faq_path: Path | None = None
    faq_jsonld_path: Path | None = None
    try:
        _guard(skip, "FAQ Agent")
        faq_agent = FAQAgent()
        faq_result = faq_agent.run(
            topic=topic,
            draft_markdown=draft_markdown,
            brief=brief,
            serp_data=serp_data,
            insight_data=insight_data,
        )
        faq_markdown = faq_agent.assemble_markdown(faq_result)
        draft_markdown = faq_agent.append_to_article(draft_markdown, faq_markdown)
        faq_path = root / "faq" / f"{topic_slug}.json"
        _save_json(faq_result, faq_path)

        faq_json_ld = faq_agent.assemble_json_ld(faq_result)
        if faq_json_ld:
            faq_jsonld_path = root / "faq" / f"{topic_slug}.jsonld"
            faq_jsonld_path.parent.mkdir(parents=True, exist_ok=True)
            faq_jsonld_path.write_text(faq_json_ld, encoding="utf-8")
    except _StepSkipped:
        pass
    except Exception as exc:
        print(f"FAQ Agent failed: {exc}", file=sys.stderr)
    results["faq_result"] = faq_result
    results["faq_markdown"] = faq_markdown
    results["faq_json_ld"] = faq_json_ld
    results["faq_path"] = faq_path
    results["faq_jsonld_path"] = faq_jsonld_path

    companion["draft_markdown"] = draft_markdown
    companion["faq_items"] = (faq_result or {}).get("items", [])
    companion["faq_json_ld"] = faq_json_ld
    companion["source_inputs_used"]["faq"] = str(faq_path) if faq_path else None
    companion["source_inputs_used"]["faq_json_ld"] = (
        str(faq_jsonld_path) if faq_jsonld_path else None
    )

    # Sources, after the FAQ so it closes the article, and before QA so the
    # reviewer sees what a reader will. Empty unless the research found enough
    # to be worth listing — a bibliography under a piece that needed one figure
    # is imitation scholarship.
    sources_markdown = sources_block.render(facts) if facts else ""
    if sources_markdown:
        draft_markdown = sources_block.append_to_article(draft_markdown, sources_markdown)
        companion["draft_markdown"] = draft_markdown
        print(
            f"  Sources block: {len(sources_block.select_sources(facts))} listed",
            file=sys.stderr,
        )
    results["sources_markdown"] = sources_markdown

    draft_md_path = root / "drafts" / f"{topic_slug}.md"
    draft_json_path = root / "drafts" / f"{topic_slug}.json"
    draft_md_path.parent.mkdir(parents=True, exist_ok=True)
    draft_md_path.write_text(draft_markdown, encoding="utf-8")
    _save_json(companion, draft_json_path)
    results["draft_markdown"] = draft_markdown
    results["draft_md_path"] = draft_md_path
    results["companion"] = companion
    results["suggested_visuals"] = draft_result.get("suggested_visuals", []) or []
    if results["suggested_visuals"]:
        _save_json(
            {"suggested_visuals": results["suggested_visuals"]},
            root / "visuals" / f"{topic_slug}.json",
        )
    results["draft_json_path"] = draft_json_path
    yield _event(steps, "FAQ Agent", "done")

    # Step 8 — QA (reviews full draft including FAQ block)
    #
    # A failing report used to end here: it was written to disk, shown as a
    # status, and nothing acted on it. The Writer never saw it. So the loop
    # below sends the findings back and re-reviews the result — the same
    # arrangement the Readability Checker and the update pipeline already use.
    yield _event(steps, "QA Review", "running")
    qa_report: dict | None = None
    qa_path: Path | None = None
    qa_history: list[dict] = []
    qa_source_inputs = {
        "draft": str(draft_json_path),
        "brief": str(brief_path),
        "serp_research": str(serp_path) if serp_path else None,
        "company_insight": str(insight_path) if insight_path else None,
    }

    def _review(markdown: str) -> dict:
        return QAAgent().run(
            topic=topic,
            draft_markdown=markdown,
            draft_wrapper=companion,
            brief=brief,
            serp_data=serp_data,
            insight_data=insight_data,
            source_inputs_used=qa_source_inputs,
        )

    try:
        _guard(skip, "QA Review")
        qa_report = _review(draft_markdown)
        qa_path = root / "qa" / f"{topic_slug}.json"
        _save_json(qa_report, qa_path)
        qa_history.append(qa_report)

        budget = qa_max_revisions()
        attempt = 0
        while (
            attempt < budget
            and qa_report.get("status") in {"fail", "revise"}
        ):
            feedback = QAAgent.format_for_writer(qa_report)
            if not feedback:
                print(
                    "QA: nothing in this report is the Writer's to fix — "
                    "leaving the draft alone.",
                    file=sys.stderr,
                )
                break

            attempt += 1
            print(
                f"QA: status={qa_report.get('status')} — revision {attempt}/{budget}",
                file=sys.stderr,
            )
            revised_result = writer_agent.run(
                topic=topic,
                brief=brief,
                serp_context=serp_context,
                insight_context=insight_context,
                seo_structure_context=seo_structure_context,
                facts_context=facts_context,
                revision_feedback=feedback,
                original_article=draft_markdown,
                comparable_length=comparable_length,
            )
            revised_markdown = writer_agent.assemble_markdown(revised_result)

            # Put the FAQ back rather than hoping the Writer kept it. It does
            # not: its own system prompt tells it a separate agent owns the FAQ
            # and to leave a placeholder, so a revision reliably comes back
            # without one, the damage check rejects it, and the fixes are lost
            # along with it. append_to_article strips whatever FAQ-shaped
            # section survived and re-inserts the canonical block in the right
            # place, which makes the outcome the same whether the Writer
            # dropped it, mangled it, or left it alone.
            if faq_markdown:
                revised_markdown = FAQAgent.append_to_article(
                    revised_markdown, faq_markdown
                )

            # And the sources, for the same reason and with a worse failure.
            # The Writer does not drop this block, it rewrites it: given an
            # article that ends in a list of links, a revision produces its own
            # list. Observed once — a selected seven became ten, four of them
            # from a single publisher, because the selection rules live here and
            # the Writer has never seen them. Re-applying restores the chosen
            # set, one entry per publisher, our own site excluded.
            if sources_markdown:
                revised_markdown = sources_block.append_to_article(
                    revised_markdown, sources_markdown
                )

            # The readability loop spends up to three Writer passes getting the
            # prose into range, and then this step rewrites the whole article
            # with no prose constraint at all. Observed: the loop finished on
            # three problems, QA asked for one factual correction, and the
            # revision came back with four. A careful contour followed by a step
            # that overwrites its result is not a contour.
            before_prose = len(prose_problems(score_markdown(draft_markdown)))
            after_prose = len(prose_problems(score_markdown(revised_markdown)))
            if after_prose > before_prose:
                print(
                    f"QA: revision {attempt} fixed the finding but left the prose "
                    f"worse ({after_prose} problems against {before_prose}) — "
                    "rejected. The reviewed draft stands.",
                    file=sys.stderr,
                )
                break

            damage = revision_damage(draft_markdown, revised_markdown)
            if damage:
                print(
                    f"QA: revision {attempt} rejected — {damage}. "
                    "Keeping the reviewed draft.",
                    file=sys.stderr,
                )
                break

            draft_result = revised_result
            draft_markdown = revised_markdown
            companion["draft_markdown"] = draft_markdown
            draft_md_path.write_text(draft_markdown, encoding="utf-8")
            _save_json(companion, draft_json_path)

            qa_report = _review(draft_markdown)
            qa_path = root / "qa" / f"{topic_slug}-revision-{attempt}.json"
            _save_json(qa_report, qa_path)
            qa_history.append(qa_report)
            print(
                f"QA: after revision {attempt} status={qa_report.get('status')}",
                file=sys.stderr,
            )
    except _StepSkipped:
        pass
    except Exception as exc:
        print(f"QA Review failed: {exc}", file=sys.stderr)
    results["qa_report"] = qa_report
    results["qa_history"] = qa_history
    results["draft_markdown"] = draft_markdown
    results["companion"] = companion
    yield _event(steps, "QA Review", "done")

    # Step 9 — Metadata
    yield _event(steps, "Metadata", "running")
    metadata: dict | None = None
    metadata_path: Path | None = None
    try:
        _guard(skip, "Metadata")
        meta_agent = MetadataCopyAgent()
        metadata = meta_agent.run(
            topic=topic,
            draft_markdown=draft_markdown,
            brief=brief,
            qa_report=qa_report,
            source_inputs_used={
                "draft": str(draft_json_path),
                "brief": str(brief_path),
                "qa_report": str(qa_path) if qa_path else None,
            },
            secondary_keywords=secondary_keywords,
        )
        metadata_path = root / "metadata" / f"{topic_slug}.json"
        _save_json(metadata, metadata_path)
    except Exception:
        pass
    results["metadata"] = metadata
    results["metadata_path"] = metadata_path
    yield _event(steps, "Metadata", "done")

    # Save to shared history
    article_title = (
        (metadata.get("h1") or metadata.get("title")) if metadata else None
    ) or brief.get("working_title") or topic
    history_entry = {
        "id": topic_slug,
        "topic": topic,
        "title": article_title,
        "primary_keyword": primary_keyword,
        "created_at": datetime.utcnow().isoformat(),
        "qa_status": qa_report.get("status", "unknown") if qa_report else "unknown",
        # Full content lives in the entry so viewing/updating never depends on
        # the ephemeral filesystem (Streamlit Cloud wipes local files on restart).
        "markdown": draft_markdown,
        "metadata": metadata,
        "qa_report": qa_report,
        "faq_json_ld": (
            faq_jsonld_path.read_text(encoding="utf-8")
            if faq_jsonld_path and faq_jsonld_path.exists()
            else None
        ),
        "suggested_visuals": draft_result.get("suggested_visuals", []) or [],
    }
    try:
        save_to_history(history_entry)
    except HistoryUnavailable as exc:
        # The article is finished and in `results`; losing it here because the
        # history backend is down would waste the whole run.
        results["history_error"] = str(exc)
        print(f"Could not save to history: {exc}", file=sys.stderr)
    results["history_entry"] = history_entry

    yield {"step": 0, "label": "done", "status": "done", "results": results}


# ─── Article Update pipeline ──────────────────────────────────────────────────

def _extract_topic_from_markdown(md: str) -> str:
    """Return the first H1 if present, else the first non-empty line."""
    h1 = re.search(r"^\s*#\s+(.+?)\s*$", md, flags=re.MULTILINE)
    if h1:
        return h1.group(1).strip()
    for line in md.splitlines():
        line = line.strip()
        if line:
            return line[:120]
    return ""


def run_update_pipeline(
    topic: str,
    primary_keyword: str,
    scope: str,
    original_article: str,
    previous_brief: dict | None = None,
    secondary_keywords: list[str] | None = None,
    *,
    output_root: Path | None = None,
):
    """Run the Article Update pipeline; yields the same event shape."""
    root = output_root or OUTPUT_ROOT
    steps = list(UPDATE_STEPS)
    results: dict = {
        "original_article": original_article,
        "scope": scope,
    }
    topic_slug = slugify(topic) or "article-update"
    run_stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    update_dir = root / "updates" / topic_slug / run_stamp
    update_dir.mkdir(parents=True, exist_ok=True)

    # Save the original next to the update for traceability
    (update_dir / "original.md").write_text(original_article, encoding="utf-8")

    # Step 1 — Fresh SERP Research
    yield _event(steps, "SERP Research (fresh)", "running")
    serp_data: dict | None = None
    try:
        serp_agent = SerpResearchAgent()
        serp_data = serp_agent.run(
            primary_keyword=primary_keyword,
            topic=topic,
            brief=previous_brief or {},
            country="us",
            language="en",
            top_n=10,
            paa_questions=(previous_brief or {}).get("questions_to_answer", []),
        )
        _save_json(serp_data, update_dir / "serp_research.json")
    except Exception:
        pass
    results["serp_data"] = serp_data
    yield _event(steps, "SERP Research (fresh)", "done")

    # Step 2 — Fresh Company Insight
    yield _event(steps, "Company Insight (fresh)", "running")
    insight_data: dict | None = None
    serp_context = _build_serp_context(serp_data) if serp_data else ""
    try:
        insight_agent = CompanyInsightAgent()
        insight_data = insight_agent.run(
            topic=topic,
            brief=previous_brief or {},
            extra_context=serp_context,
        )
        _save_json(insight_data, update_dir / "company_insight.json")
    except Exception:
        pass
    results["insight_data"] = insight_data
    yield _event(steps, "Company Insight (fresh)", "done")

    # Step 3 — Article Diagnostic (scoped update plan)
    yield _event(steps, "Article Diagnostic", "running")
    diag_plan: dict = {}
    try:
        diag_agent = ArticleDiagnosticAgent()
        diag_plan = diag_agent.run(
            topic=topic,
            original_article=original_article,
            scope=scope,
            serp_data=serp_data,
            insight_data=insight_data,
            previous_brief=previous_brief,
            secondary_keywords=secondary_keywords,
        )
        _save_json(diag_plan, update_dir / "diagnostic.json")
    except Exception as exc:
        print(f"Article Diagnostic failed: {exc}", file=sys.stderr)
        raise
    results["diagnostic"] = diag_plan
    yield _event(steps, "Article Diagnostic", "done")

    # Step 4 — Writer (update mode)
    yield _event(steps, "Writer (update mode)", "running")
    insight_context = _build_insight_context(insight_data) if insight_data else ""
    revision_feedback = ArticleDiagnosticAgent.format_for_writer(
        diag_plan, scope, secondary_keywords=secondary_keywords
    )
    writer_agent = WriterAgent()
    draft_result = writer_agent.run(
        topic=topic,
        brief=previous_brief,
        serp_context=serp_context,
        insight_context=insight_context,
        seo_structure_context="",
        revision_feedback=revision_feedback,
        original_article=original_article,
    )
    draft_markdown = writer_agent.assemble_markdown(draft_result)
    yield _event(steps, "Writer (update mode)", "done")

    # Step 5 — Readability Checker
    yield _event(steps, "Readability Checker", "running")
    readability_report: dict | None = None
    try:
        readability = ReadabilityChecker()

        def _rewrite(feedback: str) -> dict:
            return writer_agent.run(
                topic=topic,
                brief=previous_brief,
                serp_context=serp_context,
                insight_context=insight_context,
                seo_structure_context="",
                revision_feedback=feedback,
                original_article=original_article,
            )

        readability_report = readability.run(
            draft_result=draft_result,
            draft_markdown=draft_markdown,
            rewrite_fn=_rewrite,
            assemble_markdown_fn=writer_agent.assemble_markdown,
        )
        draft_result = readability_report["final_result"]
        draft_markdown = readability_report["final_markdown"]
        _save_json(readability_report, update_dir / "readability.json")
    except _StepSkipped:
        pass
    except Exception as exc:
        print(f"Readability Checker failed: {exc}", file=sys.stderr)
    results["readability_report"] = readability_report
    yield _event(steps, "Readability Checker", "done")

    # Step 6 — FAQ (refresh)
    yield _event(steps, "FAQ Agent (refresh)", "running")
    faq_result: dict | None = None
    faq_json_ld: str = ""
    try:
        faq_agent = FAQAgent()
        faq_result = faq_agent.run(
            topic=topic,
            draft_markdown=draft_markdown,
            brief=previous_brief,
            serp_data=serp_data,
            insight_data=insight_data,
        )
        faq_markdown = faq_agent.assemble_markdown(faq_result)
        draft_markdown = faq_agent.append_to_article(draft_markdown, faq_markdown)
        faq_json_ld = faq_agent.assemble_json_ld(faq_result)
        _save_json(faq_result, update_dir / "faq.json")
        if faq_json_ld:
            (update_dir / "faq.jsonld").write_text(faq_json_ld, encoding="utf-8")
    except Exception as exc:
        print(f"FAQ Agent failed: {exc}", file=sys.stderr)
    results["faq_result"] = faq_result
    results["faq_json_ld"] = faq_json_ld
    yield _event(steps, "FAQ Agent (refresh)", "done")

    # Save the updated article markdown now that all content edits are in
    updated_md_path = update_dir / "updated.md"
    updated_md_path.write_text(draft_markdown, encoding="utf-8")
    suggested_visuals = draft_result.get("suggested_visuals", []) or []
    if suggested_visuals:
        _save_json(
            {"suggested_visuals": suggested_visuals},
            update_dir / "suggested_visuals.json",
        )
    results["draft_markdown"] = draft_markdown
    results["updated_md_path"] = updated_md_path
    results["update_dir"] = update_dir
    results["suggested_visuals"] = suggested_visuals

    # Step 7 — QA Review (on full updated text including FAQ)
    yield _event(steps, "QA Review", "running")
    qa_report: dict | None = None
    try:
        qa_agent = QAAgent()
        qa_report = qa_agent.run(
            topic=topic,
            draft_markdown=draft_markdown,
            draft_wrapper={
                "claims_to_verify": draft_result.get("claims_to_verify", []),
                "internal_links_used": draft_result.get("internal_links_used", []),
                "suggested_visuals": draft_result.get("suggested_visuals", []),
                "primary_keyword": primary_keyword,
                "todos": draft_result.get("todos", []),
            },
            brief=previous_brief,
            serp_data=serp_data,
            insight_data=insight_data,
            source_inputs_used={
                "original": str(update_dir / "original.md"),
                "updated": str(updated_md_path),
                "diagnostic": str(update_dir / "diagnostic.json"),
            },
        )
        _save_json(qa_report, update_dir / "qa.json")
    except Exception:
        pass
    results["qa_report"] = qa_report
    yield _event(steps, "QA Review", "done")

    # Step 8 — Metadata (refresh)
    yield _event(steps, "Metadata (refresh)", "running")
    metadata: dict | None = None
    try:
        meta_agent = MetadataCopyAgent()
        metadata = meta_agent.run(
            topic=topic,
            draft_markdown=draft_markdown,
            brief=previous_brief or {},
            qa_report=qa_report,
            source_inputs_used={
                "updated": str(updated_md_path),
                "qa_report": str(update_dir / "qa.json"),
            },
            secondary_keywords=secondary_keywords,
        )
        _save_json(metadata, update_dir / "metadata.json")
    except Exception:
        pass
    results["metadata"] = metadata
    yield _event(steps, "Metadata (refresh)", "done")

    # Save the refreshed article to shared history (upserts the existing entry
    # for this topic, so the history card reflects the latest version).
    article_title = (
        (metadata.get("h1") or metadata.get("title")) if metadata else None
    ) or (previous_brief or {}).get("working_title") or topic
    history_entry = {
        "id": topic_slug,
        "topic": topic,
        "title": article_title,
        "primary_keyword": primary_keyword,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "qa_status": qa_report.get("status", "unknown") if qa_report else "unknown",
        "markdown": draft_markdown,
        "metadata": metadata,
        "qa_report": qa_report,
        "faq_json_ld": faq_json_ld or None,
        "suggested_visuals": suggested_visuals,
    }
    try:
        save_to_history(history_entry)
    except HistoryUnavailable as exc:
        # The article is finished and in `results`; losing it here because the
        # history backend is down would waste the whole run.
        results["history_error"] = str(exc)
        print(f"Could not save to history: {exc}", file=sys.stderr)
    results["history_entry"] = history_entry

    yield {"step": 0, "label": "done", "status": "done", "results": results}

