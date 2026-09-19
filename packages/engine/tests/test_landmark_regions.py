"""Three extraction findings from WCXB dev, each pinned so it cannot silently return.

1. **Nineteen forum pages parsed to zero blocks.** Discourse serves a JavaScript shell whose
   entire topic sits inside `<noscript>`, and `noscript` is (rightly) stripped. The visible
   page held 5 to 41 words; the noscript held 1,000 to 5,600, all of it ground truth.
2. **Form controls scored as prose.** A `<select>` of 200 countries is 400 unlinked words,
   which a content selector prizes above a 160-word article. On glossier.com the selector
   returned the country list instead of the terms and conditions.
3. **`role="main"` was invisible.** Landmarks were read from XPath, which carries tag names
   only; 178 of 1,476 pages declare their main content by ARIA role alone. Blocks now carry
   the landmark region they sit in, `strip_landmarks` honours `role="navigation"` and
   `role="contentinfo"`, and `scope_to_main` keeps only a `<main>` the guard trusts.
"""

from __future__ import annotations

from webgraph.boilerplate import MAIN_MIN_WORDS, scope_to_main, strip_landmarks
from webgraph.content import select_content
from webgraph.dom.blocks import (
    NOSCRIPT_CONTENT_MIN_WORDS,
    NOSCRIPT_SHELL_MAX_WORDS,
    parse_html,
    unwrap_noscript_shell,
)
from webgraph.pipeline import build_document

SENTENCE = "Real forum content with enough words in it to count as a post that matters. "
PARAGRAPH = "Ordinary visible prose, present without JavaScript, paragraph number "


def posts(n: int) -> str:
    return "".join(f"<p>{SENTENCE}Post {i}.</p>" for i in range(n))


class TestNoscriptShell:
    def test_a_discourse_style_shell_is_rescued(self) -> None:
        html = (
            "<html><body><div id='app'></div>"
            f"<noscript><div class='topic'>{posts(30)}</div></noscript>"
            "<script>window.x = 1</script></body></html>"
        )
        document = build_document(html, "https://forum.test/t/1")
        assert len(document.blocks) == 30
        assert "Post 29." in document.text

    def test_an_ordinary_page_keeps_its_noscript_stripped(self) -> None:
        """The common case: a real page plus a `<noscript>` pixel and a nag. Nothing changes."""
        html = (
            "<html><body><main>"
            + "".join(f"<p>{PARAGRAPH}{i}.</p>" for i in range(40))
            + "</main><noscript><img src='px.gif'>"
            + "<p>Please enable JavaScript to see comments.</p>" * 30
            + "</noscript></body></html>"
        )
        document = build_document(html, "https://x.test/")
        assert len(document.blocks) == 40
        assert "enable JavaScript" not in document.text

    def test_both_guards_are_required(self) -> None:
        # Shell, but the noscript is a sentence: nothing to rescue.
        html = (
            "<html><body><div id='app'></div><noscript><p>Enable JS.</p></noscript></body></html>"
        )
        assert unwrap_noscript_shell(parse_html(html)) == 0
        # Substantial noscript, but the page is not a shell: leave it stripped.
        html = (
            "<html><body>"
            + "".join(f"<p>{PARAGRAPH}{i}.</p>" for i in range(30))
            + f"<noscript>{posts(20)}</noscript></body></html>"
        )
        assert unwrap_noscript_shell(parse_html(html)) == 0

    def test_thresholds_are_the_measured_shape(self) -> None:
        """Shells on WCXB held 5-41 visible words; their noscripts 1,000+. Wide margins."""
        assert NOSCRIPT_SHELL_MAX_WORDS >= 100
        assert NOSCRIPT_CONTENT_MIN_WORDS <= 500


