"""``MockDataProvider`` — wires the deterministic generator to the
``DataProvider`` interface.

The dataset is built once per provider instance (the first call lazily
triggers ``generator.generate(seed)``) and then served from in-memory
indexes. The ``DataProvider`` factory caches the provider so a single
process never re-generates.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.domain.models import DataFreshness, Page
from app.providers.base import Capability, DataProvider
from app.providers.mock.generator import generate

if TYPE_CHECKING:
    from datetime import date

    from app.domain.enums import TournamentStatus
    from app.domain.models import (
        BettingLine,
        Course,
        Player,
        Round,
        Tournament,
        TournamentEntry,
    )
    from app.providers.mock.generator import MockDataset

_CURSOR_PREFIX = "offset:"


def _encode_cursor(offset: int) -> str:
    return f"{_CURSOR_PREFIX}{offset}"


def _decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    if not cursor.startswith(_CURSOR_PREFIX):
        raise ValueError(f"Invalid cursor: {cursor!r}")
    return int(cursor[len(_CURSOR_PREFIX) :])


def _paginate[T](items: list[T], cursor: str | None, limit: int) -> Page[T]:
    offset = _decode_cursor(cursor)
    page_items = items[offset : offset + limit]
    next_offset = offset + len(page_items)
    next_cursor = _encode_cursor(next_offset) if next_offset < len(items) else None
    return Page(items=page_items, next_cursor=next_cursor, total=len(items))


class MockDataProvider(DataProvider):
    """Deterministic, in-memory provider built on the mock generator."""

    def __init__(self, seed: int = 42) -> None:
        self._seed = seed
        self._dataset: MockDataset | None = None

    # --- Lazy dataset access -------------------------------------------------

    def _data(self) -> MockDataset:
        if self._dataset is None:
            self._dataset = generate(seed=self._seed)
        return self._dataset

    # --- Identity ------------------------------------------------------------

    def get_source_name(self) -> str:
        return "mock"

    def capabilities(self) -> set[Capability]:
        # The mock surfaces betting lines and runs back several seasons of
        # synthetic history. Live data and DFS land with DataGolf in Phase 5.
        return {Capability.BETTING_LINES, Capability.HISTORICAL_ODDS}

    async def get_data_freshness(self) -> DataFreshness:
        ts = self._data().generated_at
        # Mock data is "always fresh as of generation time" for every source
        return DataFreshness(
            sources={
                "players": ts,
                "courses": ts,
                "tournaments": ts,
                "rounds": ts,
                "betting_lines": ts,
            }
        )

    # --- Players -------------------------------------------------------------

    async def list_players(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> Page[Player]:
        return _paginate(self._data().players, cursor, limit)

    async def get_player(self, player_id: int) -> Player | None:
        for p in self._data().players:
            if p.id == player_id:
                return p
        return None

    # --- Courses -------------------------------------------------------------

    async def list_courses(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> Page[Course]:
        return _paginate(self._data().courses, cursor, limit)

    async def get_course(self, course_id: int) -> Course | None:
        for c in self._data().courses:
            if c.id == course_id:
                return c
        return None

    # --- Tournaments ---------------------------------------------------------

    async def list_tournaments(
        self,
        *,
        season: int | None = None,
        status: TournamentStatus | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> Page[Tournament]:
        items = self._data().tournaments
        if season is not None:
            items = [t for t in items if t.season == season]
        if status is not None:
            items = [t for t in items if t.status == status]
        return _paginate(items, cursor, limit)

    async def get_tournament(self, tournament_id: int) -> Tournament | None:
        for t in self._data().tournaments:
            if t.id == tournament_id:
                return t
        return None

    async def get_tournament_field(self, tournament_id: int) -> list[TournamentEntry]:
        return [e for e in self._data().entries if e.tournament_id == tournament_id]

    # --- Rounds --------------------------------------------------------------

    async def get_rounds(self, tournament_id: int) -> list[Round]:
        entries_in_t = {e.id for e in self._data().entries if e.tournament_id == tournament_id}
        return [r for r in self._data().rounds if r.entry_id in entries_in_t]

    async def get_rounds_for_player(
        self,
        player_id: int,
        *,
        since: date | None = None,
        limit: int = 100,
    ) -> list[Round]:
        entries_for_player = {e.id for e in self._data().entries if e.player_id == player_id}
        rounds = [
            r
            for r in self._data().rounds
            if r.entry_id in entries_for_player
            and (since is None or (r.tee_time is not None and r.tee_time.date() >= since))
        ]
        # Most recent first to match the dashboard's "recent rounds" pattern
        rounds.sort(
            key=lambda r: r.tee_time or datetime(1900, 1, 1, tzinfo=UTC),
            reverse=True,
        )
        return rounds[:limit]

    # --- Betting lines (capability) ------------------------------------------

    async def get_betting_lines(self, tournament_id: int) -> list[BettingLine]:
        return [bl for bl in self._data().betting_lines if bl.tournament_id == tournament_id]
