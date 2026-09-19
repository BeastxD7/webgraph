# webgraph

Web content extraction that says how it knows. Give it a page and it returns the page as
Markdown in reading order; give it a site and it returns every public page the same way,
with the navigation and footer separated from the content and a note on where each piece
came from.

- **Two fetches, merged.** Every page is fetched plainly and rendered in a browser, and the
  two are merged so that nothing either one had is lost. A page that needs JavaScript and a
  page whose static HTML is a consent wall are both handled, without predicting which is which.
- **Reading order is measured, not assumed.** The browser's layout decides what comes
  before what: columns are read down, cards are read one at a time, floats stay whole.
  The output says whether the order was measured or fell back to source order.
- **Content, not chrome.** Landmarks, repeated site furniture and boilerplate are separated
  from the page's own content by page type — article, product, forum, listing, documentation.
- **Refuses rather than guesses.** A wall, a login redirect, a robots.txt rule or an empty
  page is reported as what it is, not returned as a page.
- **No model in the extraction path.** Deterministic and reproducible, which is what makes
  the numbers below mean something.

## Install

```bash
pip install webgraph            # plain fetches only
pip install "webgraph[render]"  # + Playwright, for the browser fetch
playwright install chromium
```

Python 3.12 or newer. Without the `render` extra the engine still works from the plain
fetch alone and says so in `reading_order_method`.

## Use

```python
from webgraph import resolve_page, select_content, to_markdown

page = resolve_page("https://docs.python.org/3/tutorial/introduction.html")
print(page.strategy, page.document.reading_order_method)   # union, geometric-xy-cut

# The whole page, in reading order.
print(to_markdown(page.document))

# Just the content: navigation, footer and boilerplate taken out.
body = select_content(page.document.blocks, title=page.document.title)
print(to_markdown(page.document.model_copy(update={"blocks": tuple(body.blocks)})))
```

A whole site streams as it goes:

```python
from webgraph import SiteConfig, stream_site

for event in stream_site("https://example.com/", config=SiteConfig(max_pages=50)):
    if event["type"] == "page":
        print(event["url"], len(event["content_markdown"].split()), "words")
    elif event["type"] == "done":
        print(event["pages_ok"], "pages in", event["duration_seconds"], "s")
```

The command line does the same:

```bash
webgraph text https://example.com/            # one page, as Markdown
webgraph site https://example.com/ --max-pages 50
webgraph report https://example.com/          # what the site shows people and machines
```

## What it measures as

Scored on public benchmarks, unmodified, with the harnesses in the repository:

| benchmark | what it scores | webgraph |
|---|---|---|
| WCXB (1,497 dev / test pages, 7 page types) | main-content word F1 | 0.862 dev, 0.875 test — first on the published board, Sep 2026 |
| WCEB | main-content extraction | 0.883 |
| Zyte article extraction | 4-gram shingles | 0.945 |
| whole-page fidelity (38 sites vs Chromium's own text) | word recall | 0.998 mean |
| random web (300 pages nobody picked) | word recall | median 0.986 |

The reading-order claim has its own board, built from geometric axioms rather than from any
ordering algorithm. All of it is under `benchmark/` in the repository, with the numbers'
provenance.

## Where the rest is

The engine is one package of a larger repository — a FastAPI service and a Next.js front end
sit on top of it — at <https://github.com/BeastxD7/webgraph>. Documentation, the API, the
site report and the design notes live there.

Apache-2.0.
