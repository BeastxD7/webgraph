"""Turn parsed HTML into the text blocks that reading order operates on.

Granularity is the whole design question here. Per-word blocks make ordering noisy and
expensive; per-section blocks hide the column structure that reading order needs to see.
We emit one block per *innermost block-level element that contains text* -- which lands on
paragraphs, headings, list items and table cells, and keeps inline markup (`<a>`, `<em>`,
`<strong>`) inside its parent rather than shattering a sentence across blocks.
"""

from __future__ import annotations

import re
from typing import Final

from lxml import etree
from lxml import html as lxml_html
from lxml.html import HtmlElement

from webgraph import config
from webgraph.types import Block

MAX_DOCUMENT_BYTES = config.MAX_DOCUMENT_BYTES
NOSCRIPT_SHELL_MAX_WORDS = config.NOSCRIPT_SHELL_MAX_WORDS
NOSCRIPT_CONTENT_MIN_WORDS = config.NOSCRIPT_CONTENT_MIN_WORDS

__all__ = [
    "BLOCK_TAGS",
    "HEADING_CONTROL_CLASSES",
    "LINE_BREAK",
    "PERMALINK_CLASSES",
    "RTL_LANGUAGES",
    "RTL_SCRIPTS",
    "SHADOW_TEMPLATE_ATTRIBUTE",
    "SKIP_TAGS",
    "SR_ONLY_CLASSES",
    "extract_blocks",
    "flatten_shadow_roots",
    "is_rtl_document",
    "normalize_text",
    "parse_html",
    "strip_permalinks",
]

BLOCK_TAGS: Final[frozenset[str]] = frozenset({
    "p", "div", "section", "article", "main", "aside", "header", "footer", "nav",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "dt", "dd", "td", "th", "caption",
    "blockquote", "pre", "figcaption", "figure", "summary", "details",
    "address", "label", "button", "legend", "fieldset", "form",
})
"""Block-level containers. Inline tags are deliberately absent so that `<p>a <a>b</a> c</p>`
stays one block instead of three."""

SKIP_TAGS: Final[tuple[str, ...]] = (
    "script", "style", "noscript", "template", "svg",
    "iframe", "object", "embed", "audio", "video", "source", "track", "param",
    "select", "datalist", "textarea",
)
"""Stripped from the tree before extraction. Their text is never page content -- leaving a
`<script>` in place makes an ancestor's `text_content()` return JavaScript source.

`select`, `datalist` and `textarea` are form controls whose text is the *choices* a control
offers, not something the page says. Measured on WCXB dev: 12,985 words of `<option>` text
across 26 article pages -- a country selector listing 200 countries and currencies, a
WordPress archive dropdown of every month since 2010, a Google Translate widget naming 100
languages. Each is a long run of unlinked words, which is precisely what a content selector
scores highest, so on glossier.com the selector returned the country list *instead of* the
article (recall 0.06 against a 1.00 ceiling). `<button>` is kept: its label is one or two
words and occasionally the only text an interstitial has.

`noscript` is stripped here but see `unwrap_noscript_shell`, which runs first and rescues
the case where it is the *only* place the content exists.

`canvas` is deliberately *not* stripped: it has no readable text either way, but its
presence is a signal the profiler uses to flag that a vision path is required.

`math` used to be here, which meant **every equation on every page was deleted before
extraction began**. Stripped MathML does not degrade a scientific page, it removes the thing
the page is about. `replace_math_with_latex` now runs first and rewrites each `<math>` into
delimited LaTeX, so by the time extraction sees the tree there is no MathML left to strip."""

_WHITESPACE: Final[re.Pattern[str]] = re.compile(r"\s+")
_BLANK_RUN: Final[re.Pattern[str]] = re.compile(r"\n{3,}")
_WORD: Final[re.Pattern[str]] = re.compile(r"\w+")


LINE_BREAK: Final[str] = "\ue000"
"""What `flowed_text` writes for a `<br>`: a private-use character no whitespace class
matches, so the source's own newlines can still collapse to spaces while the break the
markup declared survives to become a newline in the block's text."""


