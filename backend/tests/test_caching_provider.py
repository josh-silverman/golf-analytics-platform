"""Unit tests for CachingProviderWrapper.

Uses a simple in-memory fake Redis (no real server required) and a stub
DataProvider that counts how many times each method is called.  The key
property being verified: the underlying provider is called exactly once on
a cache miss and zero times on subsequent cache hits within the same TTL.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.domain.models import DataFreshness, Page, Player
from app.providers.caching import CachingProviderWrapper

# ---------------------------------------------------------------------------
# Fake Redis — in-memory dict, no TTL enforcement (tests don't need it)
# ---------------------------------------------------------------------------


class FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value

    def clear(self) -> None:
        self._store.clear()


# ---------------------------------------------------------------------------
# Stub provider — records call counts
# ---------------------------------------------------------------------------


def _player(pid: int) -> Player:
    return Player(
        id=pid,
        dg_id=1000 + pid,
        full_name=f"Player {pid}",
        country="USA",
        dob=None,
        turned_pro=2010,
    )


class StubProvider:
    """Minimal DataProvider stub that tracks call counts."""

    def __init__(self) -> None:
        self.get_player_calls = 0
        self.list_players_calls = 0
        self.freshness_calls = 0

    def get_source_name(self) -> str:
        return "stub"

    def capabilities(self) -> set:
        return set()

    async def get_data_freshness(self) -> DataFreshness:
        self.freshness_calls += 1
        return DataFreshness(sources={"players": datetime.now(UTC)})

    async def list_players(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> Page[Player]:
        self.list_players_calls += 1
        return Page(items=[_player(1), _player(2)], next_cursor=None, total=2)

    async def get_player(self, player_id: int) -> Player | None:
        self.get_player_calls += 1
        return _player(player_id) if player_id < 900 else None

    # Stubs for unused abstract methods
    async def list_courses(self, **_):  # type: ignore[override]
        return Page(items=[], next_cursor=None, total=0)

    async def get_course(self, _):  # type: ignore[override]
        return None

    async def list_tournaments(self, **_):  # type: ignore[override]
        return Page(items=[], next_cursor=None, total=0)

    async def get_tournament(self, _):  # type: ignore[override]
        return None

    async def get_tournament_field(self, _):  # type: ignore[override]
        return []

    async def get_rounds(self, _):  # type: ignore[override]
        return []

    async def get_rounds_for_player(self, _, **__):  # type: ignore[override]
        return []


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def stub_provider() -> StubProvider:
    return StubProvider()


@pytest.fixture
def wrapper(stub_provider: StubProvider, fake_redis: FakeRedis) -> CachingProviderWrapper:
    return CachingProviderWrapper(stub_provider, redis=fake_redis)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCacheHit:
    async def test_get_player_cached_on_second_call(
        self, wrapper: CachingProviderWrapper, stub_provider: StubProvider
    ) -> None:
        # First call: miss → hits stub
        p1 = await wrapper.get_player(1)
        assert stub_provider.get_player_calls == 1

        # Second call: hit → stub not called again
        p2 = await wrapper.get_player(1)
        assert stub_provider.get_player_calls == 1

        assert p1 is not None
        assert p2 is not None
        assert p1.id == p2.id == 1

    async def test_list_players_cached(
        self, wrapper: CachingProviderWrapper, stub_provider: StubProvider
    ) -> None:
        page1 = await wrapper.list_players(limit=50)
        page2 = await wrapper.list_players(limit=50)
        assert stub_provider.list_players_calls == 1
        assert page1.total == page2.total == 2

    async def test_freshness_cached(
        self, wrapper: CachingProviderWrapper, stub_provider: StubProvider
    ) -> None:
        await wrapper.get_data_freshness()
        await wrapper.get_data_freshness()
        assert stub_provider.freshness_calls == 1


class TestCacheMiss:
    async def test_different_player_ids_are_separate_keys(
        self, wrapper: CachingProviderWrapper, stub_provider: StubProvider
    ) -> None:
        await wrapper.get_player(1)
        await wrapper.get_player(2)
        # Each unique player_id is a separate cache key → 2 calls to stub
        assert stub_provider.get_player_calls == 2

    async def test_different_page_sizes_are_separate_keys(
        self, wrapper: CachingProviderWrapper, stub_provider: StubProvider
    ) -> None:
        await wrapper.list_players(limit=10)
        await wrapper.list_players(limit=50)
        assert stub_provider.list_players_calls == 2

    async def test_cache_cleared_forces_new_fetch(
        self,
        wrapper: CachingProviderWrapper,
        stub_provider: StubProvider,
        fake_redis: FakeRedis,
    ) -> None:
        await wrapper.get_player(1)
        assert stub_provider.get_player_calls == 1

        fake_redis.clear()

        await wrapper.get_player(1)
        assert stub_provider.get_player_calls == 2


class TestNoneHandling:
    async def test_not_found_player_cached_as_null(
        self, wrapper: CachingProviderWrapper, stub_provider: StubProvider
    ) -> None:
        # player_id >= 900 → stub returns None
        p = await wrapper.get_player(999)
        assert p is None

        p2 = await wrapper.get_player(999)
        assert p2 is None
        # stub still only called once — None is cached
        assert stub_provider.get_player_calls == 1


class TestIdentityDelegation:
    def test_source_name_delegates(
        self, wrapper: CachingProviderWrapper, stub_provider: StubProvider
    ) -> None:
        assert wrapper.get_source_name() == "stub"

    def test_capabilities_delegates(
        self, wrapper: CachingProviderWrapper, stub_provider: StubProvider
    ) -> None:
        assert wrapper.capabilities() == stub_provider.capabilities()


class TestKeyNamespacing:
    async def test_keys_are_namespaced_by_source(
        self, wrapper: CachingProviderWrapper, fake_redis: FakeRedis
    ) -> None:
        await wrapper.get_player(1)
        # All keys should start with the source name
        for key in fake_redis._store:
            assert key.startswith("pga:stub:")
