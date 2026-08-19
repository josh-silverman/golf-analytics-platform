"""Tests for the forward matchup line record (capture, storage, grading).

What must hold: feed parsing survives DataGolf's off-week shape, storage is
first-capture-wins (a grade is only meaningful if the snapshot provably
predates the event), settlement matches the archive's outcome semantics per
tie rule, and the grader's money math is right — that record is the evidence
a product decision will rest on.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

import app.api.v1.analytics as analytics_module
from app.api.v1.deps import get_matchup_archive
from app.providers.factory import get_data_provider
from app.services.matchup_line_record import (
    BookQuote,
    FileMatchupArchive,
    MatchupRow,
    MatchupSnapshot,
    RedisMatchupArchive,
    bet_ev,
    compute_matchup_line_record,
    event_slug,
    fair_probs,
    settle,
    snapshot_from_feed,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI
    from fastapi.testclient import TestClient


# A realistic betting-tools/matchups response (shape verified against the live
# feed 2026-08-19): odds keyed by book, "datagolf" carrying the model line.
_FEED: dict[str, Any] = {
    "event_name": "BMW Championship",
    "last_updated": "2026-08-19 14:00:00 UTC",
    "market": "tournament_matchups",
    "match_list": [
        {
            "odds": {
                "bet365": {"p1": "-111", "p2": "-111", "tie": "+1600"},
                "fanduel": {"p1": "+100", "p2": "-120"},
                "datagolf": {"p1": "+111", "p2": "+110", "tie": "+1877"},
            },
            "p1_dg_id": 14139,
            "p1_player_name": "Thomas, Justin",
            "p2_dg_id": 22085,
            "p2_player_name": "Morikawa, Collin",
            "ties": "separate bet offered",
        },
        {  # one-sided quote is dropped; row survives on the remaining book
            "odds": {
                "bet365": {"p1": "-105", "p2": "NA"},
                "datagolf": {"p1": "-102", "p2": "-104"},
            },
            "p1_dg_id": 111,
            "p1_player_name": "A",
            "p2_dg_id": 222,
            "p2_player_name": "B",
            "ties": "void",
        },
        "not a dict — junk the parser must skip",
    ],
}


def test_snapshot_from_feed_parses_books_and_skips_junk() -> None:
    snap = snapshot_from_feed(_FEED, year=2026)
    assert snap is not None
    assert snap.event_name == "BMW Championship"
    assert snap.slug == "bmw_championship"
    assert len(snap.rows) == 2
    first = snap.rows[0]
    assert {q.book for q in first.quotes} == {"bet365", "fanduel", "datagolf"}
    assert first.quote("datagolf").tie == 1877
    assert first.quote("fanduel").tie is None
    # the incomplete bet365 quote on row 2 was dropped, datagolf kept
    assert {q.book for q in snap.rows[1].quotes} == {"datagolf"}


def test_snapshot_from_feed_handles_off_week() -> None:
    # Off weeks return a message string where the list would be.
    assert snapshot_from_feed({"match_list": "no matchups posted"}, year=2026) is None
    assert snapshot_from_feed({}, year=2026) is None


def test_event_slug_absorbs_incidental_drift() -> None:
    assert event_slug("THE BMW Championship") == event_slug("BMW Championship")
    assert event_slug("Wyndham Champ.") == "wyndham_champ"


# --- settlement math ---------------------------------------------------------


def test_settle_win_loss() -> None:
    assert settle(1.0, "void", +120) == pytest.approx(1.2)
    assert settle(0.0, "void", -150) == pytest.approx(-1.0)
    assert settle(None, "void", +100) is None


def test_settle_tie_depends_on_rule() -> None:
    # void → stake refunded; dead-heat → half stake wins, half loses;
    # separate tie bet → the 2-way sides lose outright.
    assert settle(0.5, "void", +200) == pytest.approx(0.0)
    assert settle(0.5, "dead-heat", +200) == pytest.approx(0.5)
    assert settle(0.5, "separate bet offered", +200) == pytest.approx(-1.0)


def test_fair_probs_use_three_way_devig_only_when_ties_lose() -> None:
    dg = BookQuote(book="datagolf", p1=100, p2=100, tie=800)
    p1_sep, p2_sep = fair_probs(dg, "separate bet offered")
    assert p1_sep == pytest.approx(p2_sep)
    assert p1_sep + p2_sep < 1.0  # tie mass excluded from the win probs
    p1_void, p2_void = fair_probs(dg, "void")
    assert p1_void == pytest.approx(0.5)
    assert p1_void + p2_void == pytest.approx(1.0)


def test_bet_ev_positive_when_price_beats_fair() -> None:
    # fair 50/50, price +110 → EV = 0.5*1.1 - 0.5 = +0.05
    assert bet_ev(0.5, 0.5, 110) == pytest.approx(0.05)
    assert bet_ev(0.5, 0.5, -110) < 0


# --- storage -----------------------------------------------------------------


def _snapshot(event: str = "BMW Championship", year: int = 2026) -> MatchupSnapshot:
    return MatchupSnapshot(
        event_name=event,
        year=year,
        market="tournament_matchups",
        captured_at="2026-08-19T14:05:00+00:00",
        feed_last_updated=None,
        rows=(
            MatchupRow(
                p1_dg_id=14139,
                p1_name="Thomas, Justin",
                p2_dg_id=22085,
                p2_name="Morikawa, Collin",
                ties="void",
                quotes=(
                    BookQuote(book="datagolf", p1=-110, p2=-110),
                    BookQuote(book="bet365", p1=108, p2=-125),
                ),
            ),
        ),
    )


async def test_file_archive_is_immutable_and_round_trips(tmp_path) -> None:
    archive = FileMatchupArchive(tmp_path)
    assert await archive.persist(_snapshot()) is True
    assert await archive.persist(_snapshot()) is False  # first capture wins
    assert await archive.has(2026, "bmw_championship")
    (loaded,) = await archive.list_all()
    assert loaded.rows[0].quote("bet365").p1 == 108
    assert loaded.rows[0].quote("datagolf").tie is None


class _FakeRedis:
    """In-memory stand-in for the async Redis client the archive uses."""

    def __init__(self) -> None:
        self._d: dict[str, str] = {}

    async def set(self, key: str, value: str, nx: bool = False) -> bool | None:
        if nx and key in self._d:
            return None
        self._d[key] = value
        return True

    async def exists(self, key: str) -> int:
        return int(key in self._d)

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [self._d.get(k) for k in keys]

    def scan_iter(self, match: str):
        prefix = match.rstrip("*")

        async def _gen():
            for k in list(self._d):
                if k.startswith(prefix):
                    yield k

        return _gen()


async def test_redis_archive_is_immutable_and_round_trips() -> None:
    archive = RedisMatchupArchive(_FakeRedis())
    assert await archive.persist(_snapshot()) is True
    assert await archive.persist(_snapshot()) is False
    (loaded,) = await archive.list_all()
    assert loaded.event_name == "BMW Championship"


# --- grading -----------------------------------------------------------------


class _StubHistory:
    """Historical-odds source: one settled event, one not-yet-archived."""

    def __init__(self, outcomes_by_book: dict[str, dict[str, Any]]) -> None:
        self._books = outcomes_by_book
        self.calls: list[str] = []

    async def fetch_historical_matchup_event_list(self) -> list[dict[str, Any]]:
        return [
            {"event_id": 100, "calendar_year": 2026, "event_name": "BMW Championship"},
        ]

    async def fetch_historical_matchups(
        self, event_id: int, year: int, book: str
    ) -> dict[str, Any]:
        self.calls.append(book)
        return self._books.get(book, {})


def _hist_row(out1: float, out2: float) -> dict[str, Any]:
    return {
        "bet_type": "72-hole Match",
        "p1_dg_id": 14139,
        "p2_dg_id": 22085,
        "p1_outcome": out1,
        "p2_outcome": out2,
    }


async def test_grader_settles_bets_and_reports_roi(tmp_path) -> None:
    archive = FileMatchupArchive(tmp_path)
    # DG fair (void rule): 50/50. bet365 prices p1 +108 (EV +0.04 → bet at the
    # 0c and 2c thresholds, not 5c) and p2 -125 (EV −0.10 → never bet). p1 wins.
    await archive.persist(_snapshot())
    await archive.persist(_snapshot(event="Unarchived Open"))  # no hist match
    source = _StubHistory({"bet365": {"event_completed": True, "odds": [_hist_row(1.0, 0.0)]}})

    record = await compute_matchup_line_record(archive, source)
    assert record is not None
    assert record.events_captured == 2
    assert record.events_graded == 1
    assert record.events_pending == 1
    assert record.matchups_graded == 1
    # one bet (p1 at +110, edge 5c) at the 0c and 2c thresholds, none at 5c
    for rec in record.best_price:
        expected = 1 if rec.min_edge < 0.05 else 0
        assert rec.bets == expected, rec
        if expected:
            assert rec.pnl == pytest.approx(1.08)
            assert rec.roi == pytest.approx(1.08)
    # only one non-DG book → any-price and best-price agree
    assert [r.bets for r in record.any_price] == [r.bets for r in record.best_price]
    # DG said 0.5, p1 won → brier (0.5-1)^2 = 0.25 on one sample
    assert record.dg_line_n == 1
    assert record.dg_line_brier == pytest.approx(0.25)
    (graded,) = record.events
    assert graded.event_name == "BMW Championship"
    assert graded.bets == 1
    assert graded.pnl == pytest.approx(1.08)


async def test_grader_waits_for_settlement(tmp_path) -> None:
    archive = FileMatchupArchive(tmp_path)
    await archive.persist(_snapshot())
    source = _StubHistory({"bet365": {"event_completed": False, "odds": []}})
    record = await compute_matchup_line_record(archive, source)
    assert record is not None
    assert record.events_graded == 0
    assert record.events_pending == 1


async def test_grader_none_until_first_capture(tmp_path) -> None:
    assert await compute_matchup_line_record(FileMatchupArchive(tmp_path), _StubHistory({})) is None


# --- endpoints ---------------------------------------------------------------


class _StubProvider:
    def __init__(self, feed: dict[str, Any], history: _StubHistory) -> None:
        self._feed = feed
        self._history = history

    async def fetch_live_matchups(self, market: str = "tournament_matchups") -> dict[str, Any]:
        return self._feed

    async def fetch_historical_matchup_event_list(self) -> list[dict[str, Any]]:
        return await self._history.fetch_historical_matchup_event_list()

    async def fetch_historical_matchups(
        self, event_id: int, year: int, book: str
    ) -> dict[str, Any]:
        return await self._history.fetch_historical_matchups(event_id, year, book)


@pytest.fixture
def matchup_ctx(app: FastAPI, client: TestClient, tmp_path, monkeypatch) -> Iterator[TestClient]:
    history = _StubHistory({"bet365": {"event_completed": True, "odds": [_hist_row(1.0, 0.0)]}})
    app.dependency_overrides[get_data_provider] = lambda: _StubProvider(_FEED, history)
    app.dependency_overrides[get_matchup_archive] = lambda: FileMatchupArchive(tmp_path)
    monkeypatch.setattr(
        analytics_module,
        "get_settings",
        lambda: SimpleNamespace(admin_api_token="secret", data_provider="mock"),
    )
    yield client
    for dep in (get_data_provider, get_matchup_archive):
        app.dependency_overrides.pop(dep, None)


_CAPTURE_URL = "/api/v1/analytics/matchups/capture"
_RECORD_URL = "/api/v1/analytics/matchups/line-record"


def test_capture_rejects_missing_and_wrong_token(matchup_ctx: TestClient) -> None:
    assert matchup_ctx.post(_CAPTURE_URL).status_code == 404
    assert matchup_ctx.post(_CAPTURE_URL, headers={"X-Admin-Token": "nope"}).status_code == 404


def test_capture_stores_once_then_reports_already_captured(matchup_ctx: TestClient) -> None:
    r = matchup_ctx.post(_CAPTURE_URL, headers={"X-Admin-Token": "secret"})
    assert r.status_code == 200
    body = r.json()
    assert body["captured"] is True
    assert body["event_name"] == "BMW Championship"
    assert body["matchups"] == 2

    r2 = matchup_ctx.post(_CAPTURE_URL, headers={"X-Admin-Token": "secret"})
    assert r2.status_code == 200
    assert r2.json()["captured"] is False
    assert r2.json()["detail"] == "already captured"


def test_line_record_grades_captured_events(matchup_ctx: TestClient) -> None:
    assert matchup_ctx.get(_RECORD_URL).json()["available"] is False  # nothing captured yet
    matchup_ctx.post(_CAPTURE_URL, headers={"X-Admin-Token": "secret"})
    body = matchup_ctx.get(_RECORD_URL).json()
    assert body["available"] is True
    assert body["events_captured"] == 1
    assert body["events_graded"] == 1
    assert body["dg_line_n"] >= 1
    assert body["best_price"]  # threshold records present


def test_capture_conflict_when_provider_has_no_feed(matchup_ctx: TestClient, app: FastAPI) -> None:
    app.dependency_overrides[get_data_provider] = lambda: SimpleNamespace()
    r = matchup_ctx.post(_CAPTURE_URL, headers={"X-Admin-Token": "secret"})
    assert r.status_code == 409
