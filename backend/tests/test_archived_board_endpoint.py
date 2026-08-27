"""Endpoint tests for the read-only archived board (audit F4).

``GET /predictions/{id}/archived`` serves the board that was actually pinned
before the event, so a completed-event view can stop presenting a fresh
recomputation as the pre-event board.

What is pinned here:

- the canonical snapshot is chosen by the grader's own rule, so this view and
  the forward record cannot disagree about which board counts (ledger §2.3);
- ``captured`` and ``backfilled`` stay distinguishable in the payload (§2.5);
- a missing snapshot reports ``available: false`` and never falls back to a
  recomputation;
- the endpoint writes nothing — no board capture, no settlement pin — because
  anyone loading a page can reach it.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from app.api.v1.deps import (
    get_board_archive,
    get_catalog_service,
    get_settlement_archive,
)
from app.domain.enums import EntryStatus, TournamentStatus
from app.domain.models import Player, Tournament, TournamentEntry
from app.services.board_archive import (
    BoardSnapshot,
    BoardSnapshotOutcome,
    FileBoardArchive,
)
from app.services.settlement_archive import FileSettlementArchive

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI

_START = date(2026, 6, 1)
_NO_CUT_EVENT = 3


def _url(tournament_id: int) -> str:
    return f"/api/v1/predictions/{tournament_id}/archived"


def _board(
    tournament_id: int,
    *,
    source: str = "captured",
    captured_at: str = "2026-05-31T12:00:00+00:00",
    model_version_id: str = "path_a@v2",
    trained_through: str | None = "2026-05-01",
) -> BoardSnapshot:
    return BoardSnapshot(
        tournament_id=tournament_id,
        tournament_name=f"Event {tournament_id}",
        tournament_start_date=_START.isoformat(),
        model_name="golf_v1",
        model_version_id=model_version_id,
        feature_set_hash="deadbeef",
        model_trained_through=trained_through,
        as_of="2026-05-31",
        captured_at=captured_at,
        outcomes=(
            BoardSnapshotOutcome(10, 0.40, 0.70, 0.80, 0.90, 0.98),
            BoardSnapshotOutcome(11, 0.02, 0.10, 0.30, 0.60, 0.85),
            BoardSnapshotOutcome(12, 0.01, 0.05, 0.10, 0.20, 0.40),
        ),
        source=source,
        dg_direct_count=3,
        dg_fetch_status="ok",
    )


class _Catalog:
    """Three completed events; ``_NO_CUT_EVENT`` played without a 36-hole cut."""

    source_name = "stub-provider"

    def __init__(self) -> None:
        self.field_reads = 0

    async def get_tournament(self, tournament_id: int) -> Tournament | None:
        if tournament_id not in {1, 2, _NO_CUT_EVENT, 4}:
            return None
        return Tournament(
            id=tournament_id,
            course_id=1,
            name=f"Event {tournament_id}",
            season=2026,
            start_date=_START,
            end_date=_START,
            purse=None,
            field_strength=None,
            status=TournamentStatus.COMPLETED,
        )

    async def get_tournament_field(self, tournament_id: int) -> list[TournamentEntry]:
        self.field_reads += 1
        if tournament_id == _NO_CUT_EVENT:
            # A FedExCup-style event: everyone "made" a cut never played.
            rows = [
                (10, EntryStatus.MADE_CUT, 1),
                (11, EntryStatus.MADE_CUT, 12),
                (12, EntryStatus.MADE_CUT, 25),
            ]
        else:
            rows = [
                (10, EntryStatus.MADE_CUT, 1),
                (11, EntryStatus.MADE_CUT, 30),
                (12, EntryStatus.MISSED_CUT, None),
            ]
        return [
            TournamentEntry(
                id=i,
                tournament_id=tournament_id,
                player_id=pid,
                status=st,
                final_position=pos,
                final_score_to_par=None,
                official_money_cents=None,
            )
            for i, (pid, st, pos) in enumerate(rows)
        ]

    async def get_player(self, player_id: int) -> Player | None:
        return Player(
            id=player_id,
            dg_id=player_id,
            full_name=f"Player {player_id}",
            country="USA",
            dob=None,
            turned_pro=None,
        )


@pytest.fixture
def ctx(app: FastAPI, tmp_path) -> Iterator[tuple[TestClient, FileBoardArchive, object, _Catalog]]:
    boards = FileBoardArchive(tmp_path / "boards")
    settlements = FileSettlementArchive(tmp_path / "settlements")
    catalog = _Catalog()
    app.dependency_overrides[get_board_archive] = lambda: boards
    app.dependency_overrides[get_settlement_archive] = lambda: settlements
    app.dependency_overrides[get_catalog_service] = lambda: catalog
    with TestClient(app) as c:
        yield c, boards, settlements, catalog
    for dep in (get_board_archive, get_settlement_archive, get_catalog_service):
        app.dependency_overrides.pop(dep, None)


async def test_serves_the_captured_board_with_results(ctx) -> None:
    client, boards, _, _ = ctx
    await boards.persist(_board(1))

    body = client.get(_url(1)).json()

    assert body["available"] is True
    assert body["source"] == "captured"
    assert body["graded"] is True
    assert body["out_of_sample"] is True
    assert body["event_had_a_cut"] is True
    # Probabilities are the pinned ones, not a recomputation.
    winner = next(o for o in body["outcomes"] if o["player_id"] == 10)
    assert winner["win_prob"] == pytest.approx(0.40)
    assert winner["player_name"] == "Player 10"
    assert winner["final_position"] == 1
    assert winner["made_cut"] is True
    missed = next(o for o in body["outcomes"] if o["player_id"] == 12)
    assert missed["final_position"] is None
    assert missed["made_cut"] is False


async def test_reports_a_backfilled_board_as_reconstructed(ctx) -> None:
    client, boards, _, _ = ctx
    await boards.persist(_board(2, source="backfilled"))

    body = client.get(_url(2)).json()

    assert body["available"] is True
    assert body["source"] == "backfilled"


async def test_absent_snapshot_reports_unavailable_and_serves_no_board(ctx) -> None:
    client, _, _, _ = ctx

    body = client.get(_url(4)).json()

    assert body["available"] is False
    assert body["source"] is None
    assert body["outcomes"] == []
    # The tournament is still named, so the caller can say which event it is.
    assert body["tournament_name"] == "Event 4"


def test_unknown_tournament_404s(ctx) -> None:
    client, _, _, _ = ctx
    assert client.get(_url(999)).status_code == 404


async def test_prefers_the_captured_snapshot_over_a_later_backfill(ctx) -> None:
    """The grader's canonical rule: captured beats backfilled regardless of time."""
    client, boards, _, _ = ctx
    await boards.persist(
        _board(
            1,
            source="backfilled",
            model_version_id="v3",
            captured_at="2026-05-30T00:00:00+00:00",
        )
    )
    await boards.persist(
        _board(
            1,
            source="captured",
            model_version_id="path_a@v2",
            captured_at="2026-05-31T12:00:00+00:00",
        )
    )

    body = client.get(_url(1)).json()

    # Backfill is the earlier timestamp, but the live capture is primary evidence.
    assert body["source"] == "captured"
    assert body["model_version_id"] == "path_a@v2"


