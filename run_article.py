#!/usr/bin/env python3
"""JVL Content Engine — full article pipeline from the command line.

A thin caller over `src.orchestrator.run_pipeline`, the same generator the
Streamlit UI drives. This file used to wire the agents itself, and the two
copies drifted: this one never gained the Readability, FAQ or Diagnostic
agents added in May, so a CLI run quietly produced a worse article than the
same topic through the web UI.

Examples
--------
    python run_article.py --topic "Best bartop arcade machines" \\
        --primary-keyword "bartop arcade machine"

    # cheap dev run: no SERP calls, no QA, no images
    python run_article.py --topic "..." --primary-keyword "..." \\
        --skip "SERP Research" --skip "QA Review"

    # include generated images (costs money)
    python run_article.py --topic "..." --primary-keyword "..." --with-visuals
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.orchestrator import SKIPPABLE, pipeline_steps, run_pipeline  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="JVL Content Engine — full article pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--topic", required=True, help="Article topic")
    parser.add_argument(
        "--primary-keyword", dest="primary_keyword", required=True,
        help="Primary SEO keyword",
    )
    parser.add_argument(
        "--funnel-stage", dest="funnel_stage",
        choices=["top", "mid", "bottom"], default="mid",
        help="Funnel stage (default: mid)",
    )
    parser.add_argument(
        "--secondary-keyword", dest="secondary_keywords", action="append", default=[],
        metavar="KEYWORD", help="Secondary keyword; repeat for more than one",
    )
    parser.add_argument(
        "--requirements", dest="custom_requirements", default="",
        help="Extra instructions passed to the Writer",
    )
    parser.add_argument("--country", default="US", help="Target country (default: US)")
    parser.add_argument("--language", default="en", help="Language (default: en)")
    parser.add_argument(
        "--skip", dest="skip", action="append", default=[], metavar="STEP",
        help=f"Skip a step; repeat to skip several. One of: {', '.join(sorted(SKIPPABLE))}",
    )
    parser.add_argument(
        "--with-visuals", dest="with_visuals", action="store_true",
        help="Run the Visual Agent (generates images via gpt-image — costs money)",
    )
    parser.add_argument(
        "--resume", dest="resume", action="store_true",
        help=(
            "Reuse the brief, facts, SERP research, insight and outline already "
            "in --output-root instead of regenerating them. For picking a run "
            "back up after it failed at the Writer or later — the steps before "
            "it are the expensive half, and Fact Research pays per search."
        ),
    )
    parser.add_argument(
        "--output-root", dest="output_root", default="outputs",
        help="Root output directory (default: outputs)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    unknown = set(args.skip) - SKIPPABLE
    if unknown:
        print(
            f"Unknown --skip value(s): {', '.join(sorted(unknown))}\n"
            f"Valid steps: {', '.join(sorted(SKIPPABLE))}",
            file=sys.stderr,
        )
        return 2

    steps = pipeline_steps(args.with_visuals)
    total = len(steps)
    results: dict = {}

    for event in run_pipeline(
        topic=args.topic,
        primary_keyword=args.primary_keyword,
        funnel_stage=args.funnel_stage,
        secondary_keywords=args.secondary_keywords,
        custom_requirements=args.custom_requirements,
        output_root=Path(args.output_root),
        skip=set(args.skip),
        with_visuals=args.with_visuals,
        country=args.country,
        language=args.language,
        reuse=args.resume,
    ):
        if event["step"] == 0:
            results = event["results"]
            break
        if event["status"] == "running":
            marker = "SKIP" if event["label"] in args.skip else "····"
            print(f"[{event['step']:>2}/{total}] {marker} {event['label']}", file=sys.stderr)

    draft_path = results.get("draft_md_path")
    if not draft_path:
        error = results.get("error")
        failed = results.get("failed_step")
        if error:
            print(f"\n{failed or 'Pipeline'} failed: {error}", file=sys.stderr)
        else:
            print("\nPipeline finished without producing a draft.", file=sys.stderr)

        # Say what survived. The expensive steps run before the Writer, and a
        # run that dies there should not look like it produced nothing.
        for label, key in (
            ("brief", "brief_path"),
            ("facts", "facts_path"),
            ("serp", "serp_path"),
            ("insight", "insight_path"),
            ("outline", "seo_path"),
        ):
            path = results.get(key)
            if path:
                print(f"  {label:8s}: {path}", file=sys.stderr)
        return 1

    metadata = results.get("metadata") or {}
    qa_report = results.get("qa_report") or {}
    print("\nDone.", file=sys.stderr)
    print(f"  article  : {draft_path}", file=sys.stderr)
    print(f"  companion: {results.get('draft_json_path')}", file=sys.stderr)
    if metadata:
        print(f"  slug     : {metadata.get('slug', '?')}", file=sys.stderr)
    if qa_report:
        print(f"  QA       : {qa_report.get('status', 'unknown')}", file=sys.stderr)
    # A draft that ends over its target with nothing said about why used to be
    # visible only by counting the file afterwards.
    # The measurement everything else was planned against. "mock" means the
    # search did not answer and the article was written to a default.
    serp_status = results.get("serp_status")
    if serp_status and serp_status != "live":
        print(
            f"  SERP     : {serp_status} — no live measurement, so the length "
            "target and section allowance were defaults",
            file=sys.stderr,
        )
    length = results.get("length_check") or {}
    if length:
        print(
            f"  length   : {length.get('word_count')} words ({length.get('verdict')})",
            file=sys.stderr,
        )

    # stdout is the article itself, so the run can be piped.
    print(results.get("draft_markdown", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
