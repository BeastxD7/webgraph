"""Adversarial run against creative and award-winning sites.

Why this is a different measurement
-----------------------------------
Every other benchmark here scores extracted text against a ground-truth main content. On a
creative site there is no such thing: an agency portfolio has no article, and a WebGL
showcase may have twelve words in the DOM and a thousand painted into a canvas.

So this measures **recovery** instead -- engine-extracted characters over the browser's own
`document.body.innerText` on the same rendered page. That comparison is fair in a way an F1
against a hand-labelled body is not, because both sides see exactly the same DOM at exactly
the same moment. A recovery near 1.0 means the engine saw what a reader sees. A low one means
the content is somewhere a DOM parser cannot follow, and the point of this run is to find out
*where*.

What it is looking for, specifically
------------------------------------
- **Canvas text.** `<canvas>` is deliberately not in `SKIP_TAGS` precisely so its presence can
  be reported: pixels are not recoverable without OCR, and the honest response is to say so.
- **Split-text animation.** Awwwards-style sites wrap every character in its own `<span>` to
  animate it. `normalize_text` should reassemble those; if it does not, words arrive shattered.
- **Scroll-mounted content.** A page that mounts sections on scroll shows a fraction of itself
  to a renderer that never scrolls.
- **SVG text.** `<svg>` is stripped, so `<text>` inside it is lost. Headline type on design
  sites is frequently SVG.
- **Shadow DOM and iframes**, which are counted rather than assumed.

Nothing here has a pass mark. The output is a ranked list of the worst recoveries with the
reason attached, which is the input to deciding what to fix next.

Usage
-----
    uv run --package webgraph python benchmark/creative/run.py
    uv run --package webgraph python benchmark/creative/run.py --limit 6 --json out.json
"""

from __future__ import annotations

import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Final

from webgraph.boilerplate import strip_landmarks
from webgraph.fetch.browser import shared_browser
from webgraph.fetch.render import RenderConfig, geometry_by_xpath, render_page
from webgraph.fetch.static import fetch_static
from webgraph.main_content import select_main_content
from webgraph.pipeline import build_document

DEFAULT_SITES: Final[Path] = Path(__file__).parent / "sites.txt"

_PROBE: Final[str] = r"""
() => {
  const t = (document.body && document.body.innerText || '').replace(/\s+/g, ' ').trim();
  const svgText = Array.from(document.querySelectorAll('svg text'))
    .map(n => (n.textContent || '').trim()).filter(Boolean).join(' ');
  let shadow = 0;
  const walk = (root) => {
    const w = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
    while (w.nextNode()) { const e = w.currentNode; if (e.shadowRoot) { shadow++; walk(e.shadowRoot); } }
  };
  try { walk(document.documentElement); } catch (e) {}
  // A page that splits words into one span per character for animation.
  let single = 0, spans = 0;
  for (const s of document.querySelectorAll('span')) {
    spans++;
    const v = (s.textContent || '').trim();
    if (v.length === 1) single++;
  }
  return {
    innerText: t.length,
    canvases: document.querySelectorAll('canvas').length,
    canvasArea: Array.from(document.querySelectorAll('canvas'))
      .reduce((a, c) => { const b = c.getBoundingClientRect(); return a + b.width * b.height; }, 0),
    iframes: document.querySelectorAll('iframe').length,
    svgTextChars: svgText.length,
    shadowRoots: shadow,
    spans: spans,
    singleCharSpans: single,
    scrollHeight: document.documentElement.scrollHeight,
    viewportHeight: window.innerHeight,
  };
}
"""


@dataclass
class SiteResult:
    url: str
    ok: bool = False
    error: str | None = None
    static_chars: int = 0
    rendered_chars: int = 0
    inner_text: int = 0
    blocks: int = 0
    main_chars: int = 0
    method: str = ""
    rects: int = 0
    bound: int = 0
    canvases: int = 0
    canvas_share: float = 0.0
    iframes: int = 0
    svg_text: int = 0
    shadow_roots: int = 0
    single_char_spans: int = 0
    pages_tall: float = 0.0
    flags: list[str] = field(default_factory=list)

    @property
    def recovery(self) -> float:
        return self.rendered_chars / self.inner_text if self.inner_text else 0.0


