"""Glue between the event source, the stats, and the connected browsers.

Two loops run concurrently:
  * ingest: read events as fast as they arrive, parse, update stats, buffer.
  * tick:   once a second, push a stats snapshot plus the buffered edits.

Batching on a tick (instead of one WebSocket message per edit) caps the
message rate per client regardless of stream volume, which is what keeps the
browser smooth during spikes.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any

from .hub import Client, Hub
from .llm import LLM
from .models import Edit, is_wikipedia, page_url, parse_event
from .pulse import PulseService, comments_index
from .sources import EventSource
from .stats import RollingStats
from .vandalism import VandalismService

log = logging.getLogger(__name__)

RECENT_SIZE = 50  # edits sent to a client when it first connects
MAX_BATCH = 200  # cap per tick; the feed only shows the newest anyway


class Pipeline:
    def __init__(
        self,
        source: EventSource,
        stats: RollingStats,
        hub: Hub,
        tick_seconds: float = 1.0,
        vandalism: VandalismService | None = None,
        wikipedia_only: bool = True,
    ) -> None:
        self.source = source
        self.stats = stats
        self.hub = hub
        self.tick_seconds = tick_seconds
        self.vandalism = vandalism
        self.wikipedia_only = wikipedia_only
        self.recent: deque[Edit] = deque(maxlen=RECENT_SIZE)
        # (wiki, title, comment) for the last few thousand edits; feeds the Pulse prompt.
        self.comment_log: deque[tuple[str, str, str]] = deque(maxlen=3000)
        self.pulse: PulseService | None = None
        self._pending: deque[Edit] = deque(maxlen=MAX_BATCH)
        self.servers: dict[str, str] = {}  # wiki -> host, ~1k entries at most
        self.parse_skipped = 0  # untracked event types, canaries, malformed events
        self.filtered_out = 0  # valid edits from sister projects (Wikidata, Commons, ...)
        self.started_at = time.time()
        self.failure: BaseException | None = None
        self.last_event_at: float | None = None

    def has_viewers(self) -> bool:
        """True while at least one dashboard is connected. AI work pauses otherwise."""
        return bool(self.hub.clients)

    def attach_pulse(self, llm: LLM | None, interval_seconds: float) -> PulseService:
        self.pulse = PulseService(
            self.stats, comments_index(self.comment_log), llm, interval_seconds, has_viewers=self.has_viewers
        )
        return self.pulse

    async def run(self) -> None:
        """Run ingest, tick, Pulse and vandalism review as one unit.

        A TaskGroup owns the child tasks: if one fails, the others are
        cancelled instead of carrying on half-working, and the failure is
        recorded so /health can report it."""
        try:
            async with asyncio.TaskGroup() as group:
                group.create_task(self._ingest(), name="ingest")
                group.create_task(self._tick(), name="tick")
                if self.pulse:
                    group.create_task(self.pulse.run(), name="pulse")
                if self.vandalism:
                    group.create_task(self.vandalism.run(), name="vandalism")
        except Exception as exc:
            self.failure = exc
            raise

    def handle(self, raw: Any) -> Edit | None:
        edit = parse_event(raw)
        if edit is None:
            self.parse_skipped += 1
            return None
        if self.wikipedia_only and not is_wikipedia(edit.server_name):
            self.filtered_out += 1
            return None
        self.servers[edit.wiki] = edit.server_name
        self.stats.record(edit)
        self.recent.append(edit)
        self._pending.append(edit)
        if not edit.bot:
            self.comment_log.append((edit.wiki, edit.title, edit.comment))
        if self.vandalism:
            self.vandalism.consider(edit)
        return edit

    async def _ingest(self) -> None:
        async for raw in self.source.events():
            self.last_event_at = time.time()
            self.handle(raw)

    async def _tick(self) -> None:
        while True:
            await asyncio.sleep(self.tick_seconds)
            await self.flush()

    async def flush(self) -> None:
        batch = list(self._pending)
        self._pending.clear()
        flags = self.vandalism.drain() if self.vandalism else []
        snapshots: dict[str | None, dict[str, Any]] = {}

        def build(client: Client) -> dict[str, Any]:
            # Several clients usually share a filter; compute each snapshot once.
            if client.wiki not in snapshots:
                snapshots[client.wiki] = self.snapshot(client.wiki)
            return {
                "type": "tick",
                "stats": snapshots[client.wiki],
                "edits": [e.to_wire() for e in batch if client.wiki is None or e.wiki == client.wiki],
                "flags": [f.to_wire() for f in flags if client.wiki is None or f.wiki == client.wiki],
            }

        await self.hub.broadcast(build)

    def snapshot(self, wiki: str | None = None) -> dict[str, Any]:
        return {
            "wiki": wiki,
            "edits_per_minute": self.stats.edits_per_minute(wiki),
            "series": self.stats.series(wiki=wiki),
            "top_pages": [
                {
                    "wiki": w,
                    "title": title,
                    "count": count,
                    "url": self._page_url(w, title),
                }
                for (w, title), count in self.stats.top_pages(10, wiki)
            ],
            "wikis": [{"wiki": w, "count": c} for w, c in self.stats.wikis()],
            # Pulse is global: one summary of the whole stream, refreshed on a timer.
            "pulse": self.pulse.latest.to_wire() if self.pulse and self.pulse.latest else None,
            "connected": getattr(self.source, "connected", True),
            # So the UI can say what it's showing: live or recorded data, bots or not.
            "source": getattr(self.source, "kind", "live"),
            "include_bots": self.stats.include_bots,
            "generated_at": time.time(),
        }

    def initial_message(self, wiki: str | None) -> dict[str, Any]:
        return {
            "type": "init",
            "stats": self.snapshot(wiki),
            "edits": [e.to_wire() for e in self.recent if wiki is None or e.wiki == wiki],
            "flags": [
                f.to_wire() for f in (self.vandalism.recent if self.vandalism else [])
                if wiki is None or f.wiki == wiki
            ],
        }

    def _page_url(self, wiki: str, title: str) -> str | None:
        host = self.servers.get(wiki)
        return page_url(host, title) if host else None
