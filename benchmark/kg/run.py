"""Score WebGraph's answers on a per-site QA set: correctness, citations, cost.

One JSONL row per question (see `generate.py` for the format). For each row the runner asks
the knowledge graph and scores:

- **answer correctness** by `answer_type`: `number` and `date` by normalised exact match
  (digits only; any date form the page could print), `span` and `free` by token F1 (0.5 or
  better counts as correct, and the F1 itself is reported), `list` by set F1, `yes_no` by
  the first word, `abstain` correct when the answer abstains;
- **citation precision / recall at page and at block level** -- the citations the answer
  actually used (those on supported sentences) against the gold `(page_url, block_xpath)`
  pairs. Block-level is the number nobody else measures, because nobody else stores a span;
- **unsupported-sentence rate**: sentences the answer made that cite nothing valid;
- **abstention correctness** on the not-on-site questions;
- **graph statistics** from the build: entities and relations per page, rejection rate,
  cache hits;
- **cost**: tokens in and out, dollars when prices are configured, wall time.

Three modes run in the same harness so the KG is measured against the baseline rather than
assumed to beat it: `bm25` (the observed layer's section BM25, blocks as evidence, no KG),
`kg` (the knowledge graph alone), `kg+sections` (the default: KG seeds unioned with section
BM25). The design's rule: the KG ships behind its flag until `kg+sections` beats `bm25` on
typed and two-hop questions on at least three sites.

    # CI: the fixture site on the fake provider (deterministic, no key)
    uv run --package webgraph python benchmark/kg/run.py --pages benchmark/kg/fixtures/site \\
        --root https://kg-fixture.test/ --qa benchmark/kg/fixtures/site/qa.jsonl --provider fake

    # a real model, locally
    WEBGRAPH_LLM_PROVIDER=ollama WEBGRAPH_LLM_MODEL=qwen3:8b uv run --package webgraph \\
        python benchmark/kg/run.py --pages <dir> --root <url> --qa <qa.jsonl> --out kg-bench.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

from webgraph.graph.model import SiteGraph
from webgraph.graph.retrieve import ContextAssembler
from webgraph.kg.build import BuildConfig, KGBuilder
from webgraph.kg.model import Citation, Evidence, QueryPath
from webgraph.kg.offline import graph_from_directory
from webgraph.kg.prompts import ANSWER_SYSTEM, answer_prompt
from webgraph.kg.providers import ProviderConfig, make_provider
from webgraph.kg.retrieve import KGRetriever, RetrievalConfig, parse_answer
from webgraph.kg.store import KGStore

_WORD = re.compile(r"[A-Za-z0-9][\w.'-]*")
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]


# -- scoring ----------------------------------------------------------------------------------


def tokens(text: str) -> list[str]:
    return [t.lower().strip(".,;:'\"") for t in _WORD.findall(text or "")]


def token_f1(prediction: str, gold: str) -> float:
    p, g = Counter(tokens(prediction)), Counter(tokens(gold))
    if not p or not g:
        return 0.0
    overlap = sum((p & g).values())
    if overlap == 0:
        return 0.0
    precision, recall = overlap / sum(p.values()), overlap / sum(g.values())
    return 2 * precision * recall / (precision + recall)


def numbers_in(text: str) -> set[str]:
    """Every number in `text`, digits only, so ₹1,20,000 and 120000 and 120,000 agree."""
    return {re.sub(r"\D", "", m) for m in re.findall(r"\d[\d,.]*", text or "") if re.sub(r"\D", "", m)}


def dates_in(text: str) -> set[str]:
    """Every date in `text` as YYYY-MM-DD, from the forms a page prints."""
    found: set[str] = set()
    for match in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", text or ""):
        found.add(match.group(0))
    for match in re.finditer(r"\b(\d{1,2})\s+([A-Za-z]{3,9}),?\s+(\d{4})\b", text or ""):
        month = _month(match.group(2))
        if month:
            found.add(f"{match.group(3)}-{month:02d}-{int(match.group(1)):02d}")
    for match in re.finditer(r"\b([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})\b", text or ""):
        month = _month(match.group(1))
        if month:
            found.add(f"{match.group(3)}-{month:02d}-{int(match.group(2)):02d}")
    for match in re.finditer(r"\b(?:in|since|founded|established)\s+(\d{4})\b", text or ""):
        found.add(match.group(1))
    return found


def _month(name: str) -> int | None:
    lowered = name.lower()
    for index, month in enumerate(MONTHS, start=1):
        if month.startswith(lowered[:3]):
            return index
    return None


def score_answer(row: dict[str, Any], answer: dict[str, Any]) -> tuple[bool, float]:
    """(correct, f1-or-1.0) for one answer against its gold."""
    kind = row["answer_type"]
    text = answer["text"]
    supported = " ".join(s["text"] for s in answer["sentences"] if not s["unsupported"]) or text
    gold = row["answer"]
    if kind == "abstain":
        ok = bool(answer["abstained"])
        return ok, float(ok)
    if answer["abstained"]:
        return False, 0.0
    if kind == "number":
        ok = re.sub(r"\D", "", str(gold)) in numbers_in(supported)
        return ok, float(ok)
    if kind == "date":
        wanted = str(gold)
        ok = wanted in dates_in(supported) or (len(wanted) == 4 and wanted in numbers_in(supported))
        return ok, float(ok)
    if kind == "list":
        wanted_items = [str(g) for g in gold] if isinstance(gold, list) else [str(gold)]
        hits = [g for g in wanted_items if g.lower() in supported.lower()]
        precision = len(hits) / max(1, len(wanted_items))
        f1 = precision  # every gold item found, no penalty for extra prose in a sentence
        return f1 >= 0.5, f1
    if kind == "yes_no":
        first = tokens(supported)[:1]
        ok = bool(first) and first[0] == str(gold).lower()
        return ok, float(ok)
    f1 = token_f1(supported, str(gold)) if kind == "free" else (1.0 if str(gold).lower() in supported.lower() else token_f1(supported, str(gold)))
    return f1 >= 0.5, f1


def citation_scores(row: dict[str, Any], answer: dict[str, Any]) -> dict[str, float | None]:
    gold_pages = {g["page_url"] for g in row["gold"]}
    gold_blocks = {(g["page_url"], g["block_xpath"]) for g in row["gold"]}
    used = {n for s in answer["sentences"] for n in s["citations"]}
    cited = [c for c in answer["citations"] if c["n"] in used]
    pages = {c["url"] for c in cited}
    blocks = {(c["url"], c["xpath"]) for c in cited}
    if not gold_blocks:
        return {"page_p": None, "page_r": None, "block_p": None, "block_r": None}
    return {
        "page_p": len(pages & gold_pages) / len(pages) if pages else 0.0,
        "page_r": len(pages & gold_pages) / len(gold_pages),
        "block_p": len(blocks & gold_blocks) / len(blocks) if blocks else 0.0,
        "block_r": len(blocks & gold_blocks) / len(gold_blocks),
    }


# -- the bm25 baseline ------------------------------------------------------------------------


def bm25_answer(graph: SiteGraph, assembler: ContextAssembler, provider: Any, question: str, *, limit: int = 24) -> dict[str, Any]:
    """The observed layer only: top sections by BM25, their blocks as numbered evidence."""
    candidates: list[tuple[Evidence, str]] = []
    for item in assembler.score_sections(question, limit=6):
        page = graph.pages.get(item.section.page_key)
        if page is None:
            continue
        for ref in item.section.blocks[:6]:
            text = ref.slice(item.section.text)
            if text.strip() and ref.kind not in {"code", "image"}:
                quote = text[:320]
                candidates.append((Evidence(page.key, page.url, item.section.id, ref.xpath, (0, len(quote)), quote, page.content_hash), item.section.heading))
            if len(candidates) >= limit:
                break
        if len(candidates) >= limit:
            break
    lines = [f'[{n}] {ev.url} | {heading or "(page)"} | "{ev.quote}"' for n, (ev, heading) in enumerate(candidates, start=1)]
    citations = [Citation(n, ev.url, ev.block_xpath, ev.quote, ev.section_id) for n, (ev, _) in enumerate(candidates, start=1)]
    if provider is None:
        text = "Not stated on this site." if not candidates else " ".join(f"{ev.quote.rstrip('.')} [{n}]." for n, (ev, _) in enumerate(candidates[:3], start=1))
        usage = {"input_tokens": 0, "output_tokens": 0}
    else:
        result = provider.complete_text(ANSWER_SYSTEM, answer_prompt(question, lines), model=provider.config.answer_model or provider.config.model or None)
        text, usage = result.text, {"input_tokens": result.usage.input_tokens, "output_tokens": result.usage.output_tokens}
    answer = parse_answer(text, citations, QueryPath())
    answer.usage = usage
    return answer.as_dict()


# -- the run ----------------------------------------------------------------------------------


def run(graph: SiteGraph, qa: list[dict[str, Any]], provider: Any, *, modes: list[str], kg_dir: Path, rebuild: bool) -> dict[str, Any]:
    started = time.time()
    store = KGStore.for_site(graph.root, kg_dir)
    build_stats: dict[str, Any] = {}
    if any(m.startswith("kg") for m in modes):
        for event in KGBuilder(graph, provider, store, build_config=BuildConfig(rebuild=rebuild)).run():
            if event["type"] == "estimate":
                print(f"build estimate: {event['sections']} sections, {event['cached_sections']} cached, ~{event['input_tokens']:,} input tokens", file=sys.stderr)
            elif event["type"] == "done":
                build_stats = event["stats"]
                print(
                    f"build: {build_stats['entities']} entities, {build_stats['relations']} relations, rejection {build_stats['rejection_rate']:.1%}, "
                    f"{build_stats['input_tokens']:,} in / {build_stats['output_tokens']:,} out, {build_stats['seconds']}s",
                    file=sys.stderr,
                )
    assembler = ContextAssembler(graph)
    results: dict[str, list[dict[str, Any]]] = {}
    for mode in modes:
        rows: list[dict[str, Any]] = []
        retriever = None
        if mode == "kg":
            retriever = KGRetriever(store, provider, graph=None)
        elif mode == "kg+sections":
            retriever = KGRetriever(store, provider, graph=graph, retrieval=RetrievalConfig())
        for row in qa:
            t0 = time.time()
            if mode == "bm25":
                answer = bm25_answer(graph, assembler, provider, row["question"])
            else:
                assert retriever is not None
                answer = next(e for e in retriever.ask(row["question"]) if e["type"] == "answer")
            correct, f1 = score_answer(row, answer)
            cites = citation_scores(row, answer)
            claims = [s for s in answer["sentences"] if s["unsupported"] or s["citations"]]
            rows.append({
                "id": row["id"],
                "mode": mode,
                "answer_type": row["answer_type"],
                "hops": row.get("hops", 1),
                "source": row.get("source", ""),
                "correct": correct,
                "f1": round(f1, 3),
                "abstained": answer["abstained"],
                "unsupported": answer["unsupported"],
                "claims": len(claims),
                **cites,
                "usage": answer.get("usage", {}),
                "seconds": round(time.time() - t0, 3),
                "text": answer["text"][:300],
            })
        results[mode] = rows
    store.close()
    summary = {mode: summarise(rows) for mode, rows in results.items()}
    return {
        "site": graph.root,
        "questions": len(qa),
        "provider": provider.config.redacted() if provider is not None else None,
        "build": build_stats,
        "graph": {
            "pages": len(graph.pages),
            "entities_per_page": round(build_stats.get("entities", 0) / max(1, len(graph.pages)), 2),
            "relations_per_page": round(build_stats.get("relations", 0) / max(1, len(graph.pages)), 2),
            "rejection_rate": build_stats.get("rejection_rate"),
        },
        "summary": summary,
        "rows": [r for rows in results.values() for r in rows],
        "seconds": round(time.time() - started, 2),
    }


def _mean(values: list[float | None]) -> float | None:
    real = [v for v in values if v is not None]
    return round(sum(real) / len(real), 3) if real else None


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def bucket(name: str, subset: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "n": len(subset),
            "correct": round(sum(r["correct"] for r in subset) / len(subset), 3) if subset else None,
            "f1": _mean([r["f1"] for r in subset]),
        }

    scored = [r for r in rows if r["answer_type"] != "abstain"]
    abstain = [r for r in rows if r["answer_type"] == "abstain"]
    claims = sum(r["claims"] for r in rows)
    unsupported = sum(r["unsupported"] for r in rows)
    return {
        "overall": bucket("overall", scored),
        "typed": bucket("typed", [r for r in scored if r["answer_type"] in {"number", "date"}]),
        "span": bucket("span", [r for r in scored if r["answer_type"] in {"span", "free", "list"}]),
        "two_hop": bucket("two_hop", [r for r in scored if r["hops"] >= 2]),
        "abstention_correct": round(sum(r["correct"] for r in abstain) / len(abstain), 3) if abstain else None,
        "citation_page_precision": _mean([r["page_p"] for r in scored]),
        "citation_page_recall": _mean([r["page_r"] for r in scored]),
        "citation_block_precision": _mean([r["block_p"] for r in scored]),
        "citation_block_recall": _mean([r["block_r"] for r in scored]),
        "unsupported_sentence_rate": round(unsupported / claims, 3) if claims else 0.0,
        "answer_tokens_in": sum(int(r["usage"].get("input_tokens") or 0) for r in rows),
        "answer_tokens_out": sum(int(r["usage"].get("output_tokens") or 0) for r in rows),
        "seconds": round(sum(r["seconds"] for r in rows), 2),
    }


def table(report: dict[str, Any]) -> str:
    modes = list(report["summary"])
    lines = ["| metric | " + " | ".join(modes) + " |", "|---|" + "---:|" * len(modes)]

    def cell(value: Any) -> str:
        if value is None:
            return "n/a"
        return f"{value:.3f}" if isinstance(value, float) else str(value)

    for label, path in (
        ("answer correct (all)", ("overall", "correct")),
        ("answer correct (typed: number/date)", ("typed", "correct")),
        ("answer correct (span/list/free)", ("span", "correct")),
        ("answer correct (2-hop)", ("two_hop", "correct")),
        ("abstention correct", ("abstention_correct",)),
        ("citation precision, page", ("citation_page_precision",)),
        ("citation recall, page", ("citation_page_recall",)),
        ("citation precision, block", ("citation_block_precision",)),
        ("citation recall, block", ("citation_block_recall",)),
        ("unsupported-sentence rate", ("unsupported_sentence_rate",)),
        ("answer tokens in / out", ("answer_tokens_in", "answer_tokens_out")),
        ("seconds", ("seconds",)),
    ):
        values = []
        for mode in modes:
            summary = report["summary"][mode]
            if path == ("answer_tokens_in", "answer_tokens_out"):
                values.append(f"{summary['answer_tokens_in']:,} / {summary['answer_tokens_out']:,}")
                continue
            value: Any = summary
            for key in path:
                value = value.get(key) if isinstance(value, dict) else None
            values.append(cell(value))
        lines.append(f"| {label} | " + " | ".join(values) + " |")
    build = report.get("build") or {}
    if build:
        lines.append("")
        lines.append(
            f"build: {build['entities']} entities, {build['relations']} relations over {report['graph']['pages']} pages "
            f"({report['graph']['entities_per_page']} / {report['graph']['relations_per_page']} per page); "
            f"{build['accepted']} verified assertions, {build['rejected']} rejected (rate {build['rejection_rate']:.1%}), "
            f"{build['cache_hits']} cache hits; {build['input_tokens']:,} in / {build['output_tokens']:,} out tokens"
            + (f", ${build['usd']:.4f}" if build.get("usd") else "")
            + f", {build['seconds']}s"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pages", help="directory of saved HTML pages")
    parser.add_argument("--graph", help="or a JSONL graph written by `webgraph graph`")
    parser.add_argument("--root", required=True)
    parser.add_argument("--qa", required=True, help="questions JSONL (see generate.py)")
    parser.add_argument("--provider", help="fake | openai-compatible | anthropic | gemini | a preset; default WEBGRAPH_LLM_PROVIDER")
    parser.add_argument("--model", help="default WEBGRAPH_LLM_MODEL")
    parser.add_argument("--base-url")
    parser.add_argument("--modes", default="bm25,kg,kg+sections")
    parser.add_argument("--kg-dir", help="where to keep the knowledge graph (default: a temporary directory)")
    parser.add_argument("--rebuild", action="store_true", help="ignore the model cache")
    parser.add_argument("--out", help="write the full report as JSON")
    parser.add_argument("--json", action="store_true", help="print the JSON report instead of the table")
    args = parser.parse_args()

    if args.pages:
        graph = graph_from_directory(args.pages, args.root)
    elif args.graph:
        from webgraph.graph.export import load_jsonl

        graph = load_jsonl(args.graph)
    else:
        parser.error("one of --pages or --graph is required")
    graph.root = graph.root or args.root
    qa = [json.loads(line) for line in Path(args.qa).read_text(encoding="utf-8").splitlines() if line.strip()]
    overrides = {k: v for k, v in (("provider", args.provider), ("model", args.model), ("base_url", args.base_url)) if v}
    config = ProviderConfig.from_dict(overrides, base=ProviderConfig.from_env())
    if config.provider == "fake" and not config.model:
        config = ProviderConfig.from_dict({"model": "fake-1"}, base=config)
    if not config.model:
        parser.error("no model: pass --provider fake, or --model / WEBGRAPH_LLM_MODEL")
    provider = make_provider(config)
    kg_dir = Path(args.kg_dir) if args.kg_dir else Path(tempfile.mkdtemp(prefix="webgraph-kg-bench-"))
    report = run(graph, qa, provider, modes=[m.strip() for m in args.modes.split(",") if m.strip()], kg_dir=kg_dir, rebuild=args.rebuild)
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    print(json.dumps(report, indent=1, ensure_ascii=False) if args.json else table(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
