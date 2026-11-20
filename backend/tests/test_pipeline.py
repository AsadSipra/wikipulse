from app.hub import Hub
from app.pipeline import Pipeline
from app.stats import RollingStats

from .test_models import make_raw


class NoSource:
    async def events(self):
        return
        yield


def make_pipeline():
    return Pipeline(NoSource(), RollingStats(window_seconds=300), Hub())


def test_an_event_delivered_twice_is_counted_once():
    pipeline = make_pipeline()
    assert pipeline.handle(make_raw(id=7)) is not None
    assert pipeline.handle(make_raw(id=7)) is None
    assert pipeline.duplicates == 1
    assert pipeline.stats.edits_per_minute() == 1


def test_the_same_id_on_another_wiki_is_a_different_edit():
    pipeline = make_pipeline()
    pipeline.handle(make_raw(id=7))
    other = make_raw(id=7, wiki="dewiki", server_name="de.wikipedia.org")
    assert pipeline.handle(other) is not None
    assert pipeline.duplicates == 0


def test_duplicate_memory_is_bounded(monkeypatch):
    monkeypatch.setattr("app.pipeline.SEEN_SIZE", 3)
    pipeline = make_pipeline()
    for i in range(10):
        pipeline.handle(make_raw(id=i))
    assert len(pipeline._seen) == 3
    assert pipeline.handle(make_raw(id=9)) is None  # recent: still caught
