"""Provider-agnostic contract tests.

Any ``DataProvider`` implementation should subclass :class:`DataProviderContract`
and override :meth:`make_provider`. The test suite runs identically against
every provider, so when DataGolf access lands we point the same tests at the
DataGolfProvider with a sandbox key — if they pass, the swap is safe (doc 03 §1).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pytest

from app.domain.enums import TournamentStatus
from app.domain.models import Course, Page, Player, Round, Tournament, TournamentEntry
from app.providers.base import Capability, DataProvider


class DataProviderContract(ABC):
    """Base test class — subclass for each concrete provider."""

    @abstractmethod
    async def make_provider(self) -> DataProvider:
        """Build a fresh provider instance for one test."""

    @pytest.fixture
    async def provider(self) -> DataProvider:
        return await self.make_provider()

    # --- Identity ------------------------------------------------------------

    async def test_source_name_is_nonempty(self, provider: DataProvider) -> None:
        name = provider.get_source_name()
        assert isinstance(name, str) and name

    async def test_capabilities_is_a_set(self, provider: DataProvider) -> None:
        caps = provider.capabilities()
        assert isinstance(caps, set)
        for cap in caps:
            assert isinstance(cap, Capability)

    async def test_data_freshness_has_iso_timestamps(self, provider: DataProvider) -> None:
        freshness = await provider.get_data_freshness()
        assert isinstance(freshness.sources, dict)

    # --- Players -------------------------------------------------------------

    async def test_list_players_returns_page(self, provider: DataProvider) -> None:
        page = await provider.list_players(limit=10)
        assert isinstance(page, Page)
        assert len(page.items) <= 10
        for player in page.items:
            assert isinstance(player, Player)

    async def test_get_player_round_trip(self, provider: DataProvider) -> None:
        page = await provider.list_players(limit=1)
        assert page.items, "provider must surface at least one player"
        original = page.items[0]
        looked_up = await provider.get_player(original.id)
        assert looked_up == original

    async def test_get_player_unknown_id_returns_none(self, provider: DataProvider) -> None:
        assert await provider.get_player(player_id=-1) is None

    # --- Courses -------------------------------------------------------------

    async def test_list_courses_returns_page(self, provider: DataProvider) -> None:
        page = await provider.list_courses(limit=5)
        assert isinstance(page, Page)
        for course in page.items:
            assert isinstance(course, Course)

    async def test_get_course_round_trip(self, provider: DataProvider) -> None:
        page = await provider.list_courses(limit=1)
        assert page.items
        original = page.items[0]
        assert await provider.get_course(original.id) == original

    # --- Tournaments ---------------------------------------------------------

    async def test_list_tournaments_returns_page(self, provider: DataProvider) -> None:
        page = await provider.list_tournaments(limit=10)
        assert isinstance(page, Page)
        for t in page.items:
            assert isinstance(t, Tournament)
            assert t.start_date <= t.end_date

    async def test_list_tournaments_filters_by_season(self, provider: DataProvider) -> None:
        # Pick a season we know exists by sampling
        page = await provider.list_tournaments(limit=5)
        if not page.items:
            pytest.skip("provider has no tournaments")
        season = page.items[0].season
        filtered = await provider.list_tournaments(season=season, limit=100)
        assert all(t.season == season for t in filtered.items)

    async def test_list_tournaments_filters_by_status(self, provider: DataProvider) -> None:
        for status in TournamentStatus:
            filtered = await provider.list_tournaments(status=status, limit=100)
            assert all(t.status == status for t in filtered.items)

    async def test_get_tournament_round_trip(self, provider: DataProvider) -> None:
        page = await provider.list_tournaments(limit=1)
        assert page.items
        original = page.items[0]
        assert await provider.get_tournament(original.id) == original

    async def test_tournament_field_entries_belong_to_tournament(
        self, provider: DataProvider
    ) -> None:
        tournaments = await provider.list_tournaments(status=TournamentStatus.COMPLETED, limit=1)
        if not tournaments.items:
            pytest.skip("no completed tournaments to test field for")
        t = tournaments.items[0]
        field = await provider.get_tournament_field(t.id)
        assert field, "completed tournament must have a field"
        for entry in field:
            assert isinstance(entry, TournamentEntry)
            assert entry.tournament_id == t.id

    # --- Rounds --------------------------------------------------------------

    async def test_rounds_for_completed_tournament_are_consistent(
        self, provider: DataProvider
    ) -> None:
        tournaments = await provider.list_tournaments(status=TournamentStatus.COMPLETED, limit=1)
        if not tournaments.items:
            pytest.skip("no completed tournaments to test rounds for")
        t = tournaments.items[0]
        rounds = await provider.get_rounds(t.id)
        assert rounds
        for r in rounds:
            assert isinstance(r, Round)
            assert 1 <= r.round_number <= 4
            # SG components should sum to total within float tolerance
            assert abs((r.sg_t2g + r.sg_putt) - r.sg_total) < 0.01
            assert abs((r.sg_ott + r.sg_app + r.sg_arg) - r.sg_t2g) < 0.01

    async def test_get_rounds_for_player_respects_since(self, provider: DataProvider) -> None:
        players = await provider.list_players(limit=1)
        if not players.items:
            pytest.skip("no players")
        player = players.items[0]
        all_rounds = await provider.get_rounds_for_player(player.id, limit=200)
        if not all_rounds:
            pytest.skip(f"player {player.id} has no rounds")
        # Pick a midpoint date and verify the filter narrows the set
        sorted_rounds = sorted(
            (r for r in all_rounds if r.tee_time is not None),
            key=lambda r: r.tee_time,  # type: ignore[arg-type, return-value]
        )
        if len(sorted_rounds) < 2:
            pytest.skip("need at least two timed rounds to test since")
        cutoff = sorted_rounds[len(sorted_rounds) // 2].tee_time
        assert cutoff is not None
        filtered = await provider.get_rounds_for_player(player.id, since=cutoff.date(), limit=200)
        for r in filtered:
            assert r.tee_time is None or r.tee_time.date() >= cutoff.date()
