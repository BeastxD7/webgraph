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


# -- webgraph kg: the knowledge graph (behind WEBGRAPH_KG) ---------------------------------


def _kg_guard() -> None:
    from webgraph.settings import Settings

    if not Settings.from_env().kg_enabled:
        raise SystemExit("webgraph kg is behind a flag: set WEBGRAPH_KG=1 to use it.")


def _kg_provider(args: argparse.Namespace) -> Any:
    from webgraph.kg.providers import ProviderConfig, make_provider

    overrides = {
        key: value
        for key, value in (
            ("provider", args.provider),
            ("base_url", args.base_url),
            ("model", args.model),
            ("answer_model", getattr(args, "answer_model", None)),
            ("api_key_env", args.api_key_env),
        )
        if value
    }
    config = ProviderConfig.from_dict(overrides, base=ProviderConfig.from_env())
    if not config.model and config.provider != "fake":
        raise SystemExit("no model configured: pass --model or set WEBGRAPH_LLM_MODEL")
    return make_provider(config)


def _kg_graph(args: argparse.Namespace, *, crawl: bool) -> SiteGraph | None:
    """The crawled graph for a site: a JSONL file, a directory of pages, the store, or a
    fresh crawl (build only)."""
    from webgraph.graph.export import load_jsonl
    from webgraph.graph.store import GraphStore

    if getattr(args, "graph", None):
        return load_jsonl(args.graph)
    if getattr(args, "pages", None):
        from webgraph.kg.offline import graph_from_directory

        return graph_from_directory(args.pages, args.site)
    store = GraphStore()
    stored = store.load(args.site)
    if stored is not None or not crawl:
        return stored
    print(f"no stored crawl of {args.site}; crawling {args.max_pages} pages", file=sys.stderr)
    graph = _crawl_graph([args.site], max_pages=args.max_pages, concurrency=args.concurrency, complete=False)
    store.save(graph, args.site)
    return graph


def _cmd_kg_build(args: argparse.Namespace) -> int:
    _kg_guard()
    from webgraph.kg.build import BuildConfig, KGBuilder
    from webgraph.kg.store import KGStore

    graph = _kg_graph(args, crawl=True)
    if graph is None or not graph.sections:
        print("no crawled graph to build from", file=sys.stderr)
        return 1
    provider = _kg_provider(args)
    store = KGStore.for_site(args.site, args.kg_dir)
    config = BuildConfig(
        max_pages=args.max_pages_kg,
        max_sections=args.max_sections,
        max_input_tokens=args.max_input_tokens,
        max_usd=args.max_usd,
        concurrency=provider.config.max_concurrency,
        rebuild=args.rebuild,
    )
    try:
        for event in KGBuilder(graph, provider, store, build_config=config).run():
            if args.json:
                print(json.dumps(event, default=str))
                continue
            kind = event["type"]
            if kind == "estimate":
                usd = f", ~${event['usd']:.4f}" if event.get("usd") is not None else ""
                print(
                    f"estimate: {event['sections']} sections on {event['pages']} pages, "
                    f"{event['cached_sections']} cached, ~{event['input_tokens']:,} input tokens{usd} "
                    f"with {event['model']}",
                    file=sys.stderr,
                )
            elif kind == "section":
                mark = "cache" if event.get("cached") else "model"
                if "error" in event:
                    print(f"  [{event['done']:>4}/{event['total']}] error: {event['error'][:80]}", file=sys.stderr)
                else:
                    print(
                        f"  [{event['done']:>4}/{event['total']}] {mark:5} +{event['accepted']:<3} -{event['rejected']:<2} {event['heading'][:50]}",
                        file=sys.stderr,
                    )
            elif kind == "budget":
                print(f"cap reached: {event['reason']} ({event['remaining_sections']} sections left)", file=sys.stderr)
            elif kind == "done":
                stats = event["stats"]
                print(
                    f"done: {stats['entities']} entities, {stats['relations']} relations, "
                    f"{stats['accepted']} verified assertions, {stats['rejected']} rejected "
                    f"({stats['rejection_rate']:.1%}), {stats['input_tokens']:,} in / {stats['output_tokens']:,} out tokens, "
                    f"{stats['seconds']}s{' (truncated: ' + stats['truncated_reason'] + ')' if stats['truncated'] else ''}",
                    file=sys.stderr,
                )
                print(f"knowledge graph: {store.path}", file=sys.stderr)
    finally:
        store.close()
    return 0


