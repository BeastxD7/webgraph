"""A small trained per-block keep/drop classifier for main-content extraction.

Why a model, and why this small
-------------------------------
`select_main_content` draws one contiguous boundary with a hand-tuned scoring function. It
is right on articles (F1 0.920 on WCXB dev) and wrong by construction on the page types
whose content is not one run of prose: a product grid, a listing, a thread of replies. Every
selector experiment on those types (MEMORY.md D96-D99) traded one type against another,
because a single scoring rule cannot say both "a short linked card is content" and "a short
linked card is a related-products rail".

A gradient-boosted tree ensemble can, given the block's own shape *and* its neighbourhood
*and* the page it sits on. This module holds the two halves that training and inference
must share: the feature function (`page_features`) and the pure-Python predictor
(`BlockModel`). Training lives in `benchmark/train/blockmodel_train.py` and needs
scikit-learn; inference needs nothing but this file and the exported JSON, because the
engine's runtime dependencies are httpx, lxml, pydantic and jsonschema and a classifier is
not a reason to add numpy to them.

What the model sees
-------------------
Nothing that could name the page: no URL, no domain, no ids. Every feature is computed
from the block list after `strip_landmarks` and `scope_to_main` -- the same list the
production selector gets -- and falls into four groups: the block's own text shape, its
kind and place in the DOM, its immediate neighbours, and page-level context. The names and
order in `FEATURE_DOCS` are the contract the exported model is keyed on; add a feature at
the end and retrain rather than reorder.

The exported format
-------------------
`models/block_gbdt.json` holds the scikit-learn `HistGradientBoostingClassifier` ensemble as
plain lists: one flat node table per tree, `[feature, threshold, left, right, value,
missing_goes_left]` per node with `feature == -1` marking a leaf. Prediction is exactly
scikit-learn's: raw score = baseline + sum over trees of the reached leaf's value (the
learning rate is already folded into the leaf values), then `x <= threshold` goes left, a
missing value (NaN) goes where `missing_goes_left` says, and probability is the logistic
sigmoid of the raw score. `benchmark/train/blockmodel_train.py` checks the exported
predictor against scikit-learn on 20,000 blocks before it ships the file.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Final

from webgraph.main_content import MainContentConfig, _repeat_groups, link_density, word_count
from webgraph.types import Block, BlockKind

__all__ = [
    "FEATURE_DOCS",
    "FEATURE_NAMES",
    "MODEL_FORMAT",
    "BlockModel",
    "default_model",
    "page_features",
    "select_by_model",
]

MODEL_FORMAT: Final[str] = "webgraph-block-gbdt/1"

_KINDS: Final[tuple[BlockKind, ...]] = (
    BlockKind.PARAGRAPH,
    BlockKind.HEADING,
    BlockKind.LIST_ITEM,
    BlockKind.TABLE,
    BlockKind.IMAGE,
    BlockKind.CODE,
    BlockKind.QUOTE,
    BlockKind.FIGURE_CAPTION,
    BlockKind.MEDIA,
)
_KIND_CODE: Final[dict[BlockKind, int]] = {kind: i for i, kind in enumerate(_KINDS)}
_REGIONS: Final[tuple[str, ...]] = ("main", "nav", "header", "footer", "aside")

_TOKEN: Final[re.Pattern[str]] = re.compile(r"\w+")
_SENTENCE_END: Final[re.Pattern[str]] = re.compile("[.!?\u2026][\"'\u201d\u2019)\\]]*$")
_PUNCT: Final[frozenset[str]] = frozenset(
    ".,;:!?-()[]{}\"'/\\|@#$%^&*+=<>~`\u2013\u2014\u201c\u201d\u2018\u2019"
)

_STOPWORDS: Final[frozenset[str]] = frozenset([
    "a", "an", "the", "and", "or", "but", "if", "of", "to", "in", "on", "at", "by", "for",
    "with", "from", "as", "is", "are", "was", "were", "be", "been", "being", "it", "its",
    "this", "that", "these", "those", "he", "she", "they", "we", "you", "i", "his", "her",
    "their", "our", "your", "not", "no", "so", "than", "then", "there", "here", "what",
    "which", "who", "whom", "when", "where", "why", "how", "all", "any", "each", "more",
    "most", "other", "some", "such", "only", "own", "same", "too", "very", "can", "will",
    "just", "do", "does", "did", "has", "have", "had", "into", "about", "over", "after",
    "before", "up", "down", "out", "also",
])
"""A small English list. Its share is a prose-versus-label signal, not a language model:
'Add to cart' has none, a sentence has several. Non-English prose scores zero here and is
carried by the other features."""

FEATURE_DOCS: Final[dict[str, str]] = {
    # -- the block's own text --
    "words": "word count (CJK characters count one each, see `word_count`)",
    "log_words": "log(1 + words)",
    "word_share": "words / page_words",
    "link_density": "share of the block's words inside a link, from `rich_text`",
    "chars": "length of the text in characters",
    "digit_share": "digits / non-space characters",
    "upper_share": "upper-case letters / letters",
    "punct_share": "punctuation characters / non-space characters",
    "ends_with_sentence_mark": "1 when the text ends in . ! ? (optionally followed by a quote or bracket)",
    "stopword_share": "share of tokens in a small English stopword list",
    # -- kind and place in the DOM --
    "kind_paragraph": "1 for a paragraph block",
    "kind_heading": "1 for a heading",
    "kind_list_item": "1 for a list item",
    "kind_table": "1 for a table",
    "kind_image": "1 for an image (text is its alt)",
    "kind_code": "1 for a code block",
    "kind_quote": "1 for a blockquote",
    "kind_caption": "1 for a figure caption",
    "kind_media": "1 for an untranscribed media placeholder",
    "heading_level": "1-6 for headings, else 0",
    "depth": "number of segments in the XPath",
    "in_main": "1 when any ancestor is a `main` landmark",
    "region_main": "1 when the innermost landmark is `main`",
    "region_nav": "1 when the innermost landmark is `nav`",
    "region_header": "1 when the innermost landmark is `header`",
    "region_footer": "1 when the innermost landmark is `footer`",
    "region_aside": "1 when the innermost landmark is `aside`",
    "region_none": "1 when the block is outside every landmark",
    "relative_position": "index / (blocks - 1), 0 at the top of the page and 1 at the bottom",
    "rich_has_link": "1 when `rich_text` carries at least one Markdown link",
    "is_all_link": "1 when link_density >= 0.99",
    # -- repetition --
    "group_size": "blocks in the block's repeated-sibling group (0 when not in one)",
    "group_word_share": "words of that group / page_words (0 when not in one)",
    # -- neighbours (NaN at the page edges) --
    "prev_words": "words of the previous block",
    "prev_link_density": "link_density of the previous block",
    "prev_kind": "kind code of the previous block (0 paragraph .. 8 media)",
    "prev_same_group": "1 when the previous block is in the same repeated group",
    "next_words": "words of the next block",
    "next_link_density": "link_density of the next block",
    "next_kind": "kind code of the next block",
    "next_same_group": "1 when the next block is in the same repeated group",
    # -- the page --
    "page_words": "total words on the page after landmark stripping",
    "page_blocks": "number of blocks on the page",
    "page_mean_words": "page_words / page_blocks",
    "page_link_density": "linked words / page_words over the whole page",
    "page_share_in_main": "share of page words inside a `main` landmark",
    "page_repeated_share": "share of page words inside repeated-sibling groups",
}
"""One line per feature, in the order the model consumes them."""

FEATURE_NAMES: Final[tuple[str, ...]] = tuple(FEATURE_DOCS)

_GROUPING: Final[MainContentConfig] = MainContentConfig(group_repeats="all", group_min_share=0.0)
"""Raw repeated-sibling groups: every group of three or more, whatever share it carries.
The model learns which groups matter; the config's share guard is the selector's rule."""


def _text_shape(text: str) -> tuple[float, float, float, float, float]:
    """digit_share, upper_share, punct_share, ends_with_sentence_mark, stopword_share."""
    stripped = text.strip()
    non_space = [c for c in stripped if not c.isspace()]
    n = len(non_space) or 1
    digits = sum(c.isdigit() for c in non_space)
    letters = [c for c in non_space if c.isalpha()]
    upper = sum(c.isupper() for c in letters)
    punct = sum(c in _PUNCT for c in non_space)
    tokens = _TOKEN.findall(stripped.lower())
    stop = sum(t in _STOPWORDS for t in tokens)
    return (
        digits / n,
        upper / (len(letters) or 1),
        punct / n,
        1.0 if _SENTENCE_END.search(stripped) else 0.0,
        stop / (len(tokens) or 1),
    )


def page_features(blocks: Sequence[Block]) -> list[list[float]]:
    """One feature vector per block, in `FEATURE_NAMES` order.

    Computed for the whole page at once because a third of the features are about the
    neighbours and the page, not the block. `blocks` should be what the production selector
    would see -- after `strip_landmarks` and `scope_to_main`.
    """
    n = len(blocks)
    if n == 0:
        return []
    nan = math.nan

    words = [word_count(b.text) for b in blocks]
    density = [link_density(b) for b in blocks]
    groups = _repeat_groups(blocks, _GROUPING)

    page_words = sum(words)
    safe_page_words = page_words or 1
    linked_words = sum(w * d for w, d in zip(words, density, strict=True))
    in_main_words = sum(w for w, b in zip(words, blocks, strict=True) if b.in_main)

    group_sizes: dict[int, int] = {}
    group_words: dict[int, int] = {}
    for g, w in zip(groups, words, strict=True):
        if g >= 0:
            group_sizes[g] = group_sizes.get(g, 0) + 1
            group_words[g] = group_words.get(g, 0) + w
    repeated_words = sum(group_words.values())

    page_level = [
        float(page_words),
        float(n),
        page_words / n,
        linked_words / safe_page_words,
        in_main_words / safe_page_words,
        repeated_words / safe_page_words,
    ]

    rows: list[list[float]] = []
    for i, block in enumerate(blocks):
        w = words[i]
        d = density[i]
        g = groups[i]
        digit, upper, punct, sentence, stop = _text_shape(block.text)
        rich = block.rich_text
        region = block.region

        row: list[float] = [
            float(w),
            math.log1p(w),
            w / safe_page_words,
            d,
            float(len(block.text)),
            digit,
            upper,
            punct,
            sentence,
            stop,
        ]
        row.extend(1.0 if block.kind is kind else 0.0 for kind in _KINDS)
        row.append(float(block.level) if block.kind is BlockKind.HEADING else 0.0)
        row.append(float(block.xpath.count("/")))
        row.append(1.0 if block.in_main else 0.0)
        row.extend(1.0 if region == r else 0.0 for r in _REGIONS)
        row.append(1.0 if region is None else 0.0)
        row.append(i / (n - 1) if n > 1 else 0.0)
        row.append(1.0 if rich and "](" in rich else 0.0)
        row.append(1.0 if d >= 0.99 else 0.0)
        # repetition
        row.append(float(group_sizes.get(g, 0)) if g >= 0 else 0.0)
        row.append(group_words.get(g, 0) / safe_page_words if g >= 0 else 0.0)
        # neighbours
        if i > 0:
            row.extend(
                (
                    float(words[i - 1]),
                    density[i - 1],
                    float(_KIND_CODE[blocks[i - 1].kind]),
                    1.0 if g >= 0 and groups[i - 1] == g else 0.0,
                )
            )
        else:
            row.extend((nan, nan, nan, 0.0))
        if i < n - 1:
            row.extend(
                (
                    float(words[i + 1]),
                    density[i + 1],
                    float(_KIND_CODE[blocks[i + 1].kind]),
                    1.0 if g >= 0 and groups[i + 1] == g else 0.0,
                )
            )
        else:
            row.extend((nan, nan, nan, 0.0))
        row.extend(page_level)
        rows.append(row)
    return rows


@dataclass(frozen=True, slots=True)
class BlockModel:
    """A boosted tree ensemble over `FEATURE_NAMES`, evaluated in pure Python.

    `trees` holds one flat node table per tree; each node is
    `(feature, threshold, left, right, value, missing_goes_left)` and a leaf has
    `feature == -1`. See the module docstring for the exact link function.
    """

    features: tuple[str, ...]
    baseline: float
    trees: tuple[tuple[tuple[int, float, int, int, float, bool], ...], ...]
    threshold: float = 0.5
    """Keep a block when its probability is at least this. The training run picks it by
    cross-validated page-level F1 and stores it in the JSON."""

    min_share: float = 0.02
    """Fail-open guard: when the kept blocks hold less than this share of the page's words,
    keep everything -- the same rule `MainContentConfig.min_run_share` follows."""

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> BlockModel:
        if data.get("format") != MODEL_FORMAT:
            raise ValueError(f"unexpected block model format {data.get('format')!r}")
        features = tuple(str(f) for f in _as_list(data["features"]))
        if features != FEATURE_NAMES:
            raise ValueError("block model was trained on a different feature set")
        trees = tuple(
            tuple(_node(node) for node in _as_list(tree)) for tree in _as_list(data["trees"])
        )
        return cls(
            features=features,
            baseline=float(_as_float(data["baseline"])),
            trees=trees,
            threshold=float(_as_float(data.get("threshold", 0.5))),
            min_share=float(_as_float(data.get("min_share", 0.02))),
        )

    @classmethod
    def load(cls) -> BlockModel:
        """The model packaged with the engine (`webgraph/models/block_gbdt.json`).

        Parses 327 KB of JSON each call. Callers on a hot path want `default_model()`.
        """
        text = resources.files("webgraph").joinpath("models/block_gbdt.json").read_text("utf-8")
        data: dict[str, object] = json.loads(text)
        return cls.from_dict(data)

    @property
    def n_trees(self) -> int:
        return len(self.trees)

    def raw_score(self, features: Sequence[float]) -> float:
        """baseline + sum of reached leaf values, exactly as scikit-learn computes it."""
        total = self.baseline
        for nodes in self.trees:
            node = nodes[0]
            while node[0] >= 0:
                x = features[node[0]]
                if x != x:  # NaN: scikit-learn's missing-value branch
                    node = nodes[node[2] if node[5] else node[3]]
                elif x <= node[1]:
                    node = nodes[node[2]]
                else:
                    node = nodes[node[3]]
            total += node[4]
        return total

    def predict_proba(self, features: Sequence[float]) -> float:
        """Probability that the block is content."""
        raw = self.raw_score(features)
        if raw >= 0:
            return 1.0 / (1.0 + math.exp(-raw))
        e = math.exp(raw)
        return e / (1.0 + e)

    def score(self, blocks: Sequence[Block]) -> list[float]:
        """One probability per block, from the page's own feature rows."""
        return [self.predict_proba(row) for row in page_features(blocks)]


