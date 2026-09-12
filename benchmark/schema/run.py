"""Does auto-selecting a schema by page type produce right answers or confident wrong ones?

The question this measures is narrow and it is the one that matters: when the engine picks
a schema on its own and fills it from a page's structured data, how often is a value it
reports **wrong** -- not missing, wrong. A missing field is recoverable; a wrong one is
indistinguishable from a right one to everything downstream.

Scored against WCXB, which is the only public corpus with human-reviewed titles *and*
our exact seven page types on 2,008 pages. Obtain it with

    git clone https://github.com/Murrough-Foley/web-content-extraction-benchmark

and point `--corpus` at the clone. CC-BY-4.0, not vendored.

Two numbers are reported for every mapper, and both are needed to read it honestly:

  gold    the page type taken from the corpus label -- the ceiling, what the mapping is
          worth if routing were perfect
  routed  the page type from our own router -- what a user actually gets

The router was trained on dev, so asking the shipped model to type a dev page measures its
memory rather than its judgement. Pass `--oof` with the out-of-fold predictions
`benchmark/train/router_train.py` writes: each of those came from a fold that never saw the
page it predicts, which is the only honest routed number available here.

The **test** split cannot be used at all: every file in it is in the stripped-`<script>`
cohort below, so there is no structured data left to map. That is a property of the archive,
not of the web, and it is why every number here is a dev number.

A corpus artifact that would otherwise invert every result: 1,081 of the archived files have
had every <script> tag stripped during archiving. A page with no <script> reports no JSON-LD
for reasons that have nothing to do with the web, so those files are excluded and the count
of exclusions is printed.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import lxml.html

from webgraph.extract.page_facts import facts_for_page
from webgraph.extract.pageschema import schema_for
from webgraph.extract.schema import extract_facts, merge_facts
from webgraph.pagetype import PageType, default_router, page_features
from webgraph.pipeline import build_document
from webgraph.structured.payloads import extract_payloads

HAS_SCRIPT = re.compile(r"<script", re.I)

TITLE_FIELDS = ("headline", "name")
"""Where each page type's schema puts the page's own title."""


def norm(text: Any) -> str:
    """Fold case, punctuation and whitespace, the way the corpus's own scorer does."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", str(text or "").lower())).strip()


def verdict(got: str | None, want: str, strict: bool = False) -> str:
    """One of: exact, prefix, WRONG, missing.

    `prefix` counts as correct. A page whose annotated title is "Crusher ANC 2 Wireless
    Headphones" and whose markup says "Crusher ANC 2" has not made an error -- it has been
    less verbose than the annotator.
    """
    if got is None:
        return "missing"
    a, b = norm(got), norm(want)
    if a == b:
        return "exact"
    if not strict and a and b and (a.startswith(b) or b.startswith(a)):
        return "prefix"
    return "WRONG"


def title_from(facts: dict[str, Any]) -> str | None:
    for field in TITLE_FIELDS:
        fact = facts.get(field)
        if fact is not None:
            return str(fact.value)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--split", default="test", choices=["dev", "test", "both"])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="count only exact matches. By default a value that is a prefix of the "
        "annotation, or vice versa, counts as correct -- which forgives a title carrying "
        "a ' | Site Name' suffix. Worth running both ways before believing a source.",
    )
    parser.add_argument(
        "--oof",
        type=Path,
        help="out-of-fold router predictions from router_train.py. Without it the routed "
        "column uses the shipped model, which saw these pages in training.",
    )
    args = parser.parse_args()

    splits = ["dev", "test"] if args.split == "both" else [args.split]
    router = default_router()
    oof: dict[str, dict[str, Any]] = (
        json.loads(args.oof.read_text(encoding="utf-8")) if args.oof else {}
    )

    # mapper -> page type -> verdict counts
    scores: dict[str, dict[str, Counter[str]]] = {
        "naive-gold": {},
        "gated-gold": {},
        "gated-routed": {},
    }
    skipped_no_script = 0
    seen = 0

    for split in splits:
        for path in sorted((args.corpus / split / "ground-truth").glob("*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            label = record.get("_internal", {}).get("page_type", {}).get("primary", "")
            try:
                gold = PageType(label)
            except ValueError:
                continue
            truth = record.get("ground_truth", {})
            title = truth.get("title")
            if not title:
                continue

            file_id = record.get("file_id") or path.stem
            html_path = args.corpus / split / "html" / f"{file_id}.html.gz"
            if not html_path.exists():
                continue
            html = gzip.decompress(html_path.read_bytes()).decode("utf-8", "replace")
            if not HAS_SCRIPT.search(html):
                skipped_no_script += 1
                continue

            url = record.get("url") or truth.get("url") or ""
            try:
                root = lxml.html.fromstring(html)
            except Exception:
                continue
            payloads = list(extract_payloads(root, html))
            if not payloads:
                continue

            seen += 1
            if args.limit and seen > args.limit:
                break

            schema = schema_for(gold)
            if schema is None:
                continue

            # Today's behaviour: every payload, no gate.
            naive = merge_facts(extract_facts(payloads, schema, url))
            scores["naive-gold"].setdefault(gold.value, Counter())[
                verdict(title_from(naive), title, args.strict)
            ] += 1

            # Gated by the corpus's own label: the ceiling.
            scores["gated-gold"].setdefault(gold.value, Counter())[
                verdict(title_from(facts_for_page(payloads, gold, url).facts), title, args.strict)
            ] += 1

            # Gated by what our router says, which is what a user gets. Out of fold when
            # those predictions were supplied: a router asked about a page it was trained on
            # is not answering, it is recalling.
            predicted = oof.get(file_id, {}).get("type") if oof else None
            if predicted is not None:
                routed = PageType(predicted)
            else:
                try:
                    document = build_document(url or "http://localhost/", html)
                    routed = router.route(page_features(document)).page_type
                except Exception:
                    routed = PageType.UNKNOWN
            scores["gated-routed"].setdefault(gold.value, Counter())[
                verdict(title_from(facts_for_page(payloads, routed, url).facts), title, args.strict)
            ] += 1

    print(
        f"split={args.split}  pages={seen}  "
        f"excluded (archiver stripped <script>)={skipped_no_script}  "
        f"routing={'out-of-fold' if oof else 'shipped model (saw dev in training)'}"
    )
    print()
    header = f"{'page type':15} {'n':>5}  " + "  ".join(f"{m:^28}" for m in scores)
    print(header)
    for page_type in sorted({t for m in scores.values() for t in m}):
        counts = scores["naive-gold"].get(page_type, Counter())
        total = sum(counts.values()) or 1
        row = []
        for mapper in scores:
            c = scores[mapper].get(page_type, Counter())
            ok = (c["exact"] + c["prefix"]) / total
            row.append(f"ok={ok:5.0%} WRONG={c['WRONG'] / total:4.0%} miss={c['missing'] / total:4.0%}")
        print(f"{page_type:15} {total:5}  " + "  ".join(f"{r:^28}" for r in row))

    print()
    for mapper in scores:
        c: Counter[str] = Counter()
        for counts in scores[mapper].values():
            c.update(counts)
        total = sum(c.values()) or 1
        print(
            f"ALL {mapper:14} n={total:5} "
            f"ok={(c['exact'] + c['prefix']) / total:6.1%} "
            f"WRONG={c['WRONG'] / total:6.1%} "
            f"missing={c['missing'] / total:6.1%}"
        )


if __name__ == "__main__":
    main()
