"""WebSocket fan-out to dashboard clients.

Each client may subscribe to one wiki (or all). Filtering happens on the
server so a client watching a small wiki doesn't receive the full firehose.
A slow client never blocks the others: sends run concurrently with a timeout,
and a client that fails or times out is dropped.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

log = logging.getLogger(__name__)

SEND_TIMEOUT = 2.0


@dataclass(eq=False)
class Client:
    ws: WebSocket
    wiki: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class Hub:
    def __init__(self) -> None:
        self.clients: set[Client] = set()

    def add(self, ws: WebSocket) -> Client:
        client = Client(ws)
        self.clients.add(client)
        return client

    def remove(self, client: Client) -> None:
        self.clients.discard(client)

    async def send(self, client: Client, message: dict[str, Any]) -> None:
        try:
            await asyncio.wait_for(client.ws.send_json(message), SEND_TIMEOUT)
        except Exception:  # disconnects surface as several exception types
            log.info("dropping client after failed send")
            self.remove(client)

    async def broadcast(self, build: Any) -> None:
        """Send a per-client message. `build(client)` returns a message or None."""
        sends = []
        for client in list(self.clients):
            message = build(client)
            if message is not None:
                sends.append(self.send(client, message))
        if sends:
            await asyncio.gather(*sends)
