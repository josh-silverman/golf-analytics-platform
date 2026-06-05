"""DataGolf data provider — Phase 5 integration.

DataGolf API docs: https://datagolf.com/api-access
All endpoints require ``?key=<DATAGOLF_API_KEY>``.

Selected endpoints used here:
  GET /get-player-list          — full player registry, updates weekly
  GET /historical-raw-data/rounds?tour=pga  — round-level SG for completed events
  GET /field-updates            — current tournament field (live)
  GET /preds/get-projections    — pre-tournament ML projections
  GET /preds/live-tournament-stats  — live scoring + SG

All responses are JSON; pagination is absent — DataGolf returns complete
datasets.  We cache at the ``CatalogService`` layer so individual rounds
are not re-fetched on every request.

Phase 5 checklist (in priority order):
  [x] Skeleton structure so factory.py imports cleanly
  [ ] Implement get_player(), list_players() from /get-player-list
  [ ] Implement get_rounds_for_player() from /historical-raw-data/rounds
  [ ] Implement get_tournament_field() from /field-updates
  [ ] Add LIVE_DATA to capabilities() once live endpoints are wired
  [ ] Map DataGolf's "dg_id" → Player.dg_id for cross-referencing
  [ ] Cache player list + rounds in Redis (TTL = 15 min for live, 24 h for historical)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx  # type: ignore[import-not-found]  # not in prod deps until Phase 5

from app.config import get_settings
from app.domain.models import DataFreshness, Page
from app.providers.base import Capability, DataProvider

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

_BASE_URL = "https://feeds.datagolf.com"


class DataGolfProvider(DataProvider):
    """Live DataGolf data provider.

    Requires ``DATAGOLF_API_KEY`` in settings.  Set ``DATA_PROVIDER=datagolf``
    to activate; falls back to MockDataProvider when the key is absent.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._api_key = self._settings.datagolf_api_key
        if not self._api_key:
            raise RuntimeError(
                "DATA_PROVIDER=datagolf requires DATAGOLF_API_KEY to be set. "
                "Run: fly secrets set DATAGOLF_API_KEY=<your-key>"
            )
        # Shared async client — reused across requests for connection pooling.
        # Closed at application shutdown via lifespan hook.
        self._client = httpx.AsyncClient(
            base_url=_BASE_URL,
            params={"file_format": "json", "key": self._api_key},
            timeout=15.0,
        )

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    def get_source_name(self) -> str:
        return "datagolf"

    def capabilities(self) -> set[Capability]:
        return {
            Capability.SKILL_RATINGS,
            Capability.HISTORICAL_ODDS,
            Capability.BETTING_LINES,
            # Capability.LIVE_DATA,  # uncomment once live endpoints are wired
        }

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    async def get_data_freshness(self) -> DataFreshness:
        # DataGolf publishes "last updated" in most feed responses.
        # For now, report the current time so freshness checks don't block.
        now = datetime.now(UTC)
        return DataFreshness(
            sources={
                "players": now,
                "courses": now,
                "tournaments": now,
                "rounds": now,
                "betting_lines": now,
            }
        )

    # ------------------------------------------------------------------
    # Players  —  GET /get-player-list
    # ------------------------------------------------------------------

    async def list_players(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> Page[Player]:
        """Phase 5: fetch from /get-player-list and map to Player domain model.

        DataGolf player schema::

            {"dg_id": 18417, "player_name": "Rory McIlroy", "country": "IRL", ...}

        Mapping:
          dg_id       → Player.dg_id and Player.id (use dg_id as our PK)
          player_name → Player.full_name
          country     → Player.country (ISO 3-letter code from DataGolf)
        """
        raise NotImplementedError("Phase 5: implement /get-player-list mapping")

    async def get_player(self, player_id: int) -> Player | None:
        """Phase 5: look up by dg_id from the cached player list."""
        raise NotImplementedError("Phase 5: implement single-player lookup")

    # ------------------------------------------------------------------
    # Courses — DataGolf doesn't expose a course endpoint; derive from rounds
    # ------------------------------------------------------------------

    async def list_courses(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> Page[Course]:
        raise NotImplementedError("Phase 5: derive courses from tournament schedule")

    async def get_course(self, course_id: int) -> Course | None:
        raise NotImplementedError("Phase 5: derive course from tournament schedule")

    # ------------------------------------------------------------------
    # Tournaments  —  GET /get-schedule?tour=pga
    # ------------------------------------------------------------------

    async def list_tournaments(
        self,
        *,
        season: int | None = None,
        status: TournamentStatus | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> Page[Tournament]:
        """Phase 5: fetch from /get-schedule and map to Tournament domain model.

        DataGolf schedule schema::

            {"event_id": 28, "event_name": "The Masters", "date": "2026-04-10",
             "course": "Augusta National", "purse": 18000000, ...}
        """
        raise NotImplementedError("Phase 5: implement /get-schedule mapping")

    async def get_tournament(self, tournament_id: int) -> Tournament | None:
        raise NotImplementedError("Phase 5: implement single-tournament lookup")

    async def get_tournament_field(self, tournament_id: int) -> list[TournamentEntry]:
        """Phase 5: fetch from /field-updates for live field; /historical for past events."""
        raise NotImplementedError("Phase 5: implement /field-updates mapping")

    # ------------------------------------------------------------------
    # Rounds  —  GET /historical-raw-data/rounds?tour=pga
    # ------------------------------------------------------------------

    async def get_rounds(self, tournament_id: int) -> list[Round]:
        """Phase 5: filter /historical-raw-data/rounds by event_id.

        DataGolf round schema::

            {"dg_id": 18417, "event_id": 28, "round_num": 1,
             "sg_ott": 0.8, "sg_app": 1.2, "sg_arg": -0.3,
             "sg_putt": 0.5, "sg_t2g": 1.7, "sg_total": 2.2,
             "score": 66, "score_to_par": -6}
        """
        raise NotImplementedError("Phase 5: implement /historical-raw-data/rounds mapping")

    async def get_rounds_for_player(
        self,
        player_id: int,
        *,
        since: date | None = None,
        limit: int = 100,
    ) -> list[Round]:
        """Phase 5: filter /historical-raw-data/rounds by dg_id + date range."""
        raise NotImplementedError("Phase 5: implement player rounds lookup")
