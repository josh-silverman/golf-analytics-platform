"""Closing-line capture: feed parsing, immutability, and the start guard (A5).

The guard tests are the ones that matter. Capture is first-write-wins and
there is no backfill for this archive — a line read after the event is not a
prediction — so a snapshot taken after tee-off is both permanent and
worthless, and only the guard stops it.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.domain.enums import LineFeedStatus, TournamentStatus
from app.domain.models import Page, Tournament
from app.services.closing_line_archive import (
    ClosingLineOutcome,
    FileClosingLineArchive,
    _from_dict,
    _market_from_feed,
    _to_json,
    capture_closing_lines,
    snapshot_from_feeds,
)

_START = date(2026, 8, 27)


def _feed(market: str, *, event: str = "TOUR Championship") -> dict[str, Any]:
    """A realistic outrights response (shape verified against the live feed on
    2026-08-20): American-odds strings per book, ``datagolf`` as a nested dict."""
    return {
        "event_name": event,
        "market": market,
        "last_updated": "2026-08-26 21:03:05 UTC",
        "books_offering": ["bet365", "draftkings", "fanduel"],
        "odds": [
            {
                "dg_id": 18417,
                "player_name": "Player, One",
                "bet365": "+300",
                "draftkings": "+305",
                "fanduel": "+310",
                "datagolf": {"baseline": "+473", "baseline_history_fit": "+454"},
            },
            {
                "dg_id": 10091,
                "player_name": "Player, Two",
                "bet365": "+1200",
                "draftkings": "NA",
                "fanduel": "+1250",
                "datagolf": {"baseline": "+1400", "baseline_history_fit": "+1380"},
            },
        ],
    }


def _feeds(*, event: str = "TOUR Championship", no_cut: bool = True) -> dict[str, Any]:
    out = {m: _feed(m, event=event) for m in ("win", "top_5", "top_10", "top_20")}
    if no_cut:
        # A no-cut event: DataGolf returns a message string, not a list. Verified
        # live against BMW Championship, which is a 50-player no-cut playoff.
        out["make_cut"] = {
            "event_name": event,
            "market": "make_cut",
            "last_updated": "2026-08-26 21:03:05 UTC",
            "odds": "No make_cut bets being offered right now.",
        }
    else:
        out["make_cut"] = _feed("make_cut", event=event)
    return out


class _Catalog:
    def __init__(self, tournaments: list[Tournament]) -> None:
        self._tournaments = tournaments

    async def list_tournaments(
        self, *, status: TournamentStatus | None = None, limit: int = 50, **_: object
    ) -> Page[Tournament]:
        items = [t for t in self._tournaments if status is None or t.status == status]
        return Page(items=items[:limit], next_cursor=None, has_more=False)


def _tournament(status: TournamentStatus, start: date = _START) -> Tournament:
    return Tournament(
        id=901,
        course_id=1,
        name="TOUR Championship",
        season=2026,
        start_date=start,
        end_date=start,
        purse=None,
        field_strength=None,
        status=status,
    )


class _Source:
    def __init__(self, feeds: dict[str, Any]) -> None:
        self.feeds = feeds
        self.calls: list[str] = []

    async def fetch_live_outrights(self, market: str) -> dict[str, Any]:
        self.calls.append(market)
        return self.feeds.get(market, {})


@pytest.fixture
def archive(tmp_path) -> FileClosingLineArchive:
    return FileClosingLineArchive(tmp_path / "closing")


# ---------------------------------------------------------------------------
# Feed parsing
# ---------------------------------------------------------------------------


def test_a_market_the_books_do_not_offer_is_recorded_not_dropped() -> None:
    """A no-cut event returns a message string for make_cut. The other four
    markets must still be captured, and the reason must be preserved."""
    snap = snapshot_from_feeds(_feeds(), year=2026)
    assert snap is not None
    make_cut = snap.market("make_cut_prob")
    assert make_cut is not None
    assert make_cut.offered is False
    assert make_cut.detail == "No make_cut bets being offered right now."
    assert make_cut.lines == ()
    assert sum(1 for m in snap.markets if m.offered) == 4


def test_datagolf_baseline_is_kept_apart_from_the_book_consensus() -> None:
    """The ``datagolf`` key is DataGolf's own model line, not a market price.
    Folding it into the consensus would grade the market baseline against a
    number that is partly DataGolf's own opinion."""
    snap = snapshot_from_feeds(_feeds(), year=2026)
    assert snap is not None
    win = snap.market("win_prob")
    assert win is not None
    line = next(ln for ln in win.lines if ln.dg_id == 18417)
    assert {p.book for p in line.prices} == {"bet365", "draftkings", "fanduel"}
    assert line.dg_baseline == 473
    assert line.dg_baseline_history_fit == 454
    # Median of +300/+305/+310 in probability space lands back on +305.
    assert line.consensus_american == 305


