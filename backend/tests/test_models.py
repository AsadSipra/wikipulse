import json
from pathlib import Path

import pytest

from app.models import is_anonymous, is_wikipedia, parse_event

SAMPLE = Path(__file__).parent.parent / "data" / "sample_events.jsonl"


def make_raw(**overrides):
    raw = {
        "meta": {"domain": "en.wikipedia.org"},
        "id": 1,
        "type": "edit",
        "namespace": 0,
        "title": "Lahore",
        "comment": "copyedit",
        "timestamp": 1763300000,
        "user": "Alice",
        "bot": False,
        "minor": False,
        "server_name": "en.wikipedia.org",
        "wiki": "enwiki",
        "length": {"old": 1000, "new": 1200},
        "revision": {"old": 10, "new": 11},
    }
    raw.update(overrides)
    return raw


def test_parses_a_normal_edit():
    edit = parse_event(make_raw())
    assert edit is not None
    assert edit.byte_delta == 200
    assert edit.page_url == "https://en.wikipedia.org/wiki/Lahore"
    assert edit.diff_url == "https://en.wikipedia.org/w/index.php?diff=11&oldid=10"


def test_page_creation_has_no_old_revision():
    edit = parse_event(make_raw(type="new", length={"new": 500}, revision={"new": 11}))
    assert edit is not None
    assert edit.byte_delta == 500
    assert edit.diff_url == "https://en.wikipedia.org/w/index.php?diff=11"


@pytest.mark.parametrize("event_type", ["log", "categorize", "external", None])
def test_untracked_types_are_dropped(event_type):
    assert parse_event(make_raw(type=event_type)) is None


def test_canary_events_are_dropped():
    assert parse_event(make_raw(meta={"domain": "canary"})) is None


@pytest.mark.parametrize("missing", ["id", "wiki", "title", "timestamp", "server_name"])
def test_missing_required_fields_return_none_instead_of_raising(missing):
    raw = make_raw()
    del raw[missing]
    assert parse_event(raw) is None


@pytest.mark.parametrize(
    "user, expected",
    [("192.0.2.15", True), ("2001:db8::7", True), ("~2026-41234-56", True), ("Alice", False), ("1.2.3", False)],
)
def test_anonymous_detection(user, expected):
    assert is_anonymous(user) is expected


def test_whole_sample_file_parses_without_errors():
    """Every line either parses or is cleanly skipped; nothing raises."""
    parsed = skipped = 0
    for line in SAMPLE.read_text().splitlines():
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if parse_event(raw) is None:
            skipped += 1
        else:
            parsed += 1
    assert parsed > 0
    assert skipped > 0  # the sample deliberately contains noise


@pytest.mark.parametrize(
    "server, expected",
    [
        ("en.wikipedia.org", True),
        ("ur.wikipedia.org", True),
        ("www.wikidata.org", False),
        ("commons.wikimedia.org", False),
        ("en.wiktionary.org", False),
        ("evil.wikipedia.org.example.com", False),
    ],
)
def test_is_wikipedia(server, expected):
    assert is_wikipedia(server) is expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [1, 2],
        "edit",
        make_raw(meta=None) | {"user": 3},
        make_raw(length=[1]),
        make_raw(revision="11"),
        make_raw(user=3),
        make_raw(comment=["x"]),
        make_raw(id="1"),
        make_raw(timestamp="1763300000"),
    ],
)
def test_malformed_events_are_skipped_not_raised(raw):
    """Regression: these used to raise AttributeError/TypeError and stop ingestion."""
    assert parse_event(raw) is None


def test_null_meta_alone_is_fine():
    assert parse_event(make_raw(meta=None)) is not None


@pytest.mark.parametrize("value", ["false", "true", 1, None])
def test_booleans_must_be_real_booleans(value):
    """Regression: bool("false") is True, which would drop a human edit as a bot."""
    assert parse_event(make_raw(bot=value)) is None


def test_missing_lengths_mean_unknown_delta_not_zero():
    assert parse_event(make_raw(length={"old": 8000})).byte_delta is None
    assert parse_event(make_raw(length=None)).byte_delta is None


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Lahore", "https://en.wikipedia.org/wiki/Lahore"),
        ("A B", "https://en.wikipedia.org/wiki/A_B"),
        ("A?B#C%", "https://en.wikipedia.org/wiki/A%3FB%23C%25"),
        ("AC/DC (band)", "https://en.wikipedia.org/wiki/AC/DC_(band)"),
        ("لاہور", "https://en.wikipedia.org/wiki/%D9%84%D8%A7%DB%81%D9%88%D8%B1"),
    ],
)
def test_page_urls_escape_titles(title, expected):
    assert parse_event(make_raw(title=title)).page_url == expected
