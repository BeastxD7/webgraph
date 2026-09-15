"""Draw a random sample of real web pages nobody picked.

Every other suite in `benchmark/` is a set of pages somebody chose -- a corpus's authors,
or this project, which picked old and ugly pages, modern JavaScript pages, sites the owner
named. A failure rate on chosen pages is the failure rate on chosen pages. This draws pages
at random from two public lists so the number means something about the web:

1. **Domains** from the Tranco list (`top-1m.csv`, tranco-list.eu): a million sites ranked
   by traffic. Sampled *uniformly over the rank range*, not by traffic, so rank 900,000 is
   as likely as rank 90 -- the tail is where the odd markup lives.
2. **A page per domain** from the Common Crawl index (`index.commoncrawl.org`): the crawl's
   most recent listing for that host, one URL drawn at random among the 200-status,
   `text/html` captures. That gives inner pages, not home pages, in whatever state the site
   was in when a crawler last saw them.

Seeded, so a sample can be redrawn exactly (`--seed`); one request per domain to the index,
paced. Output is the `name url` format `benchmark/fidelity/run.py --sites` reads. A domain
whose index lookup yields nothing (not in the crawl, only non-HTML, only errors) is skipped
and counted; the sample is drawn until `--count` pages are found.

    uv run python benchmark/random_web/sample.py --tranco top-1m.csv --count 300 --seed 1 \
        --out benchmark/random_web/sample-2026-09.txt
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

INDEX_LIST = "https://index.commoncrawl.org/collinfo.json"
USER_AGENT = "webgraph-random-web-sampler/0.1 (+https://github.com/webgraph/webgraph)"
# Pages the index lists but the sample is not about: a site's own machinery.
_SKIP = re.compile(r"/(wp-json|xmlrpc\.php|feed/?$|\?replytocom=|/wp-login|/cgi-bin/)", re.IGNORECASE)


def latest_index() -> str:
    request = urllib.request.Request(INDEX_LIST, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        collections = json.load(response)
    return str(collections[0]["cdx-api"])


def pages_of(index: str, domain: str, *, limit: int = 60) -> list[str]:
    """Up to `limit` HTML pages the crawl holds for `domain`, any subdomain."""
    query = urllib.parse.urlencode(
        {
            "url": f"*.{domain}",
            "output": "json",
            "limit": str(limit),
            "filter": "=status:200",
        }
    )
    request = urllib.request.Request(f"{index}?{query}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8", errors="replace")
    except Exception:
        return []
    urls: list[str] = []
    for line in body.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        mime = str(record.get("mime-detected") or record.get("mime") or "")
        url = str(record.get("url") or "")
        if "html" in mime and url.startswith(("http://", "https://")) and not _SKIP.search(url):
            urls.append(url)
    return urls


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tranco", type=Path, required=True, help="tranco top-1m.csv")
    parser.add_argument("--count", type=int, default=300)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pause", type=float, default=1.0, help="seconds between index queries")
    args = parser.parse_args()

    ranked = [line.split(",", 1)[1].strip() for line in args.tranco.read_text().splitlines() if "," in line]
    rng = random.Random(args.seed)
    index = latest_index()
    print(f"index {index}; {len(ranked):,} domains; seed {args.seed}", file=sys.stderr)

    chosen: list[tuple[int, str, str]] = []
    tried = skipped = 0
    seen: set[str] = set()
    while len(chosen) < args.count:
        rank = rng.randrange(len(ranked))
        domain = ranked[rank]
        if domain in seen:
            continue
        seen.add(domain)
        tried += 1
        pages = pages_of(index, domain)
        if not pages:
            skipped += 1
            time.sleep(args.pause)
            continue
        url = rng.choice(pages)
        chosen.append((rank + 1, domain, url))
        print(f"{len(chosen):4}  rank {rank + 1:>7}  {url[:100]}", file=sys.stderr)
        time.sleep(args.pause)

    lines = [
        f"# {len(chosen)} random pages: Tranco ranks sampled uniformly, one Common Crawl HTML capture each.",
        f"# index {index}, seed {args.seed}; {tried} domains tried, {skipped} had no HTML page in the crawl.",
        "# name url",
    ]
    for rank, domain, url in chosen:
        name = f"r{rank}-{re.sub(r'[^a-z0-9]+', '-', domain.lower())[:40]}"
        lines.append(f"{name} {url}")
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({len(chosen)} pages; {skipped} of {tried} domains skipped)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
