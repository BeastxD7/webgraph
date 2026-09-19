"""Build a site's knowledge graph from a crawl, with the bill visible before it is run up.

The order of events matters more than usual here, because each section is a model call
that costs money or minutes:

1. **`estimate`** comes first and before any call: how many sections, how many are already
   in the cache, the input tokens at four characters each, the output at a quarter of that,
   and dollars when prices are configured. GraphRAG added this only after two issues about
   surprise bills; here it is the first thing a caller sees.
2. **`section`** events stream as sections finish, out of order because they run in
   parallel, each with what was accepted and what was rejected and why.
3. **`budget`** fires when a cap stops the build -- pages, sections, input tokens, dollars
   -- and the build finishes cleanly with `truncated: true` rather than raising.
4. **`merge`**, then **`done`** with the run's statistics, which are also recorded in the
   store's `build_runs`.

Merging happens after extraction, in a fixed order (page in-degree, depth, position), so
the graph does not depend on which thread finished first.

The cache is keyed on `PROMPT_VERSION | model | section text | known entities`. A re-crawl
costs only the sections whose text changed; a second build of the same crawl costs nothing.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from collections.abc import Callable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from webgraph import config
from webgraph.graph.model import PageNode, Section, SiteGraph
from webgraph.kg.extract import Extracted, Prepared, extract_section, prepare, verify
from webgraph.kg.merge import STRUCTURED_TYPE_MAP, Merger
from webgraph.kg.prompts import EXTRACT_SYSTEM, PROMPT_VERSION
from webgraph.kg.providers import LLMError, Provider, Usage
from webgraph.kg.store import KGStore

__all__ = ["BuildConfig", "KGBuilder", "cache_key", "order_sections"]

CHARS_PER_TOKEN = config.GRAPH_CHARS_PER_TOKEN
OUTPUT_SHARE = 0.25
"""Model output as a share of input, for the estimate. Measured on the fake provider and
the design's ballpark; the real ratio is recorded per run in `build_runs`."""


