"""What each `Strategy` actually does, pinned against a fake browser.

The old `resolve_page` docstring promised that with `strategy=None` it would "render whenever
the profiler is not confident the static HTML is complete". The code rendered
unconditionally; the `requires_render` check in the expression was unreachable because
`strategy is None` sat beside it in the same `or`. And `RENDERED_ONLY`, passed in, fell
through to a static-only result. Neither was tested, so neither was noticed.

`None` now means what the module's own measurement says it must -- complete, i.e. UNION --
and each of the three named strategies does exactly what its name says.
"""

from __future__ import annotations

from typing import Any

import pytest

from webgraph import resolve as resolve_module
from webgraph.fetch.render import RenderResult
from webgraph.fetch.static import FetchResult
from webgraph.resolve import Strategy, resolve_page

URL = "https://example.test/"

STATIC = (
    "<html><body><main><h1>Static</h1>"
    "<p>Prose the server rendered, present without JavaScript.</p></main></body></html>"
)
SHELL = '<html><body><div id="root"></div><script src="/app.js"></script></body></html>'
RENDERED = (
    "<html><body><main><h1>Static</h1>"
    "<p>Prose the server rendered, present without JavaScript.</p>"
    "<p>Prose hydration added, absent from the static HTML.</p></main></body></html>"
)


@pytest.fixture(autouse=True)
def browser(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A fake static fetch and a fake render, each counting how often it ran."""
    state: dict[str, Any] = {"static_html": STATIC, "renders": 0}

    def fake_fetch(url: str, **_: Any) -> FetchResult:
        return FetchResult(
            url=url,
            requested_url=url,
            status=200,
            html=state["static_html"],
            content_type="text/html",
            elapsed_seconds=0.0,
            ok=True,
        )

    def fake_render(url: str, **_: Any) -> RenderResult:
        state["renders"] += 1
        return RenderResult(url=url, html=RENDERED, rects={}, ok=True)

    monkeypatch.setattr(resolve_module, "fetch_static", fake_fetch)
    monkeypatch.setattr(resolve_module, "render_page", fake_render)
    monkeypatch.setattr(resolve_module, "PLAYWRIGHT_AVAILABLE", True)
    return state


class TestUnset:
    def test_none_renders_and_unions(self, browser: dict[str, Any]) -> None:
        resolved = resolve_page(URL, strategy=None)
        assert browser["renders"] == 1
        assert resolved.strategy is Strategy.UNION
        assert "hydration added" in resolved.document.text
        assert "server rendered" in resolved.document.text

    def test_none_renders_even_when_the_static_page_looks_complete(
        self, browser: dict[str, Any]
    ) -> None:
        """The profiler cannot see partial loss, so its confidence must not skip the render."""
        resolve_page(URL)
        assert browser["renders"] == 1


class TestStaticOnly:
    def test_never_renders(self, browser: dict[str, Any]) -> None:
        resolved = resolve_page(URL, strategy=Strategy.STATIC_ONLY)
        assert browser["renders"] == 0
        assert resolved.strategy is Strategy.STATIC_ONLY
        assert "hydration added" not in resolved.document.text

    def test_not_even_for_a_shell(self, browser: dict[str, Any]) -> None:
        """Explicit is explicit: the caller chose budget, so no browser runs. But an empty
        shell is not a page, and it used to be returned as one -- zero blocks, `ok`. Now the
        failure says exactly what happened and what would fix it."""
        import pytest

        browser["static_html"] = SHELL
        with pytest.raises(ValueError, match="JavaScript shell") as caught:
            resolve_page(URL, strategy=Strategy.STATIC_ONLY)
        assert browser["renders"] == 0
        assert "rendering was not used" in str(caught.value)

    def test_the_shell_refusal_carries_the_shell(self, browser: dict[str, Any]) -> None:
        """A shell's hydration payload is complete without a browser, and fact extraction
        reads it: the refusal is typed and hands the document over, so `/api/extract` can
        answer from the payload while `/api/text`, with nothing to say, still refuses."""
        import pytest

        from webgraph.resolve import PageShellError

        browser["static_html"] = SHELL
        with pytest.raises(PageShellError) as caught:
            resolve_page(URL, strategy=Strategy.STATIC_ONLY)
        assert caught.value.document.url == URL
        assert caught.value.document.profile.requires_render


class TestRenderedOnly:
    def test_returns_the_browser_document_alone(self, browser: dict[str, Any]) -> None:
        resolved = resolve_page(URL, strategy=Strategy.RENDERED_ONLY)
        assert browser["renders"] == 1
        assert resolved.strategy is Strategy.RENDERED_ONLY
        assert "hydration added" in resolved.document.text

    def test_reports_what_the_static_fetch_held(self) -> None:
        resolved = resolve_page(URL, strategy=Strategy.RENDERED_ONLY)
        assert resolved.static_chars > 0
        assert resolved.rendered_chars == resolved.union_chars

    def test_falls_back_to_static_when_the_render_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def failing(url: str, **_: Any) -> RenderResult:
            return RenderResult(url=url, html="", rects={}, ok=False, error="boom")

        monkeypatch.setattr(resolve_module, "render_page", failing)
        resolved = resolve_page(URL, strategy=Strategy.RENDERED_ONLY)
        assert resolved.strategy is Strategy.STATIC_ONLY
        assert resolved.render_error == "boom"


class TestWithoutABrowser:
    def test_everything_degrades_to_static_and_says_so(
        self, browser: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(resolve_module, "PLAYWRIGHT_AVAILABLE", False)
        for strategy in (None, Strategy.UNION, Strategy.RENDERED_ONLY):
            resolved = resolve_page(URL, strategy=strategy)
            assert resolved.strategy is Strategy.STATIC_ONLY
            assert resolved.render_error == "rendering not available"
        assert browser["renders"] == 0
