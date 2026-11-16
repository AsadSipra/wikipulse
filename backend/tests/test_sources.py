from app.sources import ReplaySource, parse_sse


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
