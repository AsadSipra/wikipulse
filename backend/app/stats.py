"""Rolling statistics over a sliding time window.

Design: time is split into 1-second buckets kept in a deque. Each bucket holds
a Counter of pages edited in that second. Alongside, we keep *running totals*
for the whole window. When a bucket falls out of the window we subtract it
from the totals instead of re-scanning everything, so recording an edit and
expiring old data are both O(1) amortised per event, no matter how busy the
stream is.

Windows use ingest time (when we saw the edit), not the event's own timestamp.
That keeps the numbers meaningful when replaying an old recording and avoids
clock-skew surprises; at stream latency (~1s) the difference is negligible.
"""

from __future__ import annotations

import time
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass, field

from .models import Edit

PageKey = tuple[str, str]  # (wiki, title): the same title on two wikis is two pages
ARTICLE_NAMESPACE = 0


@dataclass
class _Bucket:
    second: int
    pages: Counter[PageKey] = field(default_factory=Counter)
    wikis: Counter[str] = field(default_factory=Counter)
    total: int = 0


class RollingStats:
    def __init__(
        self,
        window_seconds: int = 300,
        clock: Callable[[], float] = time.time,
        include_bots: bool = False,
    ) -> None:
        self.window_seconds = window_seconds
        self.include_bots = include_bots
        self._clock = clock
        self._buckets: deque[_Bucket] = deque()
        self._page_totals: Counter[PageKey] = Counter()
        self._wiki_totals: Counter[str] = Counter()
        self.total_seen = 0  # lifetime counter, handy for the health endpoint

    def record(self, edit: Edit) -> None:
        self.total_seen += 1
        if edit.bot and not self.include_bots:
            return
        now = int(self._clock())
        self._expire(now)
        if not self._buckets or self._buckets[-1].second != now:
            self._buckets.append(_Bucket(second=now))
        bucket = self._buckets[-1]
        bucket.wikis[edit.wiki] += 1
        bucket.total += 1
        self._wiki_totals[edit.wiki] += 1
        # Every edit counts towards the rate, but only articles (namespace 0)
        # can trend: user pages, sandboxes and noticeboards are noise to a reader.
        if edit.namespace == ARTICLE_NAMESPACE:
            key = (edit.wiki, edit.title)
            bucket.pages[key] += 1
            self._page_totals[key] += 1

    def _expire(self, now: int) -> None:
        cutoff = now - self.window_seconds
        while self._buckets and self._buckets[0].second <= cutoff:
            old = self._buckets.popleft()
            _subtract(self._page_totals, old.pages)
            _subtract(self._wiki_totals, old.wikis)

    def edits_in_last(self, seconds: int, wiki: str | None = None) -> int:
        now = int(self._clock())
        self._expire(now)
        cutoff = now - seconds
        count = 0
        for bucket in reversed(self._buckets):
            if bucket.second <= cutoff:
                break
            if wiki is None:
                count += bucket.total
            else:
                count += bucket.wikis[wiki]
        return count

    def edits_per_minute(self, wiki: str | None = None) -> int:
        return self.edits_in_last(60, wiki)

    def series(self, step: int = 10, points: int = 30, wiki: str | None = None) -> list[dict[str, int]]:
        """Edits/min sampled every `step` seconds, for the chart. Oldest first."""
        now = int(self._clock())
        self._expire(now)
        counts: Counter[int] = Counter()
        for bucket in self._buckets:
            n = bucket.total if wiki is None else bucket.wikis[wiki]
            counts[(now - bucket.second) // step] += n
        scale = 60 / step  # convert "edits in this step" to an edits/min rate
        return [
            {"t": now - i * step, "rate": round(counts[i] * scale)}
            for i in range(points - 1, -1, -1)
        ]

    def top_pages(self, n: int = 10, wiki: str | None = None) -> list[tuple[PageKey, int]]:
        self._expire(int(self._clock()))
        items = (
            (k, c) for k, c in self._page_totals.items()
            if wiki is None or k[0] == wiki
        )
        # Ties broken by title so the table doesn't flicker between equal pages.
        return sorted(items, key=lambda kc: (-kc[1], kc[0][1]))[:n]

    def wikis(self) -> list[tuple[str, int]]:
        self._expire(int(self._clock()))
        return sorted(self._wiki_totals.items(), key=lambda wc: (-wc[1], wc[0]))


def _subtract(totals: Counter, expired: Counter) -> None:
    """Remove an expired bucket from running totals, deleting keys that hit zero
    so the totals only ever hold pages edited inside the window."""
    for key, n in expired.items():
        remaining = totals[key] - n
        if remaining > 0:
            totals[key] = remaining
        else:
            del totals[key]