def select_by_model(
    blocks: Sequence[Block],
    model: BlockModel,
    *,
    threshold: float | None = None,
    min_share: float | None = None,
) -> list[Block]:
    """Keep the blocks the model scores at or above the threshold, failing open.

    Order is preserved; the model does not draw a boundary, so a comment thread below an
    article and a product grid beside a description are both kept if they score as content.
    When the kept blocks hold less than `min_share` of the page's words the page has no
    content the model believes in, and everything is returned rather than a fragment.
    """
    if not blocks:
        return []
    cut = model.threshold if threshold is None else threshold
    share = model.min_share if min_share is None else min_share
    probabilities = model.score(blocks)
    kept = [b for b, p in zip(blocks, probabilities, strict=True) if p >= cut]
    if not kept:
        return list(blocks)
    total = sum(word_count(b.text) for b in blocks)
    if total and sum(word_count(b.text) for b in kept) < total * share:
        return list(blocks)
    return kept


@lru_cache(maxsize=1)
def default_model() -> BlockModel | None:
    """The shipped model, parsed once per process, or None if the engine ships none.

    `select_content` calls this, so every production path -- the crawl, `/api/text`, the CLI
    -- gets the model without each one having to know it exists. Returning None rather than
    raising keeps a tree with the JSON removed working: the boundary step runs instead.
    """
    try:
        return BlockModel.load()
    except (FileNotFoundError, ModuleNotFoundError, ValueError):
        return None


def _as_list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("malformed block model: expected a list")
    return value


def _node(value: object) -> tuple[int, float, int, int, float, bool]:
    node = _as_list(value)
    if len(node) != 6:
        raise ValueError("malformed block model: a node has six fields")
    return (
        int(_as_float(node[0])),
        _as_float(node[1]),
        int(_as_float(node[2])),
        int(_as_float(node[3])),
        _as_float(node[4]),
        bool(node[5]),
    )


def _as_float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("malformed block model: expected a number")
    return float(value)
