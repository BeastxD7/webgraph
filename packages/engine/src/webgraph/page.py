"""One page, extracted as a sequence of observable stages.

Why this exists alongside `resolve_page`
----------------------------------------
`resolve_page` answers "what is on this page" in one call, which is the right shape for a
caller that wants the answer. It is the wrong shape for a caller that wants to *watch*: a
single-page extraction can take ten seconds behind a browser render, and a request that says
nothing until it finishes is indistinguishable from one that has hung.

The whole-site crawl already streams -- stage, analysis, page, done -- and a single page had
no equivalent, so the two halves of the same product behaved differently for no reason other
than which one happened to be written first.

What it does not do
-------------------
It does not reimplement the pipeline. Each stage calls the same function the batch path calls
and reports what that function measured. A streaming view that drifts from the real one is
worse than no streaming view, because it is believed.

Events
------
Every event carries `type` and `stage`. `resolve` reports how much each fetch contributed and
which strategy ran; `classify` reports the page type with the model's own reasons; `select`
reports what content selection removed and why; `done` carries the finished document. An
`error` ends the stream and is the only event that can appear out of order.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

from webgraph.content import select_content
from webgraph.fetch.render import RenderConfig
from webgraph.fetch.static import FetchConfig
from webgraph.pagetype import PageType, default_router, policy_for
from webgraph.render_markdown import MarkdownOptions, to_markdown
from webgraph.resolve import PageMissingError, Strategy, resolve_page
from webgraph.types import BlockKind, Document

__all__ = ["stream_page"]


def _elapsed(since: float) -> float:
    return round(time.monotonic() - since, 3)


def stream_page(
    url: str,
    *,
    strategy: Strategy | None = None,
    fetch_config: FetchConfig | None = None,
    render_config: RenderConfig | None = None,
) -> Iterator[dict[str, Any]]:
    """Extract one page, yielding an event per stage as it completes.

    The stages are the same ones `/how-it-works` describes, minus the ones that only exist
    for a crawl: there is no queue to build and no cross-page chrome to learn from a single
    page, and saying otherwise would be theatre.
    """
    started = time.monotonic()

    yield {
        "type": "stage",
        "stage": "resolve",
        "state": "running",
        "message": "Fetching as plain HTTP and through a browser, then merging",
    }
    try:
        resolved = resolve_page(
            url, strategy=strategy, fetch_config=fetch_config, render_config=render_config
        )
    except PageMissingError as exc:
        yield {"type": "error", "stage": "resolve", "message": str(exc), "at": _elapsed(started)}
        return
    except Exception as exc:
        yield {
            "type": "error",
            "stage": "resolve",
            "message": f"{type(exc).__name__}: {exc}",
            "at": _elapsed(started),
        }
        return

    document = resolved.document
    yield {
        "type": "resolve",
        "stage": "resolve",
        "state": "done",
        "at": _elapsed(started),
        "url": resolved.url,
        "strategy": resolved.strategy.value,
        "static_chars": resolved.static_chars,
        "rendered_chars": resolved.rendered_chars,
        "union_chars": resolved.union_chars,
        "static_coverage": round(resolved.static_coverage, 4),
        "blocks_only_in_static": resolved.blocks_only_in_static,
        "blocks_only_in_rendered": resolved.blocks_only_in_rendered,
        # Not an error in the sense of a failure: it says the browser was unavailable or
        # gave up, and that the result is the static fetch alone. A caller that shows a
        # completeness claim needs to know which it is looking at.
        "render_error": resolved.render_error,
    }

    yield {
        "type": "parse",
        "stage": "parse",
        "state": "done",
        "at": _elapsed(started),
        "blocks": len(document.blocks),
        "words": len(document.text.split()),
        "reading_order": document.reading_order_method.value,
        "kinds": _kind_counts(document),
        "payloads": sorted({p.source.value for p in document.structured_data}),
    }

    yield {
        "type": "stage",
        "stage": "classify",
        "state": "running",
        "message": "Reading the page type",
    }
    router = default_router()
    routing = router.route(document, explain=True) if router is not None else None
    yield {
        "type": "classify",
        "stage": "classify",
        "state": "done",
        "at": _elapsed(started),
        "page_type": str(routing.page_type) if routing else "unknown",
        "confidence": round(routing.confidence, 4) if routing else 0.0,
        "reasons": [
            {"says": r.says, "weight": round(r.weight, 4)} for r in (routing.reasons if routing else ())
        ],
        "runner_up": (
            {"type": routing.runner_up[0], "confidence": round(routing.runner_up[1], 4)}
            if routing
            else {"type": "", "confidence": 0.0}
        ),
        # A model that says "not sure" is telling you something. Without this a reader
        # cannot tell a confident `article` from a coin-flip one.
        "available": router is not None,
    }

    selection = select_content(
        document.blocks,
        config=policy_for(routing.page_type if routing else PageType.UNKNOWN),
    )
    yield {
        "type": "select",
        "stage": "select",
        "state": "done",
        "at": _elapsed(started),
        "kept": selection.kept,
        "total": selection.total,
        "methods": list(selection.methods),
        "removed": {
            "landmarks": selection.landmarks_removed,
            "main_landmark": selection.main_scoped_removed,
            "site_chrome": selection.chrome_removed,
            "boundary": selection.main_content_removed,
            "block_model": selection.block_model_removed,
        },
    }

    content = document.model_copy(update={"blocks": tuple(selection.blocks)})
    yield {
        "type": "done",
        "stage": "done",
        "at": _elapsed(started),
        "url": resolved.url,
        "title": _title(document),
        "text": document.text,
        "markdown": to_markdown(document, options=MarkdownOptions()),
        # Empty when nothing was removed: the content *is* the document, and emitting it
        # twice would double the payload to say so.
        "content_markdown": to_markdown(content, options=MarkdownOptions())
        if selection.changed
        else "",
        "images": [b.href for b in document.blocks if b.kind is BlockKind.IMAGE and b.href],
        "tables": sum(1 for b in document.blocks if b.kind is BlockKind.TABLE),
    }


def _kind_counts(document: Document) -> dict[str, int]:
    counts: dict[str, int] = {}
    for block in document.blocks:
        counts[block.kind.value] = counts.get(block.kind.value, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def _title(document: Document) -> str:
    for block in document.blocks:
        if block.kind is BlockKind.HEADING and block.level <= 2 and block.text.strip():
            return block.text
    return ""
