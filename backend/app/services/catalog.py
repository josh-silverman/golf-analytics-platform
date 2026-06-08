"""Catalog service — read-only access to players, tournaments, courses.

Thin orchestration over the active ``DataProvider``. When the ingestion
pipeline lands, this layer becomes the right seam to switch from "fetch
from provider" to "fetch from Postgres repository", without changing the
API routes that call into it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.domain.enums import TournamentStatus

if TYPE_CHECKING:
    from datetime import date

    from app.domain.models import (
        Course,
        DataFreshness,
        Page,
        Player,
        Round,
        Tournament,
        TournamentEntry,
    )
    from app.providers.base import DataProvider


# Anchor date used with the mock provider so /tournaments/current always
# returns an "in-progress" event from the synthetic dataset.
# For any real provider (datagolf) reference_today() returns the actual date.
_MOCK_REFERENCE_TODAY = "2026-06-03"


class CatalogService:
    def __init__(self, provider: DataProvider) -> None:
        self._provider = provider

    @property
    def source_name(self) -> str:
        return self._provider.get_source_name()

    async def data_freshness(self) -> DataFreshness:
        return await self._provider.get_data_freshness()

    # --- Players -------------------------------------------------------------

    async def list_players(
        self, *, cursor: str | None = None, limit: int = 50
    ) -> Page[Player]:
        return await self._provider.list_players(cursor=cursor, limit=limit)

    async def get_player(self, player_id: int) -> Player | None:
        return await self._provider.get_player(player_id)

    async def recent_rounds_for_player(
        self, player_id: int, *, limit: int = 20
    ) -> list[Round]:
        return await self._provider.get_rounds_for_player(player_id, limit=limit)

    # --- Tournaments ---------------------------------------------------------

    async def list_tournaments(
        self,
        *,
        season: int | None = None,
        status: TournamentStatus | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Page[Tournament]:
        return await self._provider.list_tournaments(
            season=season, status=status, cursor=cursor, limit=limit
        )

    async def get_tournament(self, tournament_id: int) -> Tournament | None:
        return await self._provider.get_tournament(tournament_id)

    async def get_tournament_field(
        self, tournament_id: int
    ) -> list[TournamentEntry]:
        return await self._provider.get_tournament_field(tournament_id)

    async def get_current_tournament(self) -> Tournament | None:
        """Return the in-progress tournament if one exists, else the next
        upcoming. This is the dashboard's headline event.
        """
        in_progress = await self._provider.list_tournaments(
            status=TournamentStatus.IN_PROGRESS, limit=1
        )
        if in_progress.items:
            return in_progress.items[0]

        upcoming = await self._provider.list_tournaments(
            status=TournamentStatus.UPCOMING, limit=200
        )
        # Closest by start date
        upcoming_sorted = sorted(upcoming.items, key=lambda t: t.start_date)
        return upcoming_sorted[0] if upcoming_sorted else None

    # --- Courses -------------------------------------------------------------

    async def list_courses(
        self, *, cursor: str | None = None, limit: int = 50
    ) -> Page[Course]:
        return await self._provider.list_courses(cursor=cursor, limit=limit)

    async def get_course(self, course_id: int) -> Course | None:
        return await self._provider.get_course(course_id)


# --- Helpers -----------------------------------------------------------------


def reference_today() -> date:
    """Return the effective "today" for prediction and simulation endpoints.

    - Mock provider: returns the fixed anchor date so the synthetic dataset
      always has an in-progress tournament relative to that date.
    - Any real provider (datagolf, …): returns the actual current UTC date.
    """
    from app.config import get_settings
    if get_settings().data_provider == "mock":
        return datetime.fromisoformat(_MOCK_REFERENCE_TODAY).date()
    return datetime.now(UTC).date()