def normalize_text(value: str | None) -> str:
    """Collapse runs of whitespace and trim. HTML whitespace is not semantic -- source
    newlines are spaces -- except the break a `<br>` declares, carried as `LINE_BREAK` and
    turned into a newline here: one for a line break, two for the blank line a `<br><br>`
    makes (an address, a verse, the paragraphs of a pre-CSS page). Lines are trimmed and
    runs of three or more newlines collapse to two."""
    if not value:
        return ""
    if LINE_BREAK not in value:
        return _WHITESPACE.sub(" ", value).strip()
    lines = [_WHITESPACE.sub(" ", line).strip() for line in value.split(LINE_BREAK)]
    return _BLANK_RUN.sub("\n\n", "\n".join(lines)).strip()


_XML_DECLARATION: Final = re.compile(r"^\s*<\?xml[^>]*\?>\s*", re.IGNORECASE)


def _without_xml_declaration(html: str) -> str:
    """Drop a leading `<?xml … encoding="utf-8"?>`.

    XHTML pages served as HTML carry one, and lxml refuses to parse a `str` that declares an
    encoding -- `ValueError: Unicode strings with encoding declaration are not supported`.
    The declaration is meaningless here: the text is already decoded. Three WCEB pages died
    on this, losing the whole document rather than a fragment of it.
    """
    return _XML_DECLARATION.sub("", html, count=1)


def parse_html(html: str, *, max_bytes: int = MAX_DOCUMENT_BYTES) -> HtmlElement:
    """Parse a document, tolerating the malformed markup that real pages ship.

    Uses `huge_tree=True` because libxml2's default HTML parser caps nesting at 255 levels
    and, past that, **silently discards the content** -- `text_content()` returns an empty
    string with no error raised. Utility-class frameworks nest wrapper `<div>`s deeply
    enough to hit this, so the default would lose whole pages invisibly.
    """
    if not html.strip():
        raise ValueError("cannot parse empty HTML")

    size = len(html.encode("utf-8", errors="ignore"))
    if size > max_bytes:
        raise ValueError(f"document is {size} bytes, exceeding the {max_bytes} byte limit")

    parser = lxml_html.HTMLParser(huge_tree=True, recover=True)
    root = lxml_html.document_fromstring(_without_xml_declaration(html), parser=parser)
    # Shadow content arrives as `<template shadowrootmode>` and must be unwrapped before
    # anything strips `<template>`. Every consumer of a parsed page wants this, so it
    # happens here rather than at each call site.
    flatten_shadow_roots(root)
    # Likewise a page whose only content is inside `<noscript>` must be unwrapped before
    # anything strips `<noscript>`.
    unwrap_noscript_shell(root)
    # And every `<math>` becomes its LaTeX source before anything can drop it. Order matters
    # for the same reason: an equation removed here is not recoverable downstream.
    replace_math_with_latex(root)
    return root


def _carry_tail(parent: HtmlElement, element: HtmlElement) -> None:
    """Move an element's trailing text onto whatever will still be there once it is gone."""
    tail = element.tail
    if not tail:
        return
    previous = element.getprevious()
    if previous is not None:
        previous.tail = (previous.tail or "") + tail
    else:
        parent.text = (parent.text or "") + tail


def replace_math_with_latex(root: HtmlElement) -> int:
    """Rewrite every `<math>` element in place as delimited LaTeX. Returns how many.

    An inline equation becomes a `<span>`, so it travels with the sentence it belongs to:
    `<p>where <math>…</math> is the input</p>` stays one paragraph reading
    `where $x_i$ is the input`, which is how a reader meets it and how every corpus in this
    field annotates it. A `display="block"` equation becomes a `<p>`, and therefore a block of
    its own, because that is what it is on the page.

    Replacing the element rather than merging its text into a neighbour is deliberate. An
    earlier version appended the LaTeX to the previous sibling's tail, and a display equation
    standing alone between two paragraphs vanished, because tail text in that position belongs
    to no block. A `<math>` nothing could be recovered from is dropped, exactly as before.
    """
    from webgraph.dom.math import math_elements, render_math

    replaced = 0
    for element in math_elements(root):
        parent = element.getparent()
        if parent is None:
            continue
        latex = render_math(element)
        if not latex:
            # Dropping the element must not drop the rest of the sentence with it. lxml keeps
            # the text that *follows* an element on that element, so removing `<math></math>`
            # from "Plain <math></math> sentence." silently deleted " sentence." too.
            _carry_tail(parent, element)
            parent.remove(element)
            continue
        display = (element.get("display") or "").lower() == "block"
        holder = parent.makeelement("p" if display else "span", {})
        holder.text = latex
        holder.tail = element.tail
        parent.replace(element, holder)
        replaced += 1
        _drop_fallback_images(holder)
    return replaced


