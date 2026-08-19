"""Tests for archive export/import — the forward record's survival mechanism.

Production stores both forward archives in a Key Value instance with no
persistence, so the contracts pinned here are what make a wipe recoverable:
the export is deterministic (the backup job diffs it to skip empty commits),
a restore round-trips every snapshot bit-for-bit, and importing can only ever
fill gaps — first write wins, so a dump can never overwrite a snapshot that
survived in the live store.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

import app.api.v1.analytics as analytics_module
from app.api.v1.deps import get_board_archive, get_matchup_archive
from app.services.archive_export import export_archives, import_archives
from app.services.board_archive import (
    BoardSnapshot,
    BoardSnapshotOutcome,
    FileBoardArchive,
)
from app.services.matchup_line_record import (
    BookQuote,
    FileMatchupArchive,
    MatchupRow,
    MatchupSnapshot,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from fastapi import FastAPI

_EXPORT_URL = "/api/v1/analytics/archive/export"
_IMPORT_URL = "/api/v1/analytics/archive/import"


def _board(tournament_id: int = 1, version: str = "path_a@v2") -> BoardSnapshot:
    return BoardSnapshot(
        tournament_id=tournament_id,
        tournament_name=f"Event {tournament_id}",
        tournament_start_date="2026-06-01",
        model_name="golf_v1",
        model_version_id=version,
        feature_set_hash="deadbeef",
        model_trained_through="2026-05-01",
        as_of="2026-05-31",
        captured_at="2026-05-31T12:00:00+00:00",
        outcomes=(
            BoardSnapshotOutcome(
                player_id=10,
                win_prob=0.1,
                top_5_prob=0.2,
                top_10_prob=0.3,
                top_20_prob=0.4,
                make_cut_prob=0.9,
            ),
        ),
        dg_direct_count=1,
    )


def _matchup(event: str = "BMW Championship", year: int = 2026) -> MatchupSnapshot:
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
                quotes=(BookQuote(book="datagolf", p1=-110, p2=-110),),
            ),
        ),
    )


def _archives(root: Path) -> tuple[FileBoardArchive, FileMatchupArchive]:
    boards = FileBoardArchive(root / "boards")
    matchups = FileMatchupArchive(root / "matchups")
    return boards, matchups


# --- Service level -----------------------------------------------------------


async def test_export_import_round_trips_both_archives(tmp_path) -> None:
    boards, matchups = _archives(tmp_path / "src")
    await boards.persist(_board(1))
    await boards.persist(_board(2, version="path_a@v3"))
    await matchups.persist(_matchup())

    doc = await export_archives(boards=boards, matchups=matchups)
    # The document must be JSON-serializable as-is (it goes over HTTP and
    # into a committed file).
    doc = json.loads(json.dumps(doc))

    fresh_boards, fresh_matchups = _archives(tmp_path / "dst")
    result = await import_archives(doc, boards=fresh_boards, matchups=fresh_matchups)

    assert result.boards_stored == 2
    assert result.matchups_stored == 1
    assert result.boards_errors == result.matchups_errors == 0
    assert sorted(await fresh_boards.list_all(), key=lambda s: s.tournament_id) == sorted(
        await boards.list_all(), key=lambda s: s.tournament_id
    )
    assert await fresh_matchups.list_all() == await matchups.list_all()


async def test_export_is_deterministic_regardless_of_write_order(tmp_path) -> None:
    a_boards, a_matchups = _archives(tmp_path / "a")
    await a_boards.persist(_board(2))
    await a_boards.persist(_board(1))
    await a_matchups.persist(_matchup("Tour Championship"))
    await a_matchups.persist(_matchup("BMW Championship"))

    b_boards, b_matchups = _archives(tmp_path / "b")
    await b_boards.persist(_board(1))
    await b_boards.persist(_board(2))
    await b_matchups.persist(_matchup("BMW Championship"))
    await b_matchups.persist(_matchup("Tour Championship"))

    doc_a = await export_archives(boards=a_boards, matchups=a_matchups)
    doc_b = await export_archives(boards=b_boards, matchups=b_matchups)
    assert json.dumps(doc_a, sort_keys=True) == json.dumps(doc_b, sort_keys=True)


async def test_import_never_overwrites_an_existing_snapshot(tmp_path) -> None:
    boards, matchups = _archives(tmp_path)
    await boards.persist(_board(1))

    # A dump claiming different probabilities for the same (tournament, version).
    doc = await export_archives(boards=boards, matchups=matchups)
    doc = json.loads(json.dumps(doc))
    doc["boards"][0]["outcomes"][0]["win_prob"] = 0.99

    result = await import_archives(doc, boards=boards, matchups=matchups)
    assert result.boards_stored == 0
    assert result.boards_skipped == 1
    (kept,) = await boards.list_all()
    assert kept.outcomes[0].win_prob == pytest.approx(0.1)  # live capture wins


async def test_import_is_idempotent(tmp_path) -> None:
    src_boards, src_matchups = _archives(tmp_path / "src")
    await src_boards.persist(_board(1))
    await src_matchups.persist(_matchup())
    doc = await export_archives(boards=src_boards, matchups=src_matchups)

    dst_boards, dst_matchups = _archives(tmp_path / "dst")
    first = await import_archives(doc, boards=dst_boards, matchups=dst_matchups)
    second = await import_archives(doc, boards=dst_boards, matchups=dst_matchups)
    assert (first.boards_stored, first.matchups_stored) == (1, 1)
    assert (second.boards_stored, second.matchups_stored) == (0, 0)
    assert (second.boards_skipped, second.matchups_skipped) == (1, 1)
    assert len(await dst_boards.list_all()) == 1


async def test_import_counts_garbage_entries_without_losing_the_rest(tmp_path) -> None:
    src_boards, src_matchups = _archives(tmp_path / "src")
    await src_boards.persist(_board(1))
    doc = await export_archives(boards=src_boards, matchups=src_matchups)
    doc = json.loads(json.dumps(doc))
    doc["boards"].append({"outcomes": "not-a-list"})  # unparseable husk
    doc["matchups"].append(42)  # not even a dict

    dst_boards, dst_matchups = _archives(tmp_path / "dst")
    result = await import_archives(doc, boards=dst_boards, matchups=dst_matchups)
    assert result.boards_stored == 1
    assert result.boards_errors == 1
    assert result.matchups_errors == 1
    assert len(await dst_boards.list_all()) == 1


async def test_import_does_not_mutate_the_caller_payload(tmp_path) -> None:
    src_boards, src_matchups = _archives(tmp_path / "src")
    await src_boards.persist(_board(1))
    await src_matchups.persist(_matchup())
    doc = json.loads(json.dumps(await export_archives(boards=src_boards, matchups=src_matchups)))
    before = json.dumps(doc, sort_keys=True)

    dst_boards, dst_matchups = _archives(tmp_path / "dst")
    await import_archives(doc, boards=dst_boards, matchups=dst_matchups)
    assert json.dumps(doc, sort_keys=True) == before


# --- Endpoint level ----------------------------------------------------------


@pytest.fixture
def archive_ctx(app: FastAPI, tmp_path, monkeypatch) -> Iterator[TestClient]:
    boards, matchups = _archives(tmp_path)
    app.dependency_overrides[get_board_archive] = lambda: boards
    app.dependency_overrides[get_matchup_archive] = lambda: matchups
    monkeypatch.setattr(
        analytics_module,
        "get_settings",
        lambda: SimpleNamespace(admin_api_token="secret", data_provider="mock"),
    )
    with TestClient(app) as c:
        yield c
    for dep in (get_board_archive, get_matchup_archive):
        app.dependency_overrides.pop(dep, None)


def test_endpoints_reject_missing_and_wrong_token(archive_ctx: TestClient) -> None:
    assert archive_ctx.get(_EXPORT_URL).status_code == 404
    assert archive_ctx.get(_EXPORT_URL, headers={"X-Admin-Token": "nope"}).status_code == 404
    assert archive_ctx.post(_IMPORT_URL, json={"schema_version": 1}).status_code == 404


def test_endpoints_disabled_when_no_token_configured(archive_ctx: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        analytics_module,
        "get_settings",
        lambda: SimpleNamespace(admin_api_token=None, data_provider="mock"),
    )
    assert archive_ctx.get(_EXPORT_URL, headers={"X-Admin-Token": "secret"}).status_code == 404
    assert (
        archive_ctx.post(
            _IMPORT_URL, json={"schema_version": 1}, headers={"X-Admin-Token": "secret"}
        ).status_code
        == 404
    )


async def test_export_then_import_round_trips_over_http(
    archive_ctx: TestClient, app: FastAPI, tmp_path
) -> None:
    # Seed the live archives, export over HTTP, wipe (swap in fresh archives),
    # import the dump back, and confirm the record is whole again.
    boards = app.dependency_overrides[get_board_archive]()
    matchups = app.dependency_overrides[get_matchup_archive]()
    await boards.persist(_board(7))
    await matchups.persist(_matchup())

    r = archive_ctx.get(_EXPORT_URL, headers={"X-Admin-Token": "secret"})
    assert r.status_code == 200
    dump = r.json()
    assert dump["schema_version"] == 1
    assert len(dump["boards"]) == 1
    assert len(dump["matchups"]) == 1

    fresh_boards, fresh_matchups = _archives(tmp_path / "restored")
    app.dependency_overrides[get_board_archive] = lambda: fresh_boards
    app.dependency_overrides[get_matchup_archive] = lambda: fresh_matchups

    r2 = archive_ctx.post(_IMPORT_URL, json=dump, headers={"X-Admin-Token": "secret"})
    assert r2.status_code == 200
    body = r2.json()
    assert body["boards_stored"] == 1
    assert body["matchups_stored"] == 1
    assert body["boards_errors"] == body["matchups_errors"] == 0

    # The restored archive grades identically to the original: same snapshots.
    r3 = archive_ctx.get(_EXPORT_URL, headers={"X-Admin-Token": "secret"})
    assert r3.json() == dump
