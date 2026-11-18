"""The rolling window is the core logic, so it gets the most careful tests.

A fake clock makes time explicit: no sleeps, no flakiness.
"""

from app.models import Edit
from app.stats import RollingStats


class FakeClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def edit(title: str = "Lahore", wiki: str = "enwiki", bot: bool = False, namespace: int = 0) -> Edit:
    return Edit(
        id=1, wiki=wiki, server_name="x", title=title, user="u", bot=bot, anonymous=False,
        type="edit", namespace=namespace, comment="", minor=False, timestamp=0,
        length_old=1, length_new=2, revision_old=1, revision_new=2,
    )


def make(window: int = 300, include_bots: bool = False):
    clock = FakeClock()
    return RollingStats(window_seconds=window, clock=clock, include_bots=include_bots), clock


def test_edits_per_minute_counts_only_the_last_60_seconds():
    stats, clock = make()
    stats.record(edit())
    clock.advance(30)
    stats.record(edit())
    assert stats.edits_per_minute() == 2
    clock.advance(31)  # first edit is now 61s old
    assert stats.edits_per_minute() == 1


def test_window_boundary_is_exclusive_of_the_oldest_second():
    stats, clock = make(window=300)
    stats.record(edit("A"))
    clock.advance(299)
    assert stats.top_pages() == [(("enwiki", "A"), 1)]
    clock.advance(1)  # exactly 300s later: out of a 5-minute window
    assert stats.top_pages() == []


def test_top_pages_ranks_by_count_and_respects_n():
    stats, _ = make()
    for title, n in [("A", 3), ("B", 5), ("C", 1)]:
        for _ in range(n):
            stats.record(edit(title))
    assert stats.top_pages(2) == [(("enwiki", "B"), 5), (("enwiki", "A"), 3)]


def test_ties_are_ordered_stably_by_title():
    stats, _ = make()
    for title in ["Zebra", "Apple", "Mango"]:
        stats.record(edit(title))
    assert [k[1] for k, _ in stats.top_pages()] == ["Apple", "Mango", "Zebra"]


def test_same_title_on_different_wikis_are_different_pages():
    stats, _ = make()
    stats.record(edit("Lahore", "enwiki"))
    stats.record(edit("Lahore", "urwiki"))
    assert len(stats.top_pages()) == 2


def test_expired_counts_are_subtracted_not_rescanned():
    stats, clock = make(window=10)
    stats.record(edit("A"))
    clock.advance(5)
    stats.record(edit("A"))
    clock.advance(6)  # first edit expires, second remains
    assert stats.top_pages() == [(("enwiki", "A"), 1)]
    clock.advance(10)
    assert stats.top_pages() == []
    assert stats.wikis() == []
    # Totals shouldn't keep dead keys around (memory stays bounded).
    assert len(stats._page_totals) == 0


def test_filter_by_wiki():
    stats, _ = make()
    stats.record(edit("A", "enwiki"))
    stats.record(edit("B", "dewiki"))
    stats.record(edit("B", "dewiki"))
    assert stats.edits_per_minute("dewiki") == 2
    assert stats.top_pages(wiki="dewiki") == [(("dewiki", "B"), 2)]
    assert stats.wikis() == [("dewiki", 2), ("enwiki", 1)]


def test_bots_are_excluded_by_default_but_can_be_included():
    stats, _ = make()
    stats.record(edit(bot=True))
    assert stats.edits_per_minute() == 0
    assert stats.total_seen == 1

    with_bots, _ = make(include_bots=True)
    with_bots.record(edit(bot=True))
    assert with_bots.edits_per_minute() == 1


def test_series_reports_rate_per_minute_oldest_first():
    stats, clock = make()
    for _ in range(5):
        stats.record(edit())  # 5 edits in the current 10s step
    series = stats.series(step=10, points=3)
    assert [p["rate"] for p in series] == [0, 0, 30]  # 5 per 10s == 30/min
    assert series[0]["t"] < series[-1]["t"]


def test_quiet_periods_do_not_break_expiry():
    stats, clock = make(window=60)
    stats.record(edit())
    clock.advance(3600)  # an hour with no edits
    assert stats.edits_per_minute() == 0
    stats.record(edit())
    assert stats.edits_per_minute() == 1


def test_only_articles_can_trend_but_every_edit_counts_towards_the_rate():
    stats, _ = make()
    stats.record(edit("User:Someone/sandbox", namespace=2))
    stats.record(edit("Wikipedia:Administrators' noticeboard", namespace=4))
    stats.record(edit("Lahore"))
    assert stats.edits_per_minute() == 3
    assert stats.top_pages() == [(("enwiki", "Lahore"), 1)]
