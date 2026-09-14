"""Live-site regression suite: the production path against a real browser's own text.

The corpora are cached HTML from a fixed moment; this is the web today. Each site in
`sites.txt` is fetched the way the API fetches it (static + rendered, merged), reduced to
content by the same `select_content` and page-type policy, and scored two ways against
Chromium's `innerText` of the page's main region:

- **recall**: page sentences (40+ characters) missing from our content;
- **precision**: our sentences that are not on the page.

The oracle is crude on purpose -- it cannot see code blocks, and `innerText` includes the
comment thread under an article -- so the absolute numbers are not a benchmark. What
matters is the **diff between two runs**: a candidate that moves a page's recall or
precision by three points, or its block count, is a page to open and read. Every fix
in `docs/SESSION-17-RESEARCH-LOOP.md` was gated on this diff.

    # baseline on main, then the candidate from another checkout, then compare
    uv run python benchmark/live/run.py --out /tmp/main.json
    uv run python benchmark/live/run.py --out /tmp/candidate.json
    uv run python benchmark/live/run.py --compare /tmp/main.json /tmp/candidate.json

The browser text is cached beside the output (`<out>.pages/<site>.txt`) so both runs
score against the same oracle; delete the cache to re-fetch. Needs Playwright with
Chromium (`uv run --package webgraph playwright install chromium`).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_SITES = HERE / "sites.txt"

ORACLE = r"""
import sys
from playwright.sync_api import sync_playwright
url, out = sys.argv[1], sys.argv[2]
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 900}, user_agent=UA)
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
    for selector in ("button:has-text('Accept all')", "button:has-text('Accept All')",
                     "button:has-text('I agree')", "button:has-text('Agree')",
                     "button:has-text('Accept')", "#onetrust-accept-btn-handler"):
        try:
            control = page.locator(selector).first
            if control.is_visible(timeout=500):
                control.click(timeout=2000)
                page.wait_for_timeout(1000)
                break
        except Exception:
            pass
    text = page.evaluate(
        "() => (document.querySelector('main, article, [role=main]') || document.body).innerText"
    )
    browser.close()
open(out, "w").write(text)
"""


def _sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text)
    out = []
    for piece in re.split(r"(?<=[.!?])\s+", text):
        folded = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", piece.lower())).strip()
        if len(folded) >= 40:
            out.append(folded)
    return out


def _fold(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", text.lower()))


def _oracle_text(url: str, cache: Path) -> str:
    if cache.exists():
        return cache.read_text()
    cache.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, "-c", ORACLE, url, str(cache)],
        check=True,
        timeout=180,
        capture_output=True,
    )
    return cache.read_text()


def run(sites: Path, out: Path) -> None:
    from webgraph.content import select_content
    from webgraph.pagetype import PageType, default_router, policy_for
    from webgraph.resolve import resolve_page
    from webgraph.types import blocks_text

    router = default_router()
    pages_dir = out.with_suffix(out.suffix + ".pages")
    results: dict[str, dict[str, object]] = {}
    for line in sites.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, url = line.split(None, 1)
        started = time.time()
        try:
            page_text = _oracle_text(url, pages_dir / f"{name}.txt")
            document = resolve_page(url).document
            routing = router.route(document) if router is not None else None
            page_type = routing.page_type if routing else PageType.UNKNOWN
            selection = select_content(
                document.blocks, config=policy_for(page_type), title=document.title
            )
            ours = blocks_text(selection.blocks)
            page_sentences, our_sentences = _sentences(page_text), _sentences(ours)
            folded_page, folded_ours = _fold(page_text), _fold(ours)
            missing = [s for s in page_sentences if s not in folded_ours]
            extra = [s for s in our_sentences if s not in folded_page]
            results[name] = {
                "url": url,
                "type": str(page_type),
                "blocks": len(document.blocks),
                "kept": len(selection.blocks),
                "methods": list(selection.methods),
                "words": len(ours.split()),
                "recall": round(1 - len(missing) / max(1, len(page_sentences)), 3),
                "precision": round(1 - len(extra) / max(1, len(our_sentences)), 3),
                "missing": missing[:6],
                "extra": extra[:6],
                "seconds": round(time.time() - started, 1),
            }
            r = results[name]
            print(
                f"{name:14} {r['type']:13} R {r['recall']:.2f} P {r['precision']:.2f} kept {r['kept']}/{r['blocks']} {selection.methods}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001 -- a site failing must not stop the suite
            results[name] = {
                "url": url,
                "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            }
            print(f"{name:14} ERROR {type(exc).__name__}: {str(exc)[:120]}", flush=True)
        out.write_text(json.dumps(results, indent=1))


def compare(base_path: Path, cand_path: Path) -> None:
    base = json.loads(base_path.read_text())
    cand = json.loads(cand_path.read_text())
    print(
        f"{'site':14} {'type':13} {'R base':>7} {'R cand':>7} {'P base':>7} {'P cand':>7}  kept       new methods"
    )
    for name in base:
        if name not in cand or "error" in base[name] or "error" in cand[name]:
            print(f"{name:14} (error or missing on one side)")
            continue
        a, b = base[name], cand[name]
        moved = (
            abs(b["recall"] - a["recall"]) >= 0.03
            or abs(b["precision"] - a["precision"]) >= 0.03
        )
        print(
            f"{name:14} {b['type']:13} {a['recall']:7.2f} {b['recall']:7.2f} {a['precision']:7.2f} {b['precision']:7.2f}  "
            f"{a['kept']:>4}->{b['kept']:<4} {','.join(m for m in b['methods'] if m not in a['methods'])}{'  <<' if moved else ''}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--sites", type=Path, default=DEFAULT_SITES)
    parser.add_argument("--out", type=Path, default=Path("live-suite.json"))
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("BASE", "CANDIDATE"))
    args = parser.parse_args()
    if args.compare:
        compare(*args.compare)
    else:
        run(args.sites, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
