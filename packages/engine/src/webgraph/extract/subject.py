"""Which structured-data node this page is *about*.

A page ships several. A product page from a WordPress shop typically carries `Organization`,
`WebSite`, `WebPage`, `BreadcrumbList` and `Product`, each a complete JSON-LD node with its
own `name`. Asked for "the name", the mapper in `schema.py` matches `Organization.name` and
`Product.name` identically — same key, same depth, same confidence — and `Fact.outranks`
breaks the tie with a strict `>`, so the winner is whichever `<script>` the page happened to
put first.

That is not a subtle tie-break. Measured across 2,008 human-labelled pages, `Organization`
supplies the winning name on **46% of category pages** and 15% of product pages. The values
it produces are exactly as wrong as they sound: `"IKEA"` where the page says "Shelving
furniture", `"Skullcandy"` where it says "Crusher ANC 2", `"Death Wish Coffee"` where it says
"Dark Roast Coffee".

Nor can document order be salvaged as a heuristic, because the two most-installed WordPress
SEO plugins disagree about it. Yoast emits the subject node **first**
(`Article, WebPage, ImageObject, BreadcrumbList, WebSite, Organization, Person`); Rank Math
emits it **last** (`Organization, WebSite, ImageObject, BreadcrumbList, WebPage, Person,
BlogPosting`). Which plugin a site installed is not evidence about which node describes the
page.

So the node is chosen by type, before any mapping happens, using the page type the router
already determined. Measured effect on titles: wrong values fall from 26.3% to 11.4%, and
what they become is *missing*, not right — the trade this codebase asks for everywhere else.
A page that declines to answer can be escalated; a page that answers wrongly poisons
everything built on it.

`select_subject` is a pre-step a caller runs, not something `extract_facts` does internally:
the mapper stays a general JSON-Schema binder that knows nothing about schema.org, and a
caller with their own payloads and their own schema is unaffected.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Final
from urllib.parse import urlsplit

from webgraph.pagetype import PageType
from webgraph.types import PayloadSource, StructuredPayload

__all__ = [
    "NEVER_SUBJECT",
    "SUBJECT_TYPES",
    "node_types",
    "select_subject",
    "subject_tiers",
]

SUBJECT_TYPES: Final[dict[PageType, frozenset[str]]] = {
    PageType.ARTICLE: frozenset(
        {
            "Article",
            "NewsArticle",
            "BlogPosting",
            "TechArticle",
            "ScholarlyArticle",
            "Report",
            "Review",
            "HowTo",
            "Recipe",
            "LiveBlogPosting",
            "AdvertiserContentArticle",
            # Medium marks every post as `SocialMediaPosting`, the parent type of
            # `DiscussionForumPosting`. It is in both sets on purpose: the page type
            # decides which reading applies, and the `@type` alone never does.
            "SocialMediaPosting",
        }
    ),
    PageType.PRODUCT: frozenset({"Product", "ProductGroup", "IndividualProduct", "SomeProducts"}),
    PageType.FORUM: frozenset(
        {"DiscussionForumPosting", "SocialMediaPosting", "QAPage", "Question"}
    ),
    # The only page type whose subject is the *site's* owner rather than the page. A
    # marketing page has no page-level node in practice: `Organization` is what is there,
    # and a company profile is the honest thing to return for it.
    PageType.SERVICE: frozenset(
        {
            "Service",
            "ProfessionalService",
            "LocalBusiness",
            "Organization",
            "Corporation",
            "SoftwareApplication",
            "WebApplication",
        }
    ),
    PageType.COLLECTION: frozenset(
        {"CollectionPage", "ItemList", "OfferCatalog", "ProductCollection", "SomeProducts"}
    ),
    PageType.LISTING: frozenset({"ItemList", "CollectionPage", "SearchResultsPage"}),
    PageType.DOCUMENTATION: frozenset({"TechArticle", "APIReference", "Article", "HowTo"}),
}
"""The `@type`s that can legitimately be what a page of each type is about.

Tighter than a permissive reading of schema.org, deliberately. Every extra type admitted
here is another chance to bind a value from a node describing something else, and the
measurements say that trade never pays: the types outside these sets contributed wrong
answers, not right ones."""

NEVER_SUBJECT: Final[frozenset[str]] = frozenset(
    {
        "BreadcrumbList",
        "WebSite",
        "SiteNavigationElement",
        "Organization",
        "Corporation",
        "LocalBusiness",
        "Person",
        "ImageObject",
        "WPHeader",
        "WPFooter",
        "ListItem",
        "ReadAction",
        "SearchAction",
        "Comment",
        "Blog",
        "VideoObject",
    }
)
"""Nodes that describe the site, its author or its furniture — never the page.

`SUBJECT_TYPES` wins over this, which is how `service` keeps `Organization` while every
other page type rejects it. `Comment` earns its place here from the forum measurements: 212
`Comment` nodes across 91 forum pages, winning the name on 16% of them — a reply's text
reported as the thread's title."""

_FALLBACK_TYPES: Final[frozenset[str]] = frozenset({"WebPage", "ItemPage", "CollectionPage"})
"""Generic page wrappers. Usable only when nothing specific matched.

`WebPage` won the naive name race on 15-30% of article, service and listing pages, and its
`name` is whatever the CMS put in the `<title>` — sometimes the page's title, often the
site's. It is a last resort, never a competitor to a specific type."""

