"""JVL Content Engine — Web UI for content managers."""

from __future__ import annotations

import difflib
import json
import re
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

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
from src.history_store import load_history, save_to_history, delete_from_history

OUTPUT_ROOT = Path("outputs")


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
):
    """Run the full 9-step pipeline; yields progress events, ends with results dict."""
    root = OUTPUT_ROOT
    results: dict = {}

    content_goal = "drive product consideration and support organic search traffic"
    if secondary_keywords:
        content_goal += f". Also incorporate these secondary keywords naturally: {', '.join(secondary_keywords)}"
    if custom_requirements:
        content_goal += f". Additional requirements from editor: {custom_requirements}"

    # Step 1 — Brief
    yield {"step": 1, "label": "Brief Agent", "status": "running"}
    brief_agent = BriefAgent()
    brief = brief_agent.run(
        topic=topic,
        primary_keyword=primary_keyword,
        content_goal=content_goal,
        funnel_stage=funnel_stage,
        audience="Mark & Linda Reynolds",
        country="US",
        language="en",
    )
    brief_slug = slugify(brief.get("primary_keyword", primary_keyword))
    brief_path = root / "briefs" / f"{brief_slug}.json"
    _save_json(brief, brief_path)
    results["brief"] = brief
    results["brief_path"] = brief_path
    yield {"step": 1, "label": "Brief Agent", "status": "done"}

    topic_slug = slugify(topic)

    # Step 2 — SERP Research
    yield {"step": 2, "label": "SERP Research", "status": "running"}
    serp_data: dict | None = None
    serp_path: Path | None = None
    try:
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
    yield {"step": 2, "label": "SERP Research", "status": "done"}

    # Step 3 — Company Insight
    yield {"step": 3, "label": "Company Insight", "status": "running"}
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
    yield {"step": 3, "label": "Company Insight", "status": "done"}

    # Step 4 — SEO Structure
    yield {"step": 4, "label": "SEO Structure", "status": "running"}
    seo_data: dict | None = None
    seo_path: Path | None = None
    try:
        seo_agent = SeoStructureAgent()
        seo_data = seo_agent.run(topic=topic, brief=brief)
        seo_path = root / "seo_structure" / f"{topic_slug}.json"
        _save_json(seo_data, seo_path)
    except Exception:
        pass
    results["seo_data"] = seo_data
    yield {"step": 4, "label": "SEO Structure", "status": "done"}

    # Step 5 — Writer
    yield {"step": 5, "label": "Writer Agent", "status": "running"}
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
    yield {"step": 5, "label": "Writer Agent", "status": "done"}

    # Step 6 — Readability Checker (Flesch Reading Ease >= 90, up to 3 rewrites)
    yield {"step": 6, "label": "Readability Checker", "status": "running"}
    readability_report: dict | None = None
    readability_path: Path | None = None
    try:
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
    except Exception as exc:
        print(f"Readability Checker failed: {exc}", file=__import__("sys").stderr)
    results["readability_report"] = readability_report
    results["readability_path"] = readability_path
    yield {"step": 6, "label": "Readability Checker", "status": "done"}

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
    # Step 7 — FAQ
    yield {"step": 7, "label": "FAQ Agent", "status": "running"}
    faq_result: dict | None = None
    faq_markdown: str = ""
    faq_json_ld: str = ""
    faq_path: Path | None = None
    faq_jsonld_path: Path | None = None
    try:
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
    except Exception as exc:
        print(f"FAQ Agent failed: {exc}", file=__import__("sys").stderr)
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
    yield {"step": 7, "label": "FAQ Agent", "status": "done"}

    # Step 8 — QA (reviews full draft including FAQ block)
    yield {"step": 8, "label": "QA Review", "status": "running"}
    qa_report: dict | None = None
    qa_path: Path | None = None
    try:
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
    yield {"step": 8, "label": "QA Review", "status": "done"}

    # Step 9 — Metadata
    yield {"step": 9, "label": "Metadata", "status": "running"}
    metadata: dict | None = None
    metadata_path: Path | None = None
    try:
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
    yield {"step": 9, "label": "Metadata", "status": "done"}

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
):
    """Run the 7-step Article Update pipeline."""
    root = OUTPUT_ROOT
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
    yield {"step": 1, "label": "SERP Research (fresh)", "status": "running"}
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
    yield {"step": 1, "label": "SERP Research (fresh)", "status": "done"}

    # Step 2 — Fresh Company Insight
    yield {"step": 2, "label": "Company Insight (fresh)", "status": "running"}
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
    yield {"step": 2, "label": "Company Insight (fresh)", "status": "done"}

    # Step 3 — Article Diagnostic (scoped update plan)
    yield {"step": 3, "label": "Article Diagnostic", "status": "running"}
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
        print(f"Article Diagnostic failed: {exc}", file=__import__("sys").stderr)
        raise
    results["diagnostic"] = diag_plan
    yield {"step": 3, "label": "Article Diagnostic", "status": "done"}

    # Step 4 — Writer (update mode)
    yield {"step": 4, "label": "Writer (update mode)", "status": "running"}
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
    yield {"step": 4, "label": "Writer (update mode)", "status": "done"}

    # Step 5 — Readability Checker
    yield {"step": 5, "label": "Readability Checker", "status": "running"}
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
    except Exception as exc:
        print(f"Readability Checker failed: {exc}", file=__import__("sys").stderr)
    results["readability_report"] = readability_report
    yield {"step": 5, "label": "Readability Checker", "status": "done"}

    # Step 6 — FAQ (refresh)
    yield {"step": 6, "label": "FAQ Agent (refresh)", "status": "running"}
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
        print(f"FAQ Agent failed: {exc}", file=__import__("sys").stderr)
    results["faq_result"] = faq_result
    results["faq_json_ld"] = faq_json_ld
    yield {"step": 6, "label": "FAQ Agent (refresh)", "status": "done"}

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
    yield {"step": 7, "label": "QA Review", "status": "running"}
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
    yield {"step": 7, "label": "QA Review", "status": "done"}

    # Step 8 — Metadata (refresh)
    yield {"step": 8, "label": "Metadata (refresh)", "status": "running"}
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
    yield {"step": 8, "label": "Metadata (refresh)", "status": "done"}

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


