"""A schema per page type, so a caller does not have to write one.

`extract_facts` maps payloads onto whatever JSON Schema it is given, which is the right
primitive and the wrong starting point for someone who just wants the product on the page.
This module supplies the schema, chosen by the page type the router already determined.

Every field here earns its place from a census of 2,008 human-labelled pages plus Web Data
Commons' 2024 crawl of 37.4m domains. Presence percentages in the comments are from that
census and are the reason a field is in or out: a field that is empty on 90% of the pages
it applies to is not a feature, it is a column of blanks that makes the output look broken.
The schemas are deliberately small for the same reason — `documentation` is nearly empty
because documentation sites genuinely do not mark themselves up (31% carry no structured
data at all, and Google offers no rich result for `TechArticle` to make them start).

Three JSON Schema keywords do real work here, all standard:

- `format: "date-time"` — ISO-8601 or nothing. 7% of `datePublished` values are neither,
  and they include `"13/11/2025"`, which is day-month or month-day depending on a locale
  the page never states.
- `enum` — matched against the value's last path segment, because the same availability
  arrives as `https://schema.org/InStock`, `http://schema.org/InStock` and `InStock`.
- nested `properties` — how `author.name` and `offers.price` are read without inventing a
  dotted-path alias syntax. The emitted fact's path is `author.name`, which is also the
  honest description of where the value came from.

What is deliberately *not* here: `title` for `service` (every method measured ~50% wrong
against the annotation, which is a disagreement about what a marketing page's title *is*,
not an extraction failure worth shipping), `upvoteCount` for forums (1.5% of domains emit
it), `articleBody` (12%, and truncated when present), and `mpn`/`gtin` (≤23%, and neither
is a SKU).
"""

from __future__ import annotations

from typing import Any, Final

from webgraph.pagetype import PageType

__all__ = ["PAGE_SCHEMAS", "schema_for"]

_ALIASES: Final[str] = "x-webgraph-aliases"

# Availability, as schema.org spells it. Anything outside this set -- including the one page
# in the census that says "OutStock" -- yields no fact: a typo is not a state.
_AVAILABILITY: Final[list[str]] = [
    "InStock",
    "OutOfStock",
    "PreOrder",
    "PreSale",
    "BackOrder",
    "SoldOut",
    "Discontinued",
    "InStoreOnly",
    "OnlineOnly",
    "LimitedAvailability",
]

_ARTICLE: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        # Both, separately, and neither aliased to the other. They disagree on 32% of the
        # nodes carrying both -- `headline` is the social/SEO line and `name` is sometimes
        # the plain title, sometimes a description (Wikipedia's `name` is "Web scraping" and
        # its `headline` is "data scraping used for extracting data from websites"). Scored
        # against human-annotated titles, preferring `headline` is the better single guess
        # by about a point; but a consumer that can see both can tell them apart, and
        # collapsing them here would destroy that for good.
        "headline": {"type": "string"},
        "name": {"type": "string"},
        "author": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        },
        "datePublished": {
            "type": "string",
            "format": "date-time",
            _ALIASES: ["dateCreated", "article:published_time"],
        },
        # Never folded into `datePublished`: they differ on 72% of article nodes, and when
        # the published date disagrees with what the page displays, the modified date is
        # what the page displays about half the time. Both, or neither -- not a guess.
        "dateModified": {
            "type": "string",
            "format": "date-time",
            _ALIASES: ["article:modified_time"],
        },
        "description": {"type": "string", _ALIASES: ["og:description"]},
        "image": {"type": "string", _ALIASES: ["og:image", "thumbnailUrl"]},
    },
}

