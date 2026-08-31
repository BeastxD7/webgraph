"""Route-discovery benchmark: does the engine find every route a real browser can see?

Method
------
For each site a real browser (Chromium via Playwright) loads the homepage, executes its
JavaScript, **interacts with it** -- hovering every nav trigger, expanding disclosure panels,
scrolling the full page for lazy content -- and reports every same-site anchor. That set is
the **oracle**: what a person exploring the front page could actually reach.

The interaction step is not optional. Measured on stripe.com, a static snapshot saw 112 links
and post-interaction saw 121: mega-menus populate on hover. An oracle without it under-reports,
and an engine scored against a weak oracle gets a free 100%.

The engine then discovers routes its own way. Recall against the oracle is the score.

Why a browser is the oracle: a static fetch cannot see JavaScript-rendered navigation.
Measured on persyn.ai, the browser found 12 on-site links and a static fetch found 5,
missing all 10 blog posts. Any discovery benchmark judged against static HTML would have
scored that as perfect.

The oracle is deliberately *homepage-only*. It bounds the comparison to something a browser
can establish in one page load, and keeps the benchmark fast enough to run often.

Usage
-----
    uv run python benchmark/route_discovery/run.py [--sites sites.txt] [--limit N]
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from webgraph.crawl.discovery import extract_links
from webgraph.crawl.frontier import (
    canonical_key,
    normalize_url,
    reconcile_scheme,
    same_site,
)
from webgraph.fetch.static import fetch_static
from webgraph.resolve import Strategy, resolve_page

HERE = Path(__file__).parent

_COLLECT_LINKS = """
() => {
  const host = location.hostname.replace(/^www\\./, '');
  const out = new Set();
  for (const a of document.querySelectorAll('a[href]')) {
    const href = a.href;
    if (!href || !href.startsWith('http')) continue;
    try {
      const u = new URL(href);
      if (u.hostname.replace(/^www\\./, '') !== host) continue;
      u.hash = '';
      out.add(u.href);
    } catch (e) {}
  }
  return [...out];
}
"""

_DEEP = """
async (maxSub) => {
  // Depth-2 discovery. The homepage is measured live (menus opened, lazy content scrolled),
  // then each nav target is fetched **same-origin from within the page** and its links read
  // too. Fetching rather than navigating keeps the whole sweep to one evaluation and avoids
  // losing the rendered homepage state.
  //
  // Homepage-only discovery badly under-reports: measured on render.com, 51 routes from the
  // front page became 169 after fetching 14 nav targets. An engine scored against the
  // shallower set gets a free pass on everything below the top level.
  const H = location.hostname.replace(/^www\\./,'');
  // `base` is the URL of the document the link was found in -- the homepage for level 1,
  // the sub-page for level 2. Resolving a fetched sub-page's relative links against the
  // homepage silently rewrites them: on scikit-learn.org a link `modules/foo.html` found at
  // /stable/getting_started.html became /modules/foo.html instead of /stable/modules/foo.html.
  // That produced two large, almost disjoint sets and scored the engine at 6% recall while
  // it was in fact correct.
  const same = (h, base) => { try { return new URL(h, base).hostname.replace(/^www\\./,'')===H } catch(e){ return false } };
  const norm = (h, base) => { const u = new URL(h, base); u.hash=''; return u.origin + u.pathname + u.search };

  const level1 = new Set([...document.querySelectorAll('a[href]')].map(a=>a.href)
    .filter(h=>h.startsWith('http')).filter(h=>same(h, location.href)).map(h=>norm(h, location.href)));

  const here = location.origin + location.pathname;
  // Sorted, so the oracle and the engine explore the *same* sub-pages. Picking in DOM order
  // on one side and alphabetically on the other measured which subset each happened to
  // choose rather than what either could discover: linear.app scored 70 "misses" that were
  // simply pages the engine never had budget to look at.
  const targets = [...level1].filter(u => u !== here).sort().slice(0, maxSub);
  const all = new Set(level1);
  let ok = 0, failed = 0;

  await Promise.all(targets.map(async u => {
    try {
      const res = await fetch(u, { credentials: 'omit', redirect: 'follow' });
      if (!res.ok) { failed++; return; }
      // Resolve against the URL actually fetched, following any redirect.
      const base = res.url || u;
      const doc = new DOMParser().parseFromString(await res.text(), 'text/html');
      for (const a of doc.querySelectorAll('a[href]')) {
        const href = a.getAttribute('href');
        if (href && same(href, base)) all.add(norm(href, base));
      }
      ok++;
    } catch (e) { failed++; }
  }));

  return { links: [...all], level1: level1.size, sub_ok: ok, sub_fail: failed };
}
"""

_REVEAL = """
async () => {
  // Surface links a single static snapshot cannot see: mega-menus that populate on hover,
  // disclosure panels that mount on click, and lazy content that loads on scroll.
  //
  // Measured on stripe.com: 112 links before interaction, 121 after opening the nav
  // dropdowns. An oracle that skips this under-reports, and an engine scored against it
  // gets a free 100%.
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));

  const triggers = document.querySelectorAll(
    'nav button, header button, [aria-haspopup], [aria-expanded], nav [role="button"], summary'
  );
  for (const el of triggers) {
    try {
      for (const type of ['pointerenter', 'mouseover', 'mouseenter', 'focus']) {
        el.dispatchEvent(new MouseEvent(type, { bubbles: true }));
      }
    } catch (e) {}
  }
  await sleep(600);

  // Open <details> without navigating.
  for (const d of document.querySelectorAll('details')) { try { d.open = true; } catch (e) {} }

  // Expand collapsed regions by attribute rather than by clicking: a click can navigate
  // away, which changes the page being measured.
  for (const el of document.querySelectorAll('[aria-expanded="false"]')) {
    try { el.setAttribute('aria-expanded', 'true'); } catch (e) {}
  }
  await sleep(400);

  // Scroll the full page to trigger lazy loading, then return to the top.
  const height = document.body.scrollHeight;
  for (let y = 0; y <= height; y += Math.max(600, Math.floor(height / 8))) {
    window.scrollTo(0, y);
    await sleep(250);
  }
  window.scrollTo(0, 0);
  await sleep(600);
  return true;
}
"""


@dataclass
class SiteResult:
    url: str
    oracle: set[str] = field(default_factory=set)
    static_only: set[str] = field(default_factory=set)
    engine: set[str] = field(default_factory=set)
    error: str | None = None
    seconds: float = 0.0

    # Sets are compared on `canonical_key`, not raw strings. solidjs.com redirects to
    # www.solidjs.com, so the oracle reports www URLs while the engine reports bare ones --
    # the same pages, scored as a total miss by string equality.
    @property
    def _oracle_keys(self) -> set[str]:
        return {canonical_key(u) for u in self.oracle}

    @property
    def _engine_keys(self) -> set[str]:
        return {canonical_key(u) for u in self.engine}

    @property
    def missed(self) -> set[str]:
        engine = self._engine_keys
        return {u for u in self.oracle if canonical_key(u) not in engine}

    @property
    def recall(self) -> float:
        oracle = self._oracle_keys
        if not oracle:
            return 1.0
        return len(oracle & self._engine_keys) / len(oracle)

    @property
    def static_recall(self) -> float:
        oracle = self._oracle_keys
        if not oracle:
            return 1.0
        static = {canonical_key(u) for u in self.static_only}
        return len(oracle & static) / len(oracle)


def browser_oracle(
    urls: list[str], *, timeout_ms: int = 45000, max_subpages: int = 14
) -> dict[str, set[str]]:
    """Discover each site's routes in a real browser, two levels deep."""
    found: dict[str, set[str]] = {}

    with sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            for url in urls:
                page = context.new_page()
                try:
                    # `domcontentloaded` first, not `load`. Sites holding long-lived
                    # connections (analytics beacons, websockets, video preload) never fire
                    # `load`, and waiting for it timed out on neon.tech and
                    # docs.pydantic.dev -- both of which serve 200 with full navigation and
                    # were wrongly recorded as unreachable. The settle below does the real
                    # work of waiting for hydration.
                    page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                    with contextlib.suppress(Exception):
                        page.wait_for_load_state("load", timeout=8000)
                    page.wait_for_timeout(1800)

                    collected: set[str] = set()

                    def harvest(
                        active: Page = page,
                        sink: set[str] = collected,
                    ) -> None:
                        # Loop variables are bound as defaults: the closure would otherwise
                        # capture the last page in the loop, not this one.
                        for raw in active.evaluate(_COLLECT_LINKS):
                            resolved = normalize_url(reconcile_scheme(raw, active.url))
                            # Scope against the landed URL, not the requested one.
                            if resolved and same_site(resolved, active.url):
                                sink.add(resolved)

                    harvest()
                    before = len(collected)
                    # A page that refuses interaction still yields its static links.
                    with contextlib.suppress(Exception):
                        page.evaluate(_REVEAL)
                    harvest()
                    revealed = len(collected) - before

                    deep_note = ""
                    try:
                        deep = page.evaluate(_DEEP, max_subpages)
                        for raw in deep["links"]:
                            resolved = normalize_url(reconcile_scheme(raw, page.url))
                            if resolved and same_site(resolved, page.url):
                                collected.add(resolved)
                        deep_note = f", depth-2 +{len(collected) - before - revealed} from {deep['sub_ok']} sub-pages"
                    except Exception as exc:
                        deep_note = f", depth-2 failed ({type(exc).__name__})"

                    print(
                        f"  {url}: {len(collected)} routes (+{revealed} by interaction{deep_note})",
                        file=sys.stderr,
                    )
                    found[url] = collected
                except Exception as exc:
                    print(f"  oracle failed for {url}: {type(exc).__name__}", file=sys.stderr)
                    found[url] = set()
                finally:
                    page.close()
        finally:
            browser.close()
    return found