def test_unquotable_prices_are_skipped_and_devigging_runs_on_the_rest() -> None:
    snap = snapshot_from_feeds(_feeds(), year=2026)
    assert snap is not None
    win = snap.market("win_prob")
    assert win is not None
    longshot = next(ln for ln in win.lines if ln.dg_id == 10091)
    assert {p.book for p in longshot.prices} == {"bet365", "fanduel"}  # "NA" dropped
    assert longshot.devigged_prob is not None
    # De-vigged win probabilities are normalized to sum to one across the field.
    assert sum(ln.devigged_prob or 0.0 for ln in win.lines) == pytest.approx(1.0)


def test_an_off_week_yields_no_snapshot() -> None:
    assert snapshot_from_feeds({}, year=2026) is None


def test_snapshot_round_trips_through_storage_json() -> None:
    snap = snapshot_from_feeds(_feeds(), year=2026, tournament_id=901)
    assert snap is not None
    import json

    assert _from_dict(json.loads(_to_json(snap))) == snap


# ---------------------------------------------------------------------------
# The start guard
# ---------------------------------------------------------------------------


async def test_captures_an_upcoming_event(archive) -> None:
    catalog = _Catalog([_tournament(TournamentStatus.UPCOMING)])
    source = _Source(_feeds())
    result = await capture_closing_lines(
        catalog=catalog, archive=archive, source=source, today=date(2026, 8, 26)
    )
    assert result.outcome is ClosingLineOutcome.CAPTURED
    assert result.outcome.is_healthy
    assert result.tournament_id == 901
    assert result.markets_offered == 4
    assert source.calls == ["win", "top_5", "top_10", "top_20", "make_cut"]
    assert len(await archive.list_all()) == 1


async def test_refuses_an_event_the_provider_calls_in_progress(archive) -> None:
    """The provider's own status is enough, even on a date before the start."""
    catalog = _Catalog([_tournament(TournamentStatus.IN_PROGRESS)])
    result = await capture_closing_lines(
        catalog=catalog,
        archive=archive,
        source=_Source(_feeds()),
        today=date(2026, 8, 26),
    )
    assert result.outcome is ClosingLineOutcome.EVENT_ALREADY_STARTED
    assert not result.outcome.is_healthy
    assert await archive.list_all() == []


async def test_refuses_on_the_start_date_even_if_status_still_says_upcoming(archive) -> None:
    """The calendar backstop. Tee times span time zones, so no hour on the
    start date is universally pre-tee-off."""
    catalog = _Catalog([_tournament(TournamentStatus.UPCOMING)])
    result = await capture_closing_lines(
        catalog=catalog, archive=archive, source=_Source(_feeds()), today=_START
    )
    assert result.outcome is ClosingLineOutcome.EVENT_ALREADY_STARTED
    assert await archive.list_all() == []


async def test_refuses_an_event_the_catalog_does_not_know(archive) -> None:
    """Without a catalog match the guard cannot be evaluated, and an
    unverifiable line is exactly the one that might be in-play."""
    catalog = _Catalog([])
    result = await capture_closing_lines(
        catalog=catalog,
        archive=archive,
        source=_Source(_feeds(event="Some Unlisted Invitational")),
        today=date(2026, 8, 26),
    )
    assert result.outcome is ClosingLineOutcome.EVENT_NOT_IN_CATALOG
    assert not result.outcome.is_healthy
    assert await archive.list_all() == []


async def test_second_run_is_a_no_op_and_never_overwrites(archive) -> None:
    catalog = _Catalog([_tournament(TournamentStatus.UPCOMING)])
    first = await capture_closing_lines(
        catalog=catalog, archive=archive, source=_Source(_feeds()), today=date(2026, 8, 26)
    )
    assert first.outcome is ClosingLineOutcome.CAPTURED
    stored = (await archive.list_all())[0]

    # A later run whose feed has moved must not touch the pinned snapshot.
    moved = _feeds()
    moved["win"]["odds"][0]["bet365"] = "+900"
    second = await capture_closing_lines(
        catalog=catalog, archive=archive, source=_Source(moved), today=date(2026, 8, 26)
    )
    assert second.outcome is ClosingLineOutcome.ALREADY_CAPTURED
    assert second.outcome.is_healthy
    assert await archive.list_all() == [stored]