def _build_unified_diff(original: str, updated: str) -> str:
    diff = difflib.unified_diff(
        original.splitlines(),
        updated.splitlines(),
        fromfile="original.md",
        tofile="updated.md",
        lineterm="",
        n=3,
    )
    return "\n".join(diff)


# ─── Shared article renderer ──────────────────────────────────────────────────

def _render_article(
    draft_markdown: str,
    metadata: dict | None,
    qa_report: dict | None,
    filename: str = "article.md",
    faq_json_ld: str = "",
    suggested_visuals: list | None = None,
) -> None:
    """Show metadata, QA badge, then content + FAQ JSON-LD + visuals tabs."""
    if metadata:
        with st.expander("SEO metadata", expanded=False):
            st.markdown(f"**Slug:** `{metadata.get('slug', '')}`")
            st.markdown(f"**H1:** {metadata.get('h1', '')}")
            st.markdown(f"**Meta Title:** {metadata.get('meta_title', '')}")
            st.markdown(f"**Meta Description:** {metadata.get('meta_description', '')}")

    if qa_report:
        status_val = qa_report.get("status", "unknown")
        counts = qa_report.get("severity_counts", {})
        badge = "✅ QA passed" if status_val == "pass" else "⚠️ Needs review"
        st.info(
            f"{badge} — critical: {counts.get('high', 0)}, "
            f"medium: {counts.get('medium', 0)}, "
            f"low: {counts.get('low', 0)}"
        )

    tab_labels = ["Rendered", "Markdown source", "Download .md"]
    if faq_json_ld:
        tab_labels.append("FAQ JSON-LD")
    visuals = suggested_visuals or []
    if visuals:
        tab_labels.append(f"Suggested visuals ({len(visuals)})")
    tabs = st.tabs(tab_labels)

    with tabs[0]:
        st.markdown(draft_markdown)

    with tabs[1]:
        st.code(draft_markdown, language="markdown")

    with tabs[2]:
        st.download_button(
            label="Download article (.md)",
            data=draft_markdown.encode("utf-8"),
            file_name=filename,
            mime="text/markdown",
        )
        st.caption(f"File: `{filename}`")

    next_idx = 3
    if faq_json_ld:
        with tabs[next_idx]:
            st.caption(
                "Paste this block into the article page `<head>`. Used by AI "
                "search engines (Perplexity, ChatGPT Search, AI Overviews) "
                "to extract atomic Q/A pairs for citation."
            )
            st.code(faq_json_ld, language="html")
            jsonld_filename = filename.rsplit(".", 1)[0] + ".jsonld"
            st.download_button(
                label="Download FAQ JSON-LD",
                data=faq_json_ld.encode("utf-8"),
                file_name=jsonld_filename,
                mime="application/ld+json",
            )
        next_idx += 1

    if visuals:
        with tabs[next_idx]:
            st.caption(
                "The Writer flagged these spots where a visual would help "
                "the reader and AI-search retrieval. Each entry corresponds "
                "to a `> **[VISUAL]**` placeholder in the markdown."
            )
            for i, v in enumerate(visuals, 1):
                with st.container(border=True):
                    st.markdown(
                        f"**{i}. {v.get('type', 'image').upper()}** — "
                        f"section: *{v.get('section_heading', '?')}*"
                    )
                    if v.get("purpose"):
                        st.markdown(f"**Purpose:** {v['purpose']}")
                    if v.get("production_note"):
                        st.markdown(f"**Production note:** {v['production_note']}")
                    if v.get("alt_text_proposal"):
                        st.markdown(f"**Alt text:** `{v['alt_text_proposal']}`")


