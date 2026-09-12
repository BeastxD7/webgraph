"""Train, cross-validate and export the per-block keep/drop model (`webgraph.blockmodel`).

Reads the set `blockmodel_data.py` built from WCXB **dev**. Every number this prints is
5-fold cross-validated with whole pages held out (a page's blocks never straddle folds, and
folds are balanced by page type), because the block-level fit is not the number that
matters: the page-level word F1 of the text the model keeps is, and it is measured with
the corpus's own metric against the production selector on identical parses.

What it reports
---------------
* per-block accuracy and AUC out of fold, for each candidate setting
* page-level F1 by page type for: the production selector, the model at several thresholds
  (with the 2% fail-open guard), and a hybrid that runs the contiguous selector on the
  blocks the model scores >= 0.3
* permutation importance of every feature, on held-out blocks
* the worst pages per type, so somebody can read them (`blockmodel_inspect.py`)

Then it trains the chosen setting on all of dev, exports it to
`packages/engine/src/webgraph/models/block_gbdt.json`, and refuses to keep the file unless
the pure-Python predictor agrees with scikit-learn to 1e-9 on 20,000 random blocks.

    cd packages/engine && uv run --group bench python ../../benchmark/train/blockmodel_train.py
"""

from __future__ import annotations

import argparse
import gzip
import json
import random
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import roc_auc_score

from webgraph.blockmodel import FEATURE_NAMES, MODEL_FORMAT, BlockModel
from webgraph.main_content import select_main_content, word_count
from webgraph.types import Block, BlockKind

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "wcxb"))
from analyze import prf

TRAIN_DIR = Path(
    "/private/tmp/claude-501/-Users-shashank-Desktop-shashank-codes-webgraph/"
    "c0642a19-5001-45ad-9934-ec93af8ed544/scratchpad/train"
)
MODEL_PATH = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "engine"
    / "src"
    / "webgraph"
    / "models"
    / "block_gbdt.json"
)
TYPE_ORDER = ("article", "documentation", "service", "forum", "collection", "listing", "product")
THRESHOLDS = (0.3, 0.4, 0.5, 0.6, 0.7)
FAIL_OPEN_SHARE = 0.02
HYBRID_THRESHOLD = 0.3

CANDIDATES: dict[str, dict[str, Any]] = {
    "d6-i150-lr0.1": {"max_iter": 150, "max_depth": 6, "learning_rate": 0.1},
    "d4-i100-lr0.1": {"max_iter": 100, "max_depth": 4, "learning_rate": 0.1},
    "d6-i300-lr0.05": {"max_iter": 300, "max_depth": 6, "learning_rate": 0.05},
    "d5-i60-lr0.15": {"max_iter": 60, "max_depth": 5, "learning_rate": 0.15},
}


@dataclass(slots=True)
class Page:
    id: str
    type: str
    reference: str
    production_text: str
    texts: list[str]
    labels: list[int]
    words: list[int]
    blocks: list[Block]
    start: int  # row offset into X


def load(path: Path) -> tuple[list[Page], np.ndarray, np.ndarray]:
    pages: list[Page] = []
    rows: list[list[float]] = []
    labels: list[int] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            start = len(rows)
            blocks: list[Block] = []
            texts: list[str] = []
            page_labels: list[int] = []
            for i, b in enumerate(record["blocks"]):
                rows.append(b["f"])
                labels.append(b["y"])
                texts.append(b["text"])
                page_labels.append(b["y"])
                blocks.append(
                    Block(
                        text=b["text"],
                        tag=b["tag"],
                        xpath=b["xpath"],
                        dom_index=i,
                        kind=BlockKind(b["kind"]),
                        level=b["level"],
                        region=b["region"],
                        in_main=b["in_main"],
                        rich_text=b["rich_text"],
                    )
                )
            pages.append(
                Page(
                    id=record["id"],
                    type=record["type"],
                    reference=record["reference"],
                    production_text=record["production_text"],
                    texts=texts,
                    labels=page_labels,
                    words=[word_count(t) for t in texts],
                    blocks=blocks,
                    start=start,
                )
            )
    X = np.asarray(rows, dtype=np.float64)  # noqa: N806 - scikit-learn's name
    y = np.asarray(labels, dtype=np.int64)
    return pages, X, y


def assign_folds(pages: list[Page], k: int, seed: int) -> np.ndarray:
    """Fold per page, balanced by type: shuffle within type, deal round-robin."""
    rng = random.Random(seed)
    folds = np.zeros(len(pages), dtype=np.int64)
    by_type: dict[str, list[int]] = defaultdict(list)
    for i, page in enumerate(pages):
        by_type[page.type].append(i)
    for indices in by_type.values():
        rng.shuffle(indices)
        for j, i in enumerate(indices):
            folds[i] = j % k
    return folds


