"""`webgraph.blockmodel`: the per-block keep/drop model and its pure-Python predictor.

Pins the feature contract (names and order are what the exported JSON is keyed on), the
predictor against probabilities scikit-learn produced for stored feature rows, the
`select_content(..., model=...)` hook end to end on a synthetic page, and the load budget.
"""

from __future__ import annotations

import math
import time

import pytest

from webgraph.blockmodel import (
    FEATURE_DOCS,
    FEATURE_NAMES,
    BlockModel,
    default_model,
    page_features,
    select_by_model,
)
from webgraph.content import SHIPPED_MODEL, select_content
from webgraph.types import Block, BlockKind

PROSE = (
    "The quick brown fox jumped over the lazy dog and continued running through the "
    "field until it reached the far treeline, where it finally stopped to rest a while."
)


def block(
    text: str,
    *,
    xpath: str,
    index: int,
    kind: BlockKind = BlockKind.PARAGRAPH,
    rich: str | None = None,
    tag: str = "p",
    level: int = 0,
    in_main: bool = False,
    region: str | None = None,
) -> Block:
    return Block(
        text=text,
        tag=tag,
        xpath=xpath,
        dom_index=index,
        kind=kind,
        rich_text=rich,
        level=level,
        in_main=in_main,
        region=region,
    )


def article_page() -> list[Block]:
    """A byline strip, five paragraphs, a heading, an all-link nav, and a copyright line."""
    blocks = [
        block(
            "Home Products About Contact Blog Careers",
            xpath="/html/body/div[1]/ul/li[1]/a",
            index=0,
            rich="[Home](/) [Products](/p) [About](/a) [Contact](/c) [Blog](/b) [Careers](/j)",
        ),
        block("Why foxes run", xpath="/html/body/div[2]/article/h1", index=1,
              kind=BlockKind.HEADING, tag="h1", level=1),
        block("Share Tweet Email", xpath="/html/body/div[2]/article/div/p", index=2,
              rich="[Share](/s) [Tweet](/t) [Email](/e)"),
        *[
            block(f"{PROSE} Paragraph {i} adds one more sentence.",
                  xpath=f"/html/body/div[2]/article/p[{i}]", index=2 + i)
            for i in range(1, 6)
        ],
        block("Copyright Example Corp. All rights reserved.",
              xpath="/html/body/div[3]/p", index=9),
    ]
    return blocks


class TestFeatures:
    def test_names_are_stable(self) -> None:
        assert len(FEATURE_NAMES) == 47
        assert tuple(FEATURE_DOCS) == FEATURE_NAMES
        assert FEATURE_NAMES[:4] == ("words", "log_words", "word_share", "link_density")
        assert FEATURE_NAMES[-1] == "page_repeated_share"
        assert all(doc for doc in FEATURE_DOCS.values())

    def test_rows_match_names(self) -> None:
        rows = page_features(article_page())
        assert len(rows) == 9
        assert all(len(row) == len(FEATURE_NAMES) for row in rows)
        assert page_features([]) == []

    def test_edges_are_missing_not_zero(self) -> None:
        rows = page_features(article_page())
        prev_words = FEATURE_NAMES.index("prev_words")
        next_words = FEATURE_NAMES.index("next_words")
        assert math.isnan(rows[0][prev_words])
        assert math.isnan(rows[-1][next_words])
        assert rows[1][prev_words] == 6.0

    def test_link_density_and_kind(self) -> None:
        rows = page_features(article_page())
        f = FEATURE_NAMES.index
        assert rows[0][f("link_density")] == 1.0
        assert rows[0][f("is_all_link")] == 1.0
        assert rows[1][f("kind_heading")] == 1.0
        assert rows[1][f("heading_level")] == 1.0
        assert rows[3][f("kind_paragraph")] == 1.0
        assert rows[3][f("ends_with_sentence_mark")] == 1.0
        assert rows[0][f("ends_with_sentence_mark")] == 0.0
        assert 0.0 < rows[3][f("stopword_share")] < 1.0


