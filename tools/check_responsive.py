"""Assert the web app does not scroll sideways at phone and tablet widths.

Why this is a check and not a screenshot
---------------------------------------
Horizontal overflow is the most common responsive failure and the easiest to miss, because
a desktop browser simply does not show it. It also has a specific and recurring cause: a
grid or flex item defaults to `min-width: auto`, so it refuses to shrink below its widest
child. One `<pre>` in a two-column layout took the landing page to a document 467 pixels
wide inside a 390-pixel viewport, and nothing about the page looked wrong on a laptop.

So it is asserted. `document.scrollWidth` must not exceed `clientWidth`, and when it does
the offending elements are named with enough of their class list to find them.

Usage
-----
    make check-responsive          # with the web app running on :3000
"""

from __future__ import annotations

import sys
from typing import Final

BASE: Final[str] = "http://localhost:3000"

PAGES: Final[tuple[tuple[str, str], ...]] = (
    ("landing", f"{BASE}/"),
    (
        "run",
        f"{BASE}/extract?url=https%3A%2F%2Fwww.attrs.org%2Fen%2Fstable%2F"
        "&mode=site&complete=false&max=12",
    ),
)

SIZES: Final[tuple[tuple[str, int, int], ...]] = (
    ("phone", 390, 844),
    ("phone-small", 320, 720),
    ("tablet", 768, 1024),
)

MEASURE: Final[str] = """() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    culprits: Array.from(document.querySelectorAll('*'))
        .filter((el) => {
            const box = el.getBoundingClientRect();
            if (box.right <= document.documentElement.clientWidth + 2) return false;
            // Skip anything a clipping ancestor already contains: a decorative image scaled
            // past its frame is not why the document scrolls.
            for (let node = el.parentElement; node; node = node.parentElement) {
                const style = getComputedStyle(node);
                if (style.overflowX !== 'visible') return false;
            }
            return true;
        })
        .slice(0, 8)
        .map((el) => el.tagName + '.' + String(el.className).slice(0, 70)),
})"""


def main() -> int:
    from playwright.sync_api import sync_playwright

    failures = 0
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        for label, width, height in SIZES:
            for name, url in PAGES:
                context = browser.new_context(viewport={"width": width, "height": height})
                page = context.new_page()
                try:
                    page.goto(url, wait_until="load", timeout=60_000)
                except Exception as exc:
                    print(f"{label:12s} {name:8s} could not load: {exc}", file=sys.stderr)
                    failures += 1
                    context.close()
                    continue
                page.wait_for_timeout(9_000 if name == "run" else 1_500)

                metrics = page.evaluate(MEASURE)
                overflowing = metrics["scrollWidth"] > metrics["clientWidth"] + 2
                status = "OVERFLOW" if overflowing else "ok"
                print(
                    f"{label:12s} {name:8s} {width:>4}px  "
                    f"{metrics['scrollWidth']:>5} / {metrics['clientWidth']:<5} {status}"
                )
                if overflowing:
                    failures += 1
                    for culprit in metrics["culprits"]:
                        print(f"             {culprit}")
                context.close()
        browser.close()

    if failures:
        print(f"\n{failures} viewport(s) scroll sideways", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
