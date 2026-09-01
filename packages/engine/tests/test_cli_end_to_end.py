"""The CLI, exercised against a real HTTP server rather than a mock.

`test_cli.py` checks that the arguments parse. This checks that the pipeline behind them
works: crawl, build a graph, write it, read it back, answer a question from it, and report
what changed on a second crawl. Those five things pass results between four modules, and
every seam is somewhere a unit test would have to fake.

A local `ThreadingHTTPServer` over fixture pages, so it runs in CI with no network and no
browser -- the crawl uses the static strategy by default.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from webgraph.cli import main

SITE = Path(__file__).parent / "fixtures" / "site"


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # noqa: ARG002 - silences the handler
        return


@pytest.fixture(scope="module")
def site() -> Iterator[str]:
    handler = partial(_QuietHandler, directory=str(SITE))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/index.html"
    finally:
        httpd.shutdown()
        httpd.server_close()


def records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class TestGraphCommand:
    def test_it_crawls_and_writes_a_graph(self, site: str, tmp_path: Path) -> None:
        out = tmp_path / "site.jsonl"
        assert main(["graph", site, "--max-pages", "10", "--out", str(out)]) == 0

        kinds = [r["kind"] for r in records(out)]
        assert kinds.count("page") == 4
        assert "section" in kinds
        assert "link" in kinds

    def test_anchor_text_survives_the_round_trip(self, site: str, tmp_path: Path) -> None:
        """The anchor is the relation label -- losing it would throw away the one thing this
        graph has that an inferred one pays a model for."""
        out = tmp_path / "site.jsonl"
        main(["graph", site, "--max-pages", "10", "--out", str(out)])

        anchors = {a for r in records(out) if r["kind"] == "link" for a in r["anchors"]}
        assert "what a widget costs" in anchors

    def test_cypher_output_is_idempotent(self, site: str, capsys) -> None:
        assert main(["graph", site, "--max-pages", "6", "--format", "cypher"]) == 0
        emitted = capsys.readouterr().out
        assert "CREATE NODE TABLE" in emitted
        assert "MERGE (p:Page" in emitted
        assert "CREATE (" not in emitted


class TestAskCommand:
    def test_it_answers_from_a_saved_graph(self, site: str, tmp_path: Path, capsys) -> None:
        """Re-crawling to answer a second question would make the graph pointless."""
        out = tmp_path / "site.jsonl"
        main(["graph", site, "--max-pages", "10", "--out", str(out)])
        capsys.readouterr()

        assert main(["ask", "enterprise plan onsite calibration", "--graph", str(out)]) == 0
        context = capsys.readouterr().out
        assert "dedicated engineer" in context

    def test_the_context_names_the_pages_it_left_out(self, site: str, tmp_path: Path, capsys) -> None:
        """A truncated context must not lie by omission."""
        out = tmp_path / "site.jsonl"
        main(["graph", site, "--max-pages", "10", "--out", str(out)])
        capsys.readouterr()

        main(["ask", "torque", "--graph", str(out), "--max-chars", "1200"])
        context = capsys.readouterr().out
        assert "Other pages on this site" in context

    def test_expansion_reaches_a_page_the_words_do_not(self, site: str, tmp_path: Path, capsys) -> None:
        """"tungsten fasteners" appears only on the home page, which links to pricing as
        "what a widget costs". Nothing in the query resembles the pricing page."""
        out = tmp_path / "site.jsonl"
        main(["graph", site, "--max-pages", "10", "--out", str(out)])
        capsys.readouterr()

        main(["ask", "tungsten fasteners machined tolerance", "--graph", str(out)])
        context = capsys.readouterr().out
        assert "pricing.html" in context


class TestDiffCommand:
    def test_the_first_run_records_a_baseline(self, site: str, tmp_path: Path, capsys) -> None:
        assert main(["diff", site, "--max-pages", "10", "--store", str(tmp_path)]) == 0
        assert "baseline saved" in capsys.readouterr().out

    def test_an_unchanged_site_reports_no_change(self, site: str, tmp_path: Path, capsys) -> None:
        main(["diff", site, "--max-pages", "10", "--store", str(tmp_path)])
        capsys.readouterr()

        assert main(["diff", site, "--max-pages", "10", "--store", str(tmp_path)]) == 0
        assert "No change" in capsys.readouterr().out

    def test_fail_on_change_exits_zero_when_nothing_changed(
        self, site: str, tmp_path: Path, capsys
    ) -> None:
        """So a scheduled job can drive on the exit code without parsing output."""
        main(["diff", site, "--max-pages", "10", "--store", str(tmp_path)])
        capsys.readouterr()

        assert (
            main(
                [
                    "diff",
                    site,
                    "--max-pages",
                    "10",
                    "--store",
                    str(tmp_path),
                    "--fail-on-change",
                ]
            )
            == 0
        )
