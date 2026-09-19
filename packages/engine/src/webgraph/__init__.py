"""webgraph: web content extraction with provenance and recovered reading order.

The stable surface, enough for the common jobs:

    from webgraph import resolve_page, to_markdown

    page = resolve_page("https://example.com/")     # plain fetch + browser, merged
    print(to_markdown(page.document))                # the whole page, in reading order

    from webgraph import select_content
    body = select_content(page.document.blocks, title=page.document.title)
    print(to_markdown(page.document.model_copy(update={"blocks": tuple(body.blocks)})))

    from webgraph import stream_site
    for event in stream_site("https://example.com/"):
        if event["type"] == "page":
            print(event["url"], event["content_markdown"][:80])

Everything else is importable from its module (`webgraph.resolve`, `webgraph.site`,
`webgraph.content`, ...) and documented there; the names below are the ones whose
signatures are kept stable across minor versions.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from webgraph.content import ContentSelection, select_content
from webgraph.metadata import PageMetadata, read_metadata
from webgraph.pipeline import build_document
from webgraph.render_markdown import MarkdownOptions, to_markdown
from webgraph.resolve import ResolvedPage, Strategy, resolve_page
from webgraph.site import SiteConfig, stream_site
from webgraph.types import Block, BlockKind, Document, ReadingOrderMethod, Rect

try:
    __version__ = version("webgraph")
except PackageNotFoundError:  # a source checkout that was never installed
    __version__ = "0.0.0"

__all__ = [
    "Block",
    "BlockKind",
    "ContentSelection",
    "Document",
    "MarkdownOptions",
    "PageMetadata",
    "ReadingOrderMethod",
    "Rect",
    "ResolvedPage",
    "SiteConfig",
    "Strategy",
    "__version__",
    "build_document",
    "read_metadata",
    "resolve_page",
    "select_content",
    "stream_site",
    "to_markdown",
]
