"""Command-line interface.

Kept dependency-free (argparse, not click) because the engine is meant to be embedded, and
a library that drags a CLI framework into its consumers' dependency trees is a bad citizen.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from webgraph.analyze import analyze_site
from webgraph.eval.harness import format_report, load_corpus, run_corpus
from webgraph.extract.schema import extract_facts, merge_facts
from webgraph.fetch.render import PLAYWRIGHT_AVAILABLE, geometry_by_xpath, render_page
from webgraph.fetch.static import fetch_static
from webgraph.pipeline import build_document
from webgraph.render_markdown import MarkdownOptions, to_markdown
from webgraph.site import SiteConfig, extract_site, stream_site
from webgraph.types import Document

if TYPE_CHECKING:  # pragma: no cover - typing only
    from webgraph.graph.model import SiteGraph

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


def _crawl_graph(
    urls: list[str], *, max_pages: int, concurrency: int, complete: bool
) -> SiteGraph:
    """Crawl one or more sites and return one graph over all of them.

    Several roots produce a corpus, merged into a single graph. Off-site links between the
    crawled sites become ordinary edges, so a question can cross from one site to another
    without the retriever knowing a boundary existed.
    """
    from webgraph.graph.build import GraphBuilder
    from webgraph.graph.corpus import Corpus
    from webgraph.graph.entities import derive_entities
    from webgraph.resolve import Strategy

    corpus = Corpus()
    for url in urls:
        builder = GraphBuilder(url)
        config = SiteConfig(
            max_pages=max_pages,
            concurrency=concurrency,
            strategy=Strategy.UNION if complete else Strategy.STATIC_ONLY,
        )
        for event in stream_site(url, config=config, builder=builder):
            if event["type"] == "page":
                print(
                    f"  [{event['extracted']:>4}] {event['url'][:96]}",
                    file=sys.stderr,
                )
            elif event["type"] == "error":
                print(f"  error: {event['message']}", file=sys.stderr)
        derive_entities(builder.graph)
        corpus.add(builder.graph)

    if len(corpus.sites) > 1:
        resolved = corpus.resolve_external()
        print(f"  resolved {resolved} cross-site redirects", file=sys.stderr)
        print(f"  {len(corpus.cross_links())} cross-site links", file=sys.stderr)
    return corpus.merged()


def _cmd_graph(args: argparse.Namespace) -> int:
    """Crawl and write the site graph out."""
    from webgraph.graph.export import to_cypher, to_jsonl

    graph = _crawl_graph(
        args.urls,
        max_pages=args.max_pages,
        concurrency=args.concurrency,
        complete=args.complete,
    )
    print(f"\n{graph.describe()}", file=sys.stderr)

    lines = (
        to_cypher(graph, include_text=args.include_text)
        if args.format == "cypher"
        else to_jsonl(graph)
    )
    if args.out:
        with Path(args.out).open("w", encoding="utf-8") as handle:
            for line in lines:
                handle.write(line + "\n")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        for line in lines:
            print(line)
    return 0


def _cmd_ask(args: argparse.Namespace) -> int:
    """Assemble a bounded context about a question, from a crawl or a saved graph."""
    from webgraph.graph.export import load_jsonl
    from webgraph.graph.retrieve import Budget, ContextAssembler

    if args.graph:
        graph = load_jsonl(args.graph)
    else:
        graph = _crawl_graph(
            args.urls,
            max_pages=args.max_pages,
            concurrency=args.concurrency,
            complete=args.complete,
        )

    if not graph.sections:
        print("no content in the graph", file=sys.stderr)
        return 1

    assembled = ContextAssembler(graph).assemble(
        args.query, budget=Budget(max_chars=args.max_chars)
    )

    # The context goes to stdout so it can be piped straight into a model; the account of how
    # it was chosen goes to stderr so it does not contaminate that.
    for item in assembled.sections_full:
        print(
            f"  [{item.hops} hop] {item.section.heading[:44]:46s} {item.reason[:48]}",
            file=sys.stderr,
        )
    print(
        f"\n  {assembled.stats['approx_tokens']:.0f} tokens from "
        f"{len(assembled.sections_full)} sections and "
        f"{len(assembled.pages_mapped)} pages listed but not included",
        file=sys.stderr,
    )
    print(assembled.text)
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

    graph = subparsers.add_parser(
        "graph", help="crawl one or more sites and export the graph"
    )
    graph.add_argument("urls", nargs="+", help="site roots; several are merged into one graph")
    graph.add_argument("--max-pages", type=int, default=40, help="0 for unlimited")
    graph.add_argument("--concurrency", type=int, default=6)
    graph.add_argument(
        "--complete",
        action="store_true",
        help="merge static and rendered fetches; slower and loses nothing",
    )
    graph.add_argument("--format", choices=("jsonl", "cypher"), default="jsonl")
    graph.add_argument(
        "--include-text",
        action="store_true",
        help="cypher only: embed section bodies rather than leaving them in the JSONL",
    )
    graph.add_argument("--out", help="write here instead of stdout")
    graph.set_defaults(func=_cmd_graph)

    ask = subparsers.add_parser(
        "ask", help="assemble a bounded context about a question"
    )
    ask.add_argument("query", help="what the context should be about")
    ask.add_argument("urls", nargs="*", help="site roots to crawl first")
    ask.add_argument("--graph", help="use a graph written by `webgraph graph` instead")
    ask.add_argument("--max-chars", type=int, default=120_000, help="~4 characters per token")
    ask.add_argument("--max-pages", type=int, default=40)
    ask.add_argument("--concurrency", type=int, default=6)
    ask.add_argument("--complete", action="store_true")
    ask.set_defaults(func=_cmd_ask)

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
