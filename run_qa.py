#!/usr/bin/env python3
"""JVL Content Engine — QA Agent v1 CLI.

Reviews a generated draft article and writes a structured JSON QA report.
Review-only — does NOT rewrite the article.

Required:
  --topic           Article topic
  --draft           Path to draft .md OR Writer wrapper .json

Optional:
  --brief           Path to brief JSON
  --serp-research   Path to SERP research JSON
  --company-insight Path to company insight JSON
  --output-dir      Save location (default: outputs/qa)

Examples:

  # Full chain
  python run_qa.py \\
    --topic "how to choose a home arcade machine" \\
    --draft outputs/drafts/how-to-choose-a-home-arcade-machine.json \\
    --brief outputs/briefs/how-to-choose-a-home-arcade-machine.json \\
    --serp-research outputs/serp_research/how-to-choose-a-home-arcade-machine.json \\
    --company-insight outputs/company_insight/how-to-choose-a-home-arcade-machine.json

  # Draft only (degraded)
  python run_qa.py \\
    --topic "no wifi arcade machine" \\
    --draft outputs/drafts/no-wifi-arcade-machine.md

Output:
  outputs/qa/<slug>.json   — structured QA report
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.qa_agent import QAAgent  # noqa: E402


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text)
    return text.strip("-")[:60]


def _load_json(path: str, label: str) -> dict | None:
    p = Path(path)
    if not p.exists():
        print(f"Warning: {label} file not found: {p} — skipping.", file=sys.stderr)
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    print(f"Loaded {label} from {p}", file=sys.stderr)
    return data


def _load_draft(path: str) -> tuple[str, dict | None]:
    """Return (markdown, wrapper_or_None) for either a .md or .json input."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Draft file not found: {p}")

    if p.suffix.lower() == ".json":
        wrapper = json.loads(p.read_text(encoding="utf-8"))
        md = wrapper.get("draft_markdown", "")
        if not md:
            raise ValueError(
                f"Draft JSON {p} has no 'draft_markdown' field — "
                "pass the .md file instead."
            )
        return md, wrapper

    return p.read_text(encoding="utf-8"), None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="JVL Content Engine — QA Agent v1",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--topic", required=True)
    parser.add_argument("--draft", required=True, dest="draft_path")
    parser.add_argument("--brief", dest="brief_path", default=None)
    parser.add_argument("--serp-research", dest="serp_research_path", default=None)
    parser.add_argument("--company-insight", dest="company_insight_path", default=None)
    parser.add_argument("--output-dir", dest="output_dir", default="outputs/qa")

    args = parser.parse_args()

    # ----------------------------------------------------------------
    # Load draft (required)
    # ----------------------------------------------------------------
    try:
        draft_markdown, draft_wrapper = _load_draft(args.draft_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # ----------------------------------------------------------------
    # Load optional upstream context
    # ----------------------------------------------------------------
    brief = _load_json(args.brief_path, "brief") if args.brief_path else None
    serp_data = (
        _load_json(args.serp_research_path, "SERP research")
        if args.serp_research_path
        else None
    )
    insight_data = (
        _load_json(args.company_insight_path, "company insight")
        if args.company_insight_path
        else None
    )

    source_inputs_used = {
        "draft": args.draft_path,
        "brief": args.brief_path,
        "serp_research": args.serp_research_path,
        "company_insight": args.company_insight_path,
    }

    print(f"\nQA Agent starting...", file=sys.stderr)
    print(f"  Topic: {args.topic}", file=sys.stderr)
    print(f"  Draft: {args.draft_path}", file=sys.stderr)
    print(f"  Brief: {'yes' if brief else 'no (degraded)'}", file=sys.stderr)
    print(f"  SERP : {'yes' if serp_data else 'no'}", file=sys.stderr)
    print(f"  Insight: {'yes' if insight_data else 'no'}\n", file=sys.stderr)

    # ----------------------------------------------------------------
    # Run QA Agent
    # ----------------------------------------------------------------
    agent = QAAgent()
    report = agent.run(
        topic=args.topic,
        draft_markdown=draft_markdown,
        draft_wrapper=draft_wrapper,
        brief=brief,
        serp_data=serp_data,
        insight_data=insight_data,
        source_inputs_used=source_inputs_used,
    )

    # ----------------------------------------------------------------
    # Save
    # ----------------------------------------------------------------
    slug = slugify(args.topic)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{slug}.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)

    counts = report.get("severity_counts", {})
    print(f"\nQA report saved → {out_path}", file=sys.stderr)
    print(f"  Status   : {report.get('status')}", file=sys.stderr)
    print(
        f"  Severity : high={counts.get('high', 0)} "
        f"medium={counts.get('medium', 0)} low={counts.get('low', 0)}",
        file=sys.stderr,
    )

    print(str(out_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
