"""End-to-end through FastAPI: replay source -> pipeline -> WebSocket."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.sources import ReplaySource

SAMPLE = Path(__file__).parent.parent / "data" / "sample_events.jsonl"


def make_client():
    source = ReplaySource(SAMPLE, speed=0, loop=False)  # speed=0: as fast as possible
    app = create_app(Settings(source="replay"), source=source)
    return app, TestClient(app)


def test_health_reports_ingested_events():
    app, client = make_client()
    with client:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # init
            ws.receive_json()  # first tick: replay has finished by now
        body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["events_seen"] > 0
    assert body["events_skipped"] > 0


def test_websocket_init_then_ticks_and_wiki_subscription():
    app, client = make_client()
    with client, client.websocket_connect("/ws") as ws:
        init = ws.receive_json()
        assert init["type"] == "init"
        tick = ws.receive_json()
        assert tick["type"] == "tick"
        stats = tick["stats"]
        assert stats["edits_per_minute"] > 0
        assert 0 < len(stats["top_pages"]) <= 10
        assert all(p["url"].startswith("https://") for p in stats["top_pages"])

        ws.send_json({"type": "subscribe", "wiki": "dewiki"})
        filtered = ws.receive_json()
        while filtered["type"] != "init":  # a tick may arrive first
            filtered = ws.receive_json()
        assert filtered["stats"]["wiki"] == "dewiki"
        assert all(p["wiki"] == "dewiki" for p in filtered["stats"]["top_pages"])
        assert all(e["wiki"] == "dewiki" for e in filtered["edits"])
