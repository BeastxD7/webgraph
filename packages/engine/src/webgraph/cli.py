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


def _since(raw: str | None) -> float | None:
    """`--since` as an epoch timestamp: seconds, an ISO date or datetime, or `3d`/`12h`."""
    if not raw:
        return None
    import re
    import time
    from datetime import datetime

    if re.fullmatch(r"\d+(?:\.\d+)?", raw):
        return float(raw)
    relative = re.fullmatch(r"(\d+)([smhdw])", raw)
    if relative:
        unit = {"s": 1, "m": 60, "h": 3600, "d": 86_400, "w": 604_800}[relative.group(2)]
        return time.time() - int(relative.group(1)) * unit
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        from datetime import UTC

        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _cmd_watch_create(args: argparse.Namespace) -> int:
    """Register a site to watch and print its id."""
    from webgraph.watch import create_watch

    options: dict[str, Any] = {}
    if args.max_pages is not None:
        options["max_pages"] = args.max_pages
    if args.max_seconds is not None:
        options["max_seconds"] = args.max_seconds
    if args.complete:
        options["complete"] = True
    if args.no_noise:
        options["noise"] = False
    if args.config:
        options.update(json.loads(Path(args.config).read_text(encoding="utf-8")))
    watch = create_watch(
        args.url, options, schedule_seconds=args.schedule_seconds, store=args.db
    )
    if args.json:
        print(json.dumps(watch.as_dict(), indent=2))
    else:
        print(watch.id)
        print(f"watching {watch.root}", file=sys.stderr)
        print("run it with: webgraph watch run " + watch.id, file=sys.stderr)
    return 0


def _cmd_watch_list(args: argparse.Namespace) -> int:
    from webgraph.watch import list_watches

    watches = list_watches(store=args.db)
    if args.json:
        print(json.dumps([w.as_dict() for w in watches], indent=2))
        return 0
    for watch in watches:
        print(f"{watch.id}  {watch.root}")
    if not watches:
        print("no watches. create one with: webgraph watch create <url>", file=sys.stderr)
    return 0


def _cmd_watch_run(args: argparse.Namespace) -> int:
    """Run a watch once; print what changed. Non-zero on change with --fail-on-change."""
    from webgraph.watch import run_watch

    def progress(event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "page" and not args.quiet:
            mark = "ok " if event.get("ok") else "err"
            print(f"  [{event['index']:>4}] {mark} {event['url'][:96]}", file=sys.stderr)
        elif kind == "change":
            headings = ", ".join(
                (s.get("heading") or "(opening)") for s in event.get("sections", [])[:3]
            )
            print(f"  {event['kind']:<8} {event['url']}  {headings}", file=sys.stderr)
        elif kind == "error":
            print(f"  error: {event['message']}", file=sys.stderr)

    summary = run_watch(args.id, store=args.db, on_event=progress)
    if args.json:
        print(json.dumps(summary.as_dict(), indent=2))
    else:
        print(summary.summary())
        for change in summary.changes:
            print(f"  {change.kind:<8} {change.url}")
            for section in change.sections[: args.detail]:
                heading = section.get("heading") or "(opening)"
                print(f"      {section.get('kind', 'edited'):<8} {heading}")
    return 1 if (args.fail_on_change and summary.any_change) else 0


def _cmd_watch_changes(args: argparse.Namespace) -> int:
    """Print a watch's changes as json, md, rss or atom."""
    from webgraph.watch import export_changes

    print(export_changes(args.id, _since(args.since), fmt=args.format, store=args.db), end="")
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

    watch = subparsers.add_parser(
        "watch", help="watch a site for changes: create, run, changes, list"
    )
    watch_sub = watch.add_subparsers(dest="watch_command", required=True)

    def db_flag(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "--db", help="SQLite file (default: ~/.cache/webgraph/watch.sqlite3 or WEBGRAPH_WATCH_DB)"
        )
        sub.add_argument("--json", action="store_true", help="emit JSON")

    create = watch_sub.add_parser("create", help="register a site to watch; prints its id")
    create.add_argument("url", help="site root URL")
    create.add_argument("--max-pages", type=int, default=None, help="0 for unlimited")
    create.add_argument("--max-seconds", type=float, default=None)
    create.add_argument("--complete", action="store_true", help="union fetch (static + rendered)")
    create.add_argument("--no-noise", action="store_true", help="compare dates and counters too")
    create.add_argument(
        "--schedule-seconds", type=int, default=0, help="advisory: how often you mean to run it"
    )
    create.add_argument("--config", help="JSON file of SiteConfig fields and watch options")
    db_flag(create)
    create.set_defaults(func=_cmd_watch_create)

    listing = watch_sub.add_parser("list", help="list watches")
    db_flag(listing)
    listing.set_defaults(func=_cmd_watch_list)

    run = watch_sub.add_parser("run", help="crawl again and record what changed")
    run.add_argument("id", help="watch id")
    run.add_argument("--detail", type=int, default=8, help="sections listed per page")
    run.add_argument(
        "--fail-on-change",
        action="store_true",
        help="exit non-zero when anything changed, for a scheduled job",
    )
    db_flag(run)
    run.set_defaults(func=_cmd_watch_run)

    changes = watch_sub.add_parser("changes", help="print recorded changes")
    changes.add_argument("id", help="watch id")
    changes.add_argument(
        "--since", help="epoch seconds, an ISO date, or a span such as 12h or 7d"
    )
    changes.add_argument("--format", choices=("json", "md", "rss", "atom"), default="md")
    db_flag(changes)
    changes.set_defaults(func=_cmd_watch_changes)

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