class TestFormControls:
    def test_select_options_are_on_the_page_and_not_content(self) -> None:
        """glossier.com's 200-country selector was returned *instead of* the article once:
        the choices are one block marked `widget="select"`, on the whole page (Chromium
        shows them; dclt.co.uk's date and location filters are 118 of its 734 words) and
        stripped by the content step with the filters and consent dialogs."""
        from webgraph.content import select_content

        options = "".join(f"<option>Country {i} / CUR</option>" for i in range(200))
        html = (
            f"<html><body><form><select name='country'>{options}</select></form>"
            "<main><h1>Terms</h1><p>Receive ten percent off your purchase of three products, "
            "on any day of the week, in every store that carries the range.</p></main>"
            "</body></html>"
        )
        document = build_document(html, "https://x.test/")
        selects = [b for b in document.blocks if b.widget == "select"]
        assert len(selects) == 1 and selects[0].tag == "select" and selects[0].alt == "country"
        assert "Country 7 / CUR · Country 8 / CUR" in selects[0].text
        # Once, as the control's block; never run into the form's own text.
        assert sum("Country 7" in b.text for b in document.blocks) == 1
        content = select_content(document.blocks, title="Terms")
        assert not any("Country 7" in b.text for b in content.blocks)
        assert any("ten percent" in b.text for b in content.blocks)

    def test_textarea_and_datalist_too(self) -> None:
        html = (
            "<html><body><textarea>Type your comment here please</textarea>"
            "<datalist><option>Alpha</option></datalist><p>Visible paragraph.</p></body></html>"
        )
        texts = [b.text for b in build_document(html, "https://x.test/").blocks]
        assert texts == ["Visible paragraph."]

    def test_buttons_are_kept(self) -> None:
        """A button label can be the only text an interstitial has (see the gate probe)."""
        html = "<html><body><button>Solo Founder</button><p>Body text here.</p></body></html>"
        texts = [b.text for b in build_document(html, "https://x.test/").blocks]
        assert "Solo Founder" in " ".join(texts)


def page(
    main_tag: str = "main", main_attrs: str = "", nav_tag: str = "nav", nav_attrs: str = ""
) -> str:
    body = "".join(f"<p>{PARAGRAPH}{i}.</p>" for i in range(20))
    return (
        f"<html><body><{nav_tag} {nav_attrs}><a href='/'>Home</a> <a href='/a'>About</a></{nav_tag}>"
        f"<div class='sidebar'><p>Subscribe to our newsletter for weekly updates and offers.</p></div>"
        f"<{main_tag} {main_attrs}><h1>Title</h1>{body}</{main_tag}>"
        "<footer><a href='/t'>Terms</a></footer></body></html>"
    )


class TestRegions:
    def test_blocks_know_their_landmark(self) -> None:
        document = build_document(page(), "https://x.test/")
        regions = {b.text[:5]: b.region for b in document.blocks}
        assert regions["Home "] == "nav"
        assert regions["Terms"] == "footer"
        assert regions["Title"] == "main"
        assert regions["Subsc"] is None
        assert all(b.in_main for b in document.blocks if b.region == "main")

    def test_aria_roles_count_as_landmarks(self) -> None:
        html = page(
            main_tag="div", main_attrs='role="main"', nav_tag="div", nav_attrs='role="navigation"'
        )
        document = build_document(html, "https://x.test/")
        regions = {b.text[:5]: b.region for b in document.blocks}
        assert regions["Home "] == "nav"
        assert regions["Title"] == "main"

    def test_a_nav_inside_main_is_both(self) -> None:
        html = (
            "<html><body><main><nav><a href='#a'>Section A</a></nav>"
            + "".join(f"<p>{PARAGRAPH}{i}.</p>" for i in range(5))
            + "</main></body></html>"
        )
        document = build_document(html, "https://x.test/")
        toc = next(b for b in document.blocks if "Section A" in b.text)
        assert toc.region == "nav"
        assert toc.in_main


class TestStripLandmarksByRole:
    def test_role_navigation_is_stripped(self) -> None:
        html = page(
            main_tag="div", main_attrs='role="main"', nav_tag="div", nav_attrs='role="navigation"'
        )
        kept = strip_landmarks(build_document(html, "https://x.test/").blocks)
        assert not any("Home" in b.text for b in kept)
        assert any("Title" in b.text for b in kept)