def engine_links(
    url: str, *, complete: bool = True, max_pages: int = 15
) -> tuple[set[str], set[str]]:
    """Return (engine routes, static-only routes).

    The engine runs its real crawl rather than reading one page, because the oracle now goes
    two levels deep. Comparing a depth-2 oracle against a depth-1 engine would measure the
    mismatch, not the engine.
    """
    url = _effective(url)
    static_links: set[str] = set()
    result = fetch_static(url)
    seed_for_static = normalize_url(result.url if result.ok else url)
    if result.ok and result.is_html:
        parsed = extract_links(result.html, result.url)
        static_links = {
            n
            for raw in parsed.links
            if (n := normalize_url(reconcile_scheme(raw, url), base=result.url))
            and same_site(n, url)
        }
        if seed_for_static:
            static_links.add(seed_for_static)

    # The seed is the URL *after* redirects. flask.palletsprojects.com/ redirects to
    # /en/stable/, and the browser reports the redirected URL; seeding with the requested
    # one scored a miss for a page the crawl obviously starts on.
    seed = normalize_url(result.url if result.ok else url)
    engine: set[str] = set(static_links) | ({seed} if seed else set())
    if not complete:
        return engine, static_links

    # Level 1: the homepage, resolved the way the engine really does it (static + rendered,
    # unioned).
    try:
        resolved = resolve_page(url, strategy=Strategy.UNION)
        document = resolved.document
        parsed = extract_links(document.html, document.url)
        engine |= {
            n
            for raw in parsed.links
            if (n := normalize_url(reconcile_scheme(raw, url), base=document.url))
            and same_site(n, url)
        }
    except Exception as exc:
        print(f"  engine level-1 failed for {url}: {type(exc).__name__}", file=sys.stderr)
        return engine, static_links

    # Level 2: fetch the same number of sub-pages the oracle does, and harvest their links.
    # The oracle fetches sub-pages statically (its in-page `fetch` returns raw HTML), so the
    # engine does too -- otherwise the comparison measures budget, not capability.
    seed_path = seed or url
    targets = [u for u in sorted(engine) if u != seed_path][:max_pages - 1]

    def harvest_sub(target: str) -> set[str]:
        try:
            sub = fetch_static(target)
            if not sub.ok or not sub.is_html:
                return set()
            found = extract_links(sub.html, sub.url)
            return {
                n
                for raw in found.links
                if (n := normalize_url(reconcile_scheme(raw, url), base=sub.url))
                and same_site(n, url)
            }
        except Exception:
            return set()

    with ThreadPoolExecutor(max_workers=6) as pool:
        for extra in pool.map(harvest_sub, targets):
            engine |= extra

    return engine, static_links


