r"""Is this engine's WCXB number comparable to the published ones, or only to itself?

A leaderboard row is meaningless unless the harness that produced it agrees with the harness
that produced everyone else's. The way to find out is not to reason about it: run a
*published* system through *this* harness, over the same cached pages and the same scorer,
and see whether the number that comes out matches what its authors reported.

If trafilatura scores its published 0.791 here, then this harness is faithful and the
engine's own row can be read beside the others. If it scores materially differently, the
engine's row is comparable to nothing and should not be printed next to theirs.

    uv run --package webgraph python benchmark/wcxb/validate.py --corpus <clone>

Reads the dev split only. Runs no system other than the one named.
"""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

# What the corpus README reports for these systems on the dev split.
PUBLISHED: dict[str, float] = {
    "trafilatura": 0.791,
    "readability": 0.675,
}


def load_word_f1(corpus: Path):  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("wcxb_evaluate", corpus / "evaluate.py")
    if spec is None or spec.loader is None:
        raise SystemExit(f"no evaluate.py in {corpus}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.word_f1


def extract_trafilatura(html: str, url: str) -> str:
    import trafilatura

    # Defaults, deliberately. Tuning someone else's extractor until it matches would
    # defeat the purpose: the question is whether the harness reproduces their number,
    # not whether their extractor can be made to reach it.
    return trafilatura.extract(html, url=url) or ""


def extract_readability(html: str, url: str) -> str:
    from lxml import html as lxml_html
    from readability import Document

    summary = Document(html).summary()
    return lxml_html.fromstring(summary).text_content()


EXTRACTORS = {"trafilatura": extract_trafilatura, "readability": extract_readability}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--system", default="trafilatura", choices=sorted(EXTRACTORS))
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    word_f1 = load_word_f1(args.corpus)
    extract = EXTRACTORS[args.system]

    by_type: dict[str, list[float]] = defaultdict(list)
    failures = 0
    paths = sorted((args.corpus / "dev" / "ground-truth").glob("*.json"))
    if args.limit:
        paths = paths[: args.limit]

    for done, gt_path in enumerate(paths, 1):
        data = json.loads(gt_path.read_text(encoding="utf-8"))
        truth = (data.get("ground_truth") or {}).get("main_content") or ""
        page_type = ((data.get("_internal") or {}).get("page_type") or {}).get("primary") or "?"
        file_id = str(data.get("file_id") or gt_path.stem)
        html_path = args.corpus / "dev" / "html" / f"{file_id}.html.gz"
        try:
            with gzip.open(html_path, "rt", encoding="utf-8", errors="replace") as handle:
                html = handle.read()
            text = extract(html, data.get("url", ""))
        except Exception:  # noqa: BLE001 - a crash is a score of zero, not a stop
            text, failures = "", failures + 1
        by_type[page_type].append(word_f1(text, truth)[2])
        if done % 200 == 0:
            print(f"  {done}/{len(paths)}", file=sys.stderr)

    every = [f for scores in by_type.values() for f in scores]
    measured = mean(every)
    published = PUBLISHED[args.system]

    print(f"\n{args.system} through this harness, WCXB dev, {len(every)} pages")
    print(f"{'page type':<16}{'N':>6}{'F1':>9}")
    for page_type in sorted(by_type):
        scores = by_type[page_type]
        print(f"{page_type:<16}{len(scores):>6}{mean(scores):>9.3f}")
    print(f"{'overall':<16}{len(every):>6}{measured:>9.3f}")
    print(f"\n  measured here   {measured:.3f}")
    print(f"  published       {published:.3f}")
    print(f"  difference      {measured - published:+.3f}")
    print(f"  extractor failures: {failures}")
    verdict = (
        "harness reproduces the published number; rows are comparable"
        if abs(measured - published) <= 0.02
        else "harness does NOT reproduce it; this engine's row is not comparable to theirs"
    )
    print(f"\n  {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
