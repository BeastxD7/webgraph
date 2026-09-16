"""Command-line interface.

Kept dependency-free (argparse, not click) because the engine is meant to be embedded, and
a library that drags a CLI framework into its consumers' dependency trees is a bad citizen.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from webgraph.analyze import analyze_site
from webgraph.content import select_content
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

__all__ = ["format_site_report", "main"]


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
    document = build_document(
        html,
        url,
        geometry=geometry,
        rtl=True if args.rtl else None,
        include_hidden_text=args.include_hidden_text,
    )

    if args.content:
        # The same reduction the crawl applies -- landmarks, then the main-content boundary.
        # A single page has no cross-page chrome profile, and says so via the method list.
        selection = select_content(document.blocks, title=document.title)
        document = document.model_copy(update={"blocks": tuple(selection.blocks)})
        if not args.quiet:
            print(
                f"# content: {selection.kept}/{selection.total} blocks kept"
                + (f" ({', '.join(selection.methods)})" if selection.methods else ""),
                file=sys.stderr,
            )

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
    document = build_document(
        html,
        url,
        geometry=geometry,
        rtl=True if args.rtl else None,
        include_hidden_text=args.include_hidden_text,
    )

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
        print(json.dumps(asdict(analysis), indent=2, default=str))
    else:
        print(analysis.report())
    return 0 if analysis.reachable else 1


def _cmd_report(args: argparse.Namespace) -> int:
    """Site report: what the site shows people, what it shows machines, how ready it is
    for agents. `--json` is the whole report; the default is a readable summary."""
    from webgraph.report import build_site_report

    report = build_site_report(args.url, pages=args.pages)
    if args.json:
        print(json.dumps(report.as_dict(), indent=2, default=str))
        return 0 if report.reachable else 1
    for line in format_site_report(report):
        print(line)
    return 0 if report.reachable else 1


def format_site_report(report: Any) -> list[str]:
    """The report as lines for a terminal: the score and its parts, the integrity
    findings, the pages, the bots, and how it was measured. The suggested files are
    printed in full at the end so they can be cut out."""
    lines: list[str] = []
    rule = "=" * 66
    lines += [rule, f"SITE REPORT  {report.url}", rule]
    if not report.reachable:
        lines += ["", "  NO REPORT: " + (report.refusal or "the root could not be read"), ""]
        lines.append("  The engine does not disguise itself to get past a refusal; see the message above.")
        return lines
    score = report.score
    lines += ["", f"  AI-READINESS  {score.total}/100" + (
        f"  (of {score.measured_weight} measured points)" if score.measured_weight < 100 else ""
    )]
    for sub in score.subscores:
        earned = "unmeasured" if sub.score is None else f"{sub.score:>4.1f}/{sub.weight}"
        lines.append(f"    {earned:>12}  {sub.label}")
        lines.append(f"                  {sub.evidence}")
        if sub.recommendation:
            lines.append(f"                  -> {sub.recommendation}")
    lines += ["", "  INTEGRITY"]
    if report.findings:
        for finding in report.findings:
            where = f"  ({finding.page})" if finding.page else ""
            lines.append(f"    [{finding.severity}] {finding.title}{where}")
            lines.append(f"      {finding.detail}")
    else:
        lines.append("    nothing found")
    lines += ["", "  STACK"]
    if report.stack:
        for entry in report.stack:
            when = f"  released {entry.released.isoformat()}, {entry.age_years:g} years ago" if entry.released else ""
            version = f" {entry.version}" if entry.version else ""
            lines.append(f"    {entry.name}{version}{when}")
    else:
        lines.append("    none detected")
    lines += ["", "  PAGES  (static words / rendered words / union; wall; hidden links; dead links)"]
    for page in report.pages:
        if page.error:
            lines.append(f"    {page.requested_url}")
            lines.append(f"      not read: {page.error}")
            continue
        lines.append(
            f"    {page.requested_url}\n      {page.static_words:,} / {page.rendered_words:,} / "
            f"{page.union_words:,} words  ({page.static_coverage:.0%} without JavaScript); "
            f"wall: {page.wall or 'none'}; hidden links: {page.hidden_links} "
            f"({page.hidden_external_hosts} external hosts); dead links: {page.dead_count}/{page.links_checked}"
        )
    robots = report.robots
    lines += ["", f"  ROBOTS.TXT  {'found' if robots.found else 'not found'}"]
    lines.append("    what the file declares per bot (the engine never fetched as any of them):")
    for bot in robots.bots:
        via = {"named": "named", "wildcard": "via *", "none": "not mentioned"}[bot.via]
        delay = f", crawl-delay {bot.crawl_delay:g}s" if bot.crawl_delay else ""
        lines.append(f"      {bot.token:<20} {bot.access:<10} {via}{delay}")
    llms = report.llms_txt
    lines += [
        "",
        f"  LLMS.TXT  {'found' if llms and llms.found else 'not found'}"
        + (f"  ({llms.sections} sections, {llms.links} links)" if llms and llms.found else ""),
        f"    {report.llms_txt_note}",
    ]
    how = report.measured
    lines += [
        "",
        "  MEASURED",
        f"    webgraph {how.engine_version} @ {how.commit}; {how.pages_sampled} pages sampled; "
        f"{how.request_interval_seconds:g}s between requests; {how.duration_seconds:.0f}s in all",
        f"    {how.statement}",
        "",
        "  SUGGESTED robots.txt",
        "  " + "-" * 40,
        *report.suggested_robots_txt.splitlines(),
        "  " + "-" * 40,
        "",
        "  SUGGESTED llms.txt  (optional -- see the note above)",
        "  " + "-" * 40,
        *report.suggested_llms_txt.splitlines(),
        "  " + "-" * 40,
    ]
    return lines


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


def _cmd_diff(args: argparse.Namespace) -> int:
    """Crawl a site and report what changed since the last crawl of it."""
    from webgraph.graph.diff import diff_graphs
    from webgraph.graph.store import GraphStore

    store = GraphStore(args.store)
    previous = store.load(args.url)
    if previous is None and not args.save_only:
        print(
            f"No stored crawl of {args.url}. Crawling now and saving it as the baseline.",
            file=sys.stderr,
        )

    current = _crawl_graph(
        [args.url],
        max_pages=args.max_pages,
        concurrency=args.concurrency,
        complete=args.complete,
    )

    if previous is None:
        store.save(current, args.url)
        print(f"baseline saved: {current.describe()}")
        return 0

    result = diff_graphs(previous, current)
    print(f"\n{result.summary()}")

    for page in result.added:
        print(f"  + {page.url}")
    for page in result.removed:
        print(f"  - {page.url}")
    for change in result.changed:
        sign = "+" if change.delta_chars >= 0 else ""
        print(f"  ~ {change.url}  ({sign}{change.delta_chars} chars)")
        for section in change.sections[: args.detail]:
            heading = section.heading or "(opening)"
            if section.kind == "edited":
                print(f"      edited   {heading}")
                if args.show_text:
                    print(f"        was: {' '.join(section.before.split())[:160]}")
                    print(f"        now: {' '.join(section.after.split())[:160]}")
            else:
                print(f"      {section.kind:<8} {heading}")

    if not args.dry_run:
        store.save(current, args.url)

    # Non-zero on change, so this can drive a scheduled job without parsing the output.
    return 1 if (result.any_change and args.fail_on_change) else 0


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
        sub.add_argument(
            "--rtl",
            action="store_true",
            help="force right-to-left reading order (otherwise detected from dir/lang)",
        )
        sub.add_argument(
            "--include-hidden-text",
            action="store_true",
            help="keep screen-reader-only labels, skip links and wiki edit controls "
            "(text the browser holds but a sighted reader never sees)",
        )

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
    text.add_argument(
        "--content", "-c", action="store_true",
        help="keep only the page's content: navigation, footers and boilerplate removed",
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

    report = subparsers.add_parser(
        "report",
        help="site report: what the site shows people, what it shows machines, "
        "how ready it is for AI agents",
    )
    report.add_argument("url", help="site root URL")
    report.add_argument(
        "--pages", type=int, default=None, help="pages to sample (default REPORT_PAGES)"
    )
    report.add_argument("--json", action="store_true", help="emit the whole report as JSON")
    report.set_defaults(func=_cmd_report)

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

    diff = subparsers.add_parser(
        "diff", help="report what changed since the last crawl of a site"
    )
    diff.add_argument("url", help="site root URL")
    diff.add_argument("--store", help="graph directory (default: the shared cache)")
    diff.add_argument("--max-pages", type=int, default=40, help="0 for unlimited")
    diff.add_argument("--concurrency", type=int, default=6)
    diff.add_argument("--complete", action="store_true")
    diff.add_argument("--detail", type=int, default=8, help="sections listed per page")
    diff.add_argument("--show-text", action="store_true", help="print before and after")
    diff.add_argument(
        "--dry-run", action="store_true", help="do not update the stored baseline"
    )
    diff.add_argument(
        "--save-only", action="store_true", help="record a baseline without comparing"
    )
    diff.add_argument(
        "--fail-on-change",
        action="store_true",
        help="exit non-zero when anything changed, for a scheduled job",
    )
    diff.set_defaults(func=_cmd_diff)

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
