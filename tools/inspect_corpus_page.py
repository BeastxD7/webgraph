"""Show one benchmark page block by block, with each block's place in the ground truth.

The corpus runners give one number per page; this shows *why*. Each block is printed in
reading order with the value the boundary step gave it, whether it was chosen, and a `T`
when its opening words occur in the annotated main content -- so a page's precision loss
reads as a list of `IN` blocks without a `T`, and its recall loss as `out` blocks with one.

    # WCXB dev page 0617 (etsy), through the policy for its annotated page type
    uv run python tools/inspect_corpus_page.py wcxb 0617 --corpus path/to/web-content-extraction-benchmark

    # Zyte article-extraction page by id prefix
    uv run python tools/inspect_corpus_page.py zyte e372e42c --corpus path/to/article-extraction-benchmark

    # only the chosen blocks, or only the ones that disagree with the truth
    uv run python tools/inspect_corpus_page.py wcxb 0617 --chosen
    uv run python tools/inspect_corpus_page.py wcxb 0617 --disagree

Corpus paths default to `$WCXB_CORPUS` / `$ZYTE_CORPUS`, then `benchmark/<runner>/corpus`,
the same as the runners. Both corpora are static HTML, so there is no render and no box;
the reading order is the DOM fallback, as it is for the runners.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

from webgraph import main_content as mc
from webgraph.boilerplate import scope_to_main, strip_landmarks
from webgraph.content import select_content
from webgraph.pagetype import default_router, policy_for
from webgraph.pipeline import build_document


def _wcxb(corpus: Path, page: str, split: str) -> tuple[str, str, str, str]:
    truth = json.loads((corpus / split / "ground-truth" / f"{page}.json").read_text())
    with gzip.open(corpus / split / "html" / f"{page}.html.gz") as handle:
        html = handle.read().decode("utf-8", "replace")
    return (
        html,
        truth.get("url") or "https://example.invalid/",
        truth["ground_truth"].get("main_content") or "",
        truth["_internal"]["page_type"]["primary"],
    )


def _zyte(corpus: Path, prefix: str) -> tuple[str, str, str, str | None]:
    truth = json.loads((corpus / "ground-truth.json").read_text())
    matches = [k for k in truth if k.startswith(prefix)]
    if len(matches) != 1:
        raise SystemExit(f"{len(matches)} pages match {prefix!r}; give more of the id")
    key = matches[0]
    with gzip.open(corpus / "html" / f"{key}.html.gz") as handle:
        html = handle.read().decode("utf-8", "replace")
    return (
        html,
        truth[key].get("url") or "https://example.invalid/",
        truth[key].get("articleBody", ""),
        None,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("corpus_kind", choices=("wcxb", "zyte"))
    parser.add_argument(
        "page", help="WCXB page id (e.g. 0617) or a Zyte page-id prefix"
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=None,
        help="corpus clone (default: $WCXB_CORPUS / $ZYTE_CORPUS)",
    )
    parser.add_argument(
        "--split", default="dev", choices=("dev", "test"), help="WCXB split"
    )
    parser.add_argument(
        "--chosen", action="store_true", help="only the blocks the content step kept"
    )
    parser.add_argument(
        "--disagree",
        action="store_true",
        help="only blocks chosen-but-not-in-truth or in-truth-but-not-chosen",
    )
    parser.add_argument("--width", type=int, default=80)
    args = parser.parse_args()

    if args.corpus_kind == "wcxb":
        corpus = args.corpus or Path(
            os.environ.get("WCXB_CORPUS", "benchmark/wcxb/corpus")
        )
        html, url, truth, page_type = _wcxb(corpus, args.page, args.split)
    else:
        corpus = args.corpus or Path(
            os.environ.get("ZYTE_CORPUS", "benchmark/article_extraction/corpus")
        )
        html, url, truth, page_type = _zyte(corpus, args.page)

    document = build_document(html, url)
    if page_type is None:
        router = default_router()
        routing = router.route(document) if router is not None else None
        page_type = str(routing.page_type) if routing else "unknown"
    policy = policy_for(page_type)
    selection = select_content(
        list(document.blocks), model=None, config=policy, title=document.title or ""
    )
    chosen = {id(b) for b in selection.blocks}

    structural = scope_to_main(strip_landmarks(list(document.blocks)))
    mean = sum(
        min(mc.word_count(b.text), policy.cost_block_cap) for b in structural
    ) / max(1, len(structural))
    cost = min(max(policy.cost_ratio * mean, policy.cost_floor), policy.cost_ceiling)
    priced = replace(policy, block_cost=cost)

    ours = " ".join(b.text for b in selection.blocks)
    print(
        f"{url[:90]} | type {page_type} | blocks {len(document.blocks)} after structural {len(structural)} "
        f"chosen {len(selection.blocks)} {selection.methods} | cost {cost:.1f} | "
        f"ours {len(ours.split())} words, truth {len(truth.split())}"
    )
    for index, block in enumerate(document.blocks):
        head = block.text[:25]
        in_truth = bool(head) and head in truth
        is_chosen = id(block) in chosen
        if args.chosen and not is_chosen:
            continue
        if args.disagree and in_truth == is_chosen:
            continue
        print(
            f"{index:4} {'IN ' if is_chosen else 'out'} {'T' if in_truth else ' '} {mc.content_value(block, priced):7.1f} "
            f"{block.kind.value:9} {block.region!s:6} m={int(block.in_main)} w={block.widget!s:8} "
            f"body={'Y' if block.body_of else '-'} {block.text[: args.width]!r}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
