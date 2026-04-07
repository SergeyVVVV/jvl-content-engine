#!/usr/bin/env python3
"""JVL Content Engine — Metadata Copy Agent CLI.

Small downstream copy agent. Runs after QA. Generates final publish-support
text assets (meta title, H1, meta description, slug, OG fields, image alt
texts, excerpt) for a single article.

Required:
  --topic   Article topic
  --draft   Path to draft .md OR Writer wrapper .json

Optional:
  --brief        Path to brief JSON
  --qa-report    Path to QA report JSON
  --output-dir   Save location (default: outputs/metadata)

Example:

  python run_metadata.py \\
    --topic "how to choose a home arcade machine" \\
    --draft outputs/drafts/how-to-choose-a-home-arcade-machine.json \\
    --brief outputs/briefs/how-to-choose-a-home-arcade-machine.json \\
    --qa-report outputs/qa/how-to-choose-a-home-arcade-machine.json

Output:
  outputs/metadata/<slug>.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.metadata_copy_agent import MetadataCopyAgent  # noqa: E402


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


def _load_draft(path: str) -> str:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Draft file not found: {p}")
    if p.suffix.lower() == ".json":
        wrapper = json.loads(p.read_text(encoding="utf-8"))
        md = wrapper.get("draft_markdown", "")
        if not md:
            raise ValueError(
                f"Draft JSON {p} has no 'draft_markdown' field — pass the .md file."
            )
        return md
    return p.read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="JVL Content Engine — Metadata Copy Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--topic", required=True)
    parser.add_argument("--draft", required=True, dest="draft_path")
    parser.add_argument("--brief", dest="brief_path", default=None)
    parser.add_argument("--qa-report", dest="qa_path", default=None)
    parser.add_argument("--output-dir", dest="output_dir", default="outputs/metadata")
    args = parser.parse_args()

    try:
        draft_markdown = _load_draft(args.draft_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    brief = _load_json(args.brief_path, "brief") if args.brief_path else None
    qa_report = _load_json(args.qa_path, "QA report") if args.qa_path else None

    source_inputs_used = {
        "draft": args.draft_path,
        "brief": args.brief_path,
        "qa_report": args.qa_path,
    }

    print("\nMetadata Copy Agent starting...", file=sys.stderr)
    print(f"  Topic: {args.topic}", file=sys.stderr)
    print(f"  Draft: {args.draft_path}", file=sys.stderr)
    print(f"  Brief: {'yes' if brief else 'no'}", file=sys.stderr)
    print(f"  QA   : {'yes' if qa_report else 'no'}\n", file=sys.stderr)

    agent = MetadataCopyAgent()
    out = agent.run(
        topic=args.topic,
        draft_markdown=draft_markdown,
        brief=brief,
        qa_report=qa_report,
        source_inputs_used=source_inputs_used,
    )

    slug = out.get("slug") or slugify(args.topic)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{slugify(args.topic)}.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)

    print(f"\nMetadata saved → {out_path}", file=sys.stderr)
    print(f"  meta_title : {out.get('meta_title')}", file=sys.stderr)
    print(f"  slug       : {slug}", file=sys.stderr)

    print(str(out_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