@dataclass(frozen=True, slots=True)
class BuildConfig:
    max_pages: int = config.KG_MAX_PAGES
    max_sections: int = config.KG_MAX_SECTIONS
    max_input_tokens: int = config.KG_MAX_INPUT_TOKENS
    max_usd: float = config.KG_MAX_USD
    min_section_chars: int = config.KG_MIN_SECTION_CHARS
    concurrency: int = config.KG_CONCURRENCY
    gleanings: int = config.KG_GLEANINGS
    rebuild: bool = False
    """Ignore the cache and call the model for every section."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_pages": self.max_pages,
            "max_sections": self.max_sections,
            "max_input_tokens": self.max_input_tokens,
            "max_usd": self.max_usd,
            "min_section_chars": self.min_section_chars,
            "concurrency": self.concurrency,
            "gleanings": self.gleanings,
            "rebuild": self.rebuild,
        }


def cache_key(model: str, section_text: str, known: list[tuple[str, str]]) -> str:
    payload = "|".join([PROMPT_VERSION, model, section_text, json.dumps(known, sort_keys=True)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def order_sections(graph: SiteGraph) -> list[tuple[PageNode, Section]]:
    """Sections by page in-degree (most linked first), then depth, then position.

    A capped build covers what the site itself points at most; the home page, the
    programme list and the contact page come before the 40th news item.
    """

    def page_rank(page: PageNode) -> tuple[int, int, str]:
        return (-len(graph.linked_from.get(page.key, ())), page.depth, page.key)

    out: list[tuple[PageNode, Section]] = []
    for page in sorted(graph.pages.values(), key=page_rank):
        for section in graph.sections_of(page.key):
            out.append((page, section))
    return out


class KGBuilder:
    def __init__(
        self,
        graph: SiteGraph,
        provider: Provider,
        store: KGStore,
        *,
        build_config: BuildConfig | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        self.graph = graph
        self.provider = provider
        self.store = store
        self.config = build_config or BuildConfig()
        self.should_stop = should_stop or (lambda: False)
        self.model = provider.config.model or "unknown"

    # -- planning ---------------------------------------------------------------------------

    def known_entities(self, page_key: str) -> list[tuple[str, str]]:
        known: list[tuple[str, str]] = []
        for entity in self.graph.entities.values():
            if (
                page_key in entity.pages
                and entity.name
                and entity.type not in {"Subject", "Symbol"}
            ):
                known.append((entity.name[:80], STRUCTURED_TYPE_MAP.get(entity.type, entity.type)))
        return sorted(set(known))[:24]

    def heading_path(self, section: Section) -> str:
        parts: list[str] = []
        current: Section | None = section
        seen: set[str] = set()
        while current is not None and current.id not in seen:
            seen.add(current.id)
            if current.heading:
                parts.append(current.heading)
            current = self.graph.sections.get(current.parent_id) if current.parent_id else None
        return " > ".join(reversed(parts))

    def plan(self) -> tuple[list[Prepared], Counter[str]]:
        """The sections that will be sent, in order, and why the rest were skipped."""
        skipped: Counter[str] = Counter()
        prepared: list[Prepared] = []
        pages_seen: list[str] = []
        for page, section in order_sections(self.graph):
            if page.key not in pages_seen:
                if self.config.max_pages and len(pages_seen) >= self.config.max_pages:
                    skipped["page_cap"] += 1
                    continue
                pages_seen.append(page.key)
            if not section.blocks:
                skipped["no_block_refs"] += 1
                continue
            if section.chars < self.config.min_section_chars:
                skipped["too_short"] += 1
                continue
            if all(ref.kind == "code" for ref in section.blocks):
                skipped["all_code"] += 1
                continue
            if self.config.max_sections and len(prepared) >= self.config.max_sections:
                skipped["section_cap"] += 1
                continue
            prepared.append(
                prepare(
                    section,
                    page,
                    self.known_entities(page.key),
                    heading_path=self.heading_path(section),
                )
            )
        return prepared, skipped

    def estimate(self, prepared: list[Prepared], skipped: Counter[str]) -> dict[str, Any]:
        cached = (
            0
            if self.config.rebuild
            else sum(
                1
                for p in prepared
                if self.store.cache_get(cache_key(self.model, p.section.text, p.known)) is not None
            )
        )
        uncached = [
            p
            for p in prepared
            if self.config.rebuild
            or self.store.cache_get(cache_key(self.model, p.section.text, p.known)) is None
        ]
        input_tokens = int(sum(p.input_chars for p in uncached) / CHARS_PER_TOKEN)
        output_tokens = int(input_tokens * OUTPUT_SHARE)
        usage = Usage(input_tokens, output_tokens)
        return {
            "type": "estimate",
            "pages": len({p.page.key for p in prepared}),
            "sections": len(prepared),
            "cached_sections": cached,
            "skipped": dict(skipped),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "usd": self.provider.config.usd(usage),
            "model": self.model,
            "prompt_version": PROMPT_VERSION,
            "caps": self.config.as_dict(),
            "provider": self.provider.config.redacted(),
        }

    # -- running ----------------------------------------------------------------------------

    def run(self) -> Iterator[dict[str, Any]]:
        started = time.time()
        seen_at = datetime.now(UTC).isoformat(timespec="seconds")
        prepared, skipped = self.plan()
        estimate = self.estimate(prepared, skipped)
        yield estimate

        yield {
            "type": "stage",
            "stage": "extract",
            "message": f"Reading {len(prepared)} sections with {self.model}",
        }
        results: dict[int, Extracted] = {}
        usage = Usage()
        rejected: Counter[str] = Counter()
        misnumbered = 0
        cache_hits = 0
        truncated = False
        truncated_reason = ""
        errors = 0
        done = 0

        def spent_usd() -> float:
            return self.provider.config.usd(usage) or 0.0

        in_flight = 0
        """Estimated input tokens of submitted sections that have not reported usage yet, so
        a cap is checked against what is committed, not only what has come back."""

        def over_budget(pending_chars: int) -> str:
            projected = usage.input_tokens + in_flight + int(pending_chars / CHARS_PER_TOKEN)
            if self.config.max_input_tokens and projected > self.config.max_input_tokens:
                return "max_input_tokens"
            if self.config.max_usd:
                projected_usd = (
                    self.provider.config.usd(Usage(projected, int(projected * OUTPUT_SHARE))) or 0.0
                )
                if projected_usd > self.config.max_usd:
                    return "max_usd"
            return ""

        def work(index: int, item: Prepared) -> tuple[int, Extracted]:
            key = cache_key(self.model, item.section.text, item.known)
            if not self.config.rebuild:
                hit = self.store.cache_get(key)
                if hit is not None:
                    text, _, _ = hit
                    try:
                        extracted = verify(json.loads(text), item)
                    except (json.JSONDecodeError, TypeError):
                        extracted = Extracted(rejected=Counter({"invalid_json": 1}))
                    extracted.cached = True
                    return index, extracted
            extracted, raw = extract_section(self.provider, item)
            if raw:
                self.store.cache_put(key, raw, extracted.usage, self.model)
            return index, extracted

        window = max(1, self.config.concurrency) * 2
        pending: dict[Future[tuple[int, Extracted]], Prepared] = {}
        queue = list(enumerate(prepared))
        with ThreadPoolExecutor(
            max_workers=max(1, self.config.concurrency), thread_name_prefix="webgraph-kg"
        ) as pool:
            while queue or pending:
                while queue and len(pending) < window and not truncated:
                    if self.should_stop():
                        truncated, truncated_reason = True, "stopped"
                        break
                    index, item = queue[0]
                    in_cache = (
                        not self.config.rebuild
                        and self.store.cache_get(
                            cache_key(self.model, item.section.text, item.known)
                        )
                        is not None
                    )
                    reason = "" if in_cache else over_budget(item.input_chars)
                    if reason:
                        truncated, truncated_reason = True, reason
                        yield {
                            "type": "budget",
                            "reason": reason,
                            "input_tokens": usage.input_tokens,
                            "output_tokens": usage.output_tokens,
                            "usd": spent_usd(),
                            "cap": getattr(self.config, reason),
                            "remaining_sections": len(queue),
                        }
                        break
                    queue.pop(0)
                    if not in_cache:
                        in_flight += int(item.input_chars / CHARS_PER_TOKEN)
                    pending[pool.submit(work, index, item)] = item
                if not pending:
                    break
                completed, _ = wait(list(pending), return_when=FIRST_COMPLETED)
                for future in completed:
                    item = pending.pop(future)
                    done += 1
                    try:
                        index, extracted = future.result()
                    except LLMError as exc:
                        errors += 1
                        in_flight = max(0, in_flight - int(item.input_chars / CHARS_PER_TOKEN))
                        yield {
                            "type": "section",
                            "page": item.page.url,
                            "section_id": item.section.id,
                            "heading": item.section.heading,
                            "error": str(exc),
                            "done": done,
                            "total": len(prepared),
                        }
                        if errors >= 5 and errors > done // 2:
                            truncated, truncated_reason = True, "provider_errors"
                            queue.clear()
                        continue
                    results[index] = extracted
                    if not extracted.cached:
                        in_flight = max(0, in_flight - int(item.input_chars / CHARS_PER_TOKEN))
                    usage = usage + (Usage() if extracted.cached else extracted.usage)
                    rejected.update(extracted.rejected)
                    misnumbered += extracted.misnumbered
                    cache_hits += int(extracted.cached)
                    yield {
                        "type": "section",
                        "page": item.page.url,
                        "section_id": item.section.id,
                        "heading": item.section.heading,
                        "entities": len(extracted.entities),
                        "relations": len(extracted.relations),
                        "accepted": extracted.accepted,
                        "rejected": extracted.rejected_count,
                        "rejected_reasons": dict(extracted.rejected),
                        "misnumbered": extracted.misnumbered,
                        "cached": extracted.cached,
                        "tokens": {
                            "in": extracted.usage.input_tokens,
                            "out": extracted.usage.output_tokens,
                        },
                        "usd": spent_usd(),
                        "done": done,
                        "total": len(prepared),
                    }
                if truncated and truncated_reason == "stopped":
                    queue.clear()

        yield {"type": "stage", "stage": "merge", "message": "Merging entities and relations"}
        merger = Merger(total_pages=len(self.graph.pages), seen_at=seen_at)
        merger.add_structured(self.graph)
        for index in sorted(results):
            merger.add_extracted(results[index])
        merged = merger.finish()
        yield {"type": "merge", **merged.stats}

        yield {
            "type": "stage",
            "stage": "store",
            "message": f"Writing {len(merged.entities)} entities and {len(merged.relations)} relations",
        }
        self.store.replace_graph(merged)
        self.store.set_meta("root", self.graph.root)
        self.store.set_meta("prompt_version", PROMPT_VERSION)
        accepted = sum(r.accepted for r in results.values())
        total_rejected = sum(rejected.values())
        finished = time.time()
        stats: dict[str, Any] = {
            "pages": estimate["pages"],
            "sections": len(prepared),
            "sections_done": len(results),
            "cache_hits": cache_hits,
            "errors": errors,
            "entities": len(merged.entities),
            "relations": len(merged.relations),
            "accepted": accepted,
            "rejected": total_rejected,
            "rejected_reasons": dict(rejected),
            "rejection_rate": round(total_rejected / (accepted + total_rejected), 4)
            if accepted + total_rejected
            else 0.0,
            "misnumbered": misnumbered,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "usd": spent_usd(),
            "seconds": round(finished - started, 2),
            "truncated": truncated,
            "truncated_reason": truncated_reason,
            "skipped": dict(skipped),
            "merge": merged.stats,
            "prompt_version": PROMPT_VERSION,
            "system_prompt_chars": len(EXTRACT_SYSTEM),
        }
        self.store.record_run(started, finished, self.model, stats)
        yield {"type": "done", "stats": stats, "truncated": truncated}
