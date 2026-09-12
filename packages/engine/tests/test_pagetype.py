"""The page-type router: features are stable, the policy is the measured one, inference is
pure Python and degrades to the default when no model is shipped.

The router exists because one selector setting cannot serve every page type (MEMORY.md
D99-D100): scoring repeated cards as one unit lifts listings and costs articles, every time.
Its accuracy is measured out of fold in `benchmark/train/router_train.py`; these tests pin
the contract around it, not the number.
"""

from __future__ import annotations

import math

from webgraph.main_content import MainContentConfig
from webgraph.pagetype import (
    FEATURE_NAMES,
    PageType,
    PageTypeRouter,
    page_features,
    policy_for,
)
from webgraph.pipeline import build_document

PROSE = "Ordinary prose in a paragraph with enough words to look like an article body, number "


def article() -> str:
    body = "".join(f"<p>{PROSE}{i}.</p>" for i in range(12))
    ld = ('<script type="application/ld+json">{"@type":"BlogPosting","headline":"x"}</script>')
    og = '<meta property="og:type" content="article">'
    return f"<html><head>{ld}{og}</head><body><main><article><h1>Title</h1>{body}</article></main></body></html>"


def grid() -> str:
    cards = "".join(
        f"<li><a href='/p/{i}'><h3>Widget {i}</h3></a><span>$ {10 + i}.00</span></li>" for i in range(30)
    )
    return f"<html><body><main><h1>Widgets</h1><ul>{cards}</ul></main></body></html>"


class TestFeatures:
    def test_vector_matches_names(self) -> None:
        document = build_document(article(), "https://example.test/blog/how-to-do-x")
        features = page_features(document)
        assert len(features) == len(FEATURE_NAMES)
        assert all(math.isfinite(v) for v in features)

    def test_url_payload_and_structure_signals_fire(self) -> None:
        document = build_document(article(), "https://example.test/blog/how-to-do-x")
        f = dict(zip(FEATURE_NAMES, page_features(document), strict=True))
        assert f["url_article"] == 1.0
        assert f["ld_article"] == 1.0
        assert f["og_article"] == 1.0
        assert f["share_paragraph"] > 0.5

    def test_a_grid_reads_as_a_grid(self) -> None:
        document = build_document(grid(), "https://example.test/collections/widgets")
        f = dict(zip(FEATURE_NAMES, page_features(document), strict=True))
        assert f["url_collection"] == 1.0
        assert f["max_group_share"] > 0.5
        assert f["max_group_size"] >= 30
        assert f["price_hits_per_100w"] > 0

    def test_no_domain_leaks_into_the_features(self) -> None:
        """Same page, two hosts: identical vector. The router must learn shapes, not sites."""
        a = page_features(build_document(article(), "https://alpha.test/blog/x"))
        b = page_features(build_document(article(), "https://beta.example/blog/x"))
        assert a == b


class TestPolicy:
    def test_grid_types_group_and_prose_types_do_not(self) -> None:
        for kind in (PageType.LISTING, PageType.COLLECTION, PageType.SERVICE, PageType.DOCUMENTATION):
            assert policy_for(kind).group_repeats == "all"
        for kind in (PageType.ARTICLE, PageType.PRODUCT, PageType.FORUM, PageType.UNKNOWN, None):
            assert policy_for(kind) == MainContentConfig()

    def test_string_types_are_accepted(self) -> None:
        assert policy_for("listing").group_repeats == "all"


class TestRouter:
    def test_load_is_none_or_a_router(self) -> None:
        router = PageTypeRouter.load()
        assert router is None or isinstance(router, PageTypeRouter)

    def test_a_shipped_model_routes_the_obvious_cases(self) -> None:
        router = PageTypeRouter.load()
        if router is None:
            return
        routed = router.route(build_document(article(), "https://example.test/blog/how-to-do-x"))
        assert routed.page_type is PageType.ARTICLE
        assert abs(sum(routed.probabilities.values()) - 1.0) < 1e-9
        routed = router.route(build_document(grid(), "https://example.test/collections/widgets"))
        assert routed.page_type in (PageType.COLLECTION, PageType.LISTING)

    def test_tree_walk_handles_a_hand_built_model(self) -> None:
        """One iteration, two classes, one split each: the walk and the softmax are exact."""
        n = len(FEATURE_NAMES)
        idx = FEATURE_NAMES.index("url_product")
        model = {
            "classes": ["article", "product"],
            "features": list(FEATURE_NAMES),
            "baseline": [0.0, 0.0],
            "trees": [[
                [[float(idx), 0.5, 1.0, 2.0, 0.0, 0.0], [-1.0, 0.0, -1.0, -1.0, 2.0, 0.0], [-1.0, 0.0, -1.0, -1.0, -2.0, 0.0]],
                [[float(idx), 0.5, 1.0, 2.0, 0.0, 0.0], [-1.0, 0.0, -1.0, -1.0, -2.0, 0.0], [-1.0, 0.0, -1.0, -1.0, 2.0, 0.0]],
            ]],
        }
        router = PageTypeRouter(model)
        x = [0.0] * n
        assert router.scores(x) == [2.0, -2.0]
        x[idx] = 1.0
        assert router.scores(x) == [-2.0, 2.0]


class TestConfidenceFloor:
    """Below 0.5 the router says `unknown` instead of guessing.

    Out of fold on 1,497 pages, predictions under 0.5 confidence were right 44% of the
    time. Committing to them is how a Hacker News page became `documentation` at 24% and
    was handed the documentation schema.
    """

    @staticmethod
    def flat_model() -> dict:
        """A model whose every score is zero: perfectly undecided across two classes."""
        return {
            "classes": ["article", "product"],
            "features": list(FEATURE_NAMES),
            "baseline": [0.0, 0.0],
            "trees": [],
        }

    def test_an_undecided_model_routes_to_unknown_by_default(self) -> None:
        from webgraph.pipeline import build_document

        router = PageTypeRouter(self.flat_model())
        routing = router.route(build_document("<html><body><p>x</p></body></html>", "https://x.test/"))
        assert routing.confidence == 0.5
        assert routing.page_type is PageType.UNKNOWN or routing.confidence >= router.min_confidence

    def test_the_floor_is_the_measured_one(self) -> None:
        from webgraph.pagetype import DEFAULT_MIN_CONFIDENCE

        assert DEFAULT_MIN_CONFIDENCE == 0.5
        assert PageTypeRouter(self.flat_model()).min_confidence == 0.5

    def test_a_caller_may_lower_it(self) -> None:
        from webgraph.pipeline import build_document

        router = PageTypeRouter(self.flat_model(), min_confidence=0.0)
        routing = router.route(build_document("<html><body><p>x</p></body></html>", "https://x.test/"))
        assert routing.page_type is not PageType.UNKNOWN