def _effective(url: str) -> str:
    """The URL a site actually serves, after redirects.

    Both sides must scope on it. docs.pydantic.dev/latest/ lands on pydantic.dev/..., and
    scoping on the requested host rejected every link as off-site.
    """
    from webgraph.site import resolve_root

    try:
        return resolve_root(url)
    except Exception:
        return url


def run(sites: list[str], *, workers: int = 3, max_subpages: int = 14) -> list[SiteResult]:
    print(
        f"Collecting depth-2 browser oracle for {len(sites)} sites "
        f"(homepage + up to {max_subpages} sub-pages each)...",
        file=sys.stderr,
    )
    oracle = browser_oracle(sites, max_subpages=max_subpages)

    def one(url: str) -> SiteResult:
        started = time.monotonic()
        row = SiteResult(url=url, oracle=oracle.get(url, set()))
        try:
            row.engine, row.static_only = engine_links(url)
        except Exception as exc:
            row.error = f"{type(exc).__name__}: {exc}"
        row.seconds = time.monotonic() - started
        return row

    print("Running engine discovery...", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, sites))


def report(rows: list[SiteResult]) -> str:
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("ROUTE DISCOVERY BENCHMARK   engine vs real-browser oracle")
    lines.append("=" * 78)
    lines.append("")
    lines.append(f"  {'site':<34} {'oracle':>7} {'engine':>7} {'recall':>8} {'static':>8}")
    lines.append("  " + "-" * 68)

    scored = [r for r in rows if r.oracle]
    for row in sorted(rows, key=lambda r: r.recall):
        host = row.url.split("//")[-1].rstrip("/")[:33]
        if not row.oracle:
            lines.append(f"  {host:<34} {'-':>7} {'-':>7} {'no oracle':>8}")
            continue
        flag = "" if row.recall >= 0.99 else "  <-- GAP"
        lines.append(
            f"  {host:<34} {len(row.oracle):>7} {len(row.engine):>7} "
            f"{row.recall:>7.0%} {row.static_recall:>7.0%}{flag}"
        )

    if scored:
        mean_recall = sum(r.recall for r in scored) / len(scored)
        mean_static = sum(r.static_recall for r in scored) / len(scored)
        perfect = sum(1 for r in scored if r.recall >= 0.99)
        lines.append("")
        lines.append(f"  sites scored          {len(scored)}")
        lines.append(f"  perfect recall        {perfect}/{len(scored)}")
        lines.append(f"  mean recall (engine)  {mean_recall:.1%}")
        lines.append(f"  mean recall (static)  {mean_static:.1%}   <- what static alone would score")

    gaps = [r for r in scored if r.recall < 0.99]
    if gaps:
        lines.append("")
        lines.append("MISSED ROUTES")
        lines.append("-" * 78)
        for row in gaps:
            lines.append(f"  {row.url}  ({len(row.missed)} missed)")
            for missed in sorted(row.missed)[:6]:
                lines.append(f"     {missed}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sites", default=str(HERE / "sites.txt"))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    sites = [
        line.strip()
        for line in Path(args.sites).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    if args.limit:
        sites = sites[: args.limit]

    rows = run(sites)

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "url": r.url,
                        "oracle": len(r.oracle),
                        "engine": len(r.engine),
                        "recall": round(r.recall, 4),
                        "static_recall": round(r.static_recall, 4),
                        "missed": sorted(r.missed)[:20],
                    }
                    for r in rows
                ],
                indent=2,
            )
        )
    else:
        print(report(rows))

    scored = [r for r in rows if r.oracle]
    return 0 if all(r.recall >= 0.99 for r in scored) else 1


if __name__ == "__main__":
    sys.exit(main())
