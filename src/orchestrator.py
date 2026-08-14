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
import re
import sys
from datetime import datetime
from pathlib import Path

from src.agents import BriefAgent
from src.serp_research_agent import SerpResearchAgent
from src.company_insight_agent import CompanyInsightAgent
from src.seo_structure_agent import SeoStructureAgent
from src.writer_agent import WriterAgent
from src.readability_agent import ReadabilityChecker
from src.faq_agent import FAQAgent
from src.qa_agent import QAAgent
from src.metadata_copy_agent import MetadataCopyAgent
from src.article_diagnostic_agent import ArticleDiagnosticAgent
from src.history_store import save_to_history

OUTPUT_ROOT = Path("outputs")

#: Canonical step order. Callers render progress from this list, so a step can
#: never be added to the pipeline without appearing in the UI, or vice versa.
PIPELINE_STEPS = [
    "Brief",
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
SKIPPABLE = {"SERP Research", "Company Insight", "SEO Structure",
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

def _build_serp_context(serp_data: dict) -> str:
    fields = {
        "serp_status": serp_data.get("serp_status"),
        "dominant_search_intent": serp_data.get("dominant_search_intent"),
        "content_gaps": serp_data.get("content_gaps", []),
        "differentiation_opportunities": serp_data.get("differentiation_opportunities", []),
        "competitor_weaknesses": serp_data.get("competitor_weaknesses", []),
        "risks_to_avoid": serp_data.get("risks_to_avoid", []),
        "notes_for_writer": serp_data.get("notes_for_writer", []),
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

    # Step 2 — SERP Research
    yield _event(steps, "SERP Research", "running")
    serp_data: dict | None = None
    serp_path: Path | None = None
    try:
        _guard(skip, "SERP Research")
        serp_agent = SerpResearchAgent()
        serp_data = serp_agent.run(
            primary_keyword=primary_keyword,
            topic=topic,
            brief=brief,
            country="us",
            language="en",
            top_n=5,
            paa_questions=brief.get("questions_to_answer", []),
        )
        serp_slug = slugify(primary_keyword)
        serp_path = root / "serp_research" / f"{serp_slug}.json"
        _save_json(serp_data, serp_path)
    except Exception:
        pass
    results["serp_data"] = serp_data
    results["serp_path"] = serp_path
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
        insight_agent = CompanyInsightAgent()
        insight_data = insight_agent.run(
            topic=topic,
            brief=brief,
            extra_context=extra_context,
        )
        insight_path = root / "company_insight" / f"{topic_slug}.json"
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
        seo_agent = SeoStructureAgent()
        seo_data = seo_agent.run(topic=topic, brief=brief)
        seo_path = root / "seo_structure" / f"{topic_slug}.json"
        _save_json(seo_data, seo_path)
    except Exception:
        pass
    results["seo_data"] = seo_data
    yield _event(steps, "SEO Structure", "done")

    # Step 5 — Writer
    yield _event(steps, "Writer", "running")
    serp_context = _build_serp_context(serp_data) if serp_data else ""
    insight_context = _build_insight_context(insight_data) if insight_data else ""
    seo_structure_context = json.dumps(seo_data, indent=2, ensure_ascii=False) if seo_data else ""
    writer_agent = WriterAgent()
    draft_result = writer_agent.run(
        topic=topic,
        brief=brief,
        serp_context=serp_context,
        insight_context=insight_context,
        seo_structure_context=seo_structure_context,
    )
    draft_markdown = writer_agent.assemble_markdown(draft_result)
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
                revision_feedback=feedback,
            )

        readability_report = readability.run(
            draft_result=draft_result,
            draft_markdown=draft_markdown,
            rewrite_fn=_rewrite,
            assemble_markdown_fn=writer_agent.assemble_markdown,
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
    }
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
    yield _event(steps, "QA Review", "running")
    qa_report: dict | None = None
    qa_path: Path | None = None
    try:
        _guard(skip, "QA Review")
        qa_agent = QAAgent()
        qa_report = qa_agent.run(
            topic=topic,
            draft_markdown=draft_markdown,
            draft_wrapper=companion,
            brief=brief,
            serp_data=serp_data,
            insight_data=insight_data,
            source_inputs_used={
                "draft": str(draft_json_path),
                "brief": str(brief_path),
                "serp_research": str(serp_path) if serp_path else None,
                "company_insight": str(insight_path) if insight_path else None,
            },
        )
        qa_path = root / "qa" / f"{topic_slug}.json"
        _save_json(qa_report, qa_path)
    except Exception:
        pass
    results["qa_report"] = qa_report
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
    save_to_history(history_entry)
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
            top_n=5,
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
    save_to_history(history_entry)
    results["history_entry"] = history_entry

    yield {"step": 0, "label": "done", "status": "done", "results": results}

