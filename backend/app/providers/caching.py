"""Redis-backed ``CachingProviderWrapper`` — composition over inheritance.

Wraps any ``DataProvider`` and caches its results in Redis with per-method
TTLs.  The wrapper is transparent: callers interact with the same
``DataProvider`` interface and never know caching is involved.

TTL strategy (doc 03 §2):
  - Players / Courses: 24 h  — roster changes are rare
  - Tournaments: 6 h          — schedule may shift; status updates
  - Tournament field: 15 min  — withdrawals / late entries during event week
  - Rounds: 1 h               — completed round data is immutable once posted
  - Data freshness: 5 min     — lightweight heartbeat

Cache keys are namespaced by source name so the mock and DataGolf providers
can coexist in development without collisions:

    pga:{source}:{method}:{args_hash}

The wrapper serialises domain objects to JSON via Pydantic's ``model_dump``
and deserialises with ``model_validate``.  This means any change to the
domain model schema will automatically invalidate all cached entries once
the old TTL expires — no manual cache-busting required.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, TypeVar

from app.domain.models import (
    Course,
    DataFreshness,
    Page,
    Player,
    Round,
    Tournament,
    TournamentEntry,
)
from app.providers.base import Capability, DataProvider

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import date

    from redis.asyncio import Redis

    from app.domain.enums import TournamentStatus
    from app.domain.models import BettingLine

_T = TypeVar("_T")

# TTLs in seconds
_TTL = {
    "players": 86_400,       # 24 h
    "courses": 86_400,       # 24 h
    "tournaments": 21_600,   # 6 h
    "field": 900,            # 15 min
    "rounds": 3_600,         # 1 h
    "freshness": 300,        # 5 min
    "betting": 300,          # 5 min — odds move
}


def _key(source: str, method: str, *parts: object) -> str:
    """Build a namespaced, deterministic Redis key."""
    raw = ":".join(str(p) for p in parts) if parts else ""
    digest = hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()[:8]  # noqa: S324
    return f"pga:{source}:{method}:{digest}"


class CachingProviderWrapper(DataProvider):
    """Decorates any ``DataProvider`` with Redis caching.

    Usage::

        from app.providers.caching import CachingProviderWrapper
        provider = CachingProviderWrapper(raw_provider, redis=redis_client)

    The wrapper passes every cache miss through to the underlying provider
    and stores the result.  A cache hit short-circuits the underlying call
    entirely, so no HTTP requests (for DataGolf) or generator work (for mock)
    are repeated within the TTL window.
    """

    def __init__(self, provider: DataProvider, *, redis: Redis) -> None:
        self._provider = provider
        self._redis = redis

    # ------------------------------------------------------------------
    # Identity — delegate; never cache these
    # ------------------------------------------------------------------

    def get_source_name(self) -> str:
        return self._provider.get_source_name()

    def capabilities(self) -> set[Capability]:
        return self._provider.capabilities()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_or_set(
        self,
        key: str,
        ttl: int,
        call: Callable[[], Awaitable[_T]],
        cls: type[_T],
    ) -> _T:
        cached = await self._redis.get(key)
        if cached is not None:
            return cls.model_validate(json.loads(cached))  # type: ignore[attr-defined, no-any-return]
        result = await call()
        await self._redis.setex(
            key, ttl, json.dumps(result.model_dump(), default=str)  # type: ignore[attr-defined]
        )
        return result

    async def _get_or_set_list(
        self,
        key: str,
        ttl: int,
        call: Callable[[], Awaitable[list[_T]]],
        cls: type[_T],
    ) -> list[_T]:
        cached = await self._redis.get(key)
        if cached is not None:
            return [cls.model_validate(item) for item in json.loads(cached)]  # type: ignore[attr-defined]
        result = await call()
        payload = [item.model_dump() for item in result]  # type: ignore[attr-defined]
        await self._redis.setex(key, ttl, json.dumps(payload, default=str))
        return result

    async def _get_or_set_page(
        self,
        key: str,
        ttl: int,
        call: Callable[[], Awaitable[Page[_T]]],
        item_cls: type[_T],
    ) -> Page[_T]:
        cached = await self._redis.get(key)
        if cached is not None:
            raw = json.loads(cached)
            return Page(
                items=[item_cls.model_validate(i) for i in raw["items"]],  # type: ignore[attr-defined]
                next_cursor=raw["next_cursor"],
                total=raw["total"],
            )
        page = await call()
        payload: dict[str, Any] = {
            "items": [item.model_dump() for item in page.items],  # type: ignore[attr-defined]
            "next_cursor": page.next_cursor,
            "total": page.total,
        }
        await self._redis.setex(key, ttl, json.dumps(payload, default=str))
        return page

    # ------------------------------------------------------------------
    # DataFreshness
    # ------------------------------------------------------------------

    async def get_data_freshness(self) -> DataFreshness:
        key = _key(self.get_source_name(), "freshness")
        return await self._get_or_set(
            key, _TTL["freshness"],
            self._provider.get_data_freshness,
            DataFreshness,
        )

    # ------------------------------------------------------------------
    # Players
    # ------------------------------------------------------------------

    async def list_players(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> Page[Player]:
        key = _key(self.get_source_name(), "list_players", cursor, limit)
        return await self._get_or_set_page(
            key, _TTL["players"],
            lambda: self._provider.list_players(cursor=cursor, limit=limit),
            Player,
        )

    async def get_player(self, player_id: int) -> Player | None:
        key = _key(self.get_source_name(), "player", player_id)
        cached = await self._redis.get(key)
        if cached is not None:
            raw = json.loads(cached)
            return Player.model_validate(raw) if raw is not None else None
        result = await self._provider.get_player(player_id)
        payload = result.model_dump() if result is not None else None
        await self._redis.setex(key, _TTL["players"], json.dumps(payload, default=str))
        return result

    # ------------------------------------------------------------------
    # Courses
    # ------------------------------------------------------------------

    async def list_courses(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> Page[Course]:
        key = _key(self.get_source_name(), "list_courses", cursor, limit)
        return await self._get_or_set_page(
            key, _TTL["courses"],
            lambda: self._provider.list_courses(cursor=cursor, limit=limit),
            Course,
        )

    async def get_course(self, course_id: int) -> Course | None:
        key = _key(self.get_source_name(), "course", course_id)
        cached = await self._redis.get(key)
        if cached is not None:
            raw = json.loads(cached)
            return Course.model_validate(raw) if raw is not None else None
        result = await self._provider.get_course(course_id)
        payload = result.model_dump() if result is not None else None
        await self._redis.setex(key, _TTL["courses"], json.dumps(payload, default=str))
        return result

    # ------------------------------------------------------------------
    # Tournaments
    # ------------------------------------------------------------------

    async def list_tournaments(
        self,
        *,
        season: int | None = None,
        status: TournamentStatus | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> Page[Tournament]:
        key = _key(self.get_source_name(), "list_tournaments", season, status, cursor, limit)
        return await self._get_or_set_page(
            key, _TTL["tournaments"],
            lambda: self._provider.list_tournaments(
                season=season, status=status, cursor=cursor, limit=limit
            ),
            Tournament,
        )

    async def get_tournament(self, tournament_id: int) -> Tournament | None:
        key = _key(self.get_source_name(), "tournament", tournament_id)
        cached = await self._redis.get(key)
        if cached is not None:
            raw = json.loads(cached)
            return Tournament.model_validate(raw) if raw is not None else None
        result = await self._provider.get_tournament(tournament_id)
        payload = result.model_dump() if result is not None else None
        await self._redis.setex(key, _TTL["tournaments"], json.dumps(payload, default=str))
        return result

    async def get_tournament_field(self, tournament_id: int) -> list[TournamentEntry]:
        key = _key(self.get_source_name(), "field", tournament_id)
        return await self._get_or_set_list(
            key, _TTL["field"],
            lambda: self._provider.get_tournament_field(tournament_id),
            TournamentEntry,
        )

    # ------------------------------------------------------------------
    # Rounds
    # ------------------------------------------------------------------

    async def get_rounds(self, tournament_id: int) -> list[Round]:
        key = _key(self.get_source_name(), "rounds", tournament_id)
        return await self._get_or_set_list(
            key, _TTL["rounds"],
            lambda: self._provider.get_rounds(tournament_id),
            Round,
        )

    async def get_rounds_for_player(
        self,
        player_id: int,
        *,
        since: date | None = None,
        limit: int = 100,
    ) -> list[Round]:
        key = _key(self.get_source_name(), "player_rounds", player_id, since, limit)
        return await self._get_or_set_list(
            key, _TTL["rounds"],
            lambda: self._provider.get_rounds_for_player(
                player_id, since=since, limit=limit
            ),
            Round,
        )

    # ------------------------------------------------------------------
    # Optional capabilities — delegate; skip cache for betting lines
    # (odds move frequently and the 5-min TTL is enforced inside)
    # ------------------------------------------------------------------

    async def get_betting_lines(self, tournament_id: int) -> list[BettingLine]:
        from app.domain.models import BettingLine as BettingLineDomain

        key = _key(self.get_source_name(), "betting", tournament_id)
        return await self._get_or_set_list(
            key, _TTL["betting"],
            lambda: self._provider.get_betting_lines(tournament_id),
            BettingLineDomain,
        )
