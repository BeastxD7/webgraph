"""Changes as a feed, a Markdown digest or JSON.

A feed is the cheapest "notify me" there is: no daemon, no account, no webhook to host.
The research behind the watch found the demand where a university's circulars are
concerned -- VTU's notices reach 16,600 people through a volunteer Telegram channel that
reposts them by hand -- and a feed of "what changed on this site, which section, in the
page's own words" is that channel without the volunteer. Any reader, Slack, or an Action
can subscribe to it.

Both RSS 2.0 and Atom 1.0 are produced, with the standard library's ElementTree. One
entry per change: the page title and URL, the kind of change, and the sections that
changed with a bounded excerpt of the text before and after. The `guid`/`id` is the
change's own id under the watch, so a reader that has seen an entry does not show it twice.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from email.utils import format_datetime
from typing import Any
from xml.etree import ElementTree as ET

from webgraph.watch.store import Change, Watch

__all__ = ["to_atom", "to_json", "to_markdown", "to_rss"]

EXCERPT_CHARS = 400


def _excerpt(text: str, limit: int = EXCERPT_CHARS) -> str:
    folded = " ".join(text.split())
    return folded if len(folded) <= limit else folded[: limit - 1].rstrip() + "…"


def _when(stamp: float) -> datetime:
    return datetime.fromtimestamp(stamp, tz=UTC)


def _title(change: Change) -> str:
    verb = {"added": "New page", "removed": "Page gone", "changed": "Changed"}[change.kind]
    name = change.title or change.url
    if change.kind == "changed" and change.sections:
        headings = [s.get("heading") or "(opening)" for s in change.sections[:3]]
        more = f" +{len(change.sections) - 3}" if len(change.sections) > 3 else ""
        return f"{verb}: {name} — {', '.join(headings)}{more}"
    return f"{verb}: {name}"


def _body_markdown(change: Change) -> str:
    lines = [f"**{change.kind}** — [{change.title or change.url}]({change.url})", ""]
    for section in change.sections:
        heading = section.get("heading") or "(opening)"
        kind = section.get("kind", "edited")
        lines.append(f"- *{kind}* **{heading}**")
        before = _excerpt(str(section.get("before") or ""))
        after = _excerpt(str(section.get("after") or ""))
        if kind == "edited":
            if before:
                lines.append(f"  - was: {before}")
            if after:
                lines.append(f"  - now: {after}")
        elif after:
            lines.append(f"  - {after}")
        elif before:
            lines.append(f"  - {before}")
    return "\n".join(lines)


def _body_html(change: Change) -> str:
    """A small HTML body for readers that render one. Escaped by ElementTree on output."""
    parts = [
        f'<p><b>{change.kind}</b> — <a href="{change.url}">{change.title or change.url}</a></p>'
    ]
    if change.sections:
        parts.append("<ul>")
        for section in change.sections:
            heading = section.get("heading") or "(opening)"
            kind = section.get("kind", "edited")
            before = _excerpt(str(section.get("before") or ""))
            after = _excerpt(str(section.get("after") or ""))
            detail = ""
            if kind == "edited":
                detail = f"<br/>was: {before}<br/>now: {after}"
            elif after or before:
                detail = f"<br/>{after or before}"
            parts.append(f"<li><i>{kind}</i> <b>{heading}</b>{detail}</li>")
        parts.append("</ul>")
    return "".join(parts)


def to_rss(watch: Watch, changes: Iterable[Change], *, feed_url: str = "") -> str:
    """An RSS 2.0 document: `rss/channel` with `title`, `link`, `description`, one `item`
    per change carrying `title`, `link`, `guid`, `pubDate`, `description`."""
    changes = list(changes)
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = f"Changes on {watch.root}"
    ET.SubElement(channel, "link").text = watch.root
    ET.SubElement(
        channel, "description"
    ).text = (
        f"What changed on {watch.root}, section by section, as webgraph watch {watch.id} saw it."
    )
    latest = max((c.detected_at for c in changes), default=watch.created_at)
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(_when(latest))
    ET.SubElement(channel, "generator").text = "webgraph watch"
    if feed_url:
        ET.SubElement(channel, "docs").text = feed_url
    for change in changes:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = _title(change)
        ET.SubElement(item, "link").text = change.url
        guid = ET.SubElement(item, "guid", isPermaLink="false")
        guid.text = f"webgraph-watch:{watch.id}:change:{change.id}"
        ET.SubElement(item, "pubDate").text = format_datetime(_when(change.detected_at))
        ET.SubElement(item, "category").text = change.kind
        ET.SubElement(item, "description").text = _body_html(change)
    return _serialise(rss)


def to_atom(watch: Watch, changes: Iterable[Change], *, feed_url: str = "") -> str:
    """An Atom 1.0 document: `feed` with `id`, `title`, `updated`, `link`, one `entry` per
    change carrying `id`, `title`, `updated`, `link`, `content`."""
    changes = list(changes)
    ns = "http://www.w3.org/2005/Atom"
    ET.register_namespace("", ns)
    feed = ET.Element(f"{{{ns}}}feed")
    ET.SubElement(feed, f"{{{ns}}}id").text = f"webgraph-watch:{watch.id}"
    ET.SubElement(feed, f"{{{ns}}}title").text = f"Changes on {watch.root}"
    latest = max((c.detected_at for c in changes), default=watch.created_at)
    ET.SubElement(feed, f"{{{ns}}}updated").text = _when(latest).isoformat()
    ET.SubElement(feed, f"{{{ns}}}link", href=watch.root, rel="alternate")
    if feed_url:
        ET.SubElement(feed, f"{{{ns}}}link", href=feed_url, rel="self")
    ET.SubElement(feed, f"{{{ns}}}generator").text = "webgraph watch"
    author = ET.SubElement(feed, f"{{{ns}}}author")
    ET.SubElement(author, f"{{{ns}}}name").text = "webgraph watch"
    for change in changes:
        entry = ET.SubElement(feed, f"{{{ns}}}entry")
        ET.SubElement(entry, f"{{{ns}}}id").text = f"webgraph-watch:{watch.id}:change:{change.id}"
        ET.SubElement(entry, f"{{{ns}}}title").text = _title(change)
        ET.SubElement(entry, f"{{{ns}}}updated").text = _when(change.detected_at).isoformat()
        ET.SubElement(entry, f"{{{ns}}}link", href=change.url, rel="alternate")
        ET.SubElement(entry, f"{{{ns}}}category", term=change.kind)
        ET.SubElement(entry, f"{{{ns}}}content", type="html").text = _body_html(change)
    return _serialise(feed)


def to_markdown(watch: Watch, changes: Iterable[Change]) -> str:
    """A digest a person or an issue can read."""
    changes = list(changes)
    lines = [f"# Changes on {watch.root}", ""]
    if not changes:
        lines.append("No changes.")
        return "\n".join(lines) + "\n"
    counts = {"added": 0, "removed": 0, "changed": 0}
    for change in changes:
        counts[change.kind] += 1
    lines.append(f"{counts['added']} new, {counts['removed']} gone, {counts['changed']} changed.")
    lines.append("")
    for change in changes:
        stamp = _when(change.detected_at).strftime("%Y-%m-%d %H:%M UTC")
        lines.append(f"## {stamp} — {_title(change)}")
        lines.append("")
        lines.append(_body_markdown(change))
        lines.append("")
    return "\n".join(lines)


def to_json(watch: Watch, changes: Iterable[Change]) -> str:
    payload: dict[str, Any] = {
        "watch": watch.as_dict(),
        "changes": [c.as_dict() for c in changes],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _serialise(root: ET.Element) -> str:
    ET.indent(root)
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode")
