"""Tests for the immutable settlement archive.

The property that matters: a settlement record is written once and can never
be overwritten, so a provider-side data revision can never rewrite what an
already-graded event's results were. Grader-level behaviour (pin on first
grade, read the pin afterwards) is tested in ``test_board_archive.py`` next
to the other grading tests.
"""

from __future__ import annotations

import json
from datetime import date

from app.domain.enums import EntryStatus, TournamentStatus
from app.domain.models import Tournament, TournamentEntry
from app.services.settlement_archive import (
    FileSettlementArchive,
    RedisSettlementArchive,
    SettlementEntry,
    SettlementRecord,
    _from_dict,
    _to_json,
    settlement_from_field,
)


class _FakeRedis:
    """In-memory stand-in implementing the ops the settlement archive uses."""

    def __init__(self) -> None:
        self._d: dict[str, str] = {}

    async def set(self, key: str, value: str, nx: bool = False) -> bool | None:
        if nx and key in self._d:
            return None
        self._d[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self._d.get(key)

    async def exists(self, key: str) -> int:
        return 1 if key in self._d else 0

    async def scan_iter(self, match: str = "*"):  # noqa: ANN201 — async generator
        prefix = match.rstrip("*")
        for key in list(self._d):
            if key.startswith(prefix):
                yield key

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [self._d.get(k) for k in keys]


def _record(tournament_id: int = 1, winner_position: int = 1) -> SettlementRecord:
    return SettlementRecord(
        tournament_id=tournament_id,
        tournament_name="The Demo",
        tournament_start_date="2026-06-01",
        provider="mock",
        settled_at="2026-06-05T12:00:00+00:00",
        entries=(
            SettlementEntry(player_id=10, final_position=winner_position, status="made_cut"),
            SettlementEntry(player_id=11, final_position=30, status="made_cut"),
            SettlementEntry(player_id=12, final_position=None, status="missed_cut"),
            SettlementEntry(player_id=13, final_position=None, status="withdrew"),
        ),
    )


async def test_file_archive_is_immutable_and_round_trips(tmp_path) -> None:
    archive = FileSettlementArchive(tmp_path)
    assert await archive.persist(_record()) is True
    assert await archive.has(1)
    # A second write for the same tournament must NOT overwrite: the pin is
    # what protects history from a provider-side revision.
    assert await archive.persist(_record(winner_position=99)) is False
    stored = await archive.get(1)
    assert stored is not None
    assert stored.entries[0].final_position == 1  # the first pin survived
    assert [r.tournament_id for r in await archive.list_all()] == [1]


async def test_redis_archive_is_immutable_and_round_trips() -> None:
    archive = RedisSettlementArchive(_FakeRedis())  # type: ignore[arg-type]
    assert await archive.persist(_record()) is True
    assert await archive.persist(_record(winner_position=99)) is False
    stored = await archive.get(1)
    assert stored is not None
    assert stored.entries[0].final_position == 1
    assert stored.entries[3].status == "withdrew"


def test_unrecognised_status_is_ungradeable_not_guessed() -> None:
    entry = SettlementEntry(player_id=10, final_position=1, status="some_future_status")
    assert entry.entry_status() is None
    assert SettlementEntry(10, 1, "made_cut").entry_status() == EntryStatus.MADE_CUT
    assert SettlementEntry(10, None, "disqualified").entry_status() == EntryStatus.DISQUALIFIED


def test_from_dict_tolerates_unknown_and_missing_keys() -> None:
    data = json.loads(_to_json(_record()))
    data["written_by_a_newer_build"] = True
    data["entries"][0]["future_field"] = 1
    loaded = _from_dict(data)
    assert loaded.tournament_id == 1
    assert loaded.entries[0].player_id == 10


def test_settlement_from_field_preserves_every_status() -> None:
    tournament = Tournament(
        id=7,
        course_id=1,
        name="The Demo",
        season=2026,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 4),
        purse=None,
        field_strength=None,
        status=TournamentStatus.COMPLETED,
    )
    field = [
        TournamentEntry(
            id=i,
            tournament_id=7,
            player_id=10 + i,
            status=st,
            final_position=pos,
            final_score_to_par=None,
            official_money_cents=None,
        )
        for i, (st, pos) in enumerate(
            [
                (EntryStatus.MADE_CUT, 1),
                (EntryStatus.MISSED_CUT, None),
                (EntryStatus.WITHDREW, None),
                (EntryStatus.DISQUALIFIED, None),
            ]
        )
    ]
    record = settlement_from_field(tournament, field, provider="mock")
    assert record.tournament_id == 7
    assert record.provider == "mock"
    assert [e.status for e in record.entries] == [
        "made_cut",
        "missed_cut",
        "withdrew",
        "disqualified",
    ]
    # Round-trips through storage with every status intact.
    reloaded = _from_dict(json.loads(_to_json(record)))
    assert reloaded == record
