"""Where events come from.

Both sources yield raw event dicts, so the pipeline doesn't care whether it is
reading the live Wikimedia stream or a recording. Replay is what makes the
system testable offline and gives a fallback for the demo if the network
misbehaves.

NOTE: LiveSource will be reconciled with the provided stream_client.py once
we receive it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Protocol

import httpx

log = logging.getLogger(__name__)

STREAM_URL = "https://stream.wikimedia.org/v2/stream/recentchange"
# Wikimedia asks every client to send a descriptive User-Agent with contact info
# (https://meta.wikimedia.org/wiki/User-Agent_policy); anonymous clients can be blocked.
USER_AGENT = "WikiPulse/0.1 (take-home assessment; contact via repository)"


class EventSource(Protocol):
    def events(self) -> AsyncIterator[dict[str, Any]]: ...


class LiveSource:
    """Server-Sent Events client with automatic reconnect.

    On disconnect it resumes from the last event id it saw (Last-Event-ID),
    so a short network blip doesn't silently drop edits. Backoff is
    exponential with jitter, capped, and resets after a healthy connection.
    """

    kind = "live"

    def __init__(self, url: str = STREAM_URL, max_backoff: float = 30.0) -> None:
        self.url = url
        self.max_backoff = max_backoff
        self.last_event_id: str | None = None
        self.connected = False

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        backoff = 1.0
        # No read timeout: the stream is long-lived. Connect timeout still applies.
        timeout = httpx.Timeout(10.0, read=None)
        async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": USER_AGENT}) as client:
            while True:
                headers = {"Accept": "text/event-stream"}
                if self.last_event_id:
                    headers["Last-Event-ID"] = self.last_event_id
                try:
                    async with client.stream("GET", self.url, headers=headers) as resp:
                        resp.raise_for_status()
                        self.connected = True
                        log.info("connected to stream")
                        backoff = 1.0
                        async for event_id, data in parse_sse(resp.aiter_lines()):
                            if event_id:
                                self.last_event_id = event_id
                            try:
                                yield json.loads(data)
                            except json.JSONDecodeError:
                                log.warning("skipping non-JSON event")
                except (httpx.HTTPError, httpx.StreamError) as exc:
                    log.warning("stream error: %s", exc)
                finally:
                    self.connected = False
                delay = backoff * (0.5 + random.random())
                log.info("reconnecting in %.1fs", delay)
                await asyncio.sleep(delay)
                backoff = min(backoff * 2, self.max_backoff)


async def parse_sse(lines: AsyncIterator[str]) -> AsyncIterator[tuple[str | None, str]]:
    """Minimal SSE parser: yields (event_id, data) per dispatched event.

    Follows the spec's rules that matter here: multi-line `data:` fields are
    joined with newlines, comment lines start with ':', and a blank line
    dispatches the event.
    """
    event_id: str | None = None
    data: list[str] = []
    async for line in lines:
        if line == "":
            if data:
                yield event_id, "\n".join(data)
            event_id, data = None, []
            continue
        if line.startswith(":"):
            continue
        name, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if name == "data":
            data.append(value)
        elif name == "id":
            event_id = value
    if data:
        yield event_id, "\n".join(data)


class ReplaySource:
    """Replays a JSONL recording, keeping the original gaps between events.

    `speed` > 1 replays faster; `loop` restarts at the end so a demo can run
    indefinitely.
    """

    kind = "replay"

    def __init__(self, path: str | Path, speed: float = 1.0, loop: bool = True) -> None:
        self.path = Path(path)
        self.speed = speed
        self.loop = loop
        self.connected = True

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            prev_ts: float | None = None
            yielded = 0
            with self.path.open() as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    ts = event.get("timestamp")
                    if isinstance(ts, (int, float)) and prev_ts is not None and self.speed > 0:
                        gap = max(0.0, min(ts - prev_ts, 5.0)) / self.speed
                        if gap:
                            await asyncio.sleep(gap)
                    else:
                        await asyncio.sleep(0)  # stay cooperative on fast replays
                    if isinstance(ts, (int, float)):
                        prev_ts = ts
                    yielded += 1
                    yield event
            if yielded == 0:
                # Looping over a file with no events would spin forever without
                # ever yielding to the event loop; fail clearly instead.
                raise RuntimeError(f"replay file has no events: {self.path}")
            if not self.loop:
                self.connected = False  # the recording has ended
                return
