"""Reuse one Chromium per worker thread instead of launching one per page.

Why thread-local rather than a shared pool
------------------------------------------
Playwright's *synchronous* API binds its driver to the thread that started it: a `Browser`
created on one thread cannot be driven from another. A single shared browser would need the
async API and an event loop the engine does not otherwise have. Crawl worker threads are
long-lived, so a browser per thread pays the launch cost once and amortises it over every
page that thread handles.

Isolation is preserved by giving each page its own `BrowserContext` -- a fresh cookie jar,
cache and storage -- which costs milliseconds rather than the seconds a launch costs.

Bounding
--------
`MAX_BROWSERS` caps live browsers process-wide. Each is roughly 150 MB resident, and a
server handling several simultaneous crawls at concurrency 6 would otherwise open dozens.
A thread that cannot get a slot falls back to a private launch, so correctness never
depends on the cap.
"""

from __future__ import annotations

import atexit
import threading
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:  # pragma: no cover - typing only
    from playwright.sync_api import Browser, Playwright

__all__ = ["MAX_BROWSERS", "close_thread_browser", "shared_browser"]

MAX_BROWSERS: Final[int] = 6
"""Live browsers across the whole process. Roughly 150 MB resident each."""

_local = threading.local()
_slots = threading.Semaphore(MAX_BROWSERS)
_registry_lock = threading.Lock()
_registry: list[tuple[Any, Any]] = []


def shared_browser(*, headless: bool = True) -> Browser | None:
    """The calling thread's browser, launching it on first use.

    Returns `None` when the process is already at `MAX_BROWSERS`; the caller should then
    launch its own short-lived browser rather than block, since blocking here would stall a
    crawl worker behind an unrelated one.
    """
    existing = getattr(_local, "browser", None)
    if existing is not None:
        if existing.is_connected():
            return existing  # type: ignore[no-any-return]
        # A crashed browser must not be handed out again.
        _forget_local()

    if not _slots.acquire(blocking=False):
        return None

    try:
        from playwright.sync_api import sync_playwright

        driver: Playwright = sync_playwright().start()
        browser = driver.chromium.launch(headless=headless)
    except Exception:
        _slots.release()
        return None

    _local.driver = driver
    _local.browser = browser
    with _registry_lock:
        _registry.append((driver, browser))
    return browser


def close_thread_browser() -> None:
    """Close the calling thread's browser, if it has one.

    Worth calling when a thread is about to be retired. It is not required for correctness:
    the operating system reaps the child processes when this one exits.
    """
    driver = getattr(_local, "driver", None)
    browser = getattr(_local, "browser", None)
    if driver is None and browser is None:
        return

    try:
        if browser is not None:
            browser.close()
        if driver is not None:
            driver.stop()
    except Exception:
        pass
    finally:
        with _registry_lock:
            _registry[:] = [
                entry for entry in _registry if entry[1] is not browser
            ]
        _forget_local()
        _slots.release()


def _forget_local() -> None:
    _local.driver = None
    _local.browser = None


@atexit.register
def _close_all() -> None:
    """Best-effort teardown.

    This runs on the main thread, and Playwright objects belong to the thread that made
    them, so most of these calls raise. They are swallowed: the point of the hook is to
    close browsers owned by the main thread, and the OS handles the rest.
    """
    with _registry_lock:
        entries = list(_registry)
        _registry.clear()
    for driver, browser in entries:
        try:
            browser.close()
            driver.stop()
        except Exception:
            pass