def _drop_fallback_images(holder: HtmlElement) -> None:
    """Remove the picture of the formula that sits beside the formula.

    MediaWiki, MathJax's CommonHTML output and several LaTeX-to-HTML converters emit the
    equation twice: once as `<math>` for machines and once as an `<img>` of the rendered
    equation for browsers without MathML, with the same LaTeX in its `alt`. Having just
    converted the first, keeping the second reports every formula twice -- on Wikipedia's
    Navier-Stokes article that was 204 images of equations already in the text, and a
    document nearly twice its real size.

    The image is identified by what it is, not by class name: an `<img>` among the same
    parent's children whose `alt` is the formula (or is empty, on converters that leave it
    blank). A genuine figure next to an equation has its own alt text and survives.
    """
    latex = (holder.text or "").strip("$ ")
    # MediaWiki wraps the `<math>` in an accessibility span and puts the image beside *that*,
    # so the image is one level up from where the formula was. Two levels covers every
    # emitter seen; further up and an image is a figure in its own right.
    node: HtmlElement | None = holder
    for _ in range(2):
        if node is None:
            return
        parent = node.getparent()
        if parent is None:
            return
        for sibling in list(parent):
            if sibling is node or sibling.tag != "img":
                continue
            alt = (sibling.get("alt") or "").strip()
            if alt and alt.strip("$ ") != latex:
                continue
            _carry_tail(parent, sibling)
            parent.remove(sibling)
        node = parent


def unwrap_noscript_shell(root: HtmlElement) -> int:
    """Promote `<noscript>` content to ordinary markup when it is all the page has. Returns
    the number of `<noscript>` elements unwrapped.

    Discourse -- which runs community.openai.com, forum.obsidian.md, users.rust-lang.org,
    community.home-assistant.io and thousands more -- serves a JavaScript shell whose entire
    topic, every post, sits inside `<noscript>` for crawlers. `noscript` is in `SKIP_TAGS`
    because on an ordinary page it holds "please enable JavaScript" and a tracking pixel.
    Stripping it here stripped the forum: measured on WCXB dev, **19 of 112 forum pages
    parsed to zero blocks**, each with 1,000-5,600 words of ground truth sitting in the
    `<noscript>` we had just deleted, and the recall of that text against the ground truth
    was 1.00 on every one of them.

    The guard is the asymmetry. Unwrapping is only done when the visible page is a shell
    (under `NOSCRIPT_SHELL_MAX_WORDS`) *and* the `<noscript>` is substantial (over
    `NOSCRIPT_CONTENT_MIN_WORDS`). On a normal page the visible text is large and the
    noscript is a sentence, so nothing changes; a page that fails both tests has no content
    either way.
    """
    noscripts = list(root.iter("noscript"))
    if not noscripts:
        return 0
    noscript_words = sum(len(_WORD.findall(n.text_content())) for n in noscripts)
    if noscript_words < NOSCRIPT_CONTENT_MIN_WORDS:
        return 0
    # Visible words: the whole document minus the script, style and noscript subtrees
    # (outermost only, so a script inside a noscript is not subtracted twice).
    hidden = root.xpath(
        "//*[self::script or self::style or self::noscript]"
        "[not(ancestor::script or ancestor::style or ancestor::noscript)]"
    )
    visible = len(_WORD.findall(root.text_content())) - sum(
        len(_WORD.findall(node.text_content())) for node in hidden
    )
    if visible >= NOSCRIPT_SHELL_MAX_WORDS:
        return 0
    unwrapped = 0
    for noscript in noscripts:
        parent = noscript.getparent()
        if parent is None:
            continue
        # libxml2 parses the *contents* of noscript as markup, so the children are real
        # elements; where it kept them as text (inside <head>), reparse that text.
        children = list(noscript)
        if not children and (noscript.text or "").strip():
            try:
                fragment = lxml_html.fragment_fromstring(noscript.text, create_parent="div")
            except Exception:
                continue
            children = [fragment]
        index = parent.index(noscript)
        for offset, child in enumerate(children):
            parent.insert(index + offset, child)
        parent.remove(noscript)
        unwrapped += 1
    return unwrapped