# ─── Streamlit UI ─────────────────────────────────────────────────────────────

st.set_page_config(page_title="JVL Content Engine", page_icon="🎮", layout="wide")

# Initialise session state
if "view_article" not in st.session_state:
    st.session_state.view_article = None
if "pipeline_results" not in st.session_state:
    st.session_state.pipeline_results = None
if "update_results" not in st.session_state:
    st.session_state.update_results = None

# ─── Sidebar: shared article history ─────────────────────────────────────────

with st.sidebar:
    st.header("Article history")

    if st.button("↩ Back to generator", disabled=st.session_state.view_article is None):
        st.session_state.view_article = None
        st.rerun()

    st.divider()

    history = load_history()

    if not history:
        st.caption("No articles yet. Generate one to get started.")
    else:
        for entry in history:
            article_id = entry.get("id", "")
            title = entry.get("title") or entry.get("topic") or "Untitled"
            created_at = entry.get("created_at", "")
            qa_status = entry.get("qa_status", "unknown")

            try:
                dt = datetime.fromisoformat(created_at)
                date_str = dt.strftime("%d %b %Y, %H:%M")
            except Exception:
                date_str = created_at[:10] if created_at else ""

            qa_badge = {"pass": "✅", "revise": "⚠️", "fail": "❌"}.get(qa_status, "❓")

            st.markdown(
                f"{qa_badge} **{title[:45]}{'…' if len(title) > 45 else ''}**"
            )
            st.caption(date_str)

            col_view, col_del = st.columns(2)
            with col_view:
                if st.button("View", key=f"view_{article_id}"):
                    st.session_state.view_article = entry
                    st.session_state.pipeline_results = None
            with col_del:
                if st.button("Delete", key=f"del_{article_id}"):
                    delete_from_history(article_id)
                    if (st.session_state.view_article or {}).get("id") == article_id:
                        st.session_state.view_article = None
                    st.rerun()

            st.divider()

