import asyncio

from app.hub import Hub


class StuckSocket:
    """A browser connection whose sends never complete."""

    def __init__(self):
        self.closed = False

    async def send_json(self, message):
        await asyncio.sleep(3600)

    async def close(self):
        self.closed = True


async def test_a_stuck_client_is_dropped_and_its_socket_closed(monkeypatch):
    monkeypatch.setattr("app.hub.SEND_TIMEOUT", 0.01)
    hub = Hub()
    ws = StuckSocket()
    client = hub.add(ws)
    await hub.send(client, {"type": "tick"})
    assert client not in hub.clients
    assert ws.closed  # so the browser reconnects instead of waiting on a silent socket