class TestScopeToMain:
    def test_a_trustworthy_main_excludes_the_sidebar(self) -> None:
        document = build_document(page(), "https://x.test/")
        kept = strip_landmarks(document.blocks)
        scoped = scope_to_main(kept)
        assert not any("newsletter" in b.text for b in scoped)
        assert sum(1 for b in scoped if PARAGRAPH in b.text) == 20

    def test_an_empty_main_is_not_trusted(self) -> None:
        """A JavaScript mount point: `<main id="root"></main>` with the content around it.
        Measured on 21 WCXB pages. Scoping to it would return nothing; the guard refuses."""
        html = (
            "<html><body><main id='root'></main>"
            + "".join(f"<p>{PARAGRAPH}{i}.</p>" for i in range(20))
            + "</body></html>"
        )
        blocks = build_document(html, "https://x.test/").blocks
        assert scope_to_main(blocks) == list(blocks)

    def test_a_minor_main_is_not_trusted(self) -> None:
        """`<main>` holding a fraction of the page -- a filter panel on a collection page --
        while the product grid sits beside it. The share guard keeps the grid."""
        html = (
            "<html><body><main><p>Filter by size and colour.</p></main>"
            + "".join(f"<p>{PARAGRAPH}{i}.</p>" for i in range(40))
            + "</body></html>"
        )
        blocks = build_document(html, "https://x.test/").blocks
        assert scope_to_main(blocks) == list(blocks)
        assert MAIN_MIN_WORDS >= 50

    def test_it_is_a_step_in_select_content(self) -> None:
        document = build_document(page(), "https://x.test/")
        selection = select_content(document.blocks)
        assert "main-landmark" in selection.methods
        assert selection.main_scoped_removed >= 1
        assert not any("newsletter" in b.text for b in selection.blocks)


class TestWrapperDuplication:
    """A non-block wrapper between a container and its paragraphs must not re-emit them.

    Measured on WCXB dev: a `<section>` wrapping `<bsx-section>` wrapping 24 paragraphs was
    emitted as one 1,372-word block *and* as 24 paragraphs -- word counts doubled, precision
    0.48 with recall 1.00, and exact-text deduplication cannot see it because the container's
    text equals no single child's.
    """

    def _words(self, html: str) -> tuple[int, int]:
        document = build_document(html, "https://x.test/")
        emitted = sum(len(b.text.split()) for b in document.blocks)
        return emitted, len(document.blocks)

    def test_custom_element_wrapper(self) -> None:
        paragraphs = "".join(f"<p>{PARAGRAPH}{i}.</p>" for i in range(10))
        html = f"<html><body><section><bsx-section><div>{paragraphs}</div></bsx-section></section></body></html>"
        emitted, count = self._words(html)
        assert count == 10
        assert emitted == 10 * len(f"{PARAGRAPH}0.".split())

    def test_span_wrapper(self) -> None:
        paragraphs = "".join(f"<p>{PARAGRAPH}{i}.</p>" for i in range(10))
        html = f"<html><body><article><div><span>{paragraphs}</span></div></article></body></html>"
        _emitted, count = self._words(html)
        assert count == 10

    def test_lists_inside_a_container_are_not_re_emitted(self) -> None:
        items = "".join(f"<li>Item number {i} of the list.</li>" for i in range(6))
        html = f"<html><body><div><p>Intro paragraph here.</p><ul>{items}</ul></div></body></html>"
        emitted, count = self._words(html)
        assert count == 7
        assert emitted == 3 + 6 * 6  # "Intro paragraph here." + six items of six words

    def test_orphaned_text_is_still_kept(self) -> None:
        """The reason `_orphan_text` exists: text between blocks, carried by nobody else."""
        html = (
            "<html><body><div>Opening sentence of the article.<br><br>"
            "<div><img src='x.png' alt='pic'><span>Caption text</span></div>"
            "<br><br>Closing sentence of the article.</div></body></html>"
        )
        document = build_document(html, "https://x.test/")
        text = document.text
        assert "Opening sentence" in text
        assert "Closing sentence" in text
        assert text.count("Caption text") == 1

    def test_a_list_item_keeps_its_label_beside_a_sublist(self) -> None:
        html = "<html><body><ul><li>outer label<ul><li>inner item</li></ul></li></ul></body></html>"
        texts = [b.text for b in build_document(html, "https://x.test/").blocks]
        assert "outer label" in texts
        assert "inner item" in texts
        assert len(texts) == 2