async def test_already_captured_wins_over_the_start_guard(archive) -> None:
    """The Wednesday retry after a successful first run reports an idempotent
    no-op, not a refusal — same ordering as board capture."""
    catalog = _Catalog([_tournament(TournamentStatus.UPCOMING)])
    await capture_closing_lines(
        catalog=catalog, archive=archive, source=_Source(_feeds()), today=date(2026, 8, 26)
    )
    started = _Catalog([_tournament(TournamentStatus.IN_PROGRESS)])
    result = await capture_closing_lines(
        catalog=started, archive=archive, source=_Source(_feeds()), today=_START
    )
    assert result.outcome is ClosingLineOutcome.ALREADY_CAPTURED


async def test_an_off_week_is_healthy_but_a_priceless_event_is_not(archive) -> None:
    catalog = _Catalog([_tournament(TournamentStatus.UPCOMING)])
    off_week = await capture_closing_lines(
        catalog=catalog, archive=archive, source=_Source({}), today=date(2026, 8, 26)
    )
    assert off_week.outcome is ClosingLineOutcome.NO_EVENT
    assert off_week.outcome.is_healthy

    empty = {m: {"event_name": "TOUR Championship", "odds": "none"} for m in ("win", "top_5")}
    broken = await capture_closing_lines(
        catalog=catalog, archive=archive, source=_Source(empty), today=date(2026, 8, 26)
    )
    assert broken.outcome is ClosingLineOutcome.NO_MARKETS
    assert not broken.outcome.is_healthy


# ---------------------------------------------------------------------------
# Feed shape drift (§2.11a). Both fixtures are built from shapes observed on
# the live feed on 2026-08-24, not invented: the decimal values are what
# DataGolf actually returns for `odds_format=decimal` (floats, not strings),
# and the flattened `datagolf` value is the price string it would collapse to.
# ---------------------------------------------------------------------------


def _decimal_feed() -> dict[str, Any]:
    """A book quoting decimal odds where American was requested.

    Real values from the live TOUR Championship board: bet365 4.2,
    draftkings 4.35, DataGolf's baseline 5.697464628240422. Under the old
    parser these rounded to the American prices +4, +4 and +6 — an implied
    probability of roughly 0.96 for every player, stored as though real.
    """
    return {
        "event_name": "TOUR Championship",
        "market": "win",
        "last_updated": "2026-08-24 18:03:05 UTC",
        "books_offering": ["bet365", "draftkings"],
        "odds": [
            {
                "dg_id": 18417,
                "player_name": "Player, One",
                "bet365": 4.2,
                "draftkings": 4.35,
                "datagolf": {
                    "baseline": 5.697464628240422,
                    "baseline_history_fit": 5.48646671543525,
                },
            }
        ],
    }


def _flattened_baseline_feed() -> dict[str, Any]:
    """DataGolf's nested baseline object collapsed to a bare price string."""
    feed = _feed("win")
    for row in feed["odds"]:
        row["datagolf"] = "+473"
    return feed


def test_decimal_odds_are_refused_rather_than_rounded_into_a_price() -> None:
    """The failure this check exists for. A decimal 4.2 is not an American
    price that needs rounding; it is a different unit."""
    market = _market_from_feed(_decimal_feed(), market="win_prob", dg_market="win")
    assert market.status == LineFeedStatus.SUSPECT_PRICES.value
    assert market.prices_rejected == 4  # two books, plus both DataGolf values
    # Nothing survived, so nothing was stored claiming to be a price.
    assert market.lines == ()
    assert market.offered is False


def test_a_refused_price_never_reaches_the_archive_as_a_probability() -> None:
    """Belt and braces on the consequence rather than the mechanism: whatever
    is stored must not imply a ~96% chance for a 4-to-1 shot."""
    market = _market_from_feed(_decimal_feed(), market="win_prob", dg_market="win")
    for line in market.lines:
        for price in line.prices:
            assert abs(price.american) >= 100
        assert (line.devigged_prob or 0.0) < 0.5


def test_a_flattened_datagolf_object_is_distinguishable_from_absent(tmp_path) -> None:
    """`dg_baseline: None` with `offered: True` used to be the only trace.
    A shape change and thin coverage must not read the same."""
    market = _market_from_feed(_flattened_baseline_feed(), market="win_prob", dg_market="win")
    assert market.offered is True  # the book prices are still good
    assert market.status == LineFeedStatus.SUSPECT_PRICES.value
    assert market.baseline_rows == 0
    assert all(line.dg_baseline is None for line in market.lines)


