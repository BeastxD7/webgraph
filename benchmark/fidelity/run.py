"""Whole-page fidelity: the full `markdown` / `text` against what Chromium shows.

The corpus boards score the *filtered* content. This scores the other product -- the
whole page, where nothing a reader sees may be lost, nothing hidden may be added, the
order must be the page's and the structure kept. Each site in `sites.txt` (old, plain and
ugly pages on purpose: framesets, `<font>`, `<br><br>` paragraphs, layout tables) is
resolved the way the API resolves it, rendered to Markdown, and compared with Chromium's
own view of the page:

- **word recall**: share of the page's visible words present in our `text` (1.0 = nothing
  lost; this is the number that must not drop);
- **extra share**: share of our words that are not on the page (hidden menus, walls);
- **order inversions**: the page's visible text lines, sampled in DOM order, found in our
  text out of order (a monotone check, so a repeated phrase does not count);
- **structure**: Chromium's count of visible headings / tables / lists / images / links
  beside what the Markdown carries (`#`, pipe rows, list markers, `![`, `](http`).

The oracle is cached beside the output (`<out>.pages/<site>.json`) so two runs score the
same page; delete the cache to re-fetch. The site list therefore avoids pages that turn
over by the minute (a news front page scored against yesterday's oracle is noise, not a
regression). What matters is the **diff**:

    uv run python benchmark/fidelity/run.py --out /tmp/main.json          # on main
    uv run python benchmark/fidelity/run.py --out /tmp/cand.json          # on the branch
    uv run python benchmark/fidelity/run.py --compare /tmp/main.json /tmp/cand.json

Needs Playwright with Chromium (`uv run --package webgraph playwright install chromium`).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections import Counter
from itertools import pairwise
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_SITES = HERE / "sites.txt"

ORACLE = r"""
import sys, json
from playwright.sync_api import sync_playwright
url, out = sys.argv[1], sys.argv[2]
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1440, "height": 900}, user_agent=UA)
    pg.goto(url, wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(2500)
    for sel in ("button:has-text('Accept all')", "button:has-text('Accept All')", "button:has-text('I agree')", "button:has-text('Accept')", "#onetrust-accept-btn-handler"):
        try:
            loc = pg.locator(sel).first
            if loc.is_visible(timeout=500):
                loc.click(timeout=2000); pg.wait_for_timeout(1000); break
        except Exception:
            pass
    VIEW = '''() => {
      const vis = el => { const s = getComputedStyle(el); const r = el.getBoundingClientRect(); return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0; };
      const lines = [];
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      let n;
      while ((n = walker.nextNode())) { const t = n.textContent.trim(); if (t.length >= 25 && n.parentElement && vis(n.parentElement) && !['SCRIPT','STYLE','NOSCRIPT'].includes(n.parentElement.tagName)) lines.push(t.slice(0, 80)); }
      const count = (sel) => [...document.querySelectorAll(sel)].filter(vis).length;
      return { text: document.body.innerText, lines, headings: count('h1,h2,h3,h4,h5,h6'), tables: count('table'), lists: count('ul,ol'), images: count('img'), links: count('a[href]') };
    }'''
    # A frameset's own body has no text; the page a reader sees is its frames, in order.
    data = {"text": "", "lines": [], "headings": 0, "tables": 0, "lists": 0, "images": 0, "links": 0}
    for frame in pg.frames:
        try:
            part = frame.evaluate(VIEW)
        except Exception:
            continue
        data["text"] += ("\n" if data["text"] else "") + part["text"]
        data["lines"] += part["lines"]
        for k in ("headings", "tables", "lists", "images", "links"):
            data[k] += part[k]
    b.close()
json.dump(data, open(out, "w"))
"""

_WORD = re.compile(r"\w+")
_PUNCT = re.compile(r"[^\w\s]")
_SPACE = re.compile(r"\s+")


def _bag(text: str) -> Counter[str]:
    return Counter(_WORD.findall(text.lower()))


def _fold(text: str) -> str:
    return _SPACE.sub(" ", _PUNCT.sub("", text.lower()))


def _oracle(url: str, cache: Path) -> dict[str, Any]:
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [sys.executable, "-c", ORACLE, url, str(cache)],
            check=True,
            timeout=240,
            capture_output=True,
        )
    loaded: dict[str, Any] = json.loads(cache.read_text())
    return loaded


def _inversions(lines: list[str], ours: str) -> tuple[int, int]:
    """Page lines found in our text, and how many sit before a line that precedes them on
    the page. Each line is searched after the previous hit, so a phrase the page repeats
    is not an inversion; a line that never appears is not one either."""
    positions: list[int] = []
    cursor = 0
    for line in lines:
        needle = _fold(line)[:40]
        if not needle:
            continue
        hit = ours.find(needle, cursor)
        if hit < 0:
            hit = ours.find(needle)
            if hit < 0:
                continue
        positions.append(hit)
        cursor = max(cursor, hit)
    return len(positions), sum(1 for a, b in pairwise(positions) if b < a)


def _markdown_counts(markdown: str) -> dict[str, int]:
    # Lines inside code fences are not headings, whatever they start with; a quoted
    # table row still is a row.
    body: list[str] = []
    fenced = False
    for line in markdown.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            body.append(line.lstrip("> ").rstrip() if line.startswith(">") else line)
    text = "\n".join(body)
    return {
        "headings": len(re.findall(r"^#{1,6} ", text, flags=re.MULTILINE)),
        "table_rows": len(re.findall(r"^\|.*\|\s*$", text, flags=re.MULTILINE)),
        "list_items": len(re.findall(r"^\s*(?:[-*]|\d+\.) ", text, flags=re.MULTILINE)),
        "images": markdown.count("!["),
        "links": len(re.findall(r"\]\(http", markdown)),
    }


def run(sites: Path, out: Path) -> None:
    from webgraph.render_markdown import MarkdownOptions, to_markdown
    from webgraph.resolve import block_page_evidence, resolve_page

    pages_dir = out.with_suffix(out.suffix + ".pages")
    results: dict[str, dict[str, object]] = {}
    for line in sites.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, url = line.split(None, 1)
        started = time.time()
        try:
            oracle = _oracle(url, pages_dir / f"{name}.json")
            blocked = block_page_evidence(str(oracle["text"]))
            if blocked is not None:
                # The oracle got a wall, not the page; there is nothing to score against.
                # (The engine may still have got the page through the other fetch.)
                results[name] = {"url": url, "error": f"oracle blocked: {blocked[:120]}"}
                print(f"{name:14} ORACLE BLOCKED: {blocked[:90]}", flush=True)
                out.write_text(json.dumps(results, indent=1, ensure_ascii=False))
                continue
            resolved = resolve_page(url)
            document = resolved.document
            markdown = to_markdown(document, options=MarkdownOptions())
            page, ours = _bag(str(oracle["text"])), _bag(document.text)
            missing, extra = page - ours, ours - page
            found, inverted = _inversions([str(x) for x in oracle["lines"]], _fold(document.text))
            results[name] = {
                "url": url,
                "strategy": resolved.strategy.value,
                "render_error": resolved.render_error,
                "order": document.reading_order_method.value,
                "blocks": len(document.blocks),
                "page_words": sum(page.values()),
                "our_words": sum(ours.values()),
                "recall": round(1 - sum(missing.values()) / max(1, sum(page.values())), 3),
                "extra": round(sum(extra.values()) / max(1, sum(ours.values())), 3),
                "order_lines": found,
                "inversions": inverted,
                "dom": {k: oracle[k] for k in ("headings", "tables", "lists", "images", "links")},
                "md": _markdown_counts(markdown),
                "missing_top": missing.most_common(10),
                "extra_top": extra.most_common(10),
                "seconds": round(time.time() - started, 1),
            }
            r = results[name]
            print(
                f"{name:14} {r['strategy']:12} recall {r['recall']:.3f} extra {r['extra']:.3f} "
                f"inv {r['inversions']}/{r['order_lines']} blocks {r['blocks']}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001 -- a site failing must not stop the suite
            results[name] = {"url": url, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
            print(f"{name:14} ERROR {type(exc).__name__}: {str(exc)[:120]}", flush=True)
        out.write_text(json.dumps(results, indent=1, ensure_ascii=False))


def compare(base_path: Path, cand_path: Path) -> None:
    base = json.loads(base_path.read_text())
    cand = json.loads(cand_path.read_text())
    print(
        f"{'site':14} {'recall':>13} {'extra':>13} {'inversions':>11} {'blocks':>11}  structure (dom vs md: h/t/l/i/a)"
    )
    for name in base:
        if name not in cand or "error" in base[name] or "error" in cand[name]:
            print(f"{name:14} (error or missing on one side)")
            continue
        a, b = base[name], cand[name]
        moved = abs(b["recall"] - a["recall"]) >= 0.01 or abs(b["extra"] - a["extra"]) >= 0.02
        dom, md_a, md_b = b["dom"], a["md"], b["md"]
        structure = " ".join(
            f"{dom[d]}:{md_a[m]}->{md_b[m]}"
            for d, m in (
                ("headings", "headings"),
                ("tables", "table_rows"),
                ("lists", "list_items"),
                ("images", "images"),
                ("links", "links"),
            )
        )
        print(
            f"{name:14} {a['recall']:6.3f}->{b['recall']:<6.3f} {a['extra']:6.3f}->{b['extra']:<6.3f} "
            f"{a['inversions']:>4}->{b['inversions']:<5} {a['blocks']:>5}->{b['blocks']:<5} {structure}{'  <<' if moved else ''}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--sites", type=Path, default=DEFAULT_SITES)
    parser.add_argument("--out", type=Path, default=Path("fidelity.json"))
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("BASE", "CANDIDATE"))
    args = parser.parse_args()
    if args.compare:
        compare(*args.compare)
    else:
        run(args.sites, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
