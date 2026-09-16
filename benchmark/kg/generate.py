"""Derive typed questions from a site's own JSON-LD, with the page and block that answer them.

Gold is cheap when the site publishes structured data: every `Offer.price`,
`Event.startDate`, `Person.jobTitle`, `Organization.telephone` / `email` and every FAQPage
question is a typed question whose answer the page states in plain text somewhere. This
script finds where -- the block whose text carries the value -- and writes one JSONL row per
question in the format `run.py` scores:

    {"id", "site", "question", "answer", "answer_type": span|number|date|list|yes_no|free|abstain,
     "unit", "gold": [{"page_url", "block_xpath", "quote"}], "hops": 1|2, "source": jsonld|human,
     "difficulty": easy|medium|hard}

A value that cannot be located verbatim on the page (a duration only the JSON-LD states, a
price the page rounds differently) is skipped and counted, never written with a guessed
xpath: the benchmark measures citation precision at block level, and a wrong gold block
would score a correct answer as a miss.

    uv run --package webgraph python benchmark/kg/generate.py --pages benchmark/kg/fixtures/site \\
        --root https://kg-fixture.test/ --out benchmark/kg/fixtures/site/qa.generated.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from webgraph.graph.model import SiteGraph
from webgraph.kg.extract import locate_quote
from webgraph.kg.offline import graph_from_directory

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def number_forms(value: str) -> list[str]:
    digits = re.sub(r"[^\d.]", "", value)
    if not digits:
        return []
    whole = digits.split(".")[0]
    forms = [digits, whole]
    if len(whole) > 3:
        forms.append(f"{int(whole):,}")  # 120,000
        head, tail = whole[:-3], whole[-3:]  # Indian grouping: 1,20,000
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        forms.append(",".join([*groups, tail]))
    return list(dict.fromkeys(forms))


def date_forms(value: str) -> list[str]:
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", value)
    if not match:
        return [value]
    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
    name = MONTHS[month - 1]
    return [value, f"{day} {name} {year}", f"{name} {day}, {year}", f"{day} {name[:3]} {year}", f"{name[:3]} {day}, {year}", f"{day:02d}/{month:02d}/{year}"]


def locate(graph: SiteGraph, page_key: str, forms: list[str]) -> tuple[str, str, str] | None:
    """(page_url, block_xpath, quote) for the first block carrying any form: the entity's
    own page first, then the rest of the site -- a course's JSON-LD sits on the courses
    page while its fee is printed on the fees page."""
    order = [page_key, *(k for k in sorted(graph.pages) if k != page_key)]
    for key in order:
        page = graph.pages.get(key)
        if page is None:
            continue
        for section in graph.sections_of(key):
            for ref in section.blocks:
                text = ref.slice(section.text)
                for form in forms:
                    span = locate_quote(text, form)
                    if span is not None:
                        return page.url, ref.xpath, _window(text, span)
    return None


def _window(text: str, span: tuple[int, int], *, words: int = 8) -> str:
    prefix = text[: span[0]]
    before = prefix.split()
    lead = " ".join(before[-words:])
    start = prefix.rfind(lead) if lead else span[0]
    after = text[span[1] :].split()
    tail = " ".join(after[:words])
    end = (text.find(tail, span[1]) + len(tail)) if tail else span[1]
    return text[max(0, start) : end].strip()


def _first(value: Any) -> Any:
    return value[0] if isinstance(value, list) and value else value


def questions_for(graph: SiteGraph, site: str) -> tuple[list[dict[str, Any]], Counter[str]]:
    out: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    seen: set[str] = set()

    def add(qid: str, question: str, answer: str, answer_type: str, unit: str, page_key: str, forms: list[str], difficulty: str = "easy") -> None:
        if qid in seen:
            return
        located = locate(graph, page_key, forms)
        if located is None:
            skipped[f"not_on_page:{answer_type}"] += 1
            return
        url, xpath, quote = located
        seen.add(qid)
        out.append({
            "id": qid,
            "site": site,
            "question": question,
            "answer": answer,
            "answer_type": answer_type,
            "unit": unit,
            "gold": [{"page_url": url, "block_xpath": xpath, "quote": quote}],
            "hops": 1,
            "source": "jsonld",
            "difficulty": difficulty,
        })

    for entity in sorted(graph.entities.values(), key=lambda e: (e.type, e.name)):
        data = entity.data if isinstance(entity.data, dict) else {}
        name = entity.name
        if not name or not entity.pages:
            continue
        page_key = entity.pages[0]
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
        offers = data.get("offers")
        offer = offers[0] if isinstance(offers, list) and offers else offers
        if isinstance(offer, dict) and offer.get("price"):
            price = str(offer["price"])
            currency = str(offer.get("priceCurrency") or "")
            noun = {"Course": "tuition fee", "Event": "registration fee"}.get(entity.type, "price")
            add(f"{slug}-price", f"What is the {noun} for {name}?", price, "number", currency, page_key, number_forms(price))
        for key, template, kind in (
            ("startDate", "When does {name} start?", "date"),
            ("endDate", "When does {name} end?", "date"),
            ("foundingDate", "When was {name} founded?", "date"),
        ):
            value = _first(data.get(key))
            if isinstance(value, str) and value:
                add(f"{slug}-{key.lower()}", template.format(name=name), value[:10] if kind == "date" else value, kind, "", page_key, date_forms(value) if "-" in value else [value])
        if entity.type == "Person" and isinstance(data.get("jobTitle"), str):
            title = data["jobTitle"]
            add(f"{slug}-role", f"What is {name}'s role?", title, "span", "", page_key, [title])
            add(f"{slug}-who", f"Who is the {title}?", name, "span", "", page_key, [name], "medium")
        for key, template in (("telephone", "What is the telephone number of {name}?"), ("email", "What is the email address of {name}?")):
            value = _first(data.get(key))
            if isinstance(value, str) and value:
                add(f"{slug}-{key}", template.format(name=name), value, "span", "", page_key, [value])
        if entity.type == "FAQPage":
            for index, item in enumerate(data.get("mainEntity") or []):
                if not isinstance(item, dict):
                    continue
                question = str(item.get("name") or "")
                accepted = item.get("acceptedAnswer") or {}
                answer = str(accepted.get("text") or "") if isinstance(accepted, dict) else ""
                if question and answer:
                    add(f"faq-{index}", question, answer, "free", "", page_key, [answer[:80]], "medium")
    return out, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pages", help="directory of saved HTML pages")
    parser.add_argument("--graph", help="or a JSONL graph written by `webgraph graph`")
    parser.add_argument("--root", required=True, help="site root URL")
    parser.add_argument("--site", help="site label (default: the root's host)")
    parser.add_argument("--out", help="write JSONL here (default: stdout)")
    args = parser.parse_args()

    if args.pages:
        graph = graph_from_directory(args.pages, args.root)
    elif args.graph:
        from webgraph.graph.export import load_jsonl

        graph = load_jsonl(args.graph)
    else:
        parser.error("one of --pages or --graph is required")
    site = args.site or args.root.split("://", 1)[-1].strip("/")
    rows, skipped = questions_for(graph, site)
    lines = [json.dumps(row, ensure_ascii=False) for row in rows]
    if args.out:
        Path(args.out).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    else:
        print("\n".join(lines))
    print(f"{len(rows)} questions from {len(graph.entities)} structured entities; skipped {dict(skipped) or 'none'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
