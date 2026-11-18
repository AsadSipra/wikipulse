"""End-to-end through FastAPI: replay source -> pipeline -> WebSocket."""

import asyncio
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import _INVALID, create_app, parse_subscription
from app.sources import ReplaySource

from .fakes import FakeLLM

SAMPLE = Path(__file__).parent.parent / "data" / "sample_events.jsonl"


def make_client(llm=None):
    source = ReplaySource(SAMPLE, speed=0, loop=False)  # speed=0: as fast as possible
    cfg = Settings(source="replay", fetch_diffs=False, pulse_interval_seconds=0.05)
    app = create_app(cfg, source=source, llm=llm)
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
    assert body["events_filtered_non_wikipedia"] > 0  # the sample includes Commons edits


def test_websocket_init_then_ticks_and_wiki_subscription():
    app, client = make_client()
    with client, client.websocket_connect("/ws") as ws:
        init = ws.receive_json()
        assert init["type"] == "init"
        tick = ws.receive_json()
        assert tick["type"] == "tick"
        stats = tick["stats"]
        assert stats["edits_per_minute"] > 0
        assert stats["source"] == "replay" and stats["include_bots"] is False
        assert 0 < len(stats["top_pages"]) <= 10
        assert all(p["url"].startswith("https://") for p in stats["top_pages"])
        assert all(p["wiki"] != "commonswiki" for p in stats["top_pages"])

        ws.send_json({"type": "subscribe", "wiki": "dewiki"})
        filtered = ws.receive_json()
        while filtered["type"] != "init":  # a tick may arrive first
            filtered = ws.receive_json()
        assert filtered["stats"]["wiki"] == "dewiki"
        assert all(p["wiki"] == "dewiki" for p in filtered["stats"]["top_pages"])
        assert all(e["wiki"] == "dewiki" for e in filtered["edits"])


def test_flags_and_pulse_reach_the_browser():
    # Diffs are off in these tests, so vandalism never calls the LLM (strong rule
    # matches still flag) and the only LLM caller is Pulse. The LLM review path
    # is covered in test_vandalism.py.
    llm = FakeLLM({"headline": "Busy afternoon", "summary": "Lots happening."})
    app, client = make_client(llm)
    with client, client.websocket_connect("/ws") as ws:
        flags, pulse = [], None
        for _ in range(40):
            msg = ws.receive_json()
            flags += msg.get("flags", [])
            pulse = msg["stats"]["pulse"] or pulse
            if flags and pulse:
                break
    assert flags and all(f["source"] == "rules" for f in flags)
    assert pulse == {**pulse, "headline": "Busy afternoon", "source": "llm"}


class BrokenSource:
    connected = True

    async def events(self):
        yield {"type": "edit"}
        raise RuntimeError("upstream exploded")


def wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_health_reports_down_when_ingestion_dies():
    """Regression: /health said "ok" (HTTP 200) after the pipeline had crashed."""
    app = create_app(Settings(source="replay", fetch_diffs=False), source=BrokenSource(), llm=None)
    with TestClient(app) as client:
        assert wait_for(lambda: app.state.pipeline.failure is not None)
        resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["status"] == "down"
    assert "upstream exploded" in resp.json()["error"]


async def test_a_failed_child_task_cancels_the_others():
    """Regression: asyncio.gather let the tick/Pulse/vandalism tasks keep running
    after ingestion had failed."""
    from app.hub import Hub
    from app.pipeline import Pipeline
    from app.stats import RollingStats
    from app.vandalism import VandalismService

    vandalism = VandalismService(None)
    pipeline = Pipeline(BrokenSource(), RollingStats(), Hub(), tick_seconds=0.01, vandalism=vandalism)
    pipeline.attach_pulse(None, interval_seconds=0.01)
    with pytest.raises(ExceptionGroup):
        await asyncio.wait_for(pipeline.run(), timeout=2)
    children = {"ingest", "tick", "pulse", "vandalism"}
    assert not [t for t in asyncio.all_tasks() if t.get_name() in children]
    assert isinstance(pipeline.failure, ExceptionGroup)
    await vandalism.aclose()


def test_empty_replay_file_fails_clearly(tmp_path):
    """Regression: a looping replay of a file with no events spun forever."""
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n\nnot json\n[1]\n")
    app = create_app(Settings(source="replay", fetch_diffs=False), source=ReplaySource(empty, speed=0), llm=None)
    with TestClient(app) as client:
        assert wait_for(lambda: app.state.pipeline.failure is not None)
        assert "no events" in client.get("/health").json()["error"]


@pytest.mark.parametrize(
    "msg, expected",
    [
        ({"type": "subscribe", "wiki": "dewiki"}, "dewiki"),
        ({"type": "subscribe", "wiki": None}, None),
        ({"type": "subscribe", "wiki": ""}, None),
    ],
)
def test_valid_subscriptions(msg, expected):
    assert parse_subscription(msg) == expected


@pytest.mark.parametrize(
    "msg",
    [None, [], 3, "subscribe", {"type": "other"}, {"type": "subscribe", "wiki": 5},
     {"type": "subscribe", "wiki": "x" * 500}, {"type": "subscribe", "wiki": "../etc"}],
)
def test_invalid_subscriptions_are_rejected(msg):
    assert parse_subscription(msg) is _INVALID


def test_malformed_subscribe_message_does_not_drop_the_client():
    app, client = make_client()
    with client, client.websocket_connect("/ws") as ws:
        ws.receive_json()  # init
        ws.send_json([1, 2, 3])
        ws.send_json({"type": "subscribe", "wiki": "dewiki"})
        for _ in range(20):
            msg = ws.receive_json()
            if msg["type"] == "init":
                break
        assert msg["type"] == "init" and msg["stats"]["wiki"] == "dewiki"


def test_ai_reports_paused_with_no_viewers_and_resumes_with_one():
    app, client = make_client(FakeLLM(*[{"headline": "h", "summary": "s"}] * 5))
    with client:
        assert client.get("/health").json()["ai"]["paused_no_viewers"] is True
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
            assert client.get("/health").json()["ai"]["paused_no_viewers"] is False