SHADOW_TEMPLATE_ATTRIBUTE: Final[str] = "shadowrootmode"
"""Marks a `<template>` that is a serialised shadow root, not an inert template.

`Element.getHTML({serializableShadowRoots: true})` emits open shadow roots as
`<template shadowrootmode="open">`. That is the standard declarative-shadow-DOM form, and
it is how the browser hands us content that `outerHTML` silently omits.
"""


def flatten_shadow_roots(root: HtmlElement) -> int:
    """Unwrap serialised shadow roots so their content is ordinary markup. Returns the count.

    Necessary because `template` is in `SKIP_TAGS`: a serialised shadow root would otherwise
    be stripped along with the inert templates it is syntactically identical to, and the
    content would be lost exactly as it was before the browser was asked for it.

    Only templates carrying `shadowrootmode` are unwrapped. A genuine inert `<template>` is
    markup the page has *not* rendered, and it stays stripped -- flattening those would
    invent content, which is the opposite failure but a failure all the same.

    The result is the browser's *flat tree*, not the shadow tree followed by the light
    tree. A shadow root's `<slot>`s are where the host's own children are painted: each
    slot is replaced by the children assigned to it -- `slot="name"` to the first
    `<slot name="name">`, everything else (text included) to the first unnamed slot -- or by
    its fallback content when nothing is. What no slot takes is not rendered and is
    dropped. Splicing the shadow content ahead of an untouched light DOM, as this did
    before, read every filled slot's fallback ("Untitled card") as text on the page, put
    the slotted children after the whole component instead of at their place, turned a
    title slotted into an `<h2>` into a paragraph, and kept children the browser never
    shows. Deepest first, so a component nested in another's shadow tree is composed --
    its slots resolved -- before the outer one moves it.
    """
    flattened = 0
    # Deepest first, so a shadow root nested inside another is unwrapped before its parent
    # moves. Materialised because the tree is mutated during the walk.
    templates = list(root.iter("template"))
    for template in reversed(templates):
        if template.get(SHADOW_TEMPLATE_ATTRIBUTE) is None:
            continue
        host = template.getparent()
        if host is None:
            continue
        _compose_slots(host, template)
        index = host.index(template)
        for offset, child in enumerate(list(template)):
            host.insert(index + offset, child)
        text = (template.text or "").strip()
        if text:
            previous = template.getprevious()
            if previous is not None:
                previous.tail = (previous.tail or "") + " " + text
            else:
                host.text = (host.text or "") + " " + text
        if template.tail:
            previous = template.getprevious()
            if previous is not None:
                previous.tail = (previous.tail or "") + template.tail
            else:
                host.text = (host.text or "") + template.tail
        host.remove(template)
        flattened += 1
    return flattened


def _compose_slots(host: HtmlElement, template: HtmlElement) -> None:
    """Move the host's light-DOM children into the template's slots, browser-style.

    Light children are every child of `host` but `template`, plus the text between them
    (which the browser assigns to the default slot as text nodes). A `<slot>` inside a
    nested serialised shadow root belongs to that root and is not this host's -- but by the
    time this runs, deeper templates are already flattened, so any slot still in the
    template's tree is this root's own.
    """
    light = [child for child in host if child is not template]
    # The text nodes of the light DOM, in order: what follows the template, then what
    # follows each light child. Kept as (after_element, text) so it can be placed.
    light_text: list[str] = []
    if template.tail and template.tail.strip():
        light_text.append(template.tail)
    for child in light:
        if child.tail and child.tail.strip():
            light_text.append(child.tail)
        child.tail = None
    template.tail = None
    if host.text and host.text.strip() and host.index(template) > 0:
        # Text before the template is light text too (the template is normally first).
        light_text.insert(0, host.text)
    host.text = None

    slots = [s for s in template.iter("slot") if isinstance(s.tag, str)]
    named_taken: set[str] = set()
    default_taken = False
    for slot in slots:
        name = (slot.get("name") or "").strip()
        if name:
            if name in named_taken:
                assigned: list[HtmlElement] = []
                text_for_slot: list[str] = []
            else:
                named_taken.add(name)
                assigned = [c for c in light if (c.get("slot") or "").strip() == name]
                text_for_slot = []
        elif default_taken:
            assigned, text_for_slot = [], []
        else:
            default_taken = True
            assigned = [c for c in light if not (c.get("slot") or "").strip()]
            text_for_slot = light_text
        _fill_slot(slot, assigned, text_for_slot)
        for c in assigned:
            light.remove(c)
    # Whatever no slot took is not in the flat tree: the browser does not paint it.
    for leftover in light:
        host.remove(leftover)


