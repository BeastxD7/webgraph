"""Command-line interface.

Kept dependency-free (argparse, not click) because the engine is meant to be embedded, and
a library that drags a CLI framework into its consumers' dependency trees is a bad citizen.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from webgraph.analyze import analyze_site
from webgraph.eval.harness import format_report, load_corpus, run_corpus
from webgraph.extract.schema import extract_facts, merge_facts
from webgraph.fetch.render import PLAYWRIGHT_AVAILABLE, geometry_by_xpath, render_page
from webgraph.fetch.static import fetch_static
from webgraph.pipeline import build_document
from webgraph.render_markdown import MarkdownOptions, to_markdown
from webgraph.site import SiteConfig, extract_site
from webgraph.types import Document

__all__ = ["main"]


def _load_source(url: str, *, render: bool, quiet: bool) -> tuple[str, dict[str, Any], str]:
    """Return (html, geometry, resolved_url), rendering only when asked or required.

    The static fetch runs first regardless: it is two orders of magnitude cheaper, and its
    result is what tells us whether a render is needed at all.
    """
    # Local files are rendered too when asked. They are valid file:// URLs and a browser
    # loads them fine -- returning early here would silently ignore --render and hand back
    # DOM order, which is exactly the wrong answer on a CSS-reordered page.
    if url.startswith("file://") or Path(url).exists():
        path = Path(url.removeprefix("file://"))
        target = path.resolve().as_uri()
        html = path.read_text(encoding="utf-8")
    else:
        result = fetch_static(url)
        if not result.ok:
            raise SystemExit(f"fetch failed: {result.error}")
        target = result.url
        html = result.html

    if not render:
        probe = build_document(html, target)
        if not probe.profile.requires_render:
            return html, {}, target
        if not quiet:
            print(
                f"note: static HTML looks like a shell "
                f"({'; '.join(probe.profile.signals[:1])}); rendering",
                file=sys.stderr,
            )

    if not PLAYWRIGHT_AVAILABLE:
        if not quiet:
            print(
                "warning: playwright not installed, falling back to static HTML. "
                "Reading order will use DOM order rather than measured geometry.",
                file=sys.stderr,
            )
        return html, {}, target

    rendered = render_page(target)
    if not rendered.ok:
        if not quiet:
            print(f"warning: render failed ({rendered.error}); using static HTML", file=sys.stderr)
        return html, {}, target

    return rendered.html, geometry_by_xpath(rendered.html, rendered.rects), rendered.url


def _describe(document: Document) -> dict[str, Any]:
    return {
        "url": document.url,
        "content_hash": document.content_hash,
        "reading_order": document.reading_order_method.value,
        "dom_order_differs": document.dom_order_differs,
        "blocks": len(document.blocks),
        "frameworks": list(document.profile.frameworks),
        "requires_render": document.profile.requires_render,
        "payloads": [p.source.value for p in document.structured_data],
    }


def _cmd_text(args: argparse.Namespace) -> int:
    html, geometry, url = _load_source(args.url, render=args.render, quiet=args.quiet)
    document = build_document(html, url, geometry=geometry, rtl=args.rtl)

    if args.markdown:
        print(to_markdown(document, options=MarkdownOptions(front_matter=args.front_matter)))
        return 0

    if args.json:
        print(json.dumps({**_describe(document), "text": document.text}, indent=2))
    else:
        if not args.quiet:
            marker = "measured" if geometry else "DOM order (no geometry)"
            print(f"# {url}\n# reading order: {marker}\n", file=sys.stderr)
        print(document.text)
    return 0


def _cmd_extract(args: argparse.Namespace) -> int:
    schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    html, geometry, url = _load_source(args.url, render=args.render, quiet=args.quiet)
    document = build_document(html, url, geometry=geometry, rtl=args.rtl)

    facts = extract_facts(document.structured_data, schema, url)
    merged = merge_facts(facts)

    output = {
        **_describe(document),
        "facts": {
            path: {
                "value": fact.value,
                "confidence": fact.provenance.confidence,
                "extractor": fact.provenance.extractor.value,
                "modality": fact.provenance.modality.value,
                "source": fact.provenance.note,
                "source_xpath": fact.provenance.source_xpath,
            }
            for path, fact in sorted(merged.items())
        },
    }
    print(json.dumps(output, indent=2, default=str))
    return 0 if merged else 1


def _cmd_analyze(args: argparse.Namespace) -> int:
    """Stage 0: identify the stack, measure whether rendering is needed, count public pages."""
    analysis = analyze_site(args.url)
    if args.json:
        print(json.dumps(analysis.__dict__, indent=2, default=str))
    else:
        print(analysis.report())
    return 0 if analysis.reachable else 1


def _cmd_site(args: argparse.Namespace) -> int:
    """Full pipeline: analyse, enumerate, crawl every page, aggregate."""
    schema = json.loads(Path(args.schema).read_text(encoding="utf-8")) if args.schema else None
    result = extract_site(
        args.url,
        schema=schema,
        config=SiteConfig(max_pages=args.max_pages, concurrency=args.concurrency),
    )
    print(result.report())
    return 0


def _cmd_bench(args: argparse.Namespace) -> int:
    cases = load_corpus(Path(args.corpus))
    score = run_corpus(cases)
    print(format_report(score, verbose=args.verbose))

    if args.min_page_success is not None and score.page_level_success < args.min_page_success:
        print(
            f"\nFAIL: page-level success {score.page_level_success:.1%} "
            f"below threshold {args.min_page_success:.1%}",
            file=sys.stderr,
        )
        return 1
    if score.wrong_rate > 0:
        # A wrong value is categorically worse than a miss: it means something guessed.
        print(f"\nWARNING: wrong-value rate is {score.wrong_rate:.1%}, expected 0", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="webgraph",
        description="Universal web content extraction with provenance and reading-order recovery.",
    )
    parser.add_argument("--quiet", "-q", action="store_true", help="suppress progress notes")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_page_args(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("url", help="URL or local HTML file")
        sub.add_argument(
            "--render",
            action="store_true",
            help="force a browser render (needed for accurate reading order)",
        )
        sub.add_argument("--rtl", action="store_true", help="right-to-left reading direction")

    text = subparsers.add_parser("text", help="print page text in reading order")
    add_page_args(text)
    text.add_argument("--json", action="store_true", help="emit JSON with diagnostics")
    text.add_argument(
        "--markdown", "-m", action="store_true",
        help="emit Markdown with headings, images, links and tables preserved",
    )
    text.add_argument(
        "--front-matter", action="store_true", help="prepend YAML front matter (with --markdown)"
    )
    text.set_defaults(func=_cmd_text)

    extract = subparsers.add_parser("extract", help="extract facts against a JSON Schema")
    add_page_args(extract)
    extract.add_argument("--schema", required=True, help="path to a JSON Schema file")
    extract.set_defaults(func=_cmd_extract)

    analyze = subparsers.add_parser(
        "analyze", help="profile a site: technology, rendering behaviour, public page count"
    )
    analyze.add_argument("url", help="site root URL")
    analyze.add_argument("--json", action="store_true", help="emit JSON")
    analyze.set_defaults(func=_cmd_analyze)

    site = subparsers.add_parser(
        "site", help="analyse, enumerate and extract an entire site"
    )
    site.add_argument("url", help="site root URL")
    site.add_argument("--schema", help="optional JSON Schema file to extract against")
    site.add_argument("--max-pages", type=int, default=40)
    site.add_argument("--concurrency", type=int, default=4)
    site.set_defaults(func=_cmd_site)

    bench = subparsers.add_parser("bench", help="score the engine against a labelled corpus")
    bench.add_argument("corpus", help="corpus directory containing gold.json")
    bench.add_argument("--verbose", "-v", action="store_true", help="show every field")
    bench.add_argument(
        "--min-page-success",
        type=float,
        default=None,
        help="exit non-zero below this page-level success rate (0-1), for CI",
    )
    bench.set_defaults(func=_cmd_bench)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