def test_missing_baseline_is_reported_when_the_key_is_simply_absent() -> None:
    """No `datagolf` key at all: nothing was mangled, but the baseline is gone
    across the whole market, which is shape rather than coverage."""
    feed = _feed("win")
    for row in feed["odds"]:
        row.pop("datagolf")
    market = _market_from_feed(feed, market="win_prob", dg_market="win")
    assert market.offered is True
    assert market.status == LineFeedStatus.MISSING_BASELINE.value
    assert market.prices_rejected == 0  # an absent key is not a mangled one
    assert market.baseline_rows == 0


def test_partial_baseline_coverage_is_not_treated_as_drift() -> None:
    """DataGolf does not model every player. Only a total absence is a signal,
    or the check fires every week on ordinary events."""
    feed = _feed("win")
    feed["odds"][1].pop("datagolf")
    market = _market_from_feed(feed, market="win_prob", dg_market="win")
    assert market.status == LineFeedStatus.OK.value
    assert market.baseline_rows == 1


def test_unpriced_players_are_not_counted_as_drift() -> None:
    """ "NA" means this book is not pricing this player. Absent, not wrong."""
    market = _market_from_feed(_feed("win"), market="win_prob", dg_market="win")
    assert market.prices_rejected == 0  # the fixture's "NA" draftkings quote
    assert market.status == LineFeedStatus.OK.value


def test_snapshot_status_rolls_up_the_worst_offered_market() -> None:
    feeds = _feeds()
    feeds["top_10"] = _decimal_feed()
    snap = snapshot_from_feeds(feeds, year=2026)
    assert snap is not None
    assert snap.status == LineFeedStatus.SUSPECT_PRICES.value
    assert snap.is_clean is False


def test_a_no_cut_event_still_reads_as_clean() -> None:
    """`make_cut` not being offered is the event's shape, not a fault."""
    snap = snapshot_from_feeds(_feeds(), year=2026)
    assert snap is not None
    assert snap.status == LineFeedStatus.OK.value
    assert snap.is_clean is True


def test_status_round_trips_through_storage() -> None:
    feeds = _feeds()
    feeds["win"] = _decimal_feed()
    snap = snapshot_from_feeds(feeds, year=2026)
    assert snap is not None
    import json

    assert _from_dict(json.loads(_to_json(snap))) == snap


# --- the refuse-then-retry half, symmetric with §2.12a ----------------------


async def test_strict_run_refuses_a_suspect_feed_and_writes_nothing(archive) -> None:
    """21:00. Nothing written, so first-write-wins has not closed the door on
    the 23:30 retry getting a clean capture."""
    feeds = _feeds()
    feeds["win"] = _decimal_feed()
    result = await capture_closing_lines(
        catalog=_Catalog([_tournament(TournamentStatus.UPCOMING)]),
        archive=archive,
        source=_Source(feeds),
        today=date(2026, 8, 26),
        allow_degraded=False,
    )
    assert result.outcome is ClosingLineOutcome.FEED_SUSPECT
    assert result.outcome.is_retryable
    assert not result.outcome.is_healthy
    assert result.status == LineFeedStatus.SUSPECT_PRICES.value
    assert result.prices_rejected == 4
    assert await archive.list_all() == []


async def test_retry_captures_the_suspect_feed_labelled(archive) -> None:
    """23:30. A stamped degraded line beats no line for the week, and the
    stamp is what stops A4b reading it as a market price."""
    feeds = _feeds()
    feeds["win"] = _decimal_feed()
    result = await capture_closing_lines(
        catalog=_Catalog([_tournament(TournamentStatus.UPCOMING)]),
        archive=archive,
        source=_Source(feeds),
        today=date(2026, 8, 26),
        allow_degraded=True,
    )
    assert result.outcome is ClosingLineOutcome.CAPTURED
    (stored,) = await archive.list_all()
    assert stored.status == LineFeedStatus.SUSPECT_PRICES.value
    assert stored.is_clean is False


async def test_a_clean_feed_is_captured_even_on_the_strict_run(archive) -> None:
    result = await capture_closing_lines(
        catalog=_Catalog([_tournament(TournamentStatus.UPCOMING)]),
        archive=archive,
        source=_Source(_feeds()),
        today=date(2026, 8, 26),
        allow_degraded=False,
    )
    assert result.outcome is ClosingLineOutcome.CAPTURED
    assert result.status == LineFeedStatus.OK.value
