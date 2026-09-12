"""What kind of page is this? A router, so the content selector can stop treating every page
the same.

Why a router
------------
One selector cannot serve every page. Measured on WCXB dev (session 15, D99-D100): scoring
a grid of repeated cards as one unit lifts listings +0.05 to +0.09 and service and
documentation pages +0.01 to +0.02, and costs articles -0.01 to -0.02 and products -0.05,
*every time*, under every guard tried. No global setting wins because the pages disagree
about what content is: on a collection page the link grid *is* the content; on a product
page the same grid is the related-products rail. rs-trafilatura, the system that leads that
benchmark, gets +0.10 to +0.21 on exactly those types from routing first and extracting
per type. This module is that first step.

What it reads
-------------
Only what a `Document` already carries: the URL path, the structured payloads (JSON-LD
`@type`, Open Graph `og:type`) and the block list. No network, no re-parse. The features
are generic by design -- never a domain, never a page id -- so the model learns what a
product page *looks like*, not which sites were in the training set.

How it decides
--------------
A gradient-boosted tree ensemble trained on the WCXB development split (1,497 pages, seven
types) and exported to `models/router_gbdt.json`; inference is pure Python, a few hundred
comparisons per page. The cross-validated accuracy is recorded in `benchmark/train/README.md`
with the confusion matrix, because a router that is wrong 30% of the time would route 30% of
pages to the wrong selector -- the number is the whole justification.

`PageType.UNKNOWN` is returned when no model is packaged or confidence is low, and every
consumer treats it as "use the default", so a missing model degrades to the behaviour that
existed before routing.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import cache, lru_cache
from importlib.resources import files
from typing import Any, Final
from urllib.parse import urlsplit

from webgraph.main_content import MainContentConfig, _repeat_groups, link_density, word_count
from webgraph.types import Block, BlockKind, Document, PayloadSource

__all__ = [
    "FEATURE_NAMES",
    "PageType",
    "PageTypeRouter",
    "Routing",
    "default_router",
    "page_features",
    "policy_for",
]


class PageType(StrEnum):
    ARTICLE = "article"
    DOCUMENTATION = "documentation"
    SERVICE = "service"
    FORUM = "forum"
    COLLECTION = "collection"
    LISTING = "listing"
    PRODUCT = "product"
    UNKNOWN = "unknown"


TYPES: Final[tuple[PageType, ...]] = (
    PageType.ARTICLE,
    PageType.DOCUMENTATION,
    PageType.SERVICE,
    PageType.FORUM,
    PageType.COLLECTION,
    PageType.LISTING,
    PageType.PRODUCT,
)

# URL path vocabularies. Generic words only; a token that names one site is a leak.
_URL_VOCAB: Final[dict[str, frozenset[str]]] = {
    "url_article": frozenset({
        "blog", "news", "article", "articles", "post", "posts", "story", "stories", "guide",
        "guides", "how", "tips", "best", "top", "review", "reviews", "why", "what", "vs",
        "insights", "resources", "learn", "magazine", "journal", "opinion", "press",
    }),
    "url_product": frozenset({
        "product", "products", "p", "item", "items", "itm", "dp", "sku", "buy", "pd", "prod",
    }),
    "url_collection": frozenset({
        "collections", "collection", "category", "categories", "c", "cat", "catalog",
        "catalogue", "shop", "store", "brand", "brands", "sale", "new", "all",
    }),
    "url_forum": frozenset({
        "threads", "thread", "topic", "topics", "t", "forum", "forums", "questions",
        "question", "discussion", "discussions", "community", "board", "viewtopic", "showthread",
        "comments", "answers", "q", "talk",
    }),
    "url_docs": frozenset({
        "docs", "doc", "documentation", "reference", "api", "manual", "tutorial", "tutorials",
        "latest", "stable", "en", "wiki", "handbook", "kb", "help", "developer", "developers",
        "sdk", "cli", "spec",
    }),
    "url_service": frozenset({
        "services", "service", "solutions", "solution", "consulting", "pricing", "features",
        "platform", "product-tour", "company", "about", "industries", "capabilities", "why",
    }),
    "url_listing": frozenset({
        "list", "lists", "listing", "listings", "jobs", "job", "search", "tag", "tags",
        "archive", "archives", "page", "directory", "events", "recipes", "results", "browse",
    }),
}

_LD_VOCAB: Final[dict[str, frozenset[str]]] = {
    "ld_article": frozenset({"Article", "NewsArticle", "BlogPosting", "TechArticle", "Report",
                             "ScholarlyArticle", "Review", "HowTo", "Recipe"}),
    "ld_product": frozenset({"Product", "Offer", "AggregateOffer", "AggregateRating", "Brand"}),
    "ld_forum": frozenset({"DiscussionForumPosting", "QAPage", "Question", "Answer", "Comment",
                           "SocialMediaPosting", "InteractionCounter"}),
    "ld_collection": frozenset({"CollectionPage", "ItemList", "ProductCollection",
                                "OfferCatalog"}),
    "ld_faq": frozenset({"FAQPage"}),
    "ld_org_only": frozenset({"Organization", "LocalBusiness", "Corporation", "Service",
                              "ProfessionalService"}),
    "ld_job": frozenset({"JobPosting"}),
    "ld_software": frozenset({"SoftwareApplication", "SoftwareSourceCode", "APIReference"}),
    "ld_webpage": frozenset({"WebPage", "WebSite"}),
    "ld_breadcrumb": frozenset({"BreadcrumbList"}),
    "ld_person": frozenset({"Person"}),
}

_OG_TYPES: Final[tuple[str, ...]] = ("article", "website", "product", "product.group", "blog",
                                     "book", "profile")

_PRICE: Final[re.Pattern[str]] = re.compile(
    r"(?:[$€£¥₹]\s?\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?\s?(?:USD|EUR|GBP|INR|CAD|AUD))"
)
_DATE_LIKE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:\d{1,2}:\d{2}|\d{4}-\d{2}-\d{2}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.? \d{1,2})\b",
    re.I,
)
_FORUM_WORDS: Final[re.Pattern[str]] = re.compile(
    r"\b(?:replies|reply|posts?|joined|member|members|quote|upvote|votes?|thread|op|karma|likes?)\b",
    re.I,
)
_COMMERCE_WORDS: Final[re.Pattern[str]] = re.compile(
    r"\b(?:add to (?:cart|bag|basket)|in stock|out of stock|free shipping|checkout|sku|"
    r"quantity|wishlist|compare|sort by|filter|filters|results?|showing \d+)\b",
    re.I,
)
_CTA_WORDS: Final[re.Pattern[str]] = re.compile(
    r"\b(?:get started|contact us|request a (?:demo|quote)|book a|learn more|free trial|"
    r"sign up|talk to|schedule|our (?:services|solutions|team|clients)|why choose|trusted by)\b",
    re.I,
)
_DOC_WORDS: Final[re.Pattern[str]] = re.compile(
    r"\b(?:parameters?|returns?|example|examples|usage|syntax|install|installation|"
    r"api|version|deprecated|arguments?|options|configuration|see also)\b",
    re.I,
)

_BLOCK_KINDS: Final[tuple[BlockKind, ...]] = (
    BlockKind.PARAGRAPH, BlockKind.HEADING, BlockKind.LIST_ITEM, BlockKind.TABLE,
    BlockKind.IMAGE, BlockKind.CODE, BlockKind.QUOTE,
)

FEATURE_NAMES: Final[tuple[str, ...]] = (
    # URL
    *tuple(_URL_VOCAB),
    "url_depth", "url_html_ext", "url_has_query", "url_numeric_segment", "url_is_root",
    "url_slug_words",
    # payloads
    *tuple(_LD_VOCAB),
    *tuple(f"og_{t.replace('.', '_')}" for t in _OG_TYPES),
    "og_none",
    # structure
    "log_blocks", "log_words", "mean_words", "link_density", "share_in_main",
    *tuple(f"share_{k.value}" for k in _BLOCK_KINDS),
    "share_short_blocks", "share_linked_blocks", "h1_count", "heading_count",
    "max_group_share", "max_group_size", "groups_over_5", "table_count", "code_count",
    "image_count", "price_hits_per_100w", "date_hits_per_100w", "forum_hits_per_100w",
    "commerce_hits_per_100w", "cta_hits_per_100w", "doc_hits_per_100w",
    "longest_block_share", "share_words_first_half",
)


def _payload_types(document: Document) -> tuple[set[str], str]:
    """Every JSON-LD / microdata `@type` on the page, and the Open Graph type."""
    types: set[str] = set()
    og = ""
    for payload in document.structured_data:
        if payload.source is PayloadSource.OPEN_GRAPH and isinstance(payload.data, dict):
            og = str(payload.data.get("og:type") or "").strip().lower()
            continue
        if payload.source not in (PayloadSource.JSON_LD, PayloadSource.MICRODATA):
            continue
        stack: list[Any] = [payload.data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                declared = node.get("@type") or node.get("type")
                if isinstance(declared, str):
                    types.add(declared.rsplit("/", 1)[-1])
                elif isinstance(declared, list):
                    types.update(str(v).rsplit("/", 1)[-1] for v in declared)
                stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
            elif isinstance(node, list):
                stack.extend(node)
    return types, og


def page_features(document: Document, url: str | None = None) -> list[float]:
    """The feature vector the router reads. Order is `FEATURE_NAMES`."""
    url = url or document.url
    path = urlsplit(url).path.lower()
    segments = [s for s in path.split("/") if s]
    tokens = {t for s in segments for t in re.split(r"[\-_.]+", s) if t}
    last = re.split(r"[\-_.]+", segments[-1]) if segments else []
    features: list[float] = []
    for vocab in _URL_VOCAB.values():
        features.append(float(bool(tokens & vocab)))
    features.extend([
        float(len(segments)),
        float(path.endswith((".html", ".htm", ".php", ".aspx"))),
        float(bool(urlsplit(url).query)),
        float(any(s.isdigit() for s in segments)),
        float(not segments),
        float(sum(1 for t in last if t.isalpha())),
    ])

    types, og = _payload_types(document)
    for vocab in _LD_VOCAB.values():
        features.append(float(bool(types & vocab)))
    for og_type in _OG_TYPES:
        features.append(float(og == og_type))
    features.append(float(og == ""))

    blocks: Sequence[Block] = document.blocks
    n = len(blocks) or 1
    words = [word_count(b.text) for b in blocks]
    total = sum(words) or 1
    text = "\n".join(b.text for b in blocks)
    per_100w = 100.0 / total
    linked_words = sum(w * link_density(b) for w, b in zip(words, blocks, strict=True))
    groups = _repeat_groups(blocks, MainContentConfig(group_repeats="all", group_min_share=0.0))
    group_words: dict[int, int] = {}
    group_sizes: dict[int, int] = {}
    for gid, w in zip(groups, words, strict=True):
        if gid >= 0:
            group_words[gid] = group_words.get(gid, 0) + w
            group_sizes[gid] = group_sizes.get(gid, 0) + 1
    first_half = sum(words[: max(1, len(words) // 2)])
    features.extend([
        math.log1p(len(blocks)),
        math.log1p(total),
        total / n,
        linked_words / total,
        sum(w for w, b in zip(words, blocks, strict=True) if b.in_main) / total,
        *[sum(1 for b in blocks if b.kind is k) / n for k in _BLOCK_KINDS],
        sum(1 for w in words if w <= 4) / n,
        sum(1 for b in blocks if link_density(b) >= 0.8) / n,
        float(sum(1 for b in blocks if b.kind is BlockKind.HEADING and b.level == 1)),
        float(sum(1 for b in blocks if b.kind is BlockKind.HEADING)),
        (max(group_words.values()) / total) if group_words else 0.0,
        float(max(group_sizes.values())) if group_sizes else 0.0,
        float(sum(1 for s in group_sizes.values() if s > 5)),
        float(sum(1 for b in blocks if b.kind is BlockKind.TABLE)),
        float(sum(1 for b in blocks if b.kind is BlockKind.CODE)),
        float(sum(1 for b in blocks if b.kind is BlockKind.IMAGE)),
        len(_PRICE.findall(text)) * per_100w,
        len(_DATE_LIKE.findall(text)) * per_100w,
        len(_FORUM_WORDS.findall(text)) * per_100w,
        len(_COMMERCE_WORDS.findall(text)) * per_100w,
        len(_CTA_WORDS.findall(text)) * per_100w,
        len(_DOC_WORDS.findall(text)) * per_100w,
        (max(words) / total) if words else 0.0,
        first_half / total,
    ])
    assert len(features) == len(FEATURE_NAMES), (len(features), len(FEATURE_NAMES))
    return features


@dataclass(frozen=True, slots=True)
class Routing:
    page_type: PageType
    confidence: float
    """Probability of the chosen type. Below `PageTypeRouter.min_confidence` the router
    answers `UNKNOWN`, which every consumer treats as "use the default"."""

    probabilities: dict[str, float]


class PageTypeRouter:
    """Pure-Python inference over an exported gradient-boosted ensemble.

    Model format (`models/router_gbdt.json`): `classes`, `features`, `baseline` (per class),
    and `trees` -- a list of iterations, each a list of one tree per class. A tree is a flat
    list of nodes `[feature, threshold, left, right, value, missing_left]`; leaves have
    `feature = -1`. Scores are `baseline[c] + sum of leaf values`, then softmax.
    """

    min_confidence: float = 0.0

    def __init__(self, model: dict[str, Any], *, min_confidence: float = 0.0) -> None:
        self.classes: list[str] = list(model["classes"])
        self.features: list[str] = list(model["features"])
        if tuple(self.features) != FEATURE_NAMES:
            raise ValueError("router model was trained on a different feature set")
        self.baseline: list[float] = [float(v) for v in model["baseline"]]
        self.trees: list[list[list[list[float]]]] = model["trees"]
        self.min_confidence = min_confidence

    @classmethod
    @cache
    def load(cls) -> PageTypeRouter | None:
        """The packaged model, or None when none is shipped."""
        resource = files("webgraph") / "models" / "router_gbdt.json"
        if not resource.is_file():
            return None
        return cls(json.loads(resource.read_text(encoding="utf-8")))

    @staticmethod
    def _tree_value(tree: list[list[float]], x: list[float]) -> float:
        node = 0
        while True:
            feature, threshold, left, right, value, missing_left = tree[node]
            if feature < 0:
                return value
            v = x[int(feature)]
            if v != v:  # NaN: sklearn's missing-value branch
                node = int(left) if missing_left else int(right)
            elif v <= threshold:
                node = int(left)
            else:
                node = int(right)

    def scores(self, x: list[float]) -> list[float]:
        raw = list(self.baseline)
        for iteration in self.trees:
            for index, tree in enumerate(iteration):
                raw[index] += self._tree_value(tree, x)
        return raw

    def route(self, document: Document, url: str | None = None) -> Routing:
        raw = self.scores(page_features(document, url))
        peak = max(raw)
        exps = [math.exp(v - peak) for v in raw]
        total = sum(exps)
        probabilities = {c: e / total for c, e in zip(self.classes, exps, strict=True)}
        best = max(probabilities, key=lambda c: probabilities[c])
        confidence = probabilities[best]
        page_type = PageType(best) if confidence >= self.min_confidence else PageType.UNKNOWN
        return Routing(page_type=page_type, confidence=confidence, probabilities=probabilities)


@lru_cache(maxsize=1)
def default_router() -> PageTypeRouter | None:
    """The shipped router, parsed once per process, or None if none ships.

    `PageTypeRouter.load()` re-reads 971 KB of JSON each call, which is fine once and wrong
    per page. Product paths that label a page call this.
    """
    return PageTypeRouter.load()


def policy_for(page_type: PageType | str | None) -> MainContentConfig:
    """The selector settings a page type has measured best with on WCXB dev (D99-D100).

    Only one knob differs today -- whether repeated sibling items are scored as one unit --
    because that is the only per-type disagreement measured so far. Unknown or unrouted
    pages get the default, which is what every page got before routing existed.

    ```
    type            grouping     dev F1 off -> on
    listing         all, 30%     0.558 -> 0.649
    collection      all, 30%     0.555 -> 0.574
    service         all, 30%     0.777 -> 0.798
    documentation   all, 30%     0.906 -> 0.922
    article         off          0.920 -> 0.897
    product         off          0.589 -> 0.538
    forum           off          0.733 -> 0.713
    ```
    """
    kind = PageType(page_type) if page_type else PageType.UNKNOWN
    if kind in (PageType.LISTING, PageType.COLLECTION, PageType.SERVICE, PageType.DOCUMENTATION):
        return MainContentConfig(group_repeats="all", group_min_share=0.3)
    return MainContentConfig()
