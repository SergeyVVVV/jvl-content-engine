"""JVL Content Engine — Web UI for content managers."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from src.agents import BriefAgent
from src.serp_research_agent import SerpResearchAgent
from src.company_insight_agent import CompanyInsightAgent
from src.seo_structure_agent import SeoStructureAgent
from src.writer_agent import WriterAgent
from src.qa_agent import QAAgent
from src.metadata_copy_agent import MetadataCopyAgent

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


def run_pipeline(topic: str, primary_keyword: str, funnel_stage: str) -> dict:
    """Run the full 7-step pipeline and return result dict."""
    root = OUTPUT_ROOT
    results: dict = {}

    # Step 1 — Brief
    yield {"step": 1, "label": "Brief Agent", "status": "running"}
    brief_agent = BriefAgent()
    brief = brief_agent.run(
        topic=topic,
        primary_keyword=primary_keyword,
        content_goal="drive product consideration and support organic search traffic",
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
        },
        "risks_to_review": _build_risks(brief, insight_data),
        "internal_links_used": draft_result.get("internal_links_used", []),
        "todos": draft_result.get("todos", []),
    }
    draft_md_path = root / "drafts" / f"{topic_slug}.md"
    draft_json_path = root / "drafts" / f"{topic_slug}.json"
    draft_md_path.parent.mkdir(parents=True, exist_ok=True)
    draft_md_path.write_text(draft_markdown, encoding="utf-8")
    _save_json(companion, draft_json_path)
    results["draft_markdown"] = draft_markdown
    results["draft_md_path"] = draft_md_path
    results["companion"] = companion
    results["draft_json_path"] = draft_json_path
    yield {"step": 5, "label": "Writer Agent", "status": "done"}

    # Step 6 — QA
    yield {"step": 6, "label": "QA Review", "status": "running"}
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
    yield {"step": 6, "label": "QA Review", "status": "done"}

    # Step 7 — Metadata
    yield {"step": 7, "label": "Metadata", "status": "running"}
    metadata: dict | None = None
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
        )
        metadata_path = root / "metadata" / f"{topic_slug}.json"
        _save_json(metadata, metadata_path)
    except Exception:
        pass
    results["metadata"] = metadata
    yield {"step": 7, "label": "Metadata", "status": "done"}

    yield {"step": 0, "label": "done", "status": "done", "results": results}


# ─── Streamlit UI ────────────────────────────────────────────────────────────

st.set_page_config(page_title="JVL Content Engine", page_icon="🎮", layout="wide")

st.title("JVL Content Engine")
st.caption("Создайте SEO-статью для JVL Echo Home — просто введите тему и нажмите кнопку.")

st.divider()

col1, col2 = st.columns([2, 1])

with col1:
    topic = st.text_input(
        "Тема статьи",
        placeholder="например: how to choose a home arcade machine",
        help="Кратко опишите, о чём должна быть статья",
    )
    keyword = st.text_input(
        "Основное ключевое слово",
        placeholder="например: home arcade machine for adults",
        help="Главный поисковый запрос, под который оптимизируется статья",
    )

with col2:
    funnel_map = {"Верхний (Top) — информационный": "top", "Средний (Mid) — сравнение": "mid", "Нижний (Bottom) — покупка": "bottom"}
    funnel_label = st.selectbox(
        "Этап воронки",
        options=list(funnel_map.keys()),
        index=1,
        help="На каком этапе принятия решения находится читатель",
    )
    funnel_stage = funnel_map[funnel_label]

st.divider()

if st.button("Сгенерировать статью", type="primary", disabled=not (topic and keyword)):

    STEP_LABELS = [
        "Brief Agent",
        "SERP Research",
        "Company Insight",
        "SEO Structure",
        "Writer Agent",
        "QA Review",
        "Metadata",
    ]

    step_placeholders = []
    progress_col, _ = st.columns([3, 1])

    with progress_col:
        st.subheader("Прогресс")
        for label in STEP_LABELS:
            step_placeholders.append(st.empty())

    def _render_step(idx: int, status: str) -> None:
        icon = {"running": "⏳", "done": "✅", "pending": "⬜"}[status]
        step_placeholders[idx].markdown(f"{icon} **Шаг {idx + 1}:** {STEP_LABELS[idx]}")

    for i in range(len(STEP_LABELS)):
        _render_step(i, "pending")

    results: dict = {}
    error: str | None = None

    try:
        for event in run_pipeline(topic, keyword, funnel_stage):
            step_idx = event["step"] - 1
            if event["step"] == 0:
                results = event["results"]
                break
            if event["status"] == "running":
                _render_step(step_idx, "running")
            elif event["status"] == "done":
                _render_step(step_idx, "done")
    except Exception as exc:
        error = str(exc)

    st.divider()

    if error:
        st.error(f"Ошибка: {error}")
    elif results:
        st.success("Статья готова!")

        draft_markdown: str = results.get("draft_markdown", "")
        metadata: dict | None = results.get("metadata")
        qa_report: dict | None = results.get("qa_report")
        draft_md_path: Path | None = results.get("draft_md_path")

        # Download button
        filename = draft_md_path.name if draft_md_path else "article.md"
        st.download_button(
            label="Скачать статью (.md)",
            data=draft_markdown.encode("utf-8"),
            file_name=filename,
            mime="text/markdown",
        )

        # Metadata summary
        if metadata:
            with st.expander("SEO-метаданные", expanded=False):
                st.markdown(f"**Slug:** `{metadata.get('slug', '')}`")
                st.markdown(f"**H1:** {metadata.get('h1', '')}")
                st.markdown(f"**Meta Title:** {metadata.get('meta_title', '')}")
                st.markdown(f"**Meta Description:** {metadata.get('meta_description', '')}")

        # QA status
        if qa_report:
            status_val = qa_report.get("status", "unknown")
            counts = qa_report.get("severity_counts", {})
            badge = "✅ Прошёл QA" if status_val == "pass" else "⚠️ Требует проверки"
            st.info(
                f"{badge} — критических: {counts.get('high', 0)}, "
                f"средних: {counts.get('medium', 0)}, "
                f"низких: {counts.get('low', 0)}"
            )

        # Article preview
        st.subheader("Предпросмотр статьи")
        st.markdown(draft_markdown)
