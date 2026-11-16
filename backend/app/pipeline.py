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
from .models import Edit, parse_event
from .sources import EventSource
from .stats import RollingStats

log = logging.getLogger(__name__)

RECENT_SIZE = 50  # edits sent to a client when it first connects
MAX_BATCH = 200  # cap per tick; the feed only shows the newest anyway


class Pipeline:
    def __init__(self, source: EventSource, stats: RollingStats, hub: Hub, tick_seconds: float = 1.0) -> None:
        self.source = source
        self.stats = stats
        self.hub = hub
        self.tick_seconds = tick_seconds
        self.recent: deque[Edit] = deque(maxlen=RECENT_SIZE)
        self._pending: deque[Edit] = deque(maxlen=MAX_BATCH)
        self.servers: dict[str, str] = {}  # wiki -> host, ~1k entries at most
        self.parse_skipped = 0
        self.started_at = time.time()

    async def run(self) -> None:
        await asyncio.gather(self._ingest(), self._tick())

    def handle(self, raw: dict[str, Any]) -> Edit | None:
        edit = parse_event(raw)
        if edit is None:
            self.parse_skipped += 1
            return None
        self.servers[edit.wiki] = edit.server_name
        self.stats.record(edit)
        self.recent.append(edit)
        self._pending.append(edit)
        return edit

    async def _ingest(self) -> None:
        async for raw in self.source.events():
            self.handle(raw)

    async def _tick(self) -> None:
        while True:
            await asyncio.sleep(self.tick_seconds)
            await self.flush()

    async def flush(self) -> None:
        batch = list(self._pending)
        self._pending.clear()
        snapshots: dict[str | None, dict[str, Any]] = {}

        def build(client: Client) -> dict[str, Any]:
            # Several clients usually share a filter; compute each snapshot once.
            if client.wiki not in snapshots:
                snapshots[client.wiki] = self.snapshot(client.wiki)
            return {
                "type": "tick",
                "stats": snapshots[client.wiki],
                "edits": [e.to_wire() for e in batch if client.wiki is None or e.wiki == client.wiki],
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
            "connected": getattr(self.source, "connected", True),
            "generated_at": time.time(),
        }

    def initial_message(self, wiki: str | None) -> dict[str, Any]:
        return {
            "type": "init",
            "stats": self.snapshot(wiki),
            "edits": [e.to_wire() for e in self.recent if wiki is None or e.wiki == wiki],
        }


    def _page_url(self, wiki: str, title: str) -> str | None:
        host = self.servers.get(wiki)
        return f"https://{host}/wiki/{title.replace(' ', '_')}" if host else None