_PRODUCT: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        # Nested rather than aliased: `Product.price` appeared on 0 of 71 product nodes in
        # the census, so the flat spelling is folklore. The real value is one level down,
        # and on WooCommerce it is inside a one-element array, which the mapper unwraps.
        "offers": {
            "type": "object",
            "properties": {
                "price": {"type": "number"},
                "priceCurrency": {"type": "string", _ALIASES: ["currency", "currencyCode"]},
                "availability": {"type": "string", "enum": _AVAILABILITY},
            },
        },
        "brand": {"type": "object", "properties": {"name": {"type": "string"}}},
        "sku": {"type": "string", _ALIASES: ["productID"]},
        "aggregateRating": {
            "type": "object",
            "properties": {
                "ratingValue": {"type": "number"},
                # `reviewCount` before `ratingCount`: 74.9% against 31.9% of domains that
                # emit an aggregate rating at all.
                "reviewCount": {"type": "integer", _ALIASES: ["ratingCount"]},
            },
        },
        "image": {"type": "string", _ALIASES: ["og:image"]},
        "description": {"type": "string", _ALIASES: ["og:description"]},
    },
}

_FORUM: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", _ALIASES: ["name"]},
        "text": {"type": "string", _ALIASES: ["articleBody"]},
        "author": {"type": "object", "properties": {"name": {"type": "string"}}},
        # Stack Exchange uses `dateCreated` on questions and answers, and `datePublished`
        # only on comments. Keyed on `datePublished` alone, a mapper reads a reply's date.
        "datePublished": {"type": "string", "format": "date-time", _ALIASES: ["dateCreated"]},
        "commentCount": {"type": "integer", _ALIASES: ["answerCount"]},
    },
}

_SERVICE: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        # Named `organizationName`, not `name`, because it is not the page's name and
        # calling it one would invite every consumer to use it as a title. Measured against
        # human-annotated titles, *every* method of titling a marketing page -- structured
        # data, the DOM h1, Open Graph -- is around 50% wrong, which is a disagreement about
        # what a service page's title is rather than a failure to find it. So this schema
        # answers the question it can answer, and declines the one it cannot.
        "organizationName": {"type": "string", _ALIASES: ["name", "legalName"]},
        # Contact details come almost entirely from `LocalBusiness`: of domains emitting a
        # plain `Organization`, 3.9% carry an address and 2.7% a telephone.
        "telephone": {"type": "string"},
        # String on 11 of 30 observed nodes and an object on 18. Both are accepted rather
        # than one being coerced into the other.
        "address": {"type": ["string", "object"]},
        "url": {"type": "string", _ALIASES: ["og:url"]},
        "priceRange": {"type": "string"},
    },
}

_LIST_ITEMS: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "itemListElement": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "name": {"type": "string"},
                    "position": {"type": "integer"},
                },
            },
        },
        "name": {"type": "string"},
    },
}

# Documentation ships nearly empty and means it: 11% of documentation pages carry a node
# about the page, 31% carry no structured data at all, and live checks of MDN, Sphinx,
# MkDocs, Docusaurus, Read the Docs, Stripe, React, Kubernetes and GitHub's own docs found
# schema.org markup on none of them. Promising fields here would be promising blanks.
_DOCUMENTATION: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", _ALIASES: ["name"]},
        "dateModified": {"type": "string", "format": "date-time"},
    },
}

PAGE_SCHEMAS: Final[dict[PageType, dict[str, Any]]] = {
    PageType.ARTICLE: _ARTICLE,
    PageType.PRODUCT: _PRODUCT,
    PageType.FORUM: _FORUM,
    PageType.SERVICE: _SERVICE,
    PageType.COLLECTION: _LIST_ITEMS,
    PageType.LISTING: _LIST_ITEMS,
    PageType.DOCUMENTATION: _DOCUMENTATION,
}


def schema_for(page_type: PageType) -> dict[str, Any] | None:
    """The schema for a page of this type, or None when there is nothing to offer.

    None for `UNKNOWN`, because a page the router could not type has no known subject and no
    known vocabulary; picking one would be a guess wearing a schema's clothes.
    """
    return PAGE_SCHEMAS.get(page_type)
