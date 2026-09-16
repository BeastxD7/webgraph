"""Assert every route of the web app lays out on every device class.

Why this is a check and not a screenshot
---------------------------------------
Horizontal overflow is the most common responsive failure and the easiest to miss, because
a desktop browser simply does not show it. It also has a specific and recurring cause: a
grid or flex item defaults to `min-width: auto`, so it refuses to shrink below its widest
child. One `<pre>` in a two-column layout took the landing page to a document 467 pixels
wide inside a 390-pixel viewport, and nothing about the page looked wrong on a laptop.

So it is asserted, per route and per viewport, and two phone-only rules ride along:

  overflow   `document.scrollWidth` must not exceed `clientWidth`; the offenders are named
             with enough of their class list to find them.
  pinned     fixed and sticky elements (the header, a rail, a sheet) may not cover more
             than 35% of a phone's viewport height, measured at the top of the page and
             again once the page has scrolled, so the reader keeps the screen.
  text       body text (paragraphs, list items, table cells, form controls, links and
             buttons) is at least 14px on a phone. Captions and labels are held to 13px
             and 11px by the type scale (globals.css) and are exempt only when they are
             short: a paragraph of caption-sized prose is still a paragraph.

Tap targets under 44px are counted on phones and printed, but do not fail the run: the
docs shell is Fumadocs' own, and its breadcrumb and footer links are not ours to size.

A finding can be waived for one route and one rule (WAIVED below), never for a route as a
whole: overflow stays enforced everywhere. A waived finding prints as `waived` with its
reason and is counted apart from the passes, so it cannot be mistaken for one.

Screenshots of every route at every viewport are written under --out (full page), so the
run doubles as a contact sheet: `--theme dark` takes the same set in the dark theme.

Usage
-----
    make check-responsive                       # web app on :3000 (or WEBGRAPH_WEB_BASE)
    python tools/check_responsive.py --out /tmp/shots --theme both
    python tools/check_responsive.py --only docs,graph --sizes 320x568,768x1024
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

BASE: Final[str] = os.environ.get("WEBGRAPH_WEB_BASE", "http://localhost:3000")

# Every route. The run and report routes are opened without the API and render their
# error/empty state -- that state has to lay out too.
PAGES: Final[tuple[tuple[str, str], ...]] = (
    ("landing", "/"),
    ("products", "/products"),
    ("report", "/report"),
    ("report-domain", "/report/example.com"),
    ("watch", "/watch"),
    ("graph", "/graph"),
    (
        "run",
        "/extract?url=https%3A%2F%2Fwww.attrs.org%2Fen%2Fstable%2F&mode=site&complete=false&max=12",
    ),
    ("benchmarks", "/benchmarks"),
    ("how-it-works", "/how-it-works"),
    ("settings", "/settings"),
    ("docs", "/docs"),
    ("docs-start", "/docs/getting-started"),
    ("docs-table", "/docs/api/errors"),  # the widest tables in the docs
    ("docs-code", "/docs/api/text"),  # the longest code lines in the docs
)

SIZES: Final[tuple[tuple[str, int, int], ...]] = (
    ("phone-320", 320, 568),
    ("phone-390", 390, 844),
    ("phone-430", 430, 932),
    ("tablet-768", 768, 1024),
    ("tablet-1024", 1024, 768),
    ("laptop-1280", 1280, 720),
    ("desktop-1440", 1440, 900),
    ("desktop-1920", 1920, 1080),
    ("short-1440", 1440, 640),
)

# (route, rule) -> why. The landing's story stage (components/landing/Stage.tsx) is sticky by
# design on phones and its chapter notes are set in caption size; both belong to the landing
# owner and are recorded here rather than silently passed. Remove the entry when they are
# fixed, and the rule takes over again.
WAIVED: Final[dict[tuple[str, str], str]] = {
    ("landing", "pinned"): "story stage is sticky on phones by design (components/landing, PR #107)",
    ("landing", "text"): "chapter notes are text-caption prose (components/landing, PR #107)",
}

PHONE_MAX_WIDTH: Final[int] = 480
PINNED_MAX_RATIO: Final[float] = 0.35
BODY_MIN_PX: Final[float] = 14.0
TAP_MIN_PX: Final[float] = 44.0

# What counts as a phone: a touch screen with a coarse pointer, so `pointer-coarse:`
# utilities apply and the tap-target count means something.
PHONE_CONTEXT: Final[dict[str, object]] = {"has_touch": True, "is_mobile": True}

OVERFLOW_JS: Final[str] = """() => ({
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

# The share of the viewport's height under fixed/sticky elements: the union of their
# on-screen vertical extents. A pinned element inside another pinned element is the same
# pixels and is not counted twice.
PINNED_JS: Final[str] = """() => {
    const H = document.documentElement.clientHeight;
    const W = document.documentElement.clientWidth;
    const spans = [];
    const names = [];
    for (const el of document.querySelectorAll('*')) {
        const pos = getComputedStyle(el).position;
        if (pos !== 'fixed' && pos !== 'sticky') continue;
        let nested = false;
        for (let node = el.parentElement; node; node = node.parentElement) {
            const p = getComputedStyle(node).position;
            if (p === 'fixed' || p === 'sticky') { nested = true; break; }
        }
        if (nested) continue;
        const box = el.getBoundingClientRect();
        if (box.width < W * 0.5 || box.height < 1) continue;  // a rail or a chip, not a bar
        const top = Math.max(0, box.top), bottom = Math.min(H, box.bottom);
        if (bottom <= top) continue;
        if (getComputedStyle(el).visibility === 'hidden' || getComputedStyle(el).opacity === '0') continue;
        spans.push([top, bottom]);
        names.push(el.tagName + '.' + String(el.className).slice(0, 50) + ' ' + Math.round(bottom - top) + 'px');
    }
    spans.sort((a, b) => a[0] - b[0]);
    let covered = 0, cursor = -1;
    for (const [top, bottom] of spans) {
        const start = Math.max(top, cursor);
        if (bottom > start) covered += bottom - start;
        cursor = Math.max(cursor, bottom);
    }
    return { ratio: covered / H, names };
}"""

# Body text under the minimum. Short caption/label text is exempt (the type scale sets
# them at 13px and 11px on purpose); anything longer is prose and is not.
TEXT_JS: Final[str] = """(minPx) => {
    const SEL = 'p, li, td, th, dd, dt, blockquote, summary, label, input, textarea, select, button, a';
    const bad = [];
    for (const el of document.querySelectorAll(SEL)) {
        const style = getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') continue;
        const box = el.getBoundingClientRect();
        if (box.width === 0 || box.height === 0) continue;
        const text = (el.tagName === 'INPUT' ? (el.value || el.placeholder) : el.textContent || '').trim();
        if (!text) continue;
        const px = parseFloat(style.fontSize);
        if (px >= minPx) continue;
        // Caption (13px) and label (11px) sizes are the type scale's own; they hold for a
        // short line -- a source, a note, a chip -- not for prose.
        if (px >= 12.9 && text.length <= 80) continue;
        if (px >= 10.9 && text.length <= 40 && style.textTransform === 'uppercase') continue;
        bad.push(el.tagName + '.' + String(el.className).slice(0, 50) + ' ' + px.toFixed(1) + 'px "' + text.slice(0, 40) + '"');
    }
    return bad;
}"""

# Interactive elements a thumb cannot hit. Counted, not failed.
TAP_JS: Final[str] = """(minPx) => {
    const SEL = 'a[href], button, input, select, textarea, summary, [role="button"], [role="tab"]';
    const small = [];
    for (const el of document.querySelectorAll(SEL)) {
        const style = getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') continue;
        const box = el.getBoundingClientRect();
        if (box.width === 0 || box.height === 0) continue;
        // Inline links inside prose are exempt: WCAG 2.5.8 excludes text-flow targets.
        if (style.display === 'inline' && el.closest('p, li, td, dd')) continue;
        if (box.height < minPx && box.width < minPx) {
            small.push(el.tagName + '.' + String(el.className).slice(0, 40) + ' ' + Math.round(box.width) + 'x' + Math.round(box.height));
        } else if (box.height < 24 || box.width < 24) {
            small.push(el.tagName + '.' + String(el.className).slice(0, 40) + ' ' + Math.round(box.width) + 'x' + Math.round(box.height));
        }
    }
    return small;
}"""


@dataclass
class Result:
    size: str
    page: str
    width: int
    scroll_width: int
    client_width: int
    pinned: float
    text_bad: int
    taps: int
    problems: list[str]
    waived: list[str]

    @property
    def ok(self) -> bool:
        return not self.problems


def parse_sizes(spec: str | None) -> tuple[tuple[str, int, int], ...]:
    if not spec:
        return SIZES
    out = []
    for token in spec.split(","):
        w, h = token.lower().split("x")
        out.append((f"{int(w)}x{int(h)}", int(w), int(h)))
    return tuple(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=None, help="directory for full-page screenshots")
    parser.add_argument("--theme", choices=("light", "dark", "both"), default="light")
    parser.add_argument("--only", default=None, help="comma-separated page names to check")
    parser.add_argument("--sizes", default=None, help="comma-separated WxH viewports (default: the matrix)")
    parser.add_argument("--verbose", action="store_true", help="name every offending element, not the first six")
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    pages = PAGES if not args.only else tuple(p for p in PAGES if p[0] in args.only.split(","))
    sizes = parse_sizes(args.sizes)
    themes = ("light", "dark") if args.theme == "both" else (args.theme,)

    results: list[Result] = []
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        for theme in themes:
            for label, width, height in sizes:
                phone = width <= PHONE_MAX_WIDTH
                for name, path in pages:
                    context = browser.new_context(
                        viewport={"width": width, "height": height},
                        color_scheme=theme,
                        **(PHONE_CONTEXT if phone else {}),
                    )
                    # Both theme switches (the site's own and next-themes under /docs) read
                    # the same key, so one line puts every page in the theme under test.
                    context.add_init_script(
                        f"try{{localStorage.setItem('theme',{theme!r})}}catch(e){{}}"
                    )
                    page = context.new_page()
                    try:
                        page.goto(f"{BASE}{path}", wait_until="load", timeout=60_000)
                    except Exception as exc:
                        print(f"{label:13s} {name:14s} could not load: {exc}", file=sys.stderr)
                        results.append(Result(label, name, width, 0, 0, 0, 0, 0, ["could not load"], []))
                        context.close()
                        continue
                    # The run and report views ask the API and settle into their error state
                    # once it answers (or refuses); everything else has settled once fonts and
                    # scripts are in.
                    if name in ("run", "report-domain"):
                        try:
                            page.wait_for_selector("[role=alert]", timeout=8_000)
                        except Exception:
                            pass
                        page.wait_for_timeout(600)
                    else:
                        page.wait_for_timeout(1_200)

                    problems: list[str] = []
                    waived: list[str] = []

                    def report(rule: str, message: str) -> None:
                        reason = WAIVED.get((name, rule))
                        if reason:
                            waived.append(f"{message} -- waived: {reason}")
                        else:
                            problems.append(message)

                    overflow = page.evaluate(OVERFLOW_JS)
                    if overflow["scrollWidth"] > overflow["clientWidth"] + 2:
                        report(
                            "overflow",
                            f"overflow {overflow['scrollWidth']}/{overflow['clientWidth']}: "
                            + ", ".join(overflow["culprits"]),
                        )

                    pinned = 0.0
                    text_bad = 0
                    taps = 0
                    if phone:
                        top = page.evaluate(PINNED_JS)
                        page.evaluate("() => window.scrollTo(0, Math.round(innerHeight * 1.5))")
                        page.wait_for_timeout(400)
                        scrolled = page.evaluate(PINNED_JS)
                        page.evaluate("() => window.scrollTo(0, 0)")
                        page.wait_for_timeout(300)
                        worst = max((top, scrolled), key=lambda m: m["ratio"])
                        pinned = worst["ratio"]
                        if pinned > PINNED_MAX_RATIO:
                            report(
                                "pinned",
                                f"pinned {pinned:.0%} of the viewport: " + ", ".join(worst["names"]),
                            )
                        small_text = page.evaluate(TEXT_JS, BODY_MIN_PX)
                        text_bad = len(small_text)
                        if small_text:
                            report(
                                "text",
                                f"{text_bad} text element(s) under {BODY_MIN_PX:g}px: "
                                + "; ".join(small_text if args.verbose else small_text[:6]),
                            )
                        taps = len(page.evaluate(TAP_JS, TAP_MIN_PX))

                    if args.out:
                        folder = args.out / theme
                        folder.mkdir(parents=True, exist_ok=True)
                        try:
                            page.screenshot(path=str(folder / f"{name}--{label}.png"), full_page=True)
                        except Exception as exc:  # a WebGL canvas can refuse a full-page capture
                            print(f"{label:13s} {name:14s} screenshot failed: {exc}", file=sys.stderr)

                    results.append(
                        Result(
                            f"{label}{'' if theme == 'light' else ' (dark)'}",
                            name,
                            width,
                            overflow["scrollWidth"],
                            overflow["clientWidth"],
                            pinned,
                            text_bad,
                            taps,
                            problems,
                            waived,
                        )
                    )
                    context.close()
        browser.close()

    print(f"{'viewport':20s} {'route':14s} {'doc/view':>11s} {'pinned':>7s} {'<14px':>6s} {'<44px':>6s}  status")
    print("-" * 78)
    for r in results:
        status = "FAIL" if not r.ok else "waived" if r.waived else "ok"
        pinned = f"{r.pinned:.0%}" if r.width <= PHONE_MAX_WIDTH else "-"
        text = str(r.text_bad) if r.width <= PHONE_MAX_WIDTH else "-"
        taps = str(r.taps) if r.width <= PHONE_MAX_WIDTH else "-"
        print(
            f"{r.size:20s} {r.page:14s} {r.scroll_width:>5}/{r.client_width:<5} {pinned:>7s} {text:>6s} {taps:>6s}  {status}"
        )
        for problem in r.problems + r.waived:
            print(f"{'':20s} {'':14s} {problem}")

    failures = sum(1 for r in results if not r.ok)
    waived = sum(1 for r in results if r.ok and r.waived)
    print()
    if failures:
        print(f"{failures} of {len(results)} route x viewport checks failed", file=sys.stderr)
    else:
        print(f"all {len(results)} route x viewport checks passed" + (f" ({waived} waived, see WAIVED)" if waived else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
