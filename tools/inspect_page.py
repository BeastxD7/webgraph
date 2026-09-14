"""Show a live page block by block, through the production path.

Every extraction bug this engine has fixed was found by reading a page this way: the
blocks in reading order, each with the value the boundary step assigned it, whether it
was chosen, which landmark and widget it sits in, and whether it carries a rendered box.
The pull-request template asks for reproduction steps that anyone can run; this is the
command those steps use.

    uv run python tools/inspect_page.py https://www.apple.com/iphone/
    uv run python tools/inspect_page.py https://linear.app/ --chosen        # chosen blocks only
    uv run python tools/inspect_page.py https://example.com/page --grep "Most read"

The fetch is the API's own: static and rendered, merged (`resolve_page`), so a browser is
used when Playwright is installed and the result says `render_error` otherwise. The page
type comes from the router and the policy from `policy_for`, exactly as `/api/text` does.

Columns: index, IN/out, value, kind, landmark region, `m=1` inside `<main>`, widget,
`body=Y` inside a declared article body, `rect` when the renderer measured a box, text.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace

from webgraph import main_content as mc
from webgraph.boilerplate import scope_to_main, strip_landmarks
from webgraph.content import select_content
from webgraph.pagetype import PageType, default_router, policy_for
from webgraph.resolve import resolve_page


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("url")
    parser.add_argument(
        "--chosen",
        action="store_true",
        help="show only the blocks the content step kept",
    )
    parser.add_argument(
        "--grep",
        default=None,
        help="show only blocks whose text contains this (case-insensitive)",
    )
    parser.add_argument(
        "--width", type=int, default=80, help="characters of text per row"
    )
    parser.add_argument(
        "--include-hidden-text",
        action="store_true",
        help="keep screen-reader-only labels, as the API option does",
    )
    args = parser.parse_args()

    resolved = resolve_page(args.url, include_hidden_text=args.include_hidden_text)
    document = resolved.document
    router = default_router()
    routing = router.route(document) if router is not None else None
    page_type = routing.page_type if routing else PageType.UNKNOWN
    policy = policy_for(page_type)
    selection = select_content(document.blocks, config=policy, title=document.title)
    chosen = {id(b) for b in selection.blocks}

    # The cost the boundary step used, recomputed the way it computes it, so the value
    # column means what it meant inside the run.
    structural = scope_to_main(strip_landmarks(list(document.blocks)))
    mean = sum(
        min(mc.word_count(b.text), policy.cost_block_cap) for b in structural
    ) / max(1, len(structural))
    cost = min(max(policy.cost_ratio * mean, policy.cost_floor), policy.cost_ceiling)
    priced = replace(policy, block_cost=cost)

    print(
        f"{resolved.url} | type {page_type} {round(routing.confidence, 2) if routing else ''} | "
        f"strategy {resolved.strategy.value} render_error {resolved.render_error} | "
        f"reading order {document.reading_order_method.value} | blocks {len(document.blocks)} "
        f"after structural {len(structural)} chosen {len(selection.blocks)} {selection.methods} | "
        f"cost {cost:.1f} | comments set aside {len(selection.comments)}"
    )
    needle = args.grep.casefold() if args.grep else None
    for index, block in enumerate(document.blocks):
        if args.chosen and id(block) not in chosen:
            continue
        if needle and needle not in block.text.casefold():
            continue
        print(
            f"{index:4} {'IN ' if id(block) in chosen else 'out'} {mc.content_value(block, priced):7.1f} "
            f"{block.kind.value:9} {block.region!s:6} m={int(block.in_main)} w={block.widget!s:8} "
            f"body={'Y' if block.body_of else '-'} {'rect' if block.rect else 'none'} "
            f"{block.text[: args.width]!r}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
