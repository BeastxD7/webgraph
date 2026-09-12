"""Count what a page's markup is made of, for the router.

One pass over the parsed tree, run at build time before block extraction strips it. The
result is a few dozen numbers that travel with the Document, so that the page-type router
can read them on a crawled page whose HTML has long since been dropped.

Every bucket vocabulary here was chosen by hand and then *kept* only because it moved a
domain-grouped cross-validation -- pages from one site never on both sides of a fold, so
none of this can be a site fingerprint in disguise. The alternative, a TF-IDF vocabulary
learned from the corpus, scored 0.4 points higher and its top terms were "coffee", "gym",
"headphones" and "insurance": topics, not page types. That is a model of what the corpus
happened to contain, and it is not shipped.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Final

from lxml.html import HtmlElement

from webgraph.types import MarkupStats

__all__ = ["CLASS_BUCKETS", "COUNTED_TAGS", "markup_stats"]

CLASS_BUCKETS: Final[dict[str, frozenset[str]]] = {
    "card": frozenset({"card", "cards", "tile", "tiles", "teaser", "teasers", "item", "items", "entry", "entries"}),
    "grid": frozenset({"grid", "row", "col", "cols", "columns", "masonry", "list", "listing", "listings"}),
    "product": frozenset({"product", "products", "sku", "price", "prices", "cart", "basket", "add-to-cart", "variant", "variants", "swatch"}),
    "post": frozenset({"post", "posts", "blog", "article", "articles", "entry-content", "excerpt", "byline", "author", "date", "published"}),
    "service": frozenset({"hero", "features", "feature", "testimonial", "testimonials", "pricing", "plans", "plan", "cta", "benefits", "clients", "logos", "partners", "faq", "banner"}),
    "forum": frozenset({"comment", "comments", "reply", "replies", "thread", "threads", "topic", "topics", "post-body", "message", "messages", "avatar", "votes", "vote", "upvote", "answer", "answers", "question"}),
    "docs": frozenset({"sidebar", "toc", "docs", "doc", "documentation", "api", "reference", "code", "highlight", "codeblock", "prose", "markdown", "content-wrapper", "nav-tree", "version"}),
    "filter": frozenset({"filter", "filters", "facet", "facets", "facets-list", "sort", "sorting", "refine", "refinement", "pagination", "pager", "page-numbers", "results", "result", "search-results"}),
    "nav": frozenset({"nav", "navbar", "menu", "breadcrumb", "breadcrumbs", "footer", "header", "sidebar"}),
}
"""Class-name vocabularies, one per thing a page might be made of.

Class names are the one place a site's own developers labelled its parts, and the labels are
more conventional than one might expect: Bootstrap, Tailwind component kits and a decade of
copied templates converge on `card`, `price`, `comment`, `pricing`."""

COUNTED_TAGS: Final[tuple[str, ...]] = (
    "input", "select", "button", "form", "time", "article", "section", "table", "img", "a",
    "li", "h2", "h3", "iframe", "video", "pre", "blockquote", "label", "option",
)

_SPLIT: Final[re.Pattern[str]] = re.compile(r"[\s_]+|(?<=[a-z])(?=[A-Z])|-+")
"""Splits `productCard`, `product_card` and `product-card` alike into `product`, `card`.
Hyphenated compounds are also kept whole where a bucket names them (`add-to-cart`)."""


def markup_stats(root: HtmlElement) -> MarkupStats:
    """Count the tree once. Linear in the number of elements; no XPath, no allocation per node
    beyond the token split."""
    tokens: Counter[str] = Counter()
    tags: Counter[str] = Counter()
    elements = 0
    with_data = 0
    itemprops = 0
    rel_next = False

    for element in root.iter():
        tag = element.tag
        if not isinstance(tag, str):
            continue
        elements += 1
        tags[tag] += 1
        attrib = element.attrib
        classes = attrib.get("class")
        if classes:
            lowered = classes.lower()
            for token in _SPLIT.split(lowered):
                if token:
                    tokens[token] += 1
            # Hyphenated compounds a bucket names whole, in addition to their parts.
            for whole in lowered.split():
                if "-" in whole:
                    tokens[whole] += 1
        if "itemprop" in attrib:
            itemprops += 1
        if tag in ("a", "link") and (attrib.get("rel") or "").lower() == "next":
            rel_next = True
        if any(key.startswith("data-") for key in attrib):
            with_data += 1

    per_100 = 100.0 / max(1, elements)
    return MarkupStats(
        elements=elements,
        class_tokens=len(tokens),
        class_hits={
            name: round(sum(tokens[t] for t in bucket) * per_100, 4)
            for name, bucket in CLASS_BUCKETS.items()
        },
        tag_counts={tag: tags[tag] for tag in COUNTED_TAGS},
        rel_next=rel_next,
        itemprop_count=itemprops,
        data_attr_share=round(with_data * per_100, 4),
    )