def _cmd_kg_ask(args: argparse.Namespace) -> int:
    _kg_guard()
    from webgraph.kg.retrieve import KGRetriever
    from webgraph.kg.store import KGStore

    if not KGStore.exists_for(args.site, args.kg_dir):
        print(f"no knowledge graph for {args.site}; run `webgraph kg build {args.site}` first", file=sys.stderr)
        return 1
    provider = None if args.no_model else _kg_provider(args)
    graph = _kg_graph(args, crawl=False)
    store = KGStore.for_site(args.site, args.kg_dir)
    try:
        answer: dict[str, Any] | None = None
        for event in KGRetriever(store, provider, graph=graph).ask(args.question):
            if args.json:
                print(json.dumps(event, default=str))
            elif event["type"] == "seeds":
                print("seeds: " + ", ".join(e["name"] for e in event["entities"][:6]), file=sys.stderr)
            elif event["type"] == "hop":
                print(f"hop {event['hop']}: {len(event['edges'])} edges", file=sys.stderr)
            elif event["type"] == "evidence":
                print(f"evidence: {len(event['items'])} quotes", file=sys.stderr)
            elif event["type"] == "error":
                print(f"error: {event['message']}", file=sys.stderr)
            if event["type"] == "answer":
                answer = event
        if answer is None:
            return 1
        if not args.json:
            print(answer["text"])
            print()
            for citation in answer["citations"]:
                print(f"  [{citation['n']}] {citation['anchor']}\n      \u201c{citation['quote'][:160]}\u201d")
            if answer["unsupported"]:
                print(f"\n  {answer['unsupported']} sentence(s) cite nothing on the site and are flagged.", file=sys.stderr)
    finally:
        store.close()
    return 0


def _cmd_kg_export(args: argparse.Namespace) -> int:
    _kg_guard()
    from webgraph.kg.export import to_cypher, to_jsonl, to_jsonld
    from webgraph.kg.store import KGStore

    if not KGStore.exists_for(args.site, args.kg_dir):
        print(f"no knowledge graph for {args.site}", file=sys.stderr)
        return 1
    store = KGStore.for_site(args.site, args.kg_dir)
    try:
        if args.format == "jsonld":
            lines: list[str] = [json.dumps(to_jsonld(store), indent=1)]
        elif args.format == "cypher":
            lines = list(to_cypher(store, typed_edges=args.typed_edges))
        else:
            lines = list(to_jsonl(store))
    finally:
        store.close()
    if args.out:
        Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        for line in lines:
            print(line)
    return 0


