"""Stage 0: work out what a site is built with, and therefore how to read it.

The profile decides routing. A Next.js page should be read from its hydration payload; a
static Hugo page needs nothing but DOM pruning; a client-rendered SPA has no content at all
until JavaScript executes, and reading its static HTML yields an empty shell.

Confidence note: this layer is an **open question** (MEMORY.md Q2). No evidence in the
research pass supports any particular fingerprinting approach, and published rulesets are
known to lag new frameworks by many months. These rules are therefore treated as hints that
must be measured locally, never as ground truth -- and `requires_render` deliberately relies
on *behavioural* signals (an empty mount point, sparse text alongside script bundles) rather
than trusting the framework label.
"""

from __future__ import annotations

import re
from typing import Final, NamedTuple

from lxml.html import HtmlElement

from webgraph.profile.technology import RuntimeEvidence, detect_technologies
from webgraph.types import StackProfile

__all__ = ["FRAMEWORK_RULES", "profile_page"]


class Rule(NamedTuple):
    """A framework signature. `pattern` is matched against the raw HTML."""

    name: str
    pattern: re.Pattern[str]
    hint: str


def _rule(name: str, pattern: str, hint: str) -> Rule:
    return Rule(name, re.compile(pattern, re.IGNORECASE), hint)


FRAMEWORK_RULES: Final[tuple[Rule, ...]] = (
    _rule("next.js", r'id="__NEXT_DATA__"|/_next/static|self\.__next_f', "next payload or asset path"),
    _rule("nuxt", r"window\.__NUXT__|/_nuxt/", "nuxt payload or asset path"),
    _rule("gatsby", r"___gatsby|window\.___chunkMapping", "gatsby runtime marker"),
    _rule("sveltekit", r"__sveltekit_|data-sveltekit", "sveltekit marker"),
    _rule("astro", r"astro-island|data-astro-|<astro-", "astro island marker"),
    _rule("remix", r"__remixContext|window\.__remixManifest", "remix context"),
    _rule("angular", r"ng-version=|_nghost-|_ngcontent-", "angular component attributes"),
    _rule("vue", r"data-v-[0-9a-f]{6,}|__VUE__", "vue scoped-style attributes"),
    _rule("react", r"data-reactroot|__REACT_DEVTOOLS", "react root marker"),
    _rule("wordpress", r"/wp-content/|/wp-includes/|/wp-json/", "wordpress asset path"),
    _rule("drupal", r"drupal-settings-json|/sites/default/files/", "drupal settings"),
    _rule("ghost", r"content=\"Ghost [\d.]+\"|/ghost/api/", "ghost generator"),
    _rule("shopify", r"cdn\.shopify\.com|Shopify\.theme|/cdn/shop/", "shopify cdn"),
    _rule("woocommerce", r"woocommerce|wc-ajax", "woocommerce marker"),
    _rule("bigcommerce", r"cdn\d*\.bigcommerce\.com", "bigcommerce cdn"),
    _rule("webflow", r"data-wf-page|data-wf-site|webflow\.js", "webflow attributes"),
    _rule("wix", r"static\.wixstatic\.com|_wixCssImports", "wix static host"),
    _rule("squarespace", r"static1\.squarespace\.com|Static\.SQUARESPACE_CONTEXT", "squarespace context"),
    _rule("hugo", r'content="Hugo [\d.]+"', "hugo generator meta"),
    _rule("jekyll", r'content="Jekyll', "jekyll generator meta"),
    _rule("eleventy", r'content="Eleventy', "eleventy generator meta"),
    _rule("docusaurus", r"docusaurus\.config|__docusaurus", "docusaurus marker"),
)

_EMPTY_TEXT_CHARS: Final[int] = 50
"""Below this, the page has effectively no readable content and is always treated as a
shell -- a bot-challenge page, a redirect stub, or an unhydrated app. Never "complete"."""

_MIN_TEXT_CHARS: Final[int] = 600
"""Below this much visible text, a page is a likely shell when script bundles corroborate.
Raised from 200 after measurement: real shells routinely render a nav bar and footer,
which clears a low threshold while the actual content is still missing."""

_CONFIDENT_TEXT_CHARS: Final[int] = 2000
"""Above this, a page with a client-side router is assumed to have server-rendered its
content already. Below it, the router markers are treated as evidence of a partial render."""

_MIN_TEXT_RATIO: Final[float] = 0.006
"""Visible text as a fraction of raw HTML. A hydrated SPA shell is nearly all markup."""

_SPA_ROOT_IDS: Final[frozenset[str]] = frozenset({"root", "app", "__next", "___gatsby", "q-app"})

_SUBSTANTIAL_SCRIPT_CHARS: Final[int] = 500
"""An inline script this long is plausibly an application bundle rather than a tracking snippet."""