async def test_withholds_make_cut_on_a_no_cut_event(ctx) -> None:
    client, boards, _, _ = ctx
    await boards.persist(_board(_NO_CUT_EVENT))

    body = client.get(_url(_NO_CUT_EVENT)).json()

    assert body["event_had_a_cut"] is False
    # Every player "made" a cut that was never played, so the result is withheld
    # rather than reported as a correct call.
    assert all(o["made_cut"] is None for o in body["outcomes"])
    assert all(o["final_position"] is not None for o in body["outcomes"])


async def test_is_read_only(ctx) -> None:
    """A GET must not pin a settlement or write a board snapshot."""
    client, boards, settlements, _ = ctx
    await boards.persist(_board(1))

    before = len(await boards.list_all())
    client.get(_url(1))

    assert await settlements.get(1) is None, "endpoint pinned a settlement record"
    assert len(await boards.list_all()) == before, "endpoint wrote a board snapshot"


async def test_uses_the_pinned_settlement_when_one_exists(ctx) -> None:
    """A pinned result is authoritative; the provider is not consulted."""
    client, boards, settlements, catalog = ctx
    await boards.persist(_board(1))
    field = await catalog.get_tournament_field(1)
    tournament = await catalog.get_tournament(1)
    from app.services.settlement_archive import settlement_from_field

    await settlements.persist(settlement_from_field(tournament, field, provider="pinned-source"))
    reads_before = catalog.field_reads

    body = client.get(_url(1)).json()

    assert body["graded"] is True
    assert catalog.field_reads == reads_before, "read the provider despite a pinned settlement"


