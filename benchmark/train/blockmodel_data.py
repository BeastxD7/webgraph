"""Build the per-block training set for `webgraph.blockmodel` from WCXB **dev** only.

For every dev page: parse with `build_document`, apply `strip_landmarks` then `scope_to_main`
(exactly the steps the production selector runs before it draws its boundary), compute one
feature row per block with `page_features`, and label each block against the ground truth.

Label
-----
1 when the block's normalised token string (three or more tokens) is a substring of the
normalised ground-truth token string -- the block's text appears verbatim in what the
annotator kept. For blocks of one or two tokens (a price, a heading word) the substring
test is too easy to hit by accident, so those are 1 only when every token is in the
ground-truth token bag. Everything else is 0.

Output
------
One gzipped JSON line per page in `<out>/blocks.jsonl.gz`: page id, page type, the
production selector's text for that page (so the comparison is on identical parses), and
per block the feature row, label, and enough of the block to rebuild it for the hybrid
experiment (text, tag, xpath, kind, level, region, in_main, rich_text). Nothing from the
test split is read, ever: the corpus path is joined with `dev` and only `dev`.

    cd packages/engine && uv run --group bench python ../../benchmark/train/blockmodel_data.py
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

DEFAULT_CORPUS = Path(
    "/private/tmp/claude-501/-Users-shashank-Desktop-shashank-codes-webgraph/"
    "c0642a19-5001-45ad-9934-ec93af8ed544/scratchpad/corpora/wcxb"
)
DEFAULT_OUT = DEFAULT_CORPUS.parent.parent / "train"

_TOKEN = re.compile(r"\w+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower()) if text else []


def label_block(text: str, reference_norm: str, reference_bag: Counter[str]) -> int:
    tokens = tokenize(text)
    if not tokens:
        return 0
    if len(tokens) >= 3:
        return 1 if f" {' '.join(tokens)} " in reference_norm else 0
    return 1 if all(reference_bag[t] > 0 for t in tokens) else 0


def process(args: tuple[Path, str]) -> dict[str, object] | None:
    corpus, file_id = args
    from webgraph.blockmodel import page_features
    from webgraph.boilerplate import scope_to_main, strip_landmarks
    from webgraph.content import select_content
    from webgraph.pipeline import build_document

    gt_path = corpus / "dev" / "ground-truth" / f"{file_id}.json"
    html_path = corpus / "dev" / "html" / f"{file_id}.html.gz"
    data = json.loads(gt_path.read_text(encoding="utf-8"))
    reference = (data.get("ground_truth") or {}).get("main_content") or ""
    page_type = ((data.get("_internal") or {}).get("page_type") or {}).get("primary", "unknown")
    url = data.get("url") or "https://example.invalid/"
    try:
        with gzip.open(html_path, "rt", encoding="utf-8", errors="replace") as handle:
            html = handle.read()
        document = build_document(html, url)
    except Exception as exc:
        print(f"{file_id}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None

    all_blocks = list(document.blocks)
    production = select_content(all_blocks)
    blocks = scope_to_main(strip_landmarks(all_blocks))
    rows = page_features(blocks)

    ref_tokens = tokenize(reference)
    ref_norm = f" {' '.join(ref_tokens)} "
    ref_bag = Counter(ref_tokens)

    return {
        "id": file_id,
        "type": page_type,
        "reference": reference,
        "production_text": "\n\n".join(b.text for b in production.blocks if b.text.strip()),
        "blocks": [
            {
                "f": row,
                "y": label_block(b.text, ref_norm, ref_bag),
                "text": b.text,
                "tag": b.tag,
                "xpath": b.xpath,
                "kind": str(b.kind),
                "level": b.level,
                "region": b.region,
                "in_main": b.in_main,
                "rich_text": b.rich_text,
            }
            for row, b in zip(rows, blocks, strict=True)
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    ids = sorted(p.stem for p in (args.corpus / "dev" / "ground-truth").glob("*.json"))
    if args.limit:
        ids = ids[: args.limit]
    args.out.mkdir(parents=True, exist_ok=True)
    out_path = args.out / "blocks.jsonl.gz"

    pages = blocks = positives = 0
    types: Counter[str] = Counter()
    with (
        gzip.open(out_path, "wt", encoding="utf-8") as out,
        ProcessPoolExecutor(max_workers=args.workers) as pool,
    ):
        for record in pool.map(process, [(args.corpus, i) for i in ids], chunksize=4):
            if record is None:
                continue
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            pages += 1
            page_blocks = record["blocks"]
            assert isinstance(page_blocks, list)
            blocks += len(page_blocks)
            positives += sum(b["y"] for b in page_blocks)
            types[str(record["type"])] += 1
            if pages % 100 == 0:
                print(f"  {pages} pages, {blocks} blocks", file=sys.stderr)

    print(f"wrote {out_path}")
    print(f"pages {pages}  blocks {blocks}  positive {positives} ({positives / max(blocks, 1):.1%})")
    for page_type, count in sorted(types.items()):
        print(f"  {page_type:<15} {count}")


if __name__ == "__main__":
    main()