def profile_page(
    root: HtmlElement,
    html: str,
    *,
    text_length: int | None = None,
    headers: dict[str, str] | None = None,
    runtime: RuntimeEvidence | None = None,
    url: str = "",
) -> StackProfile:
    """Identify the stack and decide whether a JavaScript render is required.

    `text_length` should be the length of the text actually extracted from the page. Passing
    it lets the render decision use the real post-extraction figure rather than re-deriving
    it; when omitted it is computed from the tree.
    """
    frameworks: list[str] = []
    signals: list[str] = []

    for rule in FRAMEWORK_RULES:
        if rule.pattern.search(html):
            frameworks.append(rule.name)
            signals.append(f"{rule.name}: {rule.hint}")

    has_next_data = 'id="__NEXT_DATA__"' in html or "id='__NEXT_DATA__'" in html
    has_rsc_flight = "self.__next_f" in html
    has_nuxt = "window.__NUXT__" in html
    has_json_ld = bool(
        root.xpath(
            "//script[translate(@type,'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
            "'abcdefghijklmnopqrstuvwxyz')='application/ld+json']"
        )
    )
    has_microdata = bool(root.xpath("//*[@itemscope]"))

    if text_length is None:
        text_length = len(" ".join(root.text_content().split()))

    requires_render, render_signals = _needs_render(root, html, text_length)
    signals.extend(render_signals)

    evidence = runtime or RuntimeEvidence()
    technologies = detect_technologies(
        html,
        headers,
        dict(evidence.versions),
        custom_globals=evidence.custom_globals,
        requests=evidence.requests,
        cookies=evidence.cookies,
        bundle_source=evidence.bundle_source,
        url=url,
    )
    # The framework list stays the short client-side view; `technologies` is the full picture.
    for tech in technologies:
        if tech.category in {"JavaScript frameworks", "CMS", "Ecommerce", "Website builders",
                             "Static site generators"} and tech.name.lower() not in {
            f.lower() for f in frameworks
        }:
            frameworks.append(tech.name)

    return StackProfile(
        frameworks=tuple(dict.fromkeys(frameworks)),
        has_next_data=has_next_data,
        has_rsc_flight=has_rsc_flight,
        has_nuxt_payload=has_nuxt,
        has_json_ld=has_json_ld,
        has_microdata=has_microdata,
        requires_render=requires_render,
        signals=tuple(signals),
        technologies=tuple(
            {
                "name": t.name,
                "category": t.category,
                "version": t.version,
                "confidence": t.confidence,
                "evidence": t.evidence,
            }
            for t in technologies
        ),
    )


def _needs_render(root: HtmlElement, html: str, text_length: int) -> tuple[bool, list[str]]:
    """Decide whether the static HTML is the real content.

    **Biased hard toward rendering, deliberately.** Measured against 19 real sites, an
    earlier version of this function that tried to predict cheaply scored 0/7 -- it returned
    False on every page that actually lost content, including one holding 1.8% of its real
    text. The costs are wildly asymmetric: a missed render loses most of a page's content
    permanently, while an unnecessary render costs roughly 300ms and some memory. When the
    evidence is ambiguous, render.

    A hydration payload is NOT evidence that a render is unnecessary. `nextjs.org` ships a
    payload and zero visible text; the payload describes the page, but the readable content
    still only exists after hydration.
    """
    signals: list[str] = []

    # Rule 1: no text is never "complete". This is the case an earlier version got wrong --
    # it treated a zero-text bot-challenge page as a finished short page.
    if text_length < _EMPTY_TEXT_CHARS:
        signals.append(f"render required: only {text_length} chars of text -- page is a shell")
        return True, signals

    # Rule 2: an empty framework mount point declares where content will go and admits it
    # is not there yet.
    for element in root.xpath("//*[@id]"):
        element_id = (element.get("id") or "").lower()
        if element_id in _SPA_ROOT_IDS and not element.text_content().strip():
            signals.append(f"render required: empty SPA mount point #{element_id}")
            return True, signals

    has_app_scripts = bool(root.xpath("//script[@src]")) or any(
        len(s.text_content()) > _SUBSTANTIAL_SCRIPT_CHARS for s in root.xpath("//script[not(@src)]")
    )

    # Rule 3: sparse text alongside a script bundle. Kept, but the floor is now much higher,
    # because "short but complete" pages are rarer than shells that happen to render a nav bar.
    if text_length < _MIN_TEXT_CHARS and has_app_scripts:
        signals.append(f"render required: {text_length} chars of text alongside script bundles")
        return True, signals

    # Rule 4: markup dwarfs text. A hydrated shell is nearly all markup.
    ratio = text_length / max(len(html), 1)
    if ratio < _MIN_TEXT_RATIO and has_app_scripts:
        signals.append(f"render required: text/markup ratio {ratio:.4f} below {_MIN_TEXT_RATIO}")
        return True, signals

    # Rule 5: a client-side router with little content is a single-page app mid-navigation.
    if has_app_scripts and text_length < _CONFIDENT_TEXT_CHARS:
        for marker in ("__next_f", "__NUXT__", "__remixContext", "__sveltekit_", "___gatsby"):
            if marker in html:
                signals.append(
                    f"render required: {marker} present with only {text_length} chars of text"
                )
                return True, signals

    signals.append(f"static content looks complete ({text_length} chars)")
    return False, signals
