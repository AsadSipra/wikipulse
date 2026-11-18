"""FastAPI entry point: wires the pipeline into the app lifecycle."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import Settings, settings
from .hub import Hub
from .llm import Budgeted, OpenAICompatibleLLM
from .pipeline import Pipeline
from .sources import EventSource, LiveSource, ReplaySource
from .stats import RollingStats
from .vandalism import VandalismService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("wikipulse")


def build_source(cfg: Settings) -> EventSource:
    if cfg.source == "replay":
        return ReplaySource(cfg.replay_file, speed=cfg.replay_speed)
    return LiveSource()


def build_llm(cfg: Settings) -> OpenAICompatibleLLM | None:
    if not cfg.ai_enabled or not cfg.llm_model:
        return None
    return OpenAICompatibleLLM(
        cfg.llm_base_url, cfg.llm_model, cfg.llm_api_key, timeout=cfg.llm_timeout, max_tokens=cfg.llm_max_tokens
    )


def create_app(cfg: Settings = settings, source: EventSource | None = None, llm: Any = "auto") -> FastAPI:
    hub = Hub()
    stats = RollingStats(window_seconds=cfg.window_seconds, include_bots=cfg.include_bots)
    llm = build_llm(cfg) if llm == "auto" else llm
    vandalism_llm = Budgeted(llm, cfg.vandalism_calls_per_minute, "vandalism") if llm else None
    pulse_llm = Budgeted(llm, cfg.pulse_calls_per_minute, "pulse") if llm else None
    vandalism = VandalismService(vandalism_llm, fetch_diffs=cfg.fetch_diffs)
    pipeline = Pipeline(
        source or build_source(cfg), stats, hub, vandalism=vandalism, wikipedia_only=cfg.wikipedia_only
    )
    pipeline.attach_pulse(pulse_llm, cfg.pulse_interval_seconds)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(pipeline.run(), name="pipeline")
        task.add_done_callback(_log_crash)
        try:
            yield
        finally:
            # Clean up even if the pipeline already failed: awaiting a failed
            # task re-raises, and that must not skip closing the HTTP clients.
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
            await vandalism.aclose()
            if llm is not None:
                await llm.aclose()

    app = FastAPI(title="WikiPulse", lifespan=lifespan)
    app.state.pipeline = pipeline
    app.add_middleware(CORSMiddleware, allow_origins=list(cfg.cors_origins), allow_methods=["GET"])

    # Both routes are async so they run on the event loop that owns the stats.
    # A plain `def` route runs in a worker thread while ingestion mutates them.
    @app.get("/health")
    async def health() -> JSONResponse:
        failed = pipeline.failure is not None
        body = {
            "status": "down" if failed else "ok",
            "error": _failure_summary(pipeline.failure) if failed else None,
            "seconds_since_last_event": (
                round(time.time() - pipeline.last_event_at) if pipeline.last_event_at else None
            ),
            "source": type(pipeline.source).__name__,
            "connected": getattr(pipeline.source, "connected", True),
            "events_seen": stats.total_seen,
            "events_skipped": pipeline.parse_skipped,
            "events_filtered_non_wikipedia": pipeline.filtered_out,
            "clients": len(hub.clients),
            "uptime_seconds": round(time.time() - pipeline.started_at),
            "ai": {
                "enabled": llm is not None,
                "model": getattr(llm, "model", None),
                "llm_calls": getattr(llm, "calls", 0),
                "llm_failures": getattr(llm, "failures", 0),
                "llm_last_error": getattr(llm, "last_error", None),
                "budget_exhausted": {
                    "vandalism": getattr(vandalism_llm, "rate_limited", 0),
                    "pulse": getattr(pulse_llm, "rate_limited", 0),
                },
                "vandalism": vandalism.stats,
                "pulse_source": pipeline.pulse.latest.source if pipeline.pulse and pipeline.pulse.latest else None,
            },
        }
        # 503 lets Docker's healthcheck (and a reviewer) see that ingestion stopped.
        return JSONResponse(body, status_code=503 if failed else 200)

    @app.get("/api/snapshot")
    async def snapshot(wiki: str | None = None) -> dict[str, Any]:
        return pipeline.snapshot(wiki)

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        client = hub.add(ws)
        try:
            await hub.send(client, pipeline.initial_message(None))
            while True:
                wiki = parse_subscription(await ws.receive_json())
                if wiki is _INVALID:
                    continue  # ignore malformed messages rather than drop the client
                client.wiki = wiki
                await hub.send(client, pipeline.initial_message(client.wiki))
        except (WebSocketDisconnect, ValueError):
            pass
        finally:
            hub.remove(client)

    return app


_INVALID = object()
_WIKI_ID = re.compile(r"[a-z0-9_]{2,40}")


def parse_subscription(msg: Any) -> Any:
    """Wiki id from {"type": "subscribe", "wiki": <id or null>}, or _INVALID."""
    if not isinstance(msg, dict) or msg.get("type") != "subscribe":
        return _INVALID
    wiki = msg.get("wiki")
    if wiki is None or wiki == "":
        return None
    if isinstance(wiki, str) and _WIKI_ID.fullmatch(wiki):
        return wiki
    return _INVALID


def _failure_summary(exc: BaseException | None) -> str:
    if isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return f"{type(exc).__name__}: {exc}"[:200]


def _log_crash(task: asyncio.Task[None]) -> None:
    if not task.cancelled() and task.exception():
        log.error("pipeline stopped", exc_info=task.exception())


app = create_app()