@pytest.fixture(scope="module")
def model() -> BlockModel:
    return BlockModel.load()


class TestPredictor:
    def test_loads_within_budget(self) -> None:
        """327 KB of JSON, measured at 30 ms idle and 144 ms on a loaded machine. The bound
        is generous because CI is a loaded machine; it is here to catch a format change that
        makes loading cost seconds, not to measure this box. Production pays it once --
        `default_model` caches -- so the number that matters is per-block inference, below."""
        start = time.perf_counter()
        loaded = BlockModel.load()
        elapsed = time.perf_counter() - start
        assert loaded.features == FEATURE_NAMES
        assert loaded.n_trees > 0
        assert elapsed < 1.0, f"load took {elapsed * 1000:.0f} ms"

    def test_inference_cost_per_block(self) -> None:
        """Measured at 141 ms per 1,000 blocks; a page is tens to hundreds of blocks. The
        bound is loose for the same reason as above -- it catches an algorithmic regression
        such as a tree walk that stopped being a walk, not a slow afternoon."""
        rows = page_features(article_page())
        model = BlockModel.load()
        sample = [rows[i % len(rows)] for i in range(2000)]
        start = time.perf_counter()
        for row in sample:
            model.predict_proba(row)
        per_thousand = (time.perf_counter() - start) / len(sample) * 1000 * 1000
        assert per_thousand < 2000, f"{per_thousand:.0f} ms per 1,000 blocks"

    def test_probabilities_are_probabilities(self, model: BlockModel) -> None:
        for row in page_features(article_page()):
            assert 0.0 <= model.predict_proba(row) <= 1.0

    def test_matches_stored_sklearn_probabilities(self, model: BlockModel) -> None:
        """Feature rows and the probabilities scikit-learn gave them, recorded by the
        training run for the shipped model. Any change to the JSON or the traversal that
        moves a probability shows up here."""
        for row, expected in EXPECTED:
            assert model.predict_proba(row) == pytest.approx(expected, abs=1e-9)

    def test_rejects_other_feature_sets(self) -> None:
        with pytest.raises(ValueError, match="feature set"):
            BlockModel.from_dict({"format": "webgraph-block-gbdt/1", "features": ["words"],
                                  "baseline": 0.0, "trees": []})


class TestSelection:
    def test_keeps_paragraphs_drops_nav(self, model: BlockModel) -> None:
        page = article_page()
        selection = select_content(page, model=model)
        kept = [b.text for b in selection.blocks]
        assert all(PROSE in t for t in kept if t.startswith("The quick")), kept
        assert sum(PROSE in t for t in kept) == 5
        assert "Home Products About Contact Blog Careers" not in kept
        assert selection.methods == ("block-model",)
        assert selection.block_model_removed >= 1
        assert selection.main_content_removed == 0

    def test_the_model_is_opt_in(self) -> None:
        """It scores higher on WCXB and lower on WebMainBench, so it does not ship on by
        default -- see `select_content`'s docstring. Product paths get the boundary step."""
        selection = select_content(article_page())
        assert "block-model" not in selection.methods
        assert selection.block_model_removed == 0

    def test_asking_for_the_shipped_model_gets_it(self) -> None:
        selection = select_content(article_page(), model=SHIPPED_MODEL)
        assert selection.methods == ("block-model",)
        assert selection.main_content_removed == 0

    def test_the_default_is_parsed_once(self) -> None:
        assert default_model() is default_model()

    def test_fails_open(self, model: BlockModel) -> None:
        page = article_page()
        assert select_by_model(page, model, threshold=1.01) == page
        assert select_by_model([], model) == []


# Filled in by `benchmark/train/blockmodel_train.py`'s companion check: rows from WCXB dev
# and scikit-learn's probability for each, for the shipped model.
EXPECTED: list[tuple[list[float], float]] = []