def probe(url: str) -> SiteResult:
    result = SiteResult(url=url)
    try:
        static = fetch_static(url)
        result.static_chars = len(static.html) if static.ok else 0

        rendered = render_page(url, config=RenderConfig(timeout_ms=45_000, settle_ms=1500))
        if not rendered.ok:
            result.error = rendered.error
            return result

        result.rects = len(rendered.rects)
        result.shadow_roots = rendered.shadow_roots

        document = build_document(
            rendered.html,
            rendered.url or url,
            geometry=geometry_by_xpath(rendered.html, rendered.rects),
        )
        result.bound = len(geometry_by_xpath(rendered.html, rendered.rects))
        result.blocks = len(document.blocks)
        result.rendered_chars = len(document.text)
        result.method = document.reading_order_method.value
        result.main_chars = sum(
            len(b.text) for b in select_main_content(strip_landmarks(list(document.blocks)))
        )
        result.ok = True
    except Exception as exc:  # noqa: BLE001 - a diagnostic must survive any page
        result.error = f"{type(exc).__name__}: {exc}"
        return result

    # Second visit purely to read the browser's own view, so the comparison is like for like.
    #
    # Through the engine's own thread-local browser, not a fresh `sync_playwright()`. The
    # engine already started one on this thread, and Playwright's sync API refuses a second
    # instance in the same thread -- "It looks like you are using Playwright Sync API inside
    # the asyncio loop". That failure is silent here (the probe just returns nothing), which
    # is how the first run of this benchmark reported five successful renders and zero usable
    # measurements.
    try:
        browser = shared_browser()
        if browser is None:
            result.flags.append("no browser slot for the probe")
            return result
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        try:
            page = context.new_page()
            page.goto(url, timeout=45_000, wait_until="load")
            page.wait_for_timeout(1500)
            observed = page.evaluate(_PROBE)
        finally:
            context.close()
    except Exception as exc:  # noqa: BLE001
        result.flags.append(f"probe failed: {type(exc).__name__}")
        return result

    result.inner_text = int(observed["innerText"])
    result.canvases = int(observed["canvases"])
    result.iframes = int(observed["iframes"])
    result.svg_text = int(observed["svgTextChars"])
    result.single_char_spans = int(observed["singleCharSpans"])
    viewport = float(observed["viewportHeight"]) or 900.0
    result.pages_tall = round(float(observed["scrollHeight"]) / viewport, 1)
    area = float(observed["canvasArea"])
    result.canvas_share = round(area / (1440 * 900), 2)

    if result.recovery < 0.75:
        result.flags.append("LOW RECOVERY")
    if result.canvases and result.canvas_share > 0.5:
        result.flags.append(f"canvas covers {result.canvas_share:.0%} of viewport")
    if result.svg_text > 200:
        result.flags.append(f"{result.svg_text} chars of SVG text (stripped)")
    if result.single_char_spans > 100:
        result.flags.append(f"{result.single_char_spans} single-char spans (split-text)")
    if result.iframes:
        result.flags.append(f"{result.iframes} iframe(s) (not extracted)")
    if result.inner_text and result.inner_text < 400:
        result.flags.append("almost no DOM text at all")
    if result.method == "dom-fallback":
        result.flags.append("no geometry used")
    return result


def report(results: list[SiteResult]) -> dict[str, Any]:
    ok = [r for r in results if r.ok and r.inner_text]
    failed = [r for r in results if not r.ok]

    print("\n" + "=" * 96)
    print("CREATIVE SITES -- recovery of the browser's own visible text")
    print("=" * 96)
    print(f"\n  probed {len(results)}   usable {len(ok)}   failed {len(failed)}")

    if ok:
        print(f"\n  {'site':<34}{'recov':>7}{'engine':>8}{'browser':>9}{'blocks':>7}"
              f"{'geom':>10}  notes")
        print("  " + "-" * 92)
        for r in sorted(ok, key=lambda r: r.recovery):
            host = re.sub(r"^https?://(www\.)?", "", r.url)[:33]
            geom = f"{r.bound}/{r.rects}" if r.rects else "-"
            print(f"  {host:<34}{r.recovery:>7.2f}{r.rendered_chars:>8}{r.inner_text:>9}"
                  f"{r.blocks:>7}{geom:>10}  {'; '.join(r.flags)[:44]}")

        mean = sum(r.recovery for r in ok) / len(ok)
        median = sorted(r.recovery for r in ok)[len(ok) // 2]
        print(f"\n  mean recovery   {mean:.3f}")
        print(f"  median recovery {median:.3f}")
        print(f"  below 0.75      {sum(1 for r in ok if r.recovery < 0.75)} of {len(ok)}")
        print(f"  below 0.50      {sum(1 for r in ok if r.recovery < 0.50)} of {len(ok)}")

        canvas = [r for r in ok if r.canvases]
        svg = [r for r in ok if r.svg_text > 200]
        split = [r for r in ok if r.single_char_spans > 100]
        print("\n  BLIND SPOTS PRESENT IN THIS CORPUS")
        print(f"    canvas elements        {len(canvas)} sites"
              f"  (text in pixels is unrecoverable without OCR)")
        print(f"    SVG text > 200 chars   {len(svg)} sites  (stripped by SKIP_TAGS)")
        print(f"    split-text animation   {len(split)} sites")
        print(f"    iframes                {sum(1 for r in ok if r.iframes)} sites")
        print(f"    shadow roots           {sum(1 for r in ok if r.shadow_roots)} sites")

    if failed:
        print("\n  FAILED TO RENDER")
        for r in failed:
            print(f"    {re.sub(r'^https?://(www.)?', '', r.url)[:44]:<46}{(r.error or '')[:44]}")

    return {
        "probed": len(results),
        "usable": len(ok),
        "mean_recovery": round(sum(r.recovery for r in ok) / len(ok), 4) if ok else None,
        "sites": [asdict(r) | {"recovery": round(r.recovery, 4)} for r in results],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sites", type=Path, default=DEFAULT_SITES)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    urls = [
        line.split("#")[0].strip()
        for line in args.sites.read_text(encoding="utf-8").splitlines()
        if line.split("#")[0].strip()
    ][: args.limit]

    print(f"probing {len(urls)} creative sites at concurrency {args.concurrency}")
    print("each site is rendered twice -- once through the engine, once to read the browser's")
    print("own innerText -- so this is slow by design.\n")

    started = time.monotonic()
    results: list[SiteResult] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        for index, result in enumerate(pool.map(probe, urls), start=1):
            marker = "  ok" if result.ok else "FAIL"
            print(f"  [{index:>2}/{len(urls)}] {marker}  "
                  f"{re.sub(r'^https?://(www.)?', '', result.url)[:52]}")
            results.append(result)
    print(f"\n  {time.monotonic() - started:.0f}s")

    payload = report(results)
    if args.json:
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\n  wrote {args.json}")


if __name__ == "__main__":
    main()