# ─── Main area: history viewer ────────────────────────────────────────────────

if st.session_state.view_article:
    entry = st.session_state.view_article
    title = entry.get("title") or entry.get("topic") or "Article"

    st.title(title)
    st.caption(
        f"Topic: {entry.get('topic', '')}  ·  "
        f"Keyword: {entry.get('primary_keyword', '')}  ·  "
        f"Created: {entry.get('created_at', '')[:10]}"
    )
    st.divider()

    # Content is stored in the entry itself. Fall back to disk only for legacy
    # entries created before persistent storage was added.
    draft_markdown = entry.get("markdown") or ""
    metadata = entry.get("metadata")
    qa_report = entry.get("qa_report")
    faq_json_ld = entry.get("faq_json_ld") or ""
    sidebar_visuals = entry.get("suggested_visuals") or []

    if not draft_markdown:
        md_path_str = entry.get("md_path")
        if md_path_str and Path(md_path_str).exists():
            draft_markdown = Path(md_path_str).read_text(encoding="utf-8")

    if draft_markdown:
        filename = f"{entry.get('id', 'article')}.md"
        _render_article(
            draft_markdown, metadata, qa_report, filename, faq_json_ld,
            suggested_visuals=sidebar_visuals,
        )
    else:
        st.error("Article content is unavailable for this entry.")

# ─── Main area: generator ─────────────────────────────────────────────────────

