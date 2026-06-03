"""Run the provider-agnostic contract suite against ``MockDataProvider``.

When DataGolf access lands, the same suite will be parametrized against
``DataGolfProvider`` with a sandbox key (doc 03 §1). A green sweep there
is what proves the swap is safe.

The contract suite touches the dataset on every test, so we share one
provider instance across the class via ``__init__``-style lazy loading
on the provider itself (its first method call triggers generation).
"""

from __future__ import annotations

import pytest

from app.providers.base import Capability, DataProvider
from app.providers.mock.mock_provider import MockDataProvider
from tests.contract.base import DataProviderContract

# The mock generator runs ~50s for its full 5-season dataset. The contract
# suite isn't part of the fast PR lane.
pytestmark = pytest.mark.slow


class TestMockProvider(DataProviderContract):
    """Subclass binds ``DataProviderContract`` to the mock implementation."""

    _provider: MockDataProvider | None = None

    async def make_provider(self) -> DataProvider:
        # Share one provider (and one underlying dataset) across the whole
        # test class to amortize the ~50s generation cost.
        if type(self)._provider is None:
            type(self)._provider = MockDataProvider(seed=42)
        return type(self)._provider


# --- Mock-specific smoke tests outside the abstract contract ---------------


class TestMockProviderSmoke:
    @pytest.fixture(scope="class")
    def provider(self) -> MockDataProvider:
        return MockDataProvider(seed=42)

    async def test_capabilities_include_betting_lines(self, provider: MockDataProvider) -> None:
        assert Capability.BETTING_LINES in provider.capabilities()

    async def test_data_freshness_sources_keys(self, provider: MockDataProvider) -> None:
        f = await provider.get_data_freshness()
        assert {"players", "courses", "tournaments", "rounds", "betting_lines"} <= set(
            f.sources.keys()
        )

    async def test_list_players_pagination_round_trip(self, provider: MockDataProvider) -> None:
        page = await provider.list_players(limit=50)
        assert len(page.items) == 50
        assert page.next_cursor is not None
        assert page.total == 250

        next_page = await provider.list_players(cursor=page.next_cursor, limit=50)
        assert len(next_page.items) == 50
        # No overlap between pages
        first_ids = {p.id for p in page.items}
        second_ids = {p.id for p in next_page.items}
        assert first_ids.isdisjoint(second_ids)

    async def test_list_tournaments_filter_by_status_and_season(
        self, provider: MockDataProvider
    ) -> None:
        from app.domain.enums import TournamentStatus

        completed = await provider.list_tournaments(
            season=2024, status=TournamentStatus.COMPLETED, limit=100
        )
        for t in completed.items:
            assert t.season == 2024
            assert t.status == TournamentStatus.COMPLETED

    async def test_betting_lines_only_for_live_markets(self, provider: MockDataProvider) -> None:
        from app.domain.enums import TournamentStatus

        upcoming = await provider.list_tournaments(status=TournamentStatus.UPCOMING, limit=5)
        if not upcoming.items:
            pytest.skip("no upcoming tournaments")
        lines = await provider.get_betting_lines(upcoming.items[0].id)
        assert lines, "upcoming tournament should have betting lines"
