"""Tests for the FeatureExtractor service.

Uses a hand-rolled in-memory DataProvider stub so the test runs in
milliseconds and the round set is fully controlled by the test author.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest

from app.domain.models import DataFreshness, Page, Round
from app.features.feature_sets import v1_baseline
from app.providers.base import Capability, DataProvider
from app.services.features import FeatureExtractor

if TYPE_CHECKING:
    from app.domain.enums import TournamentStatus
    from app.domain.models import (
        Course,
        Player,
        Tournament,
        TournamentEntry,
    )


def _round(
    *,
    rid: int,
    tee_time: datetime | None,
    sg_total: float = 1.0,
    sg_ott: float = 0.25,
    sg_app: float = 0.25,
    sg_arg: float = 0.25,
    sg_putt: float = 0.25,
) -> Round:
    return Round(
        id=rid,
        entry_id=rid,
        round_number=1,
        score=70,
        score_to_par=-2,
        tee_time=tee_time,
        sg_ott=sg_ott,
        sg_app=sg_app,
        sg_arg=sg_arg,
        sg_putt=sg_putt,
        sg_t2g=sg_ott + sg_app + sg_arg,
        sg_total=sg_total,
    )


class _StubProvider(DataProvider):
    """Minimal provider that only implements ``get_rounds_for_player``.

    Other abstract methods raise — the extractor doesn't touch them, and a
    test that hits one is a bug in the extractor.
    """

    def __init__(self, rounds: list[Round]) -> None:
        self._rounds = rounds
        self.calls: list[tuple[int, int]] = []

    def get_source_name(self) -> str:
        return "stub"

    def capabilities(self) -> set[Capability]:
        return set()

    async def get_data_freshness(self) -> DataFreshness:
        return DataFreshness(sources={})

    async def list_players(
        self, *, cursor: str | None = None, limit: int = 100
    ) -> Page[Player]:
        raise NotImplementedError

    async def get_player(self, player_id: int) -> Player | None:
        raise NotImplementedError

    async def list_courses(
        self, *, cursor: str | None = None, limit: int = 100
    ) -> Page[Course]:
        raise NotImplementedError

    async def get_course(self, course_id: int) -> Course | None:
        raise NotImplementedError

    async def list_tournaments(
        self,
        *,
        season: int | None = None,
        status: TournamentStatus | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> Page[Tournament]:
        raise NotImplementedError

    async def get_tournament(self, tournament_id: int) -> Tournament | None:
        raise NotImplementedError

    async def get_tournament_field(self, tournament_id: int) -> list[TournamentEntry]:
        raise NotImplementedError

    async def get_rounds(self, tournament_id: int) -> list[Round]:
        raise NotImplementedError

    async def get_rounds_for_player(
        self,
        player_id: int,
        *,
        since: date | None = None,
        limit: int = 100,
    ) -> list[Round]:
        self.calls.append((player_id, limit))
        return list(self._rounds)


async def test_extractor_returns_empty_features_for_player_with_no_rounds() -> None:
    extractor = FeatureExtractor(_StubProvider(rounds=[]))
    result = await extractor.extract(player_id=42, as_of=date(2026, 6, 1))
    assert result.n_rounds == 0
    # All v1 features defined → returned, even with no data.
    assert set(result.values.keys()) == {f.name for f in v1_baseline().features}
    # Empty rounds → all features return 0.0.
    assert all(v == 0.0 for v in result.values.values())


async def test_extractor_records_provenance() -> None:
    extractor = FeatureExtractor(_StubProvider(rounds=[]))
    result = await extractor.extract(player_id=7, as_of=date(2026, 6, 1))
    fs = v1_baseline()
    assert result.player_id == 7
    assert result.as_of == date(2026, 6, 1)
    assert result.feature_set_name == fs.name
    assert result.feature_set_hash == fs.hash


async def test_extractor_filters_rounds_after_as_of() -> None:
    """Rounds whose tee time is AFTER as_of must not influence features —
    that prevents data leakage in training."""
    rounds = [
        _round(rid=1, tee_time=datetime(2026, 5, 1, 12, 0, tzinfo=UTC), sg_total=2.0),
        # This round is after as_of=2026-06-01 and must be filtered out.
        _round(rid=2, tee_time=datetime(2026, 7, 1, 12, 0, tzinfo=UTC), sg_total=10.0),
    ]
    extractor = FeatureExtractor(_StubProvider(rounds=rounds))
    result = await extractor.extract(player_id=1, as_of=date(2026, 6, 1))
    assert result.n_rounds == 1
    # If the post-as_of round leaked in, sg_total_rating would be ~6.0.
    # Just the May round → sg_total_rating ≈ 2.0.
    assert result.values["sg_total_rating"] == pytest.approx(2.0)


async def test_extractor_skips_rounds_without_tee_time() -> None:
    rounds = [
        _round(rid=1, tee_time=datetime(2026, 5, 1, 12, 0, tzinfo=UTC), sg_total=1.0),
        _round(rid=2, tee_time=None, sg_total=999.0),
    ]
    extractor = FeatureExtractor(_StubProvider(rounds=rounds))
    result = await extractor.extract(player_id=1, as_of=date(2026, 6, 1))
    assert result.n_rounds == 1
    assert result.values["sg_total_rating"] == pytest.approx(1.0)


async def test_extractor_runs_full_v1_baseline_end_to_end() -> None:
    """One real-looking round → expect specific SG-category values back."""
    r = _round(
        rid=1,
        tee_time=datetime(2026, 5, 25, 12, 0, tzinfo=UTC),
        sg_ott=1.1,
        sg_app=1.2,
        sg_arg=0.3,
        sg_putt=0.4,
        sg_total=3.0,
    )
    extractor = FeatureExtractor(_StubProvider(rounds=[r]))
    result = await extractor.extract(player_id=1, as_of=date(2026, 6, 1))
    assert result.values["sg_ott_rating"] == pytest.approx(1.1)
    assert result.values["sg_app_rating"] == pytest.approx(1.2)
    assert result.values["sg_arg_rating"] == pytest.approx(0.3)
    assert result.values["sg_putt_rating"] == pytest.approx(0.4)
    assert result.values["sg_total_rating"] == pytest.approx(3.0)
    # Only one round → recent_mean == baseline_mean → form_index == 0.
    assert result.values["form_index"] == pytest.approx(0.0)