def block_folds(pages: list[Page], page_folds: np.ndarray, n_rows: int) -> np.ndarray:
    out = np.zeros(n_rows, dtype=np.int64)
    for page, fold in zip(pages, page_folds, strict=True):
        out[page.start : page.start + len(page.texts)] = fold
    return out


def make(params: dict[str, Any]) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(early_stopping=False, random_state=0, **params)


def join(texts: list[str]) -> str:
    return "\n\n".join(t for t in texts if t.strip())


def keep_text(page: Page, probs: np.ndarray, threshold: float) -> str:
    """Model selection with the fail-open guard, as `select_by_model` does it."""
    kept = [i for i, p in enumerate(probs) if p >= threshold]
    total = sum(page.words)
    if not kept or (total and sum(page.words[i] for i in kept) < total * FAIL_OPEN_SHARE):
        return join(page.texts)
    return join([page.texts[i] for i in kept])


def hybrid_text(page: Page, probs: np.ndarray, threshold: float) -> str:
    """Kadane over the blocks the model does not reject outright."""
    candidates = [b for b, p in zip(page.blocks, probs, strict=True) if p >= threshold]
    if not candidates:
        candidates = list(page.blocks)
    selected = select_main_content(candidates)
    total = sum(page.words)
    kept = sum(word_count(b.text) for b in selected)
    if total and kept < total * FAIL_OPEN_SHARE:
        return join(page.texts)
    return join([b.text for b in selected])


def by_type_table(scores: dict[str, list[tuple[float, float, float]]]) -> dict[str, dict[str, float]]:
    """{type: {P, R, F1, N}} plus overall, from {page id -> (p, r, f)} lists per type."""
    out: dict[str, dict[str, float]] = {}
    all_scores: list[tuple[float, float, float]] = []
    for page_type, values in scores.items():
        all_scores.extend(values)
        out[page_type] = {
            "N": len(values),
            "P": mean(v[0] for v in values),
            "R": mean(v[1] for v in values),
            "F1": mean(v[2] for v in values),
        }
    out["overall"] = {
        "N": len(all_scores),
        "P": mean(v[0] for v in all_scores),
        "R": mean(v[1] for v in all_scores),
        "F1": mean(v[2] for v in all_scores),
    }
    return out


def score_variant(pages: list[Page], text_of: Any) -> tuple[dict[str, dict[str, float]], dict[str, tuple[float, float, float]]]:
    per_type: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
    per_page: dict[str, tuple[float, float, float]] = {}
    for page in pages:
        s = prf(text_of(page), page.reference)
        per_type[page.type].append(s)
        per_page[page.id] = s
    return by_type_table(per_type), per_page


def print_table(title: str, tables: dict[str, dict[str, dict[str, float]]]) -> None:
    names = list(tables)
    print(f"\n{title}")
    print(f"  {'type':<15} {'N':>5}" + "".join(f" {n[:14]:>15}" for n in names))
    print("  " + "-" * (21 + 16 * len(names)))
    for page_type in (*TYPE_ORDER, "overall"):
        row = tables[names[0]].get(page_type)
        if row is None:
            continue
        print(f"  {page_type:<15} {int(row['N']):>5}", end="")
        for n in names:
            print(f" {tables[n][page_type]['F1']:>15.3f}", end="")
        print()
    print(f"  {'overall P':<15} {'':>5}" + "".join(f" {tables[n]['overall']['P']:>15.3f}" for n in names))
    print(f"  {'overall R':<15} {'':>5}" + "".join(f" {tables[n]['overall']['R']:>15.3f}" for n in names))


