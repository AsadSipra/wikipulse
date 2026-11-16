"""FastAPI entry point: wires the pipeline into the app lifecycle."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings, settings
from .hub import Hub
from .pipeline import Pipeline
from .sources import EventSource, LiveSource, ReplaySource
from .stats import RollingStats

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("wikipulse")


def build_source(cfg: Settings) -> EventSource:
    if cfg.source == "replay":
        return ReplaySource(cfg.replay_file, speed=cfg.replay_speed)
    return LiveSource()


def create_app(cfg: Settings = settings, source: EventSource | None = None) -> FastAPI:
    hub = Hub()
    stats = RollingStats(window_seconds=cfg.window_seconds, include_bots=cfg.include_bots)
    pipeline = Pipeline(source or build_source(cfg), stats, hub)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(pipeline.run(), name="pipeline")
        task.add_done_callback(_log_crash)
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    app = FastAPI(title="WikiPulse", lifespan=lifespan)
    app.state.pipeline = pipeline
    app.add_middleware(CORSMiddleware, allow_origins=list(cfg.cors_origins), allow_methods=["GET"])

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "source": type(pipeline.source).__name__,
            "connected": getattr(pipeline.source, "connected", True),
            "events_seen": stats.total_seen,
            "events_skipped": pipeline.parse_skipped,
            "clients": len(hub.clients),
            "uptime_seconds": round(time.time() - pipeline.started_at),
        }

    @app.get("/api/snapshot")
    def snapshot(wiki: str | None = None) -> dict[str, Any]:
        return pipeline.snapshot(wiki)

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        client = hub.add(ws)
        try:
            await hub.send(client, pipeline.initial_message(None))
            while True:
                msg = await ws.receive_json()
                if msg.get("type") == "subscribe":
                    wiki = msg.get("wiki") or None
                    client.wiki = wiki if isinstance(wiki, str) else None
                    await hub.send(client, pipeline.initial_message(client.wiki))
        except (WebSocketDisconnect, ValueError):
            pass
        finally:
            hub.remove(client)

    return app


def _log_crash(task: asyncio.Task[None]) -> None:
    if not task.cancelled() and task.exception():
        log.error("pipeline stopped", exc_info=task.exception())


app = create_app()
