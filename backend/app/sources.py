"""Event sources: the live Wikimedia stream and a JSONL replay, behind one interface."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Protocol

import httpx

from .models import normalize_timestamp

log = logging.getLogger(__name__)

STREAM_URL = "https://stream.wikimedia.org/v2/stream/recentchange"
# The stream never pauses this long, so silence means a dead connection.
IDLE_TIMEOUT = 60.0
# Required by https://meta.wikimedia.org/wiki/User-Agent_policy
USER_AGENT = "WikiPulse/0.1 (take-home assessment; contact via repository)"


class EventSource(Protocol):
    def events(self) -> AsyncIterator[dict[str, Any]]: ...


class LiveSource:
    """SSE client that reconnects with jittered backoff and resumes via Last-Event-ID."""

    kind = "live"

    def __init__(
        self,
        url: str = STREAM_URL,
        max_backoff: float = 30.0,
        idle_timeout: float = IDLE_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.url = url
        self.max_backoff = max_backoff
        self.idle_timeout = idle_timeout
        self.transport = transport
        self.last_event_id: str | None = None
        self.connected = False

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        backoff = 1.0
        # No read timeout: the idle watchdog handles silence.
        timeout = httpx.Timeout(10.0, read=None)
        async with httpx.AsyncClient(
            timeout=timeout, headers={"User-Agent": USER_AGENT}, transport=self.transport
        ) as client:
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
                        lines = until_idle(resp.aiter_lines(), self.idle_timeout)
                        async for event_id, data in parse_sse(lines):
                            if event_id:
                                self.last_event_id = event_id
                            try:
                                yield json.loads(data)
                            except json.JSONDecodeError:
                                log.warning("skipping non-JSON event")
                except (httpx.HTTPError, httpx.StreamError) as exc:
                    log.warning("stream error: %s", exc)
                except StreamIdle:
                    # Open but silent connection (seen in production): reconnect.
                    log.warning("no data for %.0fs; reconnecting", self.idle_timeout)
                finally:
                    self.connected = False
                delay = backoff * (0.5 + random.random())
                log.info("reconnecting in %.1fs", delay)
                await asyncio.sleep(delay)
                backoff = min(backoff * 2, self.max_backoff)


class StreamIdle(Exception):
    """No line arrived within the idle timeout."""


async def until_idle(lines: AsyncIterator[str], seconds: float) -> AsyncIterator[str]:
    """Pass lines through, raising StreamIdle if none arrives for `seconds`."""
    iterator = aiter(lines)
    while True:
        try:
            async with asyncio.timeout(seconds):
                line = await anext(iterator)
        except StopAsyncIteration:
            return
        except TimeoutError:
            raise StreamIdle from None
        yield line


async def parse_sse(lines: AsyncIterator[str]) -> AsyncIterator[tuple[str | None, str]]:
    """Minimal SSE parser yielding (event_id, data) per event."""
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
    """Replays a JSONL recording with its original timing (scaled by `speed`)."""

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
            with self.path.open(encoding="utf-8") as fh:
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
                    ts = normalize_timestamp(event.get("timestamp"))
                    if ts is not None and prev_ts is not None and self.speed > 0:
                        gap = max(0.0, min(ts - prev_ts, 5.0)) / self.speed
                        if gap:
                            await asyncio.sleep(gap)
                    else:
                        await asyncio.sleep(0)  # yield to the event loop
                    if ts is not None:
                        prev_ts = ts
                    yielded += 1
                    yield event
            if yielded == 0:
                # Otherwise an empty file would loop forever.
                raise RuntimeError(f"replay file has no events: {self.path}")
            if not self.loop:
                self.connected = False
                return
