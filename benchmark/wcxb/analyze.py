r"""Where, exactly, does the engine lose on WCXB -- by page type, by failure class, by page.

`run.py` produces a number per variant. This turns the `--out` predictions it wrote into a
diagnosis, because a number says *that* we lose and a diagnosis says *what to change*.

For every page and variant it computes the official word-level P/R/F1 and then classifies
the page's dominant failure against the `landmarks` variant (the complete block list minus
declared landmarks -- the recall ceiling the selector starts from):

    over-cut     recall fell by more than `--cut` against landmarks: the selector removed
                 content the ground truth wanted
    leak         precision below `--leak` while recall held: the selector kept boilerplate
    ceiling      landmarks itself is already below `--ceiling` recall: the parser never
                 emitted the text, so no selector can recover it
    ok           none of the above

It also reports which `with[]` snippets (must keep) are missing and which `without[]`
snippets (must drop) are present, per type, and prints the worst pages per type with the
first and last kept block so the boundary decision can be read directly.

    uv run --package webgraph python benchmark/wcxb/analyze.py \
        --corpus <clone> --predictions <run.py --out dir> --split dev
    ... --type product --worst 15          # one type, more pages
    ... --variant content                  # which variant to diagnose (default content)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

TYPE_ORDER = ("article", "documentation", "service", "forum", "collection", "listing", "product")


def tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower()) if text else []


def prf(predicted: str, reference: str) -> tuple[float, float, float]:
    """The corpus's own `word_f1`, restated exactly (see run.py for why importing is fragile)."""
    pred, ref = tokenize(predicted), tokenize(reference)
    if not ref:
        return (1.0, 1.0, 1.0) if not pred else (0.0, 0.0, 0.0)
    if not pred:
        return (0.0, 0.0, 0.0)
    overlap = sum((Counter(pred) & Counter(ref)).values())
    p = overlap / len(pred)
    r = overlap / len(ref)
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def _norm(text: str) -> str:
    return " ".join(tokenize(text))


@dataclass(slots=True)
class Page:
    file_id: str
    page_type: str
    url: str
    reference: str
    with_snippets: list[str]
    without_snippets: list[str]


