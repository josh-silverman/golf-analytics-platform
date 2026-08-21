"""Unit tests for CachingProviderWrapper.

Uses a simple in-memory fake Redis (no real server required) and a stub
DataProvider that counts how many times each method is called.  The key
property being verified: the underlying provider is called exactly once on
a cache miss and zero times on subsequent cache hits within the same TTL.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.domain.enums import DgFetchStatus
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
        self.full_preds_calls = 0
        self.full_preds_status_calls = 0
        self.preds_calls = 0
        self.live_matchups_calls = 0
        self.hist_event_list_calls = 0
        self.hist_matchups_calls = 0

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

    async def get_pretournament_preds(
        self, event_id: int, year: int, *, live: bool = False
    ) -> dict[int, dict[str, float]]:
        self.preds_calls += 1
        return {1: {"make_cut": 0.7, "top_20": 0.3}}

    async def get_pretournament_full_preds(
        self, event_id: int, year: int, *, live: bool = False
    ) -> dict[int, dict[str, float]]:
        self.full_preds_calls += 1
        return {1: {"win": 0.05, "top_5": 0.2, "top_10": 0.3, "top_20": 0.5, "make_cut": 0.8}}

    async def get_pretournament_full_preds_with_status(
        self, event_id: int, year: int, *, live: bool = False
    ) -> tuple[dict[int, dict[str, float]], DgFetchStatus]:
        # Deliberately reports a *failure with no data*, the one answer the
        # base class's inference can never produce.
        self.full_preds_status_calls += 1
        return {}, DgFetchStatus.FETCH_FAILED

    # DataGolf-only methods, not on the base DataProvider — present here purely
    # so the pass-through pin below can call them through the wrapper.
    async def fetch_live_matchups(self, market: str = "tournament_matchups") -> dict:
        self.live_matchups_calls += 1
        return {"event_name": "Stub Open", "match_list": []}

    async def fetch_historical_matchup_event_list(self) -> list[dict]:
        self.hist_event_list_calls += 1
        return [{"event_id": 1, "calendar_year": 2026}]

    async def fetch_historical_matchups(self, event_id: int, year: int, book: str) -> dict:
        self.hist_matchups_calls += 1
        return {"event_completed": True, "book": book}


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


class TestPretournamentPredsPassThrough:
    """Path A serving reads DataGolf's probabilities through this wrapper.

    A missing override here does not fail loudly — it silently falls through to
    ``DataProvider``'s base default of ``{}``, which cold-starts every player to
    the SG-only model. That shipped to production once and was only caught by
    grading the 3M Open after the fact (DataGolf's make-cut skill +0.127 vs the
    bug-served board's +0.007), so both methods are pinned here.
    """

    async def test_full_preds_reach_the_underlying_provider(
        self, wrapper: CachingProviderWrapper, stub_provider: StubProvider
    ) -> None:
        result = await wrapper.get_pretournament_full_preds(123, 2026)
        assert stub_provider.full_preds_calls == 1
        # Must be the provider's real five-market payload, not an empty dict.
        assert result[1]["win"] == 0.05
        assert set(result[1]) == {"win", "top_5", "top_10", "top_20", "make_cut"}

    async def test_preds_reach_the_underlying_provider(
        self, wrapper: CachingProviderWrapper, stub_provider: StubProvider
    ) -> None:
        result = await wrapper.get_pretournament_preds(123, 2026)
        assert stub_provider.preds_calls == 1
        assert result[1]["make_cut"] == 0.7

    async def test_live_flag_is_forwarded(
        self, wrapper: CachingProviderWrapper, stub_provider: StubProvider
    ) -> None:
        captured: dict[str, bool] = {}

        async def spy(
            event_id: int, year: int, *, live: bool = False
        ) -> dict[int, dict[str, float]]:
            captured["live"] = live
            return {}

        stub_provider.get_pretournament_full_preds = spy  # type: ignore[assignment]
        await wrapper.get_pretournament_full_preds(123, 2026, live=True)
        assert captured["live"] is True

    async def test_fetch_status_reaches_the_underlying_provider(
        self, wrapper: CachingProviderWrapper, stub_provider: StubProvider
    ) -> None:
        """Inheriting the base default here would be silent and wrong.

        ``DataProvider``'s default infers the status from the plain preds
        call, so it can only ever answer OK or NO_COVERAGE. A wrapper that
        inherited it would relabel every real fetch failure as "DataGolf has
        no coverage" — and the board carrying that wrong label is pinned
        permanently by first-write-wins, which is the whole reason the status
        exists.
        """
        preds, status = await wrapper.get_pretournament_full_preds_with_status(123, 2026)
        assert stub_provider.full_preds_status_calls == 1
        assert preds == {}
        assert status is DgFetchStatus.FETCH_FAILED  # never NO_COVERAGE


class TestMatchupMethodsPassThrough:
    """The matchup capture/grading endpoints feature-detect these three
    DataGolf-only methods with ``hasattr`` on whatever ``get_data_provider``
    returns. In production that's this wrapper, not the raw provider — the
    same silent-gap shape as ``TestPretournamentPredsPassThrough`` above: a
    missing override doesn't raise, it just makes ``hasattr`` return ``False``,
    so the capture endpoint 409s and the line-record endpoint reports
    ``available: False`` forever despite the feature being fully deployed.
    """

    async def test_live_matchups_reach_the_underlying_provider(
        self, wrapper: CachingProviderWrapper, stub_provider: StubProvider
    ) -> None:
        assert hasattr(wrapper, "fetch_live_matchups")
        result = await wrapper.fetch_live_matchups()  # type: ignore[attr-defined]
        assert stub_provider.live_matchups_calls == 1
        assert result["event_name"] == "Stub Open"

    async def test_historical_event_list_reaches_the_underlying_provider(
        self, wrapper: CachingProviderWrapper, stub_provider: StubProvider
    ) -> None:
        assert hasattr(wrapper, "fetch_historical_matchup_event_list")
        result = await wrapper.fetch_historical_matchup_event_list()  # type: ignore[attr-defined]
        assert stub_provider.hist_event_list_calls == 1
        assert result == [{"event_id": 1, "calendar_year": 2026}]

    async def test_historical_matchups_reaches_the_underlying_provider(
        self, wrapper: CachingProviderWrapper, stub_provider: StubProvider
    ) -> None:
        assert hasattr(wrapper, "fetch_historical_matchups")
        result = await wrapper.fetch_historical_matchups(1, 2026, "pinnacle")  # type: ignore[attr-defined]
        assert stub_provider.hist_matchups_calls == 1
        assert result == {"event_completed": True, "book": "pinnacle"}
