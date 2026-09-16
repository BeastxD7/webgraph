"""One request at a time per host, however many workers a crawl runs.

`delay_seconds` is a pause *per worker*: four workers each sleeping 0.3 s send the site
four requests a second, and a `Crawl-delay: 1` honoured the same way is four times what
the site asked for. The interval a site experiences is the one between consecutive
requests to it from the whole crawl, so it has to be enforced across the workers, not
inside each.

The throttle reserves slots rather than measuring gaps. Under one lock a caller takes the
later of "now" and the host's next free slot, and moves the next free slot one interval
past it; the sleep happens outside the lock. Two workers arriving together therefore leave
with slots one interval apart, and a third with the slot after that -- the order is the
order of arrival, and no two are ever closer than the interval, whichever thread wakes first.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from urllib.parse import urlsplit

__all__ = ["HostThrottle"]


class HostThrottle:
    """A minimum interval between requests to the same host, shared by every worker."""

    def __init__(
        self,
        interval_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.interval = max(0.0, float(interval_seconds))
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next_free: dict[str, float] = {}

    @staticmethod
    def host_of(url: str) -> str:
        try:
            return (urlsplit(url).hostname or "").lower()
        except ValueError:
            return ""

    def reserve(self, url: str) -> float:
        """Claim the next slot for `url`'s host and return how long to wait for it."""
        if self.interval <= 0:
            return 0.0
        host = self.host_of(url)
        with self._lock:
            now = self._clock()
            slot = max(now, self._next_free.get(host, 0.0))
            self._next_free[host] = slot + self.interval
        return slot - now

    def wait(self, url: str) -> float:
        """Block until `url`'s host may be asked again. Returns the seconds waited."""
        delay = self.reserve(url)
        if delay > 0:
            self._sleep(delay)
        return delay