def _fill_slot(slot: HtmlElement, assigned: list[HtmlElement], text: list[str]) -> None:
    """Replace `slot` with its assigned nodes, or leave its fallback when it got none."""
    parent = slot.getparent()
    if parent is None:
        return
    index = parent.index(slot)
    tail = slot.tail
    if not assigned and not text:
        # Fallback: the slot's own content stands. Unwrap the slot element itself so no
        # `<slot>` tag survives into the block walk.
        for offset, child in enumerate(list(slot)):
            parent.insert(index + offset, child)
        lead = slot.text or ""
        _prepend_text(parent, index, lead)
        parent.remove(slot)
        _append_text(parent, index + len(slot) - 1 if len(slot) else index - 1, tail)
        return
    for child in list(slot):
        slot.remove(child)
    slot.text = None
    for offset, node in enumerate(assigned):
        parent.insert(index + offset, node)
    joined = " ".join(t.strip() for t in text if t.strip())
    if joined:
        if assigned:
            assigned[-1].tail = ((assigned[-1].tail or "") + " " + joined).strip()
        else:
            _prepend_text(parent, index, joined)
    parent.remove(slot)
    _append_text(parent, index + len(assigned) - 1, tail)


def _prepend_text(parent: HtmlElement, index: int, text: str | None) -> None:
    """Put `text` where the child at `index` begins: after the previous sibling, or as the
    parent's leading text."""
    if not text or not text.strip():
        return
    if index > 0:
        previous = parent[index - 1]
        previous.tail = (previous.tail or "") + text
    else:
        parent.text = (parent.text or "") + text


def _append_text(parent: HtmlElement, index: int, text: str | None) -> None:
    """Put `text` after the child at `index` (or as leading text when `index` < 0)."""
    if not text:
        return
    if index >= 0 and index < len(parent):
        child = parent[index]
        child.tail = (child.tail or "") + text
    else:
        parent.text = (parent.text or "") + text


PERMALINK_CLASSES: Final[tuple[str, ...]] = (
    "headerlink",
    "hash-link",
    "anchor-link",
    "header-anchor",
    "heading-link",
    "permalink",
)
"""Class names documentation generators use for the anchor beside a heading.

Sphinx emits `<a class="headerlink">¶</a>`, MkDocs Material the same, Docusaurus
`<a class="hash-link" aria-hidden="true">#</a>`. It is a control, not part of the heading,
and left in place it reaches the reader as `Testimonials¶`, the index as a junk token, and
the Markdown as a stray glyph on every heading of a documentation site.

Matched on the class, not on the character. Stripping a trailing `¶` or `#` from every
heading would also mutilate the ones that legitimately end in one.
"""


SR_ONLY_CLASSES: Final[frozenset[str]] = frozenset({
    "sr-only", "visually-hidden", "visuallyhidden", "screen-reader-text", "screen-reader-only",
    "a11y-hidden", "u-visually-hidden", "is-visually-hidden", "sr_only", "visually_hidden",
    "assistive-text", "hidden-visually", "offscreen", "clip-hidden",
})
"""Class names that clip an element to a 1px box off screen: Bootstrap and Tailwind's
`sr-only` / `visually-hidden`, WordPress's `screen-reader-text`, and the house variants.

The text is real and read aloud by a screen reader, but it is not what a sighted reader
sees, and it is usually a label for a control rather than content: "Option: BILLY,
Bookcase, dark brown oak effect" on every variant swatch of ikea.com's category page --
1,214 words of it on one page -- "Skip to main content", "Opens in a new window". A
rendered fetch measures such an element at 1x1px and it goes as unmeasured chrome; a
static fetch has only the class to go by, and this reads it.
"""

