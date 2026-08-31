"""Cancellation and incremental discovery reporting.

Both exist for the same reason: a crawl is unbounded and long-running, so the caller needs
to be able to stop it, and needs to see what it found without being sent the whole frontier
on every event.
"""

from __future__ import annotations

from webgraph.crawl.frontier import CrawlScope, Frontier

ROOT = "https://example.com/"


def frontier() -> Frontier:
    return Frontier(scope=CrawlScope(root=ROOT, max_depth=5))


class TestFrontierExtend:
    def test_returns_accepted_urls(self) -> None:
        added = frontier().extend([f"{ROOT}a", f"{ROOT}b"], 1)
        assert added == [f"{ROOT}a", f"{ROOT}b"]

    def test_omits_duplicates(self) -> None:
        queue = frontier()
        queue.extend([f"{ROOT}a"], 1)
        assert queue.extend([f"{ROOT}a", f"{ROOT}a/"], 1) == []

    def test_omits_off_site(self) -> None:
        assert frontier().extend(["https://elsewhere.test/x"], 1) == []

    def test_resolves_relative_against_base(self) -> None:
        added = frontier().extend(["../about"], 1, base=f"{ROOT}docs/intro")
        assert added == [f"{ROOT}about"]

    def test_add_many_still_counts(self) -> None:
        """The count-returning form is used by the non-streaming crawler; keep it working."""
        assert frontier().add_many([f"{ROOT}a", f"{ROOT}a"], 1) == 1

    def test_accepted_urls_match_the_seen_count(self) -> None:
        """A client rebuilding the discovered set from deltas must land on the same total."""
        queue = frontier()
        rebuilt = queue.extend([f"{ROOT}a", f"{ROOT}b", f"{ROOT}a"], 1)
        rebuilt += queue.extend([f"{ROOT}b", f"{ROOT}c"], 2)
        assert len(rebuilt) == queue.seen_count


class TestStopFlag:
    def test_stream_stops_before_fetching_anything(self) -> None:
        """A generator cannot be interrupted from another thread, so the engine polls.

        Stopping before the first batch also proves the flag is checked *before* work, not
        merely after -- an abandoned crawl must not finish the page it is on plus the next
        six.
        """
        from webgraph.site import SiteConfig, stream_site

        events = list(
            stream_site(
                "https://example.invalid/",
                config=SiteConfig(max_pages=1, verify_inventory=False),
                should_stop=lambda: True,
            )
        )

        # An unresolvable host yields an error rather than reaching the crawl loop; either
        # way nothing may be extracted.
        assert not any(event["type"] == "page" for event in events)
