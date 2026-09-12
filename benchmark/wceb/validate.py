r"""Does WCEB's published baseline still describe the system it names?

A published baseline is frozen at the version its authors tested. This engine is current.
Comparing the two flatters whoever ran more recently, and on WCXB that turned out to be worth
**0.022** -- current trafilatura scores 0.813 through this repository's WCXB harness against
the 0.791 its paper reports, almost all of it on forum pages, because a later release learned
to read Discourse threads out of a JSON payload.

This runs a named system over WCEB's own cached HTML, scores it with the same ROUGE-LSum used
for the engine, and prints the result beside what WCEB published for that system. It answers
one question and no other: is the published column still true?

    uv run --package webgraph python benchmark/wceb/validate.py \
        --corpus <clone> --dataset cetd --system trafilatura
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from statistics import mean

# WCEB's published per-dataset F1, from the authors' own CSVs as averaged by run.py.
PUBLISHED: dict[str, dict[str, float]] = {
    "trafilatura": {
        "cleaneval": 0.857, "cleanportaleval": 0.920, "cetd": 0.907, "dragnet": 0.840,
        "google-trends-2017": 0.790, "l3s-gn1": 0.880, "readability": 0.934,
        "scrapinghub": 0.941,
    },
}


def extract(html: str, url: str) -> str:
    import trafilatura

    return trafilatura.extract(html, url=url) or ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--system", default="trafilatura", choices=sorted(PUBLISHED))
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).parent))
    from run import _ground_truth, _score_star

    truth = _ground_truth(args.corpus, args.dataset)
    page_ids = sorted(truth)[: args.limit] if args.limit else sorted(truth)
    html_dir = args.corpus / "datasets" / "combined" / "html" / args.dataset

    scores: list[float] = []
    failures = 0
    for done, page_id in enumerate(page_ids, 1):
        reference, url = truth[page_id]
        try:
            html = (html_dir / f"{page_id}.html").read_text(encoding="utf-8", errors="replace")
            text = extract(html, url or "")
        except Exception:  # noqa: BLE001 - a crash scores zero, it does not stop the run
            text, failures = "", failures + 1
        scores.append(_score_star(("x", reference, text))[3])
        if done % 100 == 0:
            print(f"  {done}/{len(page_ids)}", file=sys.stderr)

    measured = mean(scores)
    published = PUBLISHED[args.system][args.dataset]
    print(f"\n{args.system} on WCEB/{args.dataset}, {len(scores)} pages, run today")
    print(f"  measured here   {measured:.3f}")
    print(f"  WCEB publishes  {published:.3f}")
    print(f"  drift           {measured - published:+.3f}")
    print(f"  extractor failures: {failures}")
    print(
        "\n  The published column is still true.\n"
        if abs(measured - published) <= 0.02
        else "\n  The published column understates this system today. Any ranking that uses\n"
        "  it against a freshly-run engine is comparing across versions, not systems.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
