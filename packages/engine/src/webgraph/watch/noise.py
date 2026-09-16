"""What a watch ignores before it calls a page changed.

The complaint about every change monitor is false positives (research: Visualping's
dominant review theme is alerts from churn that means nothing). Two kinds of churn are
already separated by the engine and cost nothing here: navigation, headers, footers and
comment threads are removed by content selection, so a watch reads `content_markdown` and
a site-wide footer edit changes no page. The third kind is inside the content -- a "last
updated" line, a visitor counter, a clock, a cache-busting query string on an image -- and
that is what this module drops.

The rule
--------
A section is compared block by block (a block is a paragraph, a list, a table: Markdown
separated by a blank line). Each noise pattern (`config.WATCH_NOISE_PATTERNS`) is removed
from the block's text; if at least one matched and fewer than `WATCH_NOISE_MIN_WORDS`
alphabetic words remain, the block *was* the pattern -- a date, a time, a counter -- and it
is left out of the comparison. A block that no pattern touches is always compared, however
short. "Results announced on 12 September 2026" is a sentence and is compared; "Last
updated: 12 Sep 2026" and "Visitors: 1,204,551" are not. Query strings are stripped from
Markdown link and image targets, because `logo.png?v=1694` changes on every deploy and the
logo does not.

Deterministic and documented, so a reported change can always be explained and a suppressed
one can always be found: the run reports how many pages it suppressed as noise.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final

from webgraph import config

__all__ = ["NoiseRules"]

_WORD: Final[re.Pattern[str]] = re.compile(r"[^\W\d_]{2,}", re.UNICODE)
"""An alphabetic word of two or more letters, in any script; digits and underscores are not."""

_LINK_QUERY: Final[re.Pattern[str]] = re.compile(r"(\]\([^)\s?#]+)\?[^)\s#]*")
"""`](target?query` -> `](target` inside a Markdown link or image."""

_BLANK_LINES: Final[re.Pattern[str]] = re.compile(r"\n[ \t]*\n+")


@dataclass(frozen=True, slots=True)
class NoiseRules:
    patterns: tuple[re.Pattern[str], ...]
    min_words: int = config.WATCH_NOISE_MIN_WORDS
    enabled: bool = True

    @classmethod
    def default(cls) -> NoiseRules:
        return cls(patterns=_compile(config.WATCH_NOISE_PATTERNS))

    @classmethod
    def from_config(cls, options: dict[str, Any] | None) -> NoiseRules:
        """The default rules, plus a watch's own `noise_patterns`, or none when `noise`
        is false."""
        options = options or {}
        if options.get("noise") is False:
            return cls(patterns=(), enabled=False)
        extra = tuple(str(p) for p in options.get("noise_patterns") or ())
        return cls(
            patterns=_compile((*config.WATCH_NOISE_PATTERNS, *extra)),
            min_words=int(options.get("noise_min_words") or config.WATCH_NOISE_MIN_WORDS),
        )

    def is_noise(self, block: str) -> bool:
        """Whether a block is a date, a time or a counter rather than text that has one."""
        if not self.enabled:
            return False
        text = block
        matched = False
        for pattern in self.patterns:
            text, count = pattern.subn(" ", text)
            matched = matched or count > 0
        if not matched:
            return False
        return len(_WORD.findall(text)) < self.min_words

    def clean(self, text: str) -> str:
        """The text as compared: noise blocks removed, link queries stripped, whitespace
        folded within blocks and a single blank line between them."""
        if not self.enabled:
            return "\n\n".join(" ".join(b.split()) for b in _blocks(text))
        kept = []
        for block in _blocks(text):
            block = _LINK_QUERY.sub(r"\1", block)
            if self.is_noise(block):
                continue
            kept.append(" ".join(block.split()))
        return "\n\n".join(kept)

    def describe(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "min_words": self.min_words,
            "patterns": [p.pattern for p in self.patterns],
        }


def _blocks(text: str) -> list[str]:
    return [b for b in _BLANK_LINES.split(text.strip()) if b.strip()]


def _compile(patterns: Iterable[str]) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, re.IGNORECASE) for p in patterns)
