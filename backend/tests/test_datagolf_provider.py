"""Contract tests for the DataGolf provider.

The provider is written to DataGolf's documented response shapes but can't be
exercised against the live API without a paid key. These tests close that gap:
``httpx.MockTransport`` feeds the provider representative DataGolf payloads so
every parse path — players, schedule, live field, completed-event field,
historical rounds, projections — is verified offline.

The two parses that previously would have silently broken on real data are
covered explicitly:
  * rounds come back **dated** (``tee_time`` set) so the feature pipeline keeps
    them instead of dropping every one;
  * completed-event fields carry the **real ``dg_id``** and a finishing
    position parsed from ``fin_text`` so training has labels and prediction can
    match players.

The final test wires provider → features → labels end-to-end to prove a real
DataGolf field would actually train.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pytest

from app.domain.enums import EntryStatus, TournamentStatus
from app.ml.training import labels_from_entry
from app.providers.datagolf.datagolf_provider import (
    DataGolfProvider,
    _parse_dg_date_range,
    _parse_fin_text,
)
from app.services.features import FeatureExtractor

# ---------------------------------------------------------------------------
# Fixtures — shaped like real DataGolf responses
# ---------------------------------------------------------------------------

_THIS_YEAR = date.today().year
_LIVE_EVENT_ID = 999
_DONE_EVENT_ID = 100
_MISSING_EVENT_ID = 32  # scheduled but absent from the historical archive → 400

_PLAYER_LIST = [
    {"dg_id": 18417, "player_name": "McIlroy, Rory", "country": "NIR"},
    {"dg_id": 10091, "player_name": "Scheffler, Scottie", "country": "USA"},
    {"dg_id": 12345, "player_name": "No Country", "country": None},
    {"player_name": "Missing Id"},  # no dg_id → must be skipped
]

# Real DataGolf get-schedule shape: ISO ``start_date`` (no end), authoritative
# ``status``, and a *string* ``event_id``.
_SCHEDULE = {
    "schedule": [
        {
            "event_id": str(_DONE_EVENT_ID),  # arrives as a string
            "event_name": "Completed Open",
            "course": "Augusta National GC",
            "start_date": f"{_THIS_YEAR}-02-01",
            "status": "completed",
            "purse": 20000000,
        },
        {
            "event_id": str(_LIVE_EVENT_ID),
            "event_name": "Live Championship",
            "course": "TPC Sawgrass",
            "start_date": f"{_THIS_YEAR}-12-15",  # later in the year → upcoming
            "status": "upcoming",
            "purse": 25000000,
        },
    ]
}

_FIELD_UPDATES = {
    "event_id": _LIVE_EVENT_ID,
    "field": [
        {"dg_id": 18417, "player_name": "McIlroy, Rory"},
        {"dg_id": 10091, "player_name": "Scheffler, Scottie"},
        {"player_name": "no id"},  # skipped
    ],
}


def _round_obj(score: int, sg_total: float) -> dict[str, Any]:
    return {
        "score": score,
        "sg_ott": 0.5,
        "sg_app": 0.4,
        "sg_arg": 0.1,
        "sg_putt": 0.3,
        "sg_t2g": 1.0,
        "sg_total": sg_total,
        "driving_dist": 305.2,
    }


_HISTORICAL_ROUNDS = {
    "event_id": _DONE_EVENT_ID,
    "year": _THIS_YEAR,
    "scores": [
        {
            "dg_id": 18417,
            "player_name": "McIlroy, Rory",
            "fin_text": "1",  # winner
            "round_1": _round_obj(68, 2.5),
            "round_2": _round_obj(69, 1.8),
            "round_3": _round_obj(70, 0.9),
            "round_4": _round_obj(67, 3.1),
        },
        {
            "dg_id": 10091,
            "player_name": "Scheffler, Scottie",
            "fin_text": "T5",  # tied 5th
            "round_1": _round_obj(70, 1.1),
            "round_2": _round_obj(71, 0.4),
            "round_3": _round_obj(69, 1.5),
            "round_4": _round_obj(70, 0.8),
        },
        {
            "dg_id": 22222,
            "player_name": "Missed, Cut",
            "fin_text": "CUT",  # missed cut → no position
            "round_1": _round_obj(75, -1.5),
            "round_2": _round_obj(74, -1.2),
        },
    ],
}

_PROJECTIONS = {
    "projections": [
        {"dg_id": 18417, "player_name": "McIlroy, Rory",
         "win": 12.5, "top_5": 35.0, "top_10": 55.0, "top_20": 75.0, "make_cut": 88.0},
    ]
}

_OUTRIGHTS = {
    "event_name": "Live Championship",
    "last_updated": "2026-06-09 22:22:06 UTC",
    "market": "win",
    "books_offering": ["bet365", "fanduel", "pinnacle"],
    "odds": [
        {
            "dg_id": 18417,
            "player_name": "McIlroy, Rory",
            "datagolf": {"baseline": "+450", "baseline_history_fit": "+460"},
            "bet365": "+500",
            "fanduel": "+550",
            "pinnacle": "+525",  # median of {500,550,525} in prob space → +525-ish
        },
        {
            "dg_id": 10091,
            "player_name": "Scheffler, Scottie",
            "bet365": "+300",
            "fanduel": "+300",
            "pinnacle": "+300",
        },
        {
            "dg_id": 22222,
            "player_name": "No, Prices",
            "bet365": "NA",  # unpriced → no consensus → skipped
        },
    ],
}


# event-list: only _DONE_EVENT_ID is a PGA event with SG raw data this year.
_EVENT_LIST = [
    {"calendar_year": _THIS_YEAR, "event_id": _DONE_EVENT_ID, "tour": "pga",
     "sg_categories": "yes", "event_name": "Completed Open"},
    {"calendar_year": _THIS_YEAR, "event_id": 777, "tour": "pga",
     "sg_categories": "no", "event_name": "No SG Event"},  # excluded: no SG
    {"calendar_year": _THIS_YEAR, "event_id": 888, "tour": "kft",
     "sg_categories": "yes", "event_name": "Wrong Tour"},  # excluded: not PGA
]


def _handler(request: httpx.Request) -> httpx.Response:
    """Route like the real API: schedule is keyed by season, rounds by event."""
    path = request.url.path
    params = request.url.params
    if path == "/get-player-list":
        return httpx.Response(200, json=_PLAYER_LIST)
    if path == "/historical-raw-data/event-list":
        return httpx.Response(200, json=_EVENT_LIST)
    if path == "/get-schedule":
        season = int(params.get("season", 0))
        if season > _THIS_YEAR:
            # A future season DataGolf doesn't have yet returns 400, not 200.
            return httpx.Response(400, text="season not available")
        body = _SCHEDULE if season == _THIS_YEAR else {"schedule": []}
        return httpx.Response(200, json=body)
    if path == "/field-updates":
        return httpx.Response(200, json=_FIELD_UPDATES)
    if path == "/historical-raw-data/rounds":
        event_id = int(params.get("event_id", 0))
        if event_id == _MISSING_EVENT_ID:
            # DataGolf returns 400 (not 404) for an event_id absent from the
            # archive — must be tolerated like an empty event, not raised.
            return httpx.Response(
                400, text="event number 32 is not available in the 2026 pga calendar year"
            )
        body = _HISTORICAL_ROUNDS if event_id == _DONE_EVENT_ID else {"scores": []}
        return httpx.Response(200, json=body)
    if path == "/preds/get-projections":
        return httpx.Response(200, json=_PROJECTIONS)
    if path == "/betting-tools/outrights":
        return httpx.Response(200, json=_OUTRIGHTS)
    return httpx.Response(404, json={"error": "not found"})


# Providers created during a test, closed by the autouse fixture below so their
# httpx.AsyncClient is released inside the test's event loop — otherwise GC
# reaps it after the loop closes and ``filterwarnings=["error"]`` escalates the
# resulting "Event loop is closed" warning into a non-deterministic ERROR.
_CREATED: list[DataGolfProvider] = []


def _provider() -> DataGolfProvider:
    provider = DataGolfProvider(
        api_key="test-key",
        transport=httpx.MockTransport(_handler),
    )
    _CREATED.append(provider)
    return provider


@pytest.fixture(autouse=True)
async def _close_created_providers():  # noqa: ANN202
    yield
    while _CREATED:
        await _CREATED.pop().aclose()


# ---------------------------------------------------------------------------
# Pure parse helpers
# ---------------------------------------------------------------------------


def test_parse_fin_text_positions_and_statuses() -> None:
    assert _parse_fin_text("1") == (1, EntryStatus.MADE_CUT)
    assert _parse_fin_text("T5") == (5, EntryStatus.MADE_CUT)
    assert _parse_fin_text("T12") == (12, EntryStatus.MADE_CUT)
    assert _parse_fin_text("CUT") == (None, EntryStatus.MISSED_CUT)
    assert _parse_fin_text("MC") == (None, EntryStatus.MISSED_CUT)
    assert _parse_fin_text("WD") == (None, EntryStatus.WITHDREW)
    assert _parse_fin_text("DQ") == (None, EntryStatus.WITHDREW)
    assert _parse_fin_text(None) == (None, EntryStatus.MADE_CUT)
    assert _parse_fin_text("garbage") == (None, EntryStatus.MADE_CUT)


def test_parse_date_range_same_month() -> None:
    start, end = _parse_dg_date_range("Feb 1 - 4", 2026)
    assert start == date(2026, 2, 1)
    assert end == date(2026, 2, 4)


def test_parse_date_range_cross_month() -> None:
    start, end = _parse_dg_date_range("Apr 28 - May 1", 2026)
    assert start == date(2026, 4, 28)
    assert end == date(2026, 5, 1)


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------


async def test_list_players_parses_and_skips_missing_id() -> None:
    page = await _provider().list_players(limit=100)
    ids = {p.id for p in page.items}
    assert ids == {18417, 10091, 12345}  # the id-less row is skipped
    rory = next(p for p in page.items if p.id == 18417)
    assert rory.full_name == "McIlroy, Rory"
    assert rory.dg_id == 18417
    # Null country falls back to a non-null default (domain requires a value).
    no_country = next(p for p in page.items if p.id == 12345)
    assert no_country.country


async def test_get_player_by_id() -> None:
    player = await _provider().get_player(10091)
    assert player is not None
    assert player.full_name == "Scheffler, Scottie"


# ---------------------------------------------------------------------------
# Schedule / tournaments
# ---------------------------------------------------------------------------


async def test_list_tournaments_parses_schedule() -> None:
    page = await _provider().list_tournaments(season=_THIS_YEAR, limit=100)
    by_id = {t.id: t for t in page.items}
    # String event_id "100" is coerced to int 100.
    assert _DONE_EVENT_ID in by_id
    done = by_id[_DONE_EVENT_ID]
    assert done.name == "Completed Open"
    assert done.purse == 20000000
    # ISO start_date parsed; end derived as start + 3 days (Thu–Sun).
    assert done.start_date == date(_THIS_YEAR, 2, 1)
    assert done.end_date == date(_THIS_YEAR, 2, 4)
    # DataGolf's own status field is authoritative.
    assert done.status == TournamentStatus.COMPLETED


async def test_get_tournament_tolerates_future_season_400() -> None:
    # _find_tournament peeks one year ahead; that future season 400s on the
    # real API and must be swallowed, not raised, so the lookup still resolves.
    done = await _provider().get_tournament(_DONE_EVENT_ID)
    assert done is not None
    assert done.name == "Completed Open"


async def test_schedule_status_honours_datagolf_upcoming() -> None:
    page = await _provider().list_tournaments(season=_THIS_YEAR, limit=100)
    by_id = {t.id: t for t in page.items}
    live = by_id[_LIVE_EVENT_ID]
    # status="upcoming" with a future start_date stays UPCOMING (not derived
    # to completed from a missing/garbled date as the old parser did).
    assert live.status == TournamentStatus.UPCOMING
    assert live.start_date == date(_THIS_YEAR, 12, 15)


# ---------------------------------------------------------------------------
# Field — live vs completed (the critical reconstruction)
# ---------------------------------------------------------------------------


async def test_live_field_returns_active_entries_with_real_ids() -> None:
    field = await _provider().get_tournament_field(_LIVE_EVENT_ID)
    assert {e.player_id for e in field} == {18417, 10091}
    assert all(e.status == EntryStatus.ACTIVE for e in field)
    assert all(e.final_position is None for e in field)


async def test_completed_field_has_real_ids_and_parsed_positions() -> None:
    field = await _provider().get_tournament_field(_DONE_EVENT_ID)
    by_player = {e.player_id: e for e in field}
    # Real dg_ids, not hashed entry ids.
    assert set(by_player) == {18417, 10091, 22222}
    # Winner.
    assert by_player[18417].final_position == 1
    assert by_player[18417].status == EntryStatus.MADE_CUT
    # Tied 5th.
    assert by_player[10091].final_position == 5
    # Missed cut → no position, missed-cut status.
    assert by_player[22222].final_position is None
    assert by_player[22222].status == EntryStatus.MISSED_CUT


# ---------------------------------------------------------------------------
# Rounds — the dating fix
# ---------------------------------------------------------------------------


async def test_rounds_are_dated_so_features_keep_them() -> None:
    rounds = await _provider().get_rounds(_DONE_EVENT_ID)
    # 2 four-round players + 1 two-round player = 10 rounds.
    assert len(rounds) == 10
    # Every round MUST have a tee_time, else the feature pipeline drops it.
    assert all(r.tee_time is not None for r in rounds)
    # Round dates step one day per round from the Feb 1 start.
    rory_r1 = next(r for r in rounds if r.round_number == 1 and r.sg_total == 2.5)
    assert rory_r1.tee_time is not None
    assert rory_r1.tee_time.date() == date(_THIS_YEAR, 2, 1)
    rory_r4 = next(r for r in rounds if r.round_number == 4 and r.sg_total == 3.1)
    assert rory_r4.tee_time is not None
    assert rory_r4.tee_time.date() == date(_THIS_YEAR, 2, 4)


async def test_rounds_carry_sg_values() -> None:
    rounds = await _provider().get_rounds(_DONE_EVENT_ID)
    r = next(r for r in rounds if r.sg_total == 2.5)
    assert r.sg_ott == pytest.approx(0.5)
    assert r.sg_putt == pytest.approx(0.3)
    assert r.driving_distance_avg == pytest.approx(305.2)


async def test_get_rounds_for_player_filters_and_dates() -> None:
    rounds = await _provider().get_rounds_for_player(18417, limit=100)
    # Only McIlroy's four rounds from the completed event.
    assert len(rounds) == 4
    assert all(r.tee_time is not None for r in rounds)
    # Sorted newest-first by date.
    times = [r.tee_time for r in rounds]
    assert times == sorted(times, reverse=True)


# ---------------------------------------------------------------------------
# Projections
# ---------------------------------------------------------------------------


async def test_get_dg_projections_parses_rows() -> None:
    rows = await _provider().get_dg_projections()
    assert len(rows) == 1
    assert rows[0]["dg_id"] == 18417
    assert rows[0]["win"] == pytest.approx(12.5)


# ---------------------------------------------------------------------------
# Real sportsbook odds — betting-tools/outrights
# ---------------------------------------------------------------------------


async def test_get_outright_odds_builds_consensus_per_player() -> None:
    board = await _provider().get_outright_odds("win_prob")
    assert board is not None
    assert board.event_name == "Live Championship"
    assert board.market == "win"
    # Two players priced; the unpriced "NA" row is dropped.
    assert set(board.odds) == {18417, 10091}
    # Scheffler's three identical +300 books → consensus is exactly +300.
    assert board.odds[10091] == 300
    # McIlroy's consensus is the median across books (DataGolf baseline excluded),
    # so it lands between the best and worst book line.
    assert 500 <= board.odds[18417] <= 550


async def test_get_outright_odds_unknown_market_returns_none() -> None:
    assert await _provider().get_outright_odds("not_a_market") is None


# ---------------------------------------------------------------------------
# Robustness: an event missing from the archive (HTTP 400) is skipped, not fatal
# ---------------------------------------------------------------------------


async def test_missing_event_returns_no_rounds_instead_of_raising() -> None:
    # event_id 32 is in the schedule but not the historical archive → 400.
    # The provider must treat it as empty so a training loop over the whole
    # schedule isn't aborted by one absent event.
    rounds = await _provider().get_rounds(_MISSING_EVENT_ID)
    assert rounds == []


async def test_valid_event_ids_filters_to_pga_with_sg() -> None:
    # Only the PGA event flagged sg_categories="yes" survives; the no-SG and
    # wrong-tour rows are excluded.
    ids = await _provider()._valid_event_ids(_THIS_YEAR)
    assert ids == {_DONE_EVENT_ID}


async def test_event_without_sg_data_is_skipped_without_fetch() -> None:
    # Event 777 has raw data flagged sg_categories="no" → not in the valid set,
    # so the provider skips it (no rounds) rather than spending a throttled call.
    rounds = await _provider().get_rounds(777)
    assert rounds == []


# ---------------------------------------------------------------------------
# End-to-end: provider → features → labels would actually train
# ---------------------------------------------------------------------------


async def test_real_field_produces_nonzero_features_and_labels() -> None:
    """The money test: a DataGolf-shaped completed event must yield non-zero
    features (rounds are dated) and real training labels (positions parsed)."""
    provider = _provider()
    extractor = FeatureExtractor(provider)

    field = await provider.get_tournament_field(_DONE_EVENT_ID)
    # Extract features as of after the event so its rounds are in-window.
    as_of = date(_THIS_YEAR, 6, 1)
    extractions = await extractor.extract_field(
        [e.player_id for e in field], as_of
    )

    rory = extractions[18417]
    # Rounds were dated → kept → skill features are non-zero.
    assert rory.n_rounds == 4
    assert rory.values["sg_total_rating"] != 0.0

    # Labels come straight from the parsed field: winner → win=1.
    winner_entry = next(e for e in field if e.player_id == 18417)
    labels = labels_from_entry(winner_entry)
    assert labels["win"] == 1
    assert labels["top_5"] == 1
    assert labels["made_cut"] == 1

    # Missed-cut player → all-zero positive buckets.
    mc_entry = next(e for e in field if e.player_id == 22222)
    mc_labels = labels_from_entry(mc_entry)
    assert mc_labels["made_cut"] == 0
    assert mc_labels["win"] == 0
