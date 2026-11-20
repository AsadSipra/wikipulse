import asyncio

import httpx

from app.sources import LiveSource, ReplaySource, parse_sse, until_idle


async def lines(*items):
    for item in items:
        yield item


async def collect(agen):
    return [x async for x in agen]


async def test_sse_parser_handles_ids_comments_and_multiline_data():
    stream = lines(
        ":ok",
        "event: message",
        'id: [{"offset":1}]',
        'data: {"a":',
        "data: 1}",
        "",
        "data: {}",
        "",
    )
    events = await collect(parse_sse(stream))
    assert events == [('[{"offset":1}]', '{"a":\n1}'), (None, "{}")]


async def test_sse_parser_flushes_trailing_event_without_blank_line():
    assert await collect(parse_sse(lines("data: x"))) == [(None, "x")]


async def test_replay_skips_bad_lines_and_stops_when_not_looping(tmp_path):
    f = tmp_path / "events.jsonl"
    f.write_text('{"timestamp": 1}\n\nnot json\n{"timestamp": 1}\n')
    events = await collect(ReplaySource(f, speed=0, loop=False).events())
    assert len(events) == 2


class HangingStream(httpx.AsyncByteStream):
    """Sends one event, then goes silent without closing: what production saw."""

    def __init__(self, event_id: str):
        self.event_id = event_id

    async def __aiter__(self):
        yield f'id: {self.event_id}\ndata: {{"n": "{self.event_id}"}}\n\n'.encode()
        await asyncio.sleep(3600)


async def test_live_source_reconnects_and_resumes_when_the_stream_goes_silent(monkeypatch):
    monkeypatch.setattr("app.sources.random.random", lambda: 0.0)  # shortest backoff
    monkeypatch.setattr("app.sources.asyncio.sleep", _fast_sleep)
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.headers.get("Last-Event-ID"))
        return httpx.Response(200, stream=HangingStream(str(len(requests))))

    source = LiveSource(idle_timeout=0.05, transport=httpx.MockTransport(handler))
    events = source.events()
    first = await asyncio.wait_for(anext(events), 2)
    second = await asyncio.wait_for(anext(events), 2)  # only arrives after a reconnect
    await events.aclose()
    assert (first, second) == ({"n": "1"}, {"n": "2"})
    assert requests == [None, "1"]  # the reconnect resumed from the last event


async def test_until_idle_passes_lines_through_and_ends_with_the_stream():
    assert await collect(until_idle(lines("a", "b"), 1)) == ["a", "b"]


_real_sleep = asyncio.sleep


async def _fast_sleep(seconds):
    # Instant backoff; the hanging stream's long sleep stays for the watchdog to cut.
    await _real_sleep(seconds if seconds > 60 else 0)
