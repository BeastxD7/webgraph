"""A site graph from saved HTML files, for builds and benchmarks that need no network.

A directory of `*.html` is mapped onto a root URL by path: `dir/courses.html` is
`<root>/courses.html`, `dir/index.html` is the root itself. Each file goes through the
production `build_document`, its links are read with the crawler's own `extract_links`, and
the pages enter a `GraphBuilder` in name order -- so the sections carry block refs and the
link graph carries anchors, exactly as a crawl would leave them.

Used by the `benchmark/kg` fixture site, the engine tests, and `webgraph kg build --pages`.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urljoin

from webgraph.crawl.discovery import extract_links
from webgraph.graph.build import GraphBuilder
from webgraph.graph.model import SiteGraph
from webgraph.pipeline import build_document

__all__ = ["graph_from_directory", "page_url"]


def page_url(root: str, relative: str) -> str:
    base = root if root.endswith("/") else root + "/"
    if relative in ("index.html", "index.htm", ""):
        return base
    return urljoin(base, relative)


def graph_from_directory(directory: Path | str, root: str, *, glob: str = "**/*.html") -> SiteGraph:
    base = Path(directory)
    builder = GraphBuilder(root)
    files = sorted(base.glob(glob))
    # The root page first: its depth is 0 and everything else hangs off it.
    files.sort(key=lambda p: (p.name not in ("index.html", "index.htm"), str(p)))
    for path in files:
        relative = path.relative_to(base).as_posix()
        url = page_url(root, relative)
        html = path.read_text(encoding="utf-8", errors="replace")
        document = build_document(html, url)
        links = extract_links(html, url)
        depth = 0 if relative in ("index.html", "index.htm") else 1 + relative.count("/")
        builder.add(document, depth=depth, title=document.title, anchored_links=links.anchored)
    return builder.graph
