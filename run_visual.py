#!/usr/bin/env python3
"""JVL Content Engine — Visual Agent CLI.

Specifies 3 image assets (1 hero + 2 inline) for an article draft,
generates them via DALL-E 3 (or mock placeholders), downloads locally,
and injects image markdown into the draft at fixed H2-based positions.

Required:
  --topic           Article topic
  --draft           Path to draft .md OR Writer wrapper .json

Optional:
  --brief           Path to brief JSON
  --output-dir      Images directory (default: outputs/images/<slug>)
  --visuals-dir     JSON output directory (default: outputs/visuals)

Examples:

  # Mock mode (no OPENAI_API_KEY set)
  python run_visual.py \\
    --topic "how to choose a home arcade machine" \\
    --draft outputs/drafts/how-to-choose-a-home-arcade-machine.json

  # Live mode (requires OPENAI_API_KEY in .env)
  python run_visual.py \\
    --topic "how to choose a home arcade machine" \\
    --draft outputs/drafts/how-to-choose-a-home-arcade-machine.json \\
    --brief outputs/briefs/how-to-choose-a-home-arcade-machine.json

Output:
  outputs/visuals/<slug>.json          — asset metadata (paths, sources, alt texts)
  outputs/images/<slug>/hero-01.png    — hero image (or placeholder)
  outputs/images/<slug>/inline-01.png  — inline image 1
  outputs/images/<slug>/inline-02.png  — inline image 2
  outputs/drafts/<slug>.md             — enriched draft with images injected
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.visual_agent import VisualAgent  # noqa: E402


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
        description="JVL Content Engine — Visual Agent CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--topic", required=True, help="Article topic")
    parser.add_argument("--draft", required=True, dest="draft_path")
    parser.add_argument("--brief", dest="brief_path", default=None)
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        default=None,
        help="Images directory (default: outputs/images/<slug>)",
    )
    parser.add_argument(
        "--visuals-dir",
        dest="visuals_dir",
        default="outputs/visuals",
        help="JSON output directory (default: outputs/visuals)",
    )

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
    # Load optional brief
    # ----------------------------------------------------------------
    brief = _load_json(args.brief_path, "brief") if args.brief_path else None

    slug = slugify(args.topic)

    output_dir = Path(args.output_dir) if args.output_dir else None

    print(f"\nVisual Agent starting...", file=sys.stderr)
    print(f"  Topic: {args.topic}", file=sys.stderr)
    print(f"  Draft: {args.draft_path}", file=sys.stderr)
    print(f"  Brief: {'yes' if brief else 'no'}\n", file=sys.stderr)

    # ----------------------------------------------------------------
    # Run Visual Agent
    # ----------------------------------------------------------------
    agent = VisualAgent()
    result = agent.run(
        topic=args.topic,
        brief=brief,
        draft_markdown=draft_markdown,
        output_dir=output_dir,
    )

    # ----------------------------------------------------------------
    # Save visuals JSON
    # ----------------------------------------------------------------
    visuals_dir = Path(args.visuals_dir)
    visuals_dir.mkdir(parents=True, exist_ok=True)
    visuals_path = visuals_dir / f"{slug}.json"
    with open(visuals_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)

    # ----------------------------------------------------------------
    # Overwrite draft .md with enriched version
    # ----------------------------------------------------------------
    draft_md_path = Path(args.draft_path)
    if draft_md_path.suffix.lower() == ".json":
        draft_md_path = draft_md_path.with_suffix(".md")
    draft_md_path.write_text(result["enriched_markdown"], encoding="utf-8")

    # ----------------------------------------------------------------
    # Summary
    # ----------------------------------------------------------------
    assets = result.get("assets", [])
    dalle_count = sum(1 for a in assets if a.get("source") == "dalle3")
    mock_count = sum(1 for a in assets if a.get("source") == "mock")
    failed_count = sum(
        1 for a in assets if a.get("source") == "dalle3_download_failed"
    )

    print(f"\nVisual Agent complete.", file=sys.stderr)
    print(f"  Assets   : {len(assets)}", file=sys.stderr)
    print(f"  dalle3   : {dalle_count}", file=sys.stderr)
    print(f"  mock     : {mock_count}", file=sys.stderr)
    if failed_count:
        print(f"  failed   : {failed_count}", file=sys.stderr)
    print(f"  Visuals JSON → {visuals_path}", file=sys.stderr)
    print(f"  Enriched draft → {draft_md_path}", file=sys.stderr)

    print(str(visuals_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
