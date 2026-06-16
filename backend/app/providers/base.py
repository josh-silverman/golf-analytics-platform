"""The ``DataProvider`` interface — the architectural keystone.

Every other layer (services, repositories, ingestion, API routes) depends on
this interface, never on a concrete implementation. Implementations live in
sibling modules (``app.providers.mock``, eventually ``app.providers.datagolf``)
and are swapped via :func:`app.providers.factory.get_data_provider`.

See ``docs/architecture/02-technical-core.md`` §5 for the rationale.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date

    from app.domain.enums import TournamentStatus
    from app.domain.models import (
        BettingLine,
        Course,
        DataFreshness,
        OutrightOdds,
        Page,
        Player,
        PlayerSkillSnapshot,
        Round,
        Tournament,
        TournamentEntry,
    )


class Capability(StrEnum):
    """Optional features a provider may declare. The mock provider supports
    ``BETTING_LINES``; DataGolf will add ``HISTORICAL_ODDS`` and ``LIVE_DATA``.
    """

    SHOT_LEVEL_DATA = "shot_level_data"
    LIVE_DATA = "live_data"
    HISTORICAL_ODDS = "historical_odds"
    BETTING_LINES = "betting_lines"
    DFS_DATA = "dfs_data"
    SKILL_RATINGS = "skill_ratings"


class DataProvider(ABC):
    """Single source of truth for golf data access.

    All methods that fetch over a network are async — even the mock provider,
    which uses ``await asyncio.sleep(0)`` style yields, so swapping in DataGolf
    later is a class substitution, not an interface change.
    """

    # --- Identity & metadata -------------------------------------------------

    @abstractmethod
    def get_source_name(self) -> str:
        """Stable identifier (``"mock"``, ``"datagolf"``) used in metrics, cache
        keys, and the ``meta.source`` field on API responses.
        """

    @abstractmethod
    def capabilities(self) -> set[Capability]:
        """Optional features this provider supports. Callers should branch on
        this rather than catching ``NotImplementedError``.
        """

    @abstractmethod
    async def get_data_freshness(self) -> DataFreshness:
        """Per-resource last sync timestamps. Surfaced at
        ``/api/v1/meta/data-freshness``.
        """

    # --- Players -------------------------------------------------------------

    @abstractmethod
    async def list_players(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> Page[Player]:
        """Paginated player list."""

    @abstractmethod
    async def get_player(self, player_id: int) -> Player | None: ...

    # --- Courses -------------------------------------------------------------

    @abstractmethod
    async def list_courses(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> Page[Course]: ...

    @abstractmethod
    async def get_course(self, course_id: int) -> Course | None: ...

    # --- Tournaments ---------------------------------------------------------

    @abstractmethod
    async def list_tournaments(
        self,
        *,
        season: int | None = None,
        status: TournamentStatus | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> Page[Tournament]: ...

    @abstractmethod
    async def get_tournament(self, tournament_id: int) -> Tournament | None: ...

    @abstractmethod
    async def get_tournament_field(self, tournament_id: int) -> list[TournamentEntry]: ...

    # --- Rounds (the granular unit per doc 03 §1) ----------------------------

    @abstractmethod
    async def get_rounds(self, tournament_id: int) -> list[Round]: ...

    @abstractmethod
    async def get_rounds_for_player(
        self,
        player_id: int,
        *,
        since: date | None = None,
        limit: int = 100,
    ) -> list[Round]: ...

    # --- Optional capabilities ----------------------------------------------

    async def get_betting_lines(self, tournament_id: int) -> list[BettingLine]:
        """Default raises; override if the provider declares
        :attr:`Capability.BETTING_LINES`.
        """
        raise NotImplementedError(
            f"{self.get_source_name()} does not support betting lines",
        )

    async def get_skill_snapshots(
        self,
        player_id: int,
        *,
        as_of: date | None = None,
    ) -> list[PlayerSkillSnapshot]:
        """Default raises; override if the provider declares
        :attr:`Capability.SKILL_RATINGS`.
        """
        raise NotImplementedError(
            f"{self.get_source_name()} does not surface skill snapshots",
        )

    async def get_outright_odds(self, market: str) -> OutrightOdds | None:
        """Real sportsbook outright odds for the current event's field.

        ``market`` is an outcome key (``"win_prob"``, ``"top_5_prob"`` …).
        Returns ``None`` when the provider has no live odds feed — the betting
        service then falls back to synthetic lines. Override if the provider
        declares :attr:`Capability.BETTING_LINES` with live data.
        """
        return None