# --- GET /predictions/archived — the public event-picker list --------------
# Backs the Track Record page. Metadata only: no probabilities, no player
# names leave this endpoint (ledger §2.8).


def _list_url() -> str:
    return "/api/v1/predictions/archived"


async def test_lists_no_events_when_the_archive_is_empty(ctx) -> None:
    client, _, _, _ = ctx
    assert client.get(_list_url()).json() == []


async def test_lists_a_pinned_event_with_metadata_only(ctx) -> None:
    client, boards, _, _ = ctx
    await boards.persist(_board(1))

    body = client.get(_list_url()).json()

    assert len(body) == 1
    row = body[0]
    assert row["tournament_id"] == 1
    assert row["tournament_name"] == "Event 1"
    assert row["tournament_start_date"] == _START.isoformat()
    assert row["source"] == "captured"
    assert row["out_of_sample"] is True
    # No per-player data of any kind.
    assert "outcomes" not in row
    assert "win_prob" not in str(row)


async def test_orders_newest_tournament_first(ctx) -> None:
    client, boards, _, _ = ctx
    await boards.persist(
        BoardSnapshot(
            tournament_id=1,
            tournament_name="Earlier Event",
            tournament_start_date=date(2026, 5, 1).isoformat(),
            model_name="golf_v1",
            model_version_id="path_a@v2",
            feature_set_hash="deadbeef",
            model_trained_through="2026-04-01",
            as_of="2026-04-30",
            captured_at="2026-04-30T12:00:00+00:00",
            outcomes=(BoardSnapshotOutcome(10, 0.4, 0.7, 0.8, 0.9, 0.98),),
        )
    )
    await boards.persist(_board(2))  # _START = 2026-06-01, later

    body = client.get(_list_url()).json()

    assert [row["tournament_id"] for row in body] == [2, 1]


async def test_collapses_several_snapshots_of_one_event_to_the_canonical_row(ctx) -> None:
    """Same rule as the per-tournament endpoint: one row per event, captured
    beats backfilled, even when a retrain left several snapshots behind."""
    client, boards, _, _ = ctx
    await boards.persist(
        _board(1, source="backfilled", model_version_id="v3", captured_at="2026-05-30T00:00:00+00:00")
    )
    await boards.persist(
        _board(1, source="captured", model_version_id="path_a@v2", captured_at="2026-05-31T12:00:00+00:00")
    )

    body = client.get(_list_url()).json()

    assert len(body) == 1
    assert body[0]["source"] == "captured"


async def test_reports_not_out_of_sample_when_training_cutoff_is_unknown(ctx) -> None:
    client, boards, _, _ = ctx
    await boards.persist(_board(1, trained_through=None))

    body = client.get(_list_url()).json()

    assert body[0]["out_of_sample"] is False


async def test_list_endpoint_is_read_only(ctx) -> None:
    client, boards, settlements, _ = ctx
    await boards.persist(_board(1))

    before = len(await boards.list_all())
    client.get(_list_url())

    assert await settlements.get(1) is None
    assert len(await boards.list_all()) == before
