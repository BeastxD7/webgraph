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
from webgraph.fetch.render import RenderConfig
from webgraph.fetch.static import FetchConfig
from webgraph.main_content import MainContentConfig
from webgraph.metadata import PageMetadata, read_metadata
from webgraph.pagetype import PageType, Routing, default_router, policy_for
from webgraph.pipeline import build_document
from webgraph.render_markdown import MarkdownOptions, to_markdown
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
    "FetchConfig",
    "MainContentConfig",
    "MarkdownOptions",
    "PageBlockedError",
    "PageDisallowedError",
    "PageMetadata",
    "PageMissingError",
    "PageShellError",
    "PageType",
    "ReadingOrderMethod",
    "Rect",
    "RenderConfig",
    "ResolvedPage",
    "Routing",
    "SiteConfig",
    "Strategy",
    "__version__",
    "build_document",
    "default_router",
    "policy_for",
    "read_metadata",
    "resolve_page",
    "resolve_supplied",
    "select_content",
    "stream_site",
    "to_markdown",
]
