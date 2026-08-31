"""Score extracted main content against a consensus of established extractors.

Why a consensus and not a gold standard
---------------------------------------
There is no ground truth for "the main content of this page" that survives contact with a
real website. Hand-labelling is slow and, worse, arbitrary at the edges everyone disagrees
about -- captions, author bylines, related-article strips. So the reference is a **majority
vote of three independent extractors** (trafilatura, readability, jusText): a shingle counts
as content when at least two of the three keep it.

This is not a claim that the vote is correct. It is a claim that it is *independent* of this
engine, stable between runs, and disagrees with any one tool as much as this engine does --
which is enough to make the number comparable over time.

Why shingles
------------
Comparing extracted text token-by-token confuses two different things: whether the right
words were kept, and whether they were split into the same sentences. An early version of
this measurement reported F=0.611 for the engine when 5-word shingles put the same output at
0.796 -- the gap was segmentation, not content.

A shingle is five consecutive words, lower-cased, punctuation stripped. Precision is the
share of the engine's shingles that the vote also has; recall is the share of the vote's
shingles the engine has.

The comparison trap
-------------------
Compare like with like. The first version of this measurement reported danluu.com as "51.8%
of content missing" because trafilatura had been called with `include_links=True`, inflating
its character count with `[text](url)`, while the engine emitted no links at all. Plain
against plain, the two were 8,945 versus 9,138 characters -- 98% agreement. Every extractor
here is therefore asked for **plain text with no markup**.

Usage
-----
    uv run --group bench python benchmark/content_quality/run.py [url ...]
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

DEFAULT_SITES: Final[tuple[str, ...]] = (
    "https://danluu.com/futurist-predictions/",
    "https://simonwillison.net/2025/Sep/6/anthropic-settlement/",
    "https://docs.pytest.org/en/stable/how-to/fixtures.html",
    "https://www.attrs.org/en/stable/examples.html",
    "https://jinja.palletsprojects.com/en/stable/templates/",
    "https://click.palletsprojects.com/en/stable/options/",
)

SHINGLE: Final[int] = 5
_WORD = re.compile(r"[a-z0-9]+")


def shingles(text: str, size: int = SHINGLE) -> set[tuple[str, ...]]:
    words = _WORD.findall(text.lower())
    if len(words) < size:
        return {tuple(words)} if words else set()
    return {tuple(words[i : i + size]) for i in range(len(words) - size + 1)}


@dataclass(frozen=True, slots=True)
class Score:
    name: str
    precision: float
    recall: float
    chars: int

    @property
    def f1(self) -> float:
        total = self.precision + self.recall
        return 2 * self.precision * self.recall / total if total else 0.0


def score(candidate: str, reference: set[tuple[str, ...]], name: str) -> Score:
    produced = shingles(candidate)
    if not produced or not reference:
        return Score(name=name, precision=0.0, recall=0.0, chars=len(candidate))
    overlap = len(produced & reference)
    return Score(
        name=name,
        precision=overlap / len(produced),
        recall=overlap / len(reference),
        chars=len(candidate),
    )


def consensus(texts: dict[str, str], votes: int = 2) -> set[tuple[str, ...]]:
    """Shingles that at least `votes` of the reference extractors kept."""
    counts: dict[tuple[str, ...], int] = {}
    for text in texts.values():
        for shingle in shingles(text):
            counts[shingle] = counts.get(shingle, 0) + 1
    return {shingle for shingle, count in counts.items() if count >= votes}


def reference_texts(html: str, url: str) -> dict[str, str]:
    """Plain text from each reference extractor. Markup off everywhere -- see the docstring."""
    import justext
    import trafilatura
    from readability import Document as ReadabilityDocument

    out: dict[str, str] = {}

    try:
        extracted = trafilatura.extract(
            html, url=url, include_links=False, include_comments=False, output_format="txt"
        )
        out["trafilatura"] = extracted or ""
    except Exception as exc:
        out["trafilatura"] = ""
        print(f"    trafilatura failed: {type(exc).__name__}: {exc}", file=sys.stderr)

    try:
        summary_html = ReadabilityDocument(html).summary()
        out["readability"] = re.sub(r"<[^>]+>", " ", summary_html)
    except Exception as exc:
        out["readability"] = ""
        print(f"    readability failed: {type(exc).__name__}: {exc}", file=sys.stderr)

    try:
        paragraphs = justext.justext(html.encode("utf-8"), justext.get_stoplist("English"))
        out["justext"] = "\n".join(p.text for p in paragraphs if not p.is_boilerplate)
    except Exception as exc:
        out["justext"] = ""
        print(f"    justext failed: {type(exc).__name__}: {exc}", file=sys.stderr)

    return out


def engine_texts(url: str) -> dict[str, str]:
    """The engine's output, raw and with cross-page chrome removed.

    Chrome removal needs a corpus, so the site around the page is crawled shallowly. That is
    the honest way to measure it: the feature's whole premise is that it is unavailable to a
    single-page extractor.
    """
    from webgraph.boilerplate import detect_site_chrome, strip_site_chrome
    from webgraph.crawl.discovery import discover_by_crawling, load_robots
    from webgraph.crawl.frontier import same_site
    from webgraph.resolve import Strategy, resolve_page
    from webgraph.types import BlockKind

    resolved = resolve_page(url, strategy=Strategy.STATIC_ONLY)
    document = resolved.document
    raw = document.text

    root = f"{url.split('/')[0]}//{url.split('/')[2]}/"
    neighbours = [
        candidate
        for candidate in discover_by_crawling(
            root, max_urls=14, max_depth=2, policy=load_robots(root)
        )
        if same_site(candidate, root)
    ][:12]

    corpus = [document.blocks]
    for candidate in neighbours:
        if candidate == url:
            continue
        try:
            corpus.append(resolve_page(candidate, strategy=Strategy.STATIC_ONLY).document.blocks)
        except Exception:
            continue

    stripped = raw
    if len(corpus) >= 6:
        chrome = detect_site_chrome(corpus)
        kept = strip_site_chrome(list(document.blocks), chrome)
        stripped = "\n\n".join(b.text for b in kept if b.text.strip())

    # A third variant, because the first diff run showed what the precision gap actually is.
    # Almost everything the engine keeps and the vote does not is a code block or a table --
    # Jinja template examples, pytest fixtures, filter reference tables. All three reference
    # extractors are tuned for prose and drop or flatten those, so the consensus is biased
    # against exactly the content a documentation site exists to publish.
    #
    # Scoring prose alone isolates the question: is the engine noisy, or is it keeping
    # structure the references throw away?
    prose = "\n\n".join(
        block.text
        for block in document.blocks
        if block.kind not in {BlockKind.CODE, BlockKind.TABLE, BlockKind.FIGURE_CAPTION}
        and block.text.strip()
    )

    return {
        "engine (raw)": raw,
        "engine (chrome removed)": stripped,
        "engine (prose only)": prose,
    }


def report_excess(url: str, vote: set[tuple[str, ...]]) -> None:
    """Show what the engine keeps that the reference vote does not.

    Precision is where this engine trails, and a precision number on its own says nothing
    about what to change. Listing the blocks that no two reference extractors kept turns the
    gap into a specific list of things to look at.
    """
    from webgraph.resolve import Strategy, resolve_page

    document = resolve_page(url, strategy=Strategy.STATIC_ONLY).document
    excess: list[tuple[int, str, str]] = []
    for block in document.blocks:
        text = block.text.strip()
        if len(text) < 20:
            continue
        produced = shingles(text)
        if not produced:
            continue
        if len(produced - vote) / len(produced) > 0.9:
            excess.append((len(text), block.kind.value, " ".join(text.split())[:88]))

    excess.sort(reverse=True)
    print(f"  kept but not in the vote: {len(excess)} blocks, {sum(s for s, _, _ in excess):,} chars")
    for size, kind, text in excess[:10]:
        print(f"    {size:>6,}  {kind:<14} {text}")


def run(urls: Iterable[str], *, diff: bool = False) -> None:
    from webgraph.fetch.static import fetch_static

    totals: dict[str, list[Score]] = {}

    for url in urls:
        print(f"\n{url}")
        result = fetch_static(url)
        if not result.ok or not result.html:
            print(f"  unreachable: {result.error}")
            continue

        references = reference_texts(result.html, url)
        vote = consensus(references)
        if not vote:
            print("  reference extractors agreed on nothing; skipped")
            continue

        if diff:
            report_excess(url, vote)

        candidates = {**references, **engine_texts(url)}
        print(f"  {'extractor':26s} {'P':>7} {'R':>7} {'F':>7} {'chars':>8}")
        for name, text in candidates.items():
            entry = score(text, vote, name)
            totals.setdefault(name, []).append(entry)
            print(
                f"  {name:26s} {entry.precision:>7.3f} {entry.recall:>7.3f} "
                f"{entry.f1:>7.3f} {entry.chars:>8,}"
            )

    if not totals:
        return
    print(f"\n{'=' * 64}\nMEAN OVER {len(next(iter(totals.values())))} PAGES")
    print(f"  {'extractor':26s} {'P':>7} {'R':>7} {'F':>7}")
    for name, scores in sorted(totals.items(), key=lambda kv: -_mean(s.f1 for s in kv[1])):
        print(
            f"  {name:26s} {_mean(s.precision for s in scores):>7.3f} "
            f"{_mean(s.recall for s in scores):>7.3f} {_mean(s.f1 for s in scores):>7.3f}"
        )
    print(
        "\nA reference extractor scoring below 1.0 against the vote is expected: the vote is"
        "\nwhat two of the three agreed on, not what any one of them produced."
    )


def _mean(values: Iterable[float]) -> float:
    items = list(values)
    return sum(items) / len(items) if items else 0.0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="*", default=list(DEFAULT_SITES))
    parser.add_argument(
        "--diff",
        action="store_true",
        help="list the blocks the engine keeps that the reference vote does not",
    )
    args = parser.parse_args()
    run(args.urls or DEFAULT_SITES, diff=args.diff)
