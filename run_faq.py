#!/usr/bin/env python3
"""JVL Content Engine — FAQ Agent CLI.

Produces a FAQ block (5+ PAA-style items) for an Echo Home article.
Outputs structured JSON to outputs/faq/<slug>.json.

No live internet access required — all output is grounded in knowledge files.

Required:
  --topic           Article topic
  --draft           Path to draft .md OR Writer wrapper .json

Optional:
  --brief           Path to brief JSON from Brief Agent
  --seo-outline     Path to SEO structure JSON from SEO Structure Agent
  --output-dir      Save location (default: outputs/faq)

Examples:

  # Full chain
  python run_faq.py \\
    --topic "how to choose a home arcade machine" \\
    --draft outputs/drafts/how-to-choose-a-home-arcade-machine.json \\
    --brief outputs/briefs/how-to-choose-a-home-arcade-machine.json \\
    --seo-outline outputs/seo_structure/how-to-choose-a-home-arcade-machine.json

  # Draft only (minimal)
  python run_faq.py \\
    --topic "no wifi arcade machine" \\
    --draft outputs/drafts/no-wifi-arcade-machine.md

Output:
  outputs/faq/<slug>.json   — FAQ block with 5+ items
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.faq_agent import FaqAgent  # noqa: E402


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
        description="JVL Content Engine — FAQ Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--topic", required=True)
    parser.add_argument("--draft", required=True, dest="draft_path")
    parser.add_argument("--brief", dest="brief_path", default=None)
    parser.add_argument("--seo-outline", dest="seo_outline_path", default=None)
    parser.add_argument("--output-dir", dest="output_dir", default="outputs/faq")

    args = parser.parse_args()

    # ----------------------------------------------------------------
    # Load draft (required)
    # ----------------------------------------------------------------
    try:
        draft_markdown, _ = _load_draft(args.draft_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # ----------------------------------------------------------------
    # Load optional upstream context
    # ----------------------------------------------------------------
    brief = _load_json(args.brief_path, "brief") if args.brief_path else None
    seo_outline = (
        _load_json(args.seo_outline_path, "SEO outline") if args.seo_outline_path else None
    )

    print(f"\nFAQ Agent starting...", file=sys.stderr)
    print(f"  Topic     : {args.topic}", file=sys.stderr)
    print(f"  Draft     : {args.draft_path}", file=sys.stderr)
    print(f"  Brief     : {'yes' if brief else 'no'}", file=sys.stderr)
    print(f"  SEO outline: {'yes' if seo_outline else 'no'}\n", file=sys.stderr)

    # ----------------------------------------------------------------
    # Run FAQ Agent
    # ----------------------------------------------------------------
    agent = FaqAgent()
    result = agent.run(
        topic=args.topic,
        brief=brief,
        seo_outline=seo_outline,
        draft_markdown=draft_markdown,
    )

    # ----------------------------------------------------------------
    # Save
    # ----------------------------------------------------------------
    slug = slugify(args.topic)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{slug}.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)

    print(f"\nFAQ saved → {out_path}", file=sys.stderr)
    print(f"  FAQ items : {len(result.get('items', []))}", file=sys.stderr)
    print(f"  TODOs     : {len(result.get('todos', []))}", file=sys.stderr)

    print(str(out_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