_STRUCTURED: Final[tuple[PayloadSource, ...]] = (PayloadSource.JSON_LD, PayloadSource.MICRODATA)
"""The two sources that carry `@type` at all.

Microdata is not a fallback here. On forum pages it is present more often than JSON-LD (76%
against 62%), and two of the four major forum platforms — Discourse and Stack Exchange —
publish JSON-LD for *site identity only* and put the actual discussion in microdata. A
reader of JSON-LD alone gets the site's name and none of its content."""


def node_types(data: Any) -> set[str]:
    """The `@type`s a node declares, as bare names.

    Microdata records the type as a full URL (`http://schema.org/Product`), JSON-LD as a
    bare name, and either may hold a list. All three arrive here as `{"Product"}`.
    """
    if not isinstance(data, dict):
        return set()
    declared = data.get("@type") or data.get("type")
    values = declared if isinstance(declared, list) else [declared]
    return {
        str(value).rstrip("/").rsplit("/", 1)[-1]
        for value in values
        if isinstance(value, str | int | float) and str(value).strip()
    }


def _url_key(url: str) -> tuple[str, str]:
    """Host and path, normalised enough that two spellings of one address compare equal."""
    parts = urlsplit(url.split("#")[0])
    return (parts.netloc.lower().removeprefix("www."), parts.path.rstrip("/").lower())


def _self_references(data: dict[str, Any], target: tuple[str, str]) -> bool:
    """Whether this node claims to be about the page at `target`.

    The strongest signal available when several nodes of the right type are present: a node
    carrying `"url": "<this page>"` is about this page, and one carrying another address is
    about something else it happens to mention.
    """
    candidates: list[Any] = [data.get("url"), data.get("@id")]
    main = data.get("mainEntityOfPage")
    if isinstance(main, str):
        candidates.append(main)
    elif isinstance(main, dict):
        candidates.append(main.get("@id") or main.get("url"))
    return any(
        isinstance(candidate, str) and _url_key(candidate) == target for candidate in candidates
    )


def subject_tiers(
    payloads: Iterable[StructuredPayload], page_type: PageType, url: str = ""
) -> tuple[list[StructuredPayload], list[StructuredPayload]]:
    """The nodes that describe this page, in two tiers: specific, then generic wrappers.

    Two tiers rather than one list because they answer differently. A `Product` or an
    `Article` node is *about* the page. A `WebPage` node is the CMS describing the URL it
    served, and its `name` is the `<title>` -- which is the article's title on many sites
    and "Acme Blog | Acme" on many others. Measured, using the generic tier only where the
    specific tier said nothing recovers most of the coverage the gate costs without
    bringing back the wrong answers, so the caller fills gaps with it rather than letting
    it compete.

    Returns a list rather than one payload because a page may legitimately split its subject
    across nodes — a `QAPage` wrapper and the `Question` inside it, a `Product` and its
    `Offer` — and because returning several preserves `merge_facts`' existing job of
    resolving them. It returns an **empty list** when nothing qualifies, which is the
    answer on the majority of collection and listing pages: 72-79% of them ship JSON-LD and
    only 16% ship a node that is about the page. The rest is breadcrumbs and site identity.

    `PageType.UNKNOWN` also returns nothing. A page the router could not type is a page
    whose subject set is unknown, and guessing one is how this function would reintroduce
    the problem it exists to remove.
    """
    wanted = SUBJECT_TYPES.get(page_type)
    if not wanted:
        return [], []

    structured = [
        payload
        for payload in payloads
        if payload.source in _STRUCTURED and isinstance(payload.data, dict)
    ]

    specific: list[StructuredPayload] = []
    fallback: list[StructuredPayload] = []
    for payload in structured:
        types = node_types(payload.data)
        if types & wanted:
            # `SUBJECT_TYPES` beats `NEVER_SUBJECT`: `service` wants the `Organization` that
            # every other page type refuses.
            specific.append(payload)
        elif types & _FALLBACK_TYPES and not (types & NEVER_SUBJECT):
            fallback.append(payload)

    return _narrow(specific, url), fallback


def _narrow(chosen: list[StructuredPayload], url: str) -> list[StructuredPayload]:
    """Among several nodes of the right type, prefer the one that names this page."""
    if len(chosen) <= 1 or not url:
        return chosen
    target = _url_key(url)
    matched = [payload for payload in chosen if _self_references(payload.data, target)]
    return matched or chosen


def select_subject(
    payloads: Iterable[StructuredPayload], page_type: PageType, url: str = ""
) -> list[StructuredPayload]:
    """The nodes that describe this page, generic wrappers included when nothing else did.

    The flat view of `subject_tiers`, for a caller that does not distinguish the two.
    """
    primary, fallback = subject_tiers(payloads, page_type, url)
    return primary or fallback


def subject_types_for(page_type: PageType) -> Sequence[str]:
    """The accepted `@type`s, sorted, for reporting to a reader who asks why."""
    return sorted(SUBJECT_TYPES.get(page_type, frozenset()))