def export(model: HistGradientBoostingClassifier, threshold: float, meta: dict[str, Any]) -> dict[str, Any]:
    trees: list[list[list[Any]]] = []
    for (predictor,) in model._predictors:
        nodes = predictor.nodes
        table: list[list[Any]] = []
        for node in nodes:
            if node["is_leaf"]:
                table.append([-1, 0.0, 0, 0, float(node["value"]), False])
            else:
                if node["is_categorical"]:
                    raise SystemExit("categorical splits are not exported")
                table.append(
                    [
                        int(node["feature_idx"]),
                        float(node["num_threshold"]),
                        int(node["left"]),
                        int(node["right"]),
                        0.0,
                        bool(node["missing_go_to_left"]),
                    ]
                )
        trees.append(table)
    baseline = float(np.asarray(model._baseline_prediction).ravel()[0])
    return {
        "format": MODEL_FORMAT,
        "features": list(FEATURE_NAMES),
        "baseline": baseline,
        "link": "sigmoid(baseline + sum of leaf values)",
        "threshold": threshold,
        "min_share": FAIL_OPEN_SHARE,
        "trees": trees,
        "meta": meta,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=TRAIN_DIR / "blocks.jsonl.gz")
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, default=MODEL_PATH)
    parser.add_argument("--candidates", nargs="*", default=list(CANDIDATES))
    parser.add_argument(
        "--reuse-oof",
        action="store_true",
        help="load oof_<candidate>.npy from a previous run instead of refitting the folds",
    )
    args = parser.parse_args()

    t0 = time.perf_counter()
    pages, X, y = load(args.data)  # noqa: N806
    print(f"loaded {len(pages)} pages, {len(y)} blocks, {y.mean():.1%} positive, "
          f"{X.shape[1]} features in {time.perf_counter() - t0:.1f}s")
    assert X.shape[1] == len(FEATURE_NAMES)
    print("  by type:", dict(sorted(Counter(p.type for p in pages).items())))

    page_folds = assign_folds(pages, args.folds, args.seed)
    row_folds = block_folds(pages, page_folds, len(y))

    tables: dict[str, dict[str, dict[str, float]]] = {}
    production_table, production_pages = score_variant(pages, lambda p: p.production_text)
    tables["production"] = production_table

    results: dict[str, Any] = {"production": production_table, "candidates": {}}
    oof_by_candidate: dict[str, np.ndarray] = {}
    for name in args.candidates:
        params = CANDIDATES[name]
        t1 = time.perf_counter()
        if args.reuse_oof:
            oof = np.load(TRAIN_DIR / f"oof_{name}.npy")
            assert len(oof) == len(y)
        else:
            oof = np.zeros(len(y), dtype=np.float64)
            for fold in range(args.folds):
                train = row_folds != fold
                model = make(params).fit(X[train], y[train])
                oof[~train] = model.predict_proba(X[~train])[:, 1]
        fit_time = time.perf_counter() - t1
        oof_by_candidate[name] = oof
        accuracy = float(((oof >= 0.5).astype(int) == y).mean())
        auc = float(roc_auc_score(y, oof))
        print(f"\n[{name}] {params}  cv fits {fit_time:.0f}s  block acc {accuracy:.4f}  auc {auc:.4f}")

        entry: dict[str, Any] = {"params": params, "block_accuracy": accuracy, "block_auc": auc, "thresholds": {}}
        for threshold in THRESHOLDS:
            table, _ = score_variant(
                pages,
                lambda p, t=threshold, o=oof: keep_text(p, o[p.start : p.start + len(p.texts)], t),
            )
            entry["thresholds"][str(threshold)] = table
            tables[f"{name}@{threshold}"] = table
            print(f"   @{threshold}: F1 {table['overall']['F1']:.4f}  P {table['overall']['P']:.3f}  R {table['overall']['R']:.3f}")
        hybrid, _ = score_variant(
            pages,
            lambda p, o=oof: hybrid_text(p, o[p.start : p.start + len(p.texts)], HYBRID_THRESHOLD),
        )
        entry["hybrid"] = hybrid
        tables[f"{name}-hybrid"] = hybrid
        print(f"   hybrid(>= {HYBRID_THRESHOLD} then Kadane): F1 {hybrid['overall']['F1']:.4f}  P {hybrid['overall']['P']:.3f}  R {hybrid['overall']['R']:.3f}")
        results["candidates"][name] = entry
        np.save(TRAIN_DIR / f"oof_{name}.npy", oof)

    # Pick the candidate and threshold by CV page F1.
    best_name, best_threshold, best_f1 = "", 0.5, -1.0
    for name, entry in results["candidates"].items():
        for threshold, table in entry["thresholds"].items():
            if table["overall"]["F1"] > best_f1:
                best_name, best_threshold, best_f1 = name, float(threshold), table["overall"]["F1"]
    print(f"\nchosen: {best_name} @ {best_threshold}  (cv page F1 {best_f1:.4f})")
    results["chosen"] = {"candidate": best_name, "threshold": best_threshold, "cv_page_f1": best_f1}

    print_table(
        "CV page-level F1 by type",
        {
            "production": production_table,
            "model@0.5": results["candidates"][best_name]["thresholds"]["0.5"],
            f"model@{best_threshold}": results["candidates"][best_name]["thresholds"][str(best_threshold)],
            "hybrid": results["candidates"][best_name]["hybrid"],
        },
    )
    print_table("All candidates at 0.5", {n: results["candidates"][n]["thresholds"]["0.5"] for n in args.candidates})

    # Worst pages per type at the chosen setting, from out-of-fold predictions.
    oof = oof_by_candidate[best_name]
    _, model_pages = score_variant(
        pages, lambda p: keep_text(p, oof[p.start : p.start + len(p.texts)], best_threshold)
    )
    worst: dict[str, list[dict[str, Any]]] = {}
    for page_type in TYPE_ORDER:
        ranked = sorted((p for p in pages if p.type == page_type), key=lambda p: model_pages[p.id][2])
        worst[page_type] = [
            {
                "id": p.id,
                "model": [round(v, 3) for v in model_pages[p.id]],
                "production": [round(v, 3) for v in production_pages[p.id]],
            }
            for p in ranked[:5]
        ]
    results["worst"] = worst
    print("\nWorst 5 pages per type at the chosen setting (model P/R/F1 | production P/R/F1)")
    for page_type, entries in worst.items():
        print(f"  {page_type}: " + "  ".join(f"{e['id']} {e['model'][2]:.2f}|{e['production'][2]:.2f}" for e in entries))

    # Permutation importance on fold 0's held-out blocks (a subsample), AUC as the score.
    params = CANDIDATES[best_name]
    train = row_folds != 0
    model0 = make(params).fit(X[train], y[train])
    held = np.flatnonzero(~train)
    rng = np.random.default_rng(args.seed)
    sample = rng.choice(held, size=min(30000, len(held)), replace=False)
    t2 = time.perf_counter()
    perm = permutation_importance(
        model0, X[sample], y[sample], scoring="roc_auc", n_repeats=3, random_state=args.seed
    )
    order = np.argsort(-perm.importances_mean)
    print(f"\nPermutation importance (AUC drop, fold-0 held-out, {len(sample)} blocks, {time.perf_counter() - t2:.0f}s)")
    for rank, i in enumerate(order[:20], 1):
        print(f"  {rank:>2} {FEATURE_NAMES[i]:<24} {perm.importances_mean[i]:+.4f} +/- {perm.importances_std[i]:.4f}")
    results["importance"] = {FEATURE_NAMES[i]: float(perm.importances_mean[i]) for i in order}

    # Final model on all of dev, exported, and proven equivalent to scikit-learn.
    t3 = time.perf_counter()
    final = make(params).fit(X, y)
    print(f"\nfinal fit on all dev: {time.perf_counter() - t3:.1f}s, {len(final._predictors)} trees, "
          f"{sum(len(p[0].nodes) for p in final._predictors)} nodes")
    payload = export(
        final,
        best_threshold,
        {
            "trained_on": "WCXB dev split only",
            "pages": len(pages),
            "blocks": len(y),
            "params": params,
            "cv_folds": args.folds,
            "cv_page_f1": round(best_f1, 4),
            "cv_block_auc": round(results["candidates"][best_name]["block_auc"], 4),
        },
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    size = args.out.stat().st_size
    print(f"wrote {args.out} ({size / 1024:.0f} KB)")

    t4 = time.perf_counter()
    loaded = BlockModel.load()
    load_ms = (time.perf_counter() - t4) * 1000
    check = rng.choice(len(y), size=min(20000, len(y)), replace=False)
    sk = final.predict_proba(X[check])[:, 1]
    py = np.array([loaded.predict_proba(X[i].tolist()) for i in check])
    max_diff = float(np.max(np.abs(sk - py)))
    print(f"equivalence on {len(check)} blocks: max |sklearn - python| = {max_diff:.3e}  ({'OK' if max_diff < 1e-9 else 'FAIL'})")
    if max_diff >= 1e-9:
        args.out.unlink()
        raise SystemExit("exported model does not reproduce scikit-learn; file removed")

    rows = [X[i].tolist() for i in check[:1000]]
    t5 = time.perf_counter()
    for row in rows:
        loaded.predict_proba(row)
    predict_ms = (time.perf_counter() - t5) * 1000
    from webgraph.blockmodel import page_features

    sample_page = max(pages, key=lambda p: len(p.blocks))
    t6 = time.perf_counter()
    page_features(sample_page.blocks)
    feature_ms = (time.perf_counter() - t6) * 1000 / len(sample_page.blocks) * 1000
    print(f"load {load_ms:.0f} ms; predict {predict_ms:.1f} ms / 1000 blocks; features {feature_ms:.1f} ms / 1000 blocks (page of {len(sample_page.blocks)})")
    results["export"] = {
        "bytes": size,
        "load_ms": load_ms,
        "predict_ms_per_1000": predict_ms,
        "features_ms_per_1000": feature_ms,
        "max_abs_diff": max_diff,
        "trees": len(final._predictors),
    }
    (TRAIN_DIR / "cv_report.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    np.save(TRAIN_DIR / "page_folds.npy", page_folds)


if __name__ == "__main__":
    main()