HEADING_CONTROL_CLASSES: Final[tuple[str, ...]] = ("mw-editsection", "editsection")
"""Class names of the control strip beside a heading that is not an anchor.

MediaWiki puts `<span class="mw-editsection">[edit | edit source]</span>` beside every
section heading of every Wikipedia, Wiktionary and Fandom page. Two links and two
brackets, and once per section: measured on ar.wikipedia's "حاسوب", 49 of them, each a
paragraph of its own in the Markdown right before the heading it belongs to. Older
MediaWiki skins -- cppreference.com -- write `<span class="editsection noprint">[edit]`
beside every heading and every table row: 56 of them on the `std::vector` page, hidden
by the stylesheet, a quarter of our words on that page, and, because the static fetch
kept them and the rendered one did not, the member-function tables emitted twice.
"""


def strip_permalinks(root: HtmlElement, *, keep_hidden_text: bool = False) -> None:
    """Drop the permalink anchors documentation generators attach to headings, the
    edit-section controls a wiki does, and the screen-reader-only labels.

    `keep_hidden_text` keeps the last two: the text a browser holds but a sighted reader
    never sees -- "Option: BILLY, Bookcase, white" on every swatch, "Skip to main content",
    "[edit]" beside every wiki heading. Off by default because that text is labels for
    controls, not content, and a reader of the Markdown is better without it; on for a
    caller that wants every string in the DOM. The permalink glyphs go either way: a `¶`
    is a control's glyph, not text.
    """
    permalinks = set(PERMALINK_CLASSES)
    controls = set(HEADING_CONTROL_CLASSES)
    for element in root.xpath(".//*[@class] | .//a[starts-with(@href, '#')]"):
        classes = set((element.get("class") or "").lower().split())
        if not (
            (element.tag == "a" and (classes & permalinks or _is_permalink_glyph(element)))
            or (
                not keep_hidden_text
                and (
                    classes & controls
                    or (classes & SR_ONLY_CLASSES and not _sr_only_is_content(element))
                )
            )
        ):
            continue
        parent = element.getparent()
        if parent is None:
            continue
        # Keep the tail: a permalink is often followed by whitespace separating the heading
        # from what comes after it.
        if element.tail:
            previous = element.getprevious()
            if previous is not None:
                previous.tail = (previous.tail or "") + element.tail
            else:
                parent.text = (parent.text or "") + element.tail
        parent.remove(element)


PERMALINK_GLYPHS: Final[frozenset[str]] = frozenset("¶#§🔗⚓↩🔗︎")
"""What a permalink anchor says when it says anything. php.net's `<a class="genanchor"
href="#refsect1-…"> ¶</a>` is added by a script the static fetch never runs, so the
rendered heading read "Description ¶" and the static one "Description": two keys, and
the union emitted both. The class list cannot be complete; the glyph and the fragment
href together are the thing itself."""


def _is_permalink_glyph(element: HtmlElement) -> bool:
    if not (element.get("href") or "").startswith("#"):
        return False
    text = "".join(element.text_content().split())
    return bool(text) and all(ch in PERMALINK_GLYPHS or ch == "\ufe0e" for ch in text)


def _sr_only_is_content(element: HtmlElement) -> bool:
    """A screen-reader-only element that is the page's own heading is kept: some sites
    put the article's `<h1>` in `sr-only` beside a logo image. A label of a few words is
    what the class is for and goes."""
    tag = element.tag if isinstance(element.tag, str) else ""
    if tag not in {"h1", "h2", "h3"}:
        return False
    return len(element.text_content().split()) >= 4


RTL_LANGUAGES: Final[frozenset[str]] = frozenset({
    "ar",    # Arabic
    "arc",   # Aramaic
    "ckb",   # Sorani Kurdish
    "dv",    # Divehi
    "fa",    # Persian
    "he",    # Hebrew
    "iw",    # Hebrew, deprecated code still emitted by older systems
    "ji",    # Yiddish, deprecated code
    "ks",    # Kashmiri
    "ku",    # Kurdish
    "nqo",   # N'Ko
    "prs",   # Dari
    "ps",    # Pashto
    "sd",    # Sindhi
    "syr",   # Syriac
    "ug",    # Uyghur
    "ur",    # Urdu
    "yi",    # Yiddish
})
"""Primary language subtags written right-to-left."""

RTL_SCRIPTS: Final[frozenset[str]] = frozenset({
    "arab", "hebr", "thaa", "syrc", "nkoo", "adlm", "rohg", "yezi", "mand", "samr",
})
"""Script subtags written right-to-left, for tags like `az-Arab` or `pa-Arab`, where the
language is written in more than one script and only the script settles the direction."""