def _cmd_kg_sync_neo4j(args: argparse.Namespace) -> int:
    _kg_guard()
    import os

    from webgraph.kg.neo4j import Neo4jUnavailableError, sync_to_neo4j
    from webgraph.kg.store import KGStore

    if not KGStore.exists_for(args.site, args.kg_dir):
        print(f"no knowledge graph for {args.site}", file=sys.stderr)
        return 1
    password = os.environ.get(args.password_env, "")
    if not password:
        raise SystemExit(f"set {args.password_env} to the database password (never pass it on the command line)")
    store = KGStore.for_site(args.site, args.kg_dir)
    try:
        for event in sync_to_neo4j(
            store, uri=args.uri, user=args.user, password=password, database=args.database, typed_edges=args.typed_edges
        ):
            if event["type"] == "batch":
                print(f"  {event['label']:<15} {event['rows']:>6} rows", file=sys.stderr)
            else:
                print(f"done: {event['batches']} batches, {event['counts']}", file=sys.stderr)
    except Neo4jUnavailableError as exc:
        raise SystemExit(str(exc)) from None
    finally:
        store.close()
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

    kg = subparsers.add_parser(
        "kg", help="WebGraph: build, query and export a site's knowledge graph (WEBGRAPH_KG=1)"
    )
    kg_sub = kg.add_subparsers(dest="kg_command", required=True)

    def add_provider_args(sub: argparse.ArgumentParser, *, answer: bool = False) -> None:
        sub.add_argument("--provider", help="openai-compatible | anthropic | gemini, or a preset: openai, groq, ollama, ...")
        sub.add_argument("--base-url", help="API base URL (Ollama: http://localhost:11434/v1)")
        sub.add_argument("--model", help="model name; default WEBGRAPH_LLM_MODEL")
        if answer:
            sub.add_argument("--answer-model", help="a stronger model for answers; default the extraction model")
        sub.add_argument("--api-key-env", help="environment variable holding the key (never the key itself)")
        sub.add_argument("--kg-dir", help="where knowledge graphs are kept (default WEBGRAPH_KG_DIR or ~/.cache/webgraph/kg)")

    def add_graph_source_args(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--graph", help="a JSONL graph written by `webgraph graph`")
        sub.add_argument("--pages", help="a directory of saved HTML pages, mapped onto the site root")

    kg_build = kg_sub.add_parser("build", help="read every section with the model and write the graph")
    kg_build.add_argument("site", help="site root URL (crawled before, or crawled now)")
    add_graph_source_args(kg_build)
    add_provider_args(kg_build)
    kg_build.add_argument("--max-pages", type=int, default=40, help="pages to crawl when no crawl is stored")
    kg_build.add_argument("--concurrency", type=int, default=6, help="crawl concurrency when crawling")
    kg_build.add_argument("--max-pages-kg", type=int, default=0, help="cap on pages read by the model; 0 = all")
    kg_build.add_argument("--max-sections", type=int, default=0, help="cap on sections; 0 = all")
    kg_build.add_argument("--max-input-tokens", type=int, default=2_000_000)
    kg_build.add_argument("--max-usd", type=float, default=0.0, help="stop at this spend (needs WEBGRAPH_LLM_PRICE_IN/OUT)")
    kg_build.add_argument("--rebuild", action="store_true", help="ignore the model cache")
    kg_build.add_argument("--json", action="store_true", help="emit every event as a JSON line")
    kg_build.set_defaults(func=_cmd_kg_build)

    kg_ask = kg_sub.add_parser("ask", help="answer a question with per-sentence citations")
    kg_ask.add_argument("site")
    kg_ask.add_argument("question")
    add_graph_source_args(kg_ask)
    add_provider_args(kg_ask, answer=True)
    kg_ask.add_argument("--no-model", action="store_true", help="extractive answer: the best-matching quotes, cited")
    kg_ask.add_argument("--json", action="store_true", help="emit every event as a JSON line")
    kg_ask.set_defaults(func=_cmd_kg_ask)

    kg_export = kg_sub.add_parser("export", help="write the graph as JSONL, Cypher or JSON-LD")
    kg_export.add_argument("site")
    kg_export.add_argument("--format", choices=("jsonl", "cypher", "jsonld"), default="jsonl")
    kg_export.add_argument("--typed-edges", action="store_true", help="cypher: also emit -[:PREDICATE]-> edges")
    kg_export.add_argument("--out", help="write here instead of stdout")
    kg_export.add_argument("--kg-dir")
    kg_export.set_defaults(func=_cmd_kg_export)

    kg_sync = kg_sub.add_parser("sync-neo4j", help="push the graph into Neo4j over bolt (extra: kg-neo4j)")
    kg_sync.add_argument("site")
    kg_sync.add_argument("--uri", default="bolt://localhost:7687")
    kg_sync.add_argument("--user", default="neo4j")
    kg_sync.add_argument("--password-env", default="NEO4J_PASSWORD", help="variable holding the password")
    kg_sync.add_argument("--database")
    kg_sync.add_argument("--typed-edges", action="store_true")
    kg_sync.add_argument("--kg-dir")
    kg_sync.set_defaults(func=_cmd_kg_sync_neo4j)

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
