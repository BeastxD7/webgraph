"""webgraph: web content extraction with provenance and recovered reading order.

The stable surface, enough for the common jobs:

    from webgraph import resolve_page, to_markdown

    page = resolve_page("https://example.com/")     # plain fetch + browser, merged
    print(to_markdown(page.document))                # the whole page, in reading order: the default

    from webgraph import select_content              # opt in to the content alone
    body = select_content(page.document.blocks, title=page.document.title)
    print(to_markdown(page.document.model_copy(update={"blocks": tuple(body.blocks)})))

    from webgraph import stream_site
    for event in stream_site("https://example.com/"):
        if event["type"] == "page":
            print(event["url"], event["markdown"][:80])

    from webgraph import build_site_report, create_watch, run_watch, ContextAssembler

The same package answers for a site's report, a watch on it, its graph and a bounded
context assembled from that graph -- everything the API and the web UI do. Everything
else is importable from its module (`webgraph.resolve`, `webgraph.site`,
`webgraph.content`, ...) and documented there; the names below are the ones whose
signatures are kept stable across minor versions.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from webgraph.analyze import SiteAnalysis, analyze_site
from webgraph.content import ContentSelection, select_content
from webgraph.extract.page_facts import PageFacts, facts_for_page
from webgraph.extract.schema import extract_facts, merge_facts
from webgraph.fetch.render import RenderConfig
from webgraph.fetch.static import FetchConfig
from webgraph.graph.build import GraphBuilder
from webgraph.graph.entities import derive_entities
from webgraph.graph.export import load_jsonl, to_cypher, to_jsonl, write_jsonl
from webgraph.graph.model import SiteGraph
from webgraph.graph.retrieve import Assembled, Budget, ContextAssembler
from webgraph.graph.store import GraphStore
from webgraph.main_content import MainContentConfig
from webgraph.metadata import PageMetadata, read_metadata
from webgraph.pagetype import PageType, Routing, default_router, policy_for
from webgraph.pipeline import build_document
from webgraph.render_markdown import MarkdownOptions, to_markdown
from webgraph.report import SiteReport, build_site_report
from webgraph.resolve import (
    PageBlockedError,
    PageDisallowedError,
    PageMissingError,
    PageShellError,
    ResolvedPage,
    Strategy,
    resolve_page,
    resolve_supplied,
)
from webgraph.site import SiteConfig, stream_site
from webgraph.types import Block, BlockKind, Document, Fact, ReadingOrderMethod, Rect
from webgraph.watch import (
    RunSummary,
    Watch,
    create_watch,
    export_changes,
    get_watch,
    list_changes,
    list_watches,
    run_watch,
    stream_watch,
)

try:
    __version__ = version("webgraph")
except PackageNotFoundError:  # a source checkout that was never installed
    __version__ = "0.0.0"

__all__ = [
    "Assembled",
    "Block",
    "BlockKind",
    "Budget",
    "ContentSelection",
    "ContextAssembler",
    "Document",
    "Fact",
    "FetchConfig",
    "GraphBuilder",
    "GraphStore",
    "MainContentConfig",
    "MarkdownOptions",
    "PageBlockedError",
    "PageDisallowedError",
    "PageFacts",
    "PageMetadata",
    "PageMissingError",
    "PageShellError",
    "PageType",
    "ReadingOrderMethod",
    "Rect",
    "RenderConfig",
    "ResolvedPage",
    "Routing",
    "RunSummary",
    "SiteAnalysis",
    "SiteConfig",
    "SiteGraph",
    "SiteReport",
    "Strategy",
    "Watch",
    "__version__",
    "analyze_site",
    "build_document",
    "build_site_report",
    "create_watch",
    "default_router",
    "derive_entities",
    "export_changes",
    "extract_facts",
    "facts_for_page",
    "get_watch",
    "list_changes",
    "list_watches",
    "load_jsonl",
    "merge_facts",
    "policy_for",
    "read_metadata",
    "resolve_page",
    "resolve_supplied",
    "run_watch",
    "select_content",
    "stream_site",
    "stream_watch",
    "to_cypher",
    "to_jsonl",
    "to_markdown",
    "write_jsonl",
]