else:
    st.title("JVL Content Engine")
    st.caption("Generate or refresh SEO articles for JVL Echo Home.")

    tab_create, tab_update = st.tabs(["✏️ Create new article", "🔄 Update existing article"])

    with tab_create:
        col1, col2 = st.columns([2, 1])

        with col1:
            topic = st.text_input(
                "Article topic",
                placeholder="e.g. how to choose a home arcade machine",
                help="Briefly describe what the article should be about",
                key="create_topic",
            )
            keyword = st.text_input(
                "Primary keyword",
                placeholder="e.g. home arcade machine for adults",
                help="The main search query this article will be optimised for",
                key="create_keyword",
            )
            secondary_raw = st.text_area(
                "Secondary keywords (optional)",
                placeholder="arcade machine for living room\nbest home arcade games\nretro arcade cabinet for home",
                help="One keyword per line, up to 10. These will be woven naturally into the article.",
                height=120,
                key="create_secondary",
            )
            custom_requirements = st.text_area(
                "Additional requirements (optional)",
                placeholder="e.g. Mention that the Echo Home fits under a standard staircase. Include a comparison table. Avoid mentioning competitors by name.",
                help="Any specific instructions for this article — facts to include, sections to add, things to avoid, etc.",
                height=100,
                key="create_custom",
            )

        with col2:
            funnel_stage = st.radio(
                "Reader intent",
                options=["top", "mid", "bottom"],
                index=1,
                format_func=lambda x: {
                    "top": "Top — Just exploring",
                    "mid": "Mid — Comparing options",
                    "bottom": "Bottom — Ready to buy",
                }[x],
                captions=[
                    "Reader is curious but not thinking about buying yet. E.g. 'what games did people play in the 80s'. Article is educational; product is mentioned lightly.",
                    "Reader is evaluating options and considering a purchase. E.g. 'how to choose a home arcade machine'. Best for most JVL articles.",
                    "Reader is close to buying and wants confirmation. E.g. 'JVL Echo Home review'. Article is product-focused.",
                ],
                key="create_funnel",
            )

        st.divider()

        secondary_keywords = [kw.strip() for kw in secondary_raw.splitlines() if kw.strip()][:10]

        if st.button("Generate article", type="primary", disabled=not (topic and keyword), key="create_btn"):
            STEP_LABELS = [
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

            step_placeholders = []
            progress_col, _ = st.columns([3, 1])

            with progress_col:
                st.subheader("Progress")
                for label in STEP_LABELS:
                    step_placeholders.append(st.empty())

            def _render_step(idx: int, status: str) -> None:
                icon = {"running": "⏳", "done": "✅", "pending": "⬜"}[status]
                step_placeholders[idx].markdown(f"{icon} **Step {idx + 1}:** {STEP_LABELS[idx]}")

            for i in range(len(STEP_LABELS)):
                _render_step(i, "pending")

            pipeline_results: dict = {}
            error: str | None = None

            try:
                for event in run_pipeline(
                    topic, keyword, funnel_stage, secondary_keywords, custom_requirements
                ):
                    step_idx = event["step"] - 1
                    if event["step"] == 0:
                        pipeline_results = event["results"]
                        break
                    if event["status"] == "running":
                        _render_step(step_idx, "running")
                    elif event["status"] == "done":
                        _render_step(step_idx, "done")
            except Exception as exc:
                error = str(exc)

            st.divider()

            if error:
                st.error(f"Error: {error}")
            elif pipeline_results:
                st.session_state.pipeline_results = pipeline_results
                # Refresh so the just-saved article appears in the sidebar history.
                st.rerun()

        if st.session_state.pipeline_results:
            res = st.session_state.pipeline_results
            draft_markdown: str = res.get("draft_markdown", "")
            metadata: dict | None = res.get("metadata")
            qa_report: dict | None = res.get("qa_report")
            draft_md_path: Path | None = res.get("draft_md_path")
            faq_json_ld: str = res.get("faq_json_ld", "")
            suggested_visuals: list = res.get("suggested_visuals", []) or []
            filename = draft_md_path.name if draft_md_path else "article.md"

            st.success("Article ready!")
            _render_article(
                draft_markdown, metadata, qa_report, filename, faq_json_ld,
                suggested_visuals=suggested_visuals,
            )

    with tab_update:
        st.caption(
            "Refresh an existing article: fix stale facts, close new SERP gaps, "
            "improve brand alignment. The Writer Agent works in revise mode and "
            "preserves what the diagnostic flags as still strong."
        )

        history_for_update = load_history()
        history_options = ["(paste manually)"] + [
            f"{h.get('title') or h.get('topic', '?')}  —  {h.get('id', '')}"
            for h in history_for_update
        ]
        source_choice = st.selectbox(
            "Source article",
            history_options,
            index=0,
            help="Pick an article previously generated in this engine, or choose '(paste manually)' to supply markdown.",
            key="update_source",
        )

        preloaded_md = ""
        preloaded_topic = ""
        preloaded_keyword = ""
        preloaded_brief: dict | None = None
        if source_choice != "(paste manually)":
            picked_index = history_options.index(source_choice) - 1
            picked = history_for_update[picked_index]
            # Prefer content stored in the entry; fall back to disk for legacy entries.
            preloaded_md = picked.get("markdown") or ""
            preloaded_topic = picked.get("topic", "") or ""
            preloaded_keyword = picked.get("primary_keyword") or ""
            if not preloaded_md:
                md_path_str = picked.get("md_path")
                if md_path_str and Path(md_path_str).exists():
                    try:
                        preloaded_md = Path(md_path_str).read_text(encoding="utf-8")
                    except Exception:
                        pass

        update_topic = st.text_input(
            "Article topic",
            value=preloaded_topic,
            placeholder="auto-detected from H1 when you paste markdown below",
            key="update_topic",
        )
        update_keyword = st.text_input(
            "Primary keyword",
            value=preloaded_keyword,
            placeholder="e.g. home arcade machine for adults",
            key="update_keyword",
        )

        update_secondary_raw = st.text_area(
            "Secondary keywords (optional)",
            placeholder="arcade machine for living room\nbest home arcade games\nretro arcade cabinet for home",
            help="One keyword per line, up to 10. Lower priority than the primary keyword. The Diagnostic will flag missing coverage and the Writer will weave them naturally.",
            height=110,
            key="update_secondary",
        )

        original_markdown = st.text_area(
            "Existing article markdown",
            value=preloaded_md,
            placeholder=(
                "# Article H1\n\n"
                "Intro paragraph in plain prose.\n\n"
                "## Section heading\n\n"
                "Paragraph text. Internal links like [Echo Home](/en/echo) work.\n\n"
                "### Subsection\n\n"
                "More paragraph text…"
            ),
            help=(
                "Markdown format: `#` for H1, `##` for H2, `###` for H3, blank "
                "lines between paragraphs. If your article is HTML on the site, "
                "paste it through html-to-markdown.com first — or just paste "
                "the visible text and prefix headings with `#`/`##` manually; "
                "the Diagnostic will work with messy markdown too."
            ),
            height=320,
            key="update_markdown",
        )

        scope = st.radio(
            "Update scope",
            options=["light", "medium", "heavy"],
            index=1,
            horizontal=True,
            captions=[
                "Freshness only — dates, numbers, broken links, forbidden claims.",
                "Light + close SERP gaps + targeted paragraph rewrites for brand drift.",
                "Medium + reorder sections + replace intro/outro (preserves ≥60% prose).",
            ],
            key="update_scope",
        )

        effective_topic = update_topic.strip() or _extract_topic_from_markdown(original_markdown)
        update_secondary_keywords = [
            kw.strip()
            for kw in update_secondary_raw.splitlines()
            if kw.strip()
        ][:10]
        update_disabled = not (effective_topic and update_keyword.strip() and original_markdown.strip())

        if st.button("Update article", type="primary", disabled=update_disabled, key="update_btn"):
            UPDATE_STEP_LABELS = [
                "SERP Research (fresh)",
                "Company Insight (fresh)",
                "Article Diagnostic",
                "Writer (update mode)",
                "Readability Checker",
                "FAQ Agent (refresh)",
                "QA Review",
                "Metadata (refresh)",
            ]

            step_placeholders: list = []
            progress_col, _ = st.columns([3, 1])
            with progress_col:
                st.subheader("Progress")
                for label in UPDATE_STEP_LABELS:
                    step_placeholders.append(st.empty())

            def _render_update_step(idx: int, status: str) -> None:
                icon = {"running": "⏳", "done": "✅", "pending": "⬜"}[status]
                step_placeholders[idx].markdown(
                    f"{icon} **Step {idx + 1}:** {UPDATE_STEP_LABELS[idx]}"
                )

            for i in range(len(UPDATE_STEP_LABELS)):
                _render_update_step(i, "pending")

            update_results: dict = {}
            update_error: str | None = None

            try:
                for event in run_update_pipeline(
                    topic=effective_topic,
                    primary_keyword=update_keyword.strip(),
                    scope=scope,
                    original_article=original_markdown,
                    previous_brief=preloaded_brief,
                    secondary_keywords=update_secondary_keywords,
                ):
                    step_idx = event["step"] - 1
                    if event["step"] == 0:
                        update_results = event["results"]
                        break
                    if event["status"] == "running":
                        _render_update_step(step_idx, "running")
                    elif event["status"] == "done":
                        _render_update_step(step_idx, "done")
            except Exception as exc:
                update_error = str(exc)

            st.divider()

            if update_error:
                st.error(f"Error: {update_error}")
            elif update_results:
                st.session_state.update_results = update_results
                # Refresh so the refreshed article appears in the sidebar history.
                st.rerun()

        if st.session_state.get("update_results"):
            res = st.session_state.update_results
            updated_md: str = res.get("draft_markdown", "")
            original_md: str = res.get("original_article", "")
            qa_report: dict | None = res.get("qa_report")
            metadata: dict | None = res.get("metadata")
            faq_json_ld: str = res.get("faq_json_ld", "")
            diagnostic: dict = res.get("diagnostic") or {}
            scope_used: str = res.get("scope", "medium")
            update_dir: Path | None = res.get("update_dir")

            st.success(f"Article updated (scope: **{scope_used}**)")

            if diagnostic:
                with st.expander("Diagnostic summary", expanded=False):
                    diag = diagnostic.get("diagnosis", {})
                    if diag.get("summary"):
                        st.markdown(diag["summary"])
                    cols = st.columns(2)
                    with cols[0]:
                        st.markdown("**Freshness issues**")
                        for x in diag.get("freshness_issues") or ["(none)"]:
                            st.markdown(f"- {x}")
                        st.markdown("**SERP gaps closed**")
                        for x in diag.get("serp_gaps_to_close") or ["(none)"]:
                            st.markdown(f"- {x}")
                    with cols[1]:
                        st.markdown("**Brand alignment issues**")
                        for x in diag.get("brand_alignment_issues") or ["(none)"]:
                            st.markdown(f"- {x}")
                        st.markdown("**Experience anchor gaps**")
                        for x in diag.get("experience_anchor_gaps") or ["(none)"]:
                            st.markdown(f"- {x}")

            update_visuals: list = res.get("suggested_visuals", []) or []
            tab_labels = ["Updated", "Original", "Diff", "Diagnostic JSON"]
            if faq_json_ld:
                tab_labels.append("FAQ JSON-LD")
            if update_visuals:
                tab_labels.append(f"Suggested visuals ({len(update_visuals)})")
            update_tabs = st.tabs(tab_labels)

            with update_tabs[0]:
                st.markdown(updated_md)
                st.download_button(
                    "Download updated.md",
                    data=updated_md.encode("utf-8"),
                    file_name="updated.md",
                    mime="text/markdown",
                    key="dl_updated",
                )
            with update_tabs[1]:
                st.markdown(original_md)
            with update_tabs[2]:
                diff_text = _build_unified_diff(original_md, updated_md)
                if diff_text:
                    st.code(diff_text, language="diff")
                else:
                    st.info("No textual differences detected.")
            with update_tabs[3]:
                st.code(json.dumps(diagnostic, indent=2, ensure_ascii=False), language="json")
            update_next_idx = 4
            if faq_json_ld:
                with update_tabs[update_next_idx]:
                    st.caption(
                        "Paste into the article page `<head>`. Helps AI search "
                        "engines extract atomic Q/A pairs for citation."
                    )
                    st.code(faq_json_ld, language="html")
                update_next_idx += 1

            if update_visuals:
                with update_tabs[update_next_idx]:
                    st.caption(
                        "Spots flagged in the updated draft where a visual would "
                        "help. Each entry matches a `> **[VISUAL]**` placeholder."
                    )
                    for i, v in enumerate(update_visuals, 1):
                        with st.container(border=True):
                            st.markdown(
                                f"**{i}. {v.get('type', 'image').upper()}** — "
                                f"section: *{v.get('section_heading', '?')}*"
                            )
                            if v.get("purpose"):
                                st.markdown(f"**Purpose:** {v['purpose']}")
                            if v.get("production_note"):
                                st.markdown(f"**Production note:** {v['production_note']}")
                            if v.get("alt_text_proposal"):
                                st.markdown(f"**Alt text:** `{v['alt_text_proposal']}`")

            if update_dir:
                st.caption(f"Run artifacts saved to: `{update_dir}`")
            if qa_report:
                status_val = qa_report.get("status", "unknown")
                counts = qa_report.get("severity_counts", {})
                badge = "✅ QA passed" if status_val == "pass" else "⚠️ Needs review"
                st.info(
                    f"{badge} — critical: {counts.get('high', 0)}, "
                    f"medium: {counts.get('medium', 0)}, "
                    f"low: {counts.get('low', 0)}"
                )
            if metadata:
                with st.expander("Refreshed metadata", expanded=False):
                    st.markdown(f"**Slug:** `{metadata.get('slug', '')}`")
                    st.markdown(f"**H1:** {metadata.get('h1', '')}")
                    st.markdown(f"**Meta Title:** {metadata.get('meta_title', '')}")
                    st.markdown(f"**Meta Description:** {metadata.get('meta_description', '')}")