def is_rtl_document(root: HtmlElement) -> bool:
    """Whether this document reads right to left.

    Reading order needs this. `order_blocks` reverses column order when `rtl` is set, so on
    a multi-column Arabic or Hebrew page getting it wrong does not degrade the output -- it
    reads the columns backwards, and reports `geometric-xy-cut` while doing so. Confidently
    wrong is the worst failure this engine has.

    Two sources, in order of authority:

    1. **`dir` on `<html>` or `<body>`.** The page's own declaration, and it wins outright --
       including when it says `ltr` on a page whose language is usually RTL, which is a
       deliberate choice by its author (a Hebrew-language site presenting code or tabular
       data left-to-right).
    2. **`lang` on `<html>`.** Needed because the attribute is frequently absent:
       `ynet.co.il` carries **no `dir` anywhere** in either representation, and is RTL only
       via CSS. Its `lang="he"` is the sole signal in the markup.

    Deliberately *not* a character-frequency heuristic. A page that merely quotes Arabic --
    a dictionary entry, a news article about the region, this engine's own test fixtures --
    would flip the reading order of the whole document. The cost of a false positive is a
    silently reversed page, so only a declaration counts.
    """
    for element in (root, *root.xpath("//body")):
        declared = (element.get("dir") or "").strip().lower()
        if declared in ("rtl", "ltr"):
            return declared == "rtl"

    tag = (root.get("lang") or root.get("xml:lang") or "").strip().lower()
    if not tag:
        return False

    parts = tag.replace("_", "-").split("-")
    if parts[0] in RTL_LANGUAGES:
        return True
    return any(part in RTL_SCRIPTS for part in parts[1:])


def _strip_noise(root: HtmlElement) -> None:
    """Remove non-content elements, keeping their tail text.

    `with_tail=False` is load-bearing: it preserves the text that *follows* the element.
    Dropping it would silently lose the sentence after an inline `<script>`, which is
    common in ad-laden markup.
    """
    etree.strip_elements(root, *SKIP_TAGS, with_tail=False)
    etree.strip_elements(root, etree.Comment, with_tail=False)
    strip_permalinks(root)


def _text_maps(
    root: HtmlElement,
) -> tuple[dict[HtmlElement, bool], dict[HtmlElement, bool]]:
    """Compute, for every element, whether it holds text and whether a block descendant does.

    Both are built in one reverse-document-order pass. The naive form -- calling
    `text_content()` on every descendant of every candidate -- is quadratic, and pathological
    on the deeply nested wrapper `<div>`s that utility-class frameworks emit.
    """
    has_text: dict[HtmlElement, bool] = {}
    has_block_descendant: dict[HtmlElement, bool] = {}

    for element in reversed(list(root.iter())):
        if not isinstance(element.tag, str):
            has_text[element] = False
            has_block_descendant[element] = False
            continue

        own = bool(normalize_text(element.text))
        from_children = any(
            has_text.get(child, False) or bool(normalize_text(child.tail))
            for child in element
        )
        has_text[element] = own or from_children

        has_block_descendant[element] = any(
            (
                isinstance(child.tag, str)
                and child.tag in BLOCK_TAGS
                and has_text.get(child, False)
            )
            or has_block_descendant.get(child, False)
            for child in element
        )

    return has_text, has_block_descendant


def extract_blocks(root: HtmlElement, *, min_chars: int = 1) -> list[Block]:
    """Collect text blocks in document order.

    `dom_index` records that source order, which is what makes CSS reordering detectable
    later: if the geometric order disagrees with it, the page reordered its own content.
    """
    _strip_noise(root)
    has_text, has_block_descendant = _text_maps(root)

    tree = root.getroottree()
    blocks: list[Block] = []
    index = 0

    for element in root.iter():
        if not isinstance(element.tag, str) or element.tag not in BLOCK_TAGS:
            continue
        if not has_text.get(element, False):
            continue
        if has_block_descendant.get(element, False):
            continue

        text = normalize_text(element.text_content())
        if len(text) < min_chars:
            continue

        blocks.append(
            Block(
                text=text,
                tag=element.tag,
                xpath=tree.getpath(element),
                dom_index=index,
                depth=_depth_of(element),
            )
        )
        index += 1

    return blocks


def _depth_of(element: HtmlElement) -> int:
    depth = 0
    parent = element.getparent()
    while parent is not None:
        depth += 1
        parent = parent.getparent()
    return depth