def load_ground_truth(corpus: Path, split: str) -> dict[str, Page]:
    pages: dict[str, Page] = {}
    for path in sorted((corpus / split / "ground-truth").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        gt = data.get("ground_truth") or {}
        page_type = ((data.get("_internal") or {}).get("page_type") or {}).get("primary", "unknown")
        file_id = str(data.get("file_id") or path.stem)
        pages[file_id] = Page(
            file_id=file_id,
            page_type=page_type,
            url=data.get("url", ""),
            reference=gt.get("main_content", ""),
            with_snippets=list(gt.get("with") or []),
            without_snippets=list(gt.get("without") or []),
        )
    return pages


def load_predictions(predictions: Path, variant: str, split: str) -> dict[str, str]:
    path = predictions / f"webgraph-{variant}-{split}.json"
    if not path.is_file():
        raise SystemExit(f"no predictions at {path}; run run.py with --out first")
    return json.loads(path.read_text(encoding="utf-8"))


def classify(
    target: tuple[float, float, float],
    ceiling: tuple[float, float, float],
    *,
    cut: float,
    leak: float,
    floor: float,
) -> str:
    _, r_t, _ = target
    p_t = target[0]
    _, r_c, _ = ceiling
    if r_c < floor:
        return "ceiling"
    if r_c - r_t > cut:
        return "over-cut"
    if p_t < leak:
        return "leak"
    return "ok"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--split", default="dev", choices=("dev", "test"))
    parser.add_argument("--variant", default="content")
    parser.add_argument("--baseline", default="landmarks", help="the recall ceiling to compare against")
    parser.add_argument("--type", dest="only_type", default=None)
    parser.add_argument("--worst", type=int, default=8)
    parser.add_argument("--cut", type=float, default=0.15, help="recall drop vs baseline that counts as over-cut")
    parser.add_argument("--leak", type=float, default=0.70, help="precision below this counts as a leak")
    parser.add_argument("--floor", type=float, default=0.60, help="baseline recall below this is a parser ceiling")
    parser.add_argument("--json", type=Path, default=None, help="write the per-page table here")
    args = parser.parse_args()

    pages = load_ground_truth(args.corpus, args.split)
    target = load_predictions(args.predictions, args.variant, args.split)
    base = load_predictions(args.predictions, args.baseline, args.split)

    rows: list[dict[str, object]] = []
    for fid, page in pages.items():
        if args.only_type and page.page_type != args.only_type:
            continue
        t = prf(target.get(fid, ""), page.reference)
        c = prf(base.get(fid, ""), page.reference)
        out_norm = _norm(target.get(fid, ""))
        missing = [s for s in page.with_snippets if _norm(s) and _norm(s) not in out_norm]
        leaked = [s for s in page.without_snippets if _norm(s) and _norm(s) in out_norm]
        rows.append(
            {
                "file_id": fid,
                "type": page.page_type,
                "url": page.url,
                "p": t[0], "r": t[1], "f1": t[2],
                "base_p": c[0], "base_r": c[1], "base_f1": c[2],
                "class": classify(t, c, cut=args.cut, leak=args.leak, floor=args.floor),
                "missing_with": missing,
                "leaked_without": leaked,
                "pred_tokens": len(tokenize(target.get(fid, ""))),
                "ref_tokens": len(tokenize(page.reference)),
            }
        )

    by_type: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_type[str(row["type"])].append(row)

    print(f"WCXB {args.split}: variant `{args.variant}` diagnosed against `{args.baseline}` "
          f"({len(rows)} pages)\n")
    print(f"{'type':<14}{'N':>5}{'F1':>8}{'P':>7}{'R':>7} | {'base F1':>8}{'base R':>7} | "
          f"{'over-cut':>9}{'leak':>6}{'ceiling':>8}{'ok':>5} | {'miss with':>10}{'keep w/o':>9}")
    for page_type in [*TYPE_ORDER, *sorted(set(by_type) - set(TYPE_ORDER))]:
        group = by_type.get(page_type)
        if not group:
            continue
        classes = Counter(str(r["class"]) for r in group)
        n_with = sum(len(pages[str(r["file_id"])].with_snippets) for r in group)
        n_without = sum(len(pages[str(r["file_id"])].without_snippets) for r in group)
        missing = sum(len(r["missing_with"]) for r in group)  # type: ignore[arg-type]
        leaked = sum(len(r["leaked_without"]) for r in group)  # type: ignore[arg-type]
        print(
            f"{page_type:<14}{len(group):>5}"
            f"{mean(float(r['f1']) for r in group):>8.3f}"
            f"{mean(float(r['p']) for r in group):>7.3f}"
            f"{mean(float(r['r']) for r in group):>7.3f} | "
            f"{mean(float(r['base_f1']) for r in group):>8.3f}"
            f"{mean(float(r['base_r']) for r in group):>7.3f} | "
            f"{classes['over-cut']:>9}{classes['leak']:>6}{classes['ceiling']:>8}{classes['ok']:>5} | "
            f"{missing:>5}/{n_with:<4}{leaked:>5}/{n_without:<4}"
        )
    print(f"{'all':<14}{len(rows):>5}{mean(float(r['f1']) for r in rows):>8.3f}"
          f"{mean(float(r['p']) for r in rows):>7.3f}{mean(float(r['r']) for r in rows):>7.3f}")

    # What would fixing each class be worth? Replace each page's F1 with its baseline F1
    # for over-cut pages (the selector did nothing), with 1.0-recall-at-current... no: with
    # the baseline recall and perfect precision (an upper bound), for leak pages.
    print("\nheadroom if a class were fixed (mean F1 over all pages, upper bounds):")
    for cls in ("over-cut", "leak", "ceiling"):
        adjusted = []
        for r in rows:
            if r["class"] == cls:
                if cls == "over-cut":
                    adjusted.append(max(float(r["f1"]), float(r["base_f1"])))
                else:
                    rr = float(r["base_r"]) if cls == "leak" else 1.0
                    adjusted.append(2 * rr / (1 + rr) if rr else 0.0)
            else:
                adjusted.append(float(r["f1"]))
        print(f"  {cls:<9} -> {mean(adjusted):.3f}")

    # Worst pages per type, with the boundary readable.
    for page_type in [*TYPE_ORDER, *sorted(set(by_type) - set(TYPE_ORDER))]:
        group = by_type.get(page_type)
        if not group:
            continue
        worst = sorted(group, key=lambda r: float(r["f1"]))[: args.worst]
        print(f"\n== worst {page_type} pages ==")
        for r in worst:
            fid = str(r["file_id"])
            text = target.get(fid, "")
            blocks = [b for b in text.split("\n\n") if b.strip()]
            first = blocks[0][:90] if blocks else ""
            last = blocks[-1][:90] if len(blocks) > 1 else ""
            print(f"  {fid}  F1 {float(r['f1']):.3f} P {float(r['p']):.2f} R {float(r['r']):.2f} "
                  f"(base R {float(r['base_r']):.2f}) {r['class']:<8} "
                  f"pred {r['pred_tokens']}w / ref {r['ref_tokens']}w  {r['url'][:70]}")
            if r["missing_with"]:
                print(f"      missing: {str(r['missing_with'][0])[:100]!r}")  # type: ignore[index]
            if r["leaked_without"]:
                print(f"      leaked : {str(r['leaked_without'][0])[:100]!r}")  # type: ignore[index]
            if first:
                print(f"      first  : {first!r}")
            if last:
                print(f"      last   : {last!r}")

    if args.json:
        args.json.write_text(json.dumps(rows, indent=1), encoding="utf-8")
        print(f"\nwrote {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
