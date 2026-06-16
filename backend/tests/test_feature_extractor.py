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
from app.features.player import SGTotalRating, shrink_to_prior
from app.features.primitives import days_between, exponential_decay_weight
from app.providers.base import Capability, DataProvider
from app.services.features import FeatureExtractor


def _expected_sg(observed: float, played_on: date, as_of: date, prior: float) -> float:
    """The shrunk single-round rating the extractor should produce."""
    w = exponential_decay_weight(days_between(played_on, as_of), 60.0)
    return shrink_to_prior(observed * w, w, prior)

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
    extractor = FeatureExtractor(_StubProvider(rounds=[]), v1_baseline())
    result = await extractor.extract(player_id=42, as_of=date(2026, 6, 1))
    assert result.n_rounds == 0
    # All v1 features defined → returned, even with no data.
    assert set(result.values.keys()) == {f.name for f in v1_baseline().features}
    # Empty rounds → SG ratings fall back to their below-average priors (the
    # low-data fix), while form_index has nothing to compare and stays 0.0.
    from app.features.player import (  # noqa: PLC0415
        SGApproachRating,
        SGAroundTheGreenRating,
        SGOffTheTeeRating,
        SGPuttingRating,
    )
    assert result.values["sg_ott_rating"] == pytest.approx(SGOffTheTeeRating._prior)
    assert result.values["sg_app_rating"] == pytest.approx(SGApproachRating._prior)
    assert result.values["sg_arg_rating"] == pytest.approx(SGAroundTheGreenRating._prior)
    assert result.values["sg_putt_rating"] == pytest.approx(SGPuttingRating._prior)
    assert result.values["sg_total_rating"] == pytest.approx(SGTotalRating._prior)
    assert result.values["form_index"] == pytest.approx(0.0)


async def test_extractor_records_provenance() -> None:
    extractor = FeatureExtractor(_StubProvider(rounds=[]), v1_baseline())
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
    # Only the May round counts (the July one is post-as_of leakage), shrunk
    # toward the prior. If the leak got in, the rating would be far higher.
    expected = _expected_sg(2.0, date(2026, 5, 1), date(2026, 6, 1), SGTotalRating._prior)
    assert result.values["sg_total_rating"] == pytest.approx(expected)
    leaked = _expected_sg(6.0, date(2026, 5, 1), date(2026, 6, 1), SGTotalRating._prior)
    assert result.values["sg_total_rating"] < leaked


async def test_extractor_skips_rounds_without_tee_time() -> None:
    rounds = [
        _round(rid=1, tee_time=datetime(2026, 5, 1, 12, 0, tzinfo=UTC), sg_total=1.0),
        _round(rid=2, tee_time=None, sg_total=999.0),
    ]
    extractor = FeatureExtractor(_StubProvider(rounds=rounds))
    result = await extractor.extract(player_id=1, as_of=date(2026, 6, 1))
    assert result.n_rounds == 1
    expected = _expected_sg(1.0, date(2026, 5, 1), date(2026, 6, 1), SGTotalRating._prior)
    assert result.values["sg_total_rating"] == pytest.approx(expected)


async def test_extract_field_resolves_field_relative_margins() -> None:
    """Two-pass field extraction: each player's field-relative SG should be
    their own skill minus the field mean, computed over the whole field."""
    # Provider returns the same rounds for whatever player is asked; we vary
    # skill by handing each player a distinct stub provider instead.
    p1 = _StubProvider(rounds=[
        _round(rid=1, tee_time=datetime(2026, 5, 1, tzinfo=UTC), sg_total=2.0),
    ])
    # Build one extractor per provider isn't how the real flow works (one
    # provider serves all players), so instead use a provider keyed by player.
    class _PerPlayerProvider(_StubProvider):
        def __init__(self, skill_by_player: dict[int, float]) -> None:
            super().__init__(rounds=[])
            self._skill = skill_by_player

        async def get_rounds_for_player(
            self, player_id, *, since=None, limit=100,
        ):
            sg = self._skill.get(player_id, 0.0)
            return [_round(rid=player_id, tee_time=datetime(2026, 5, 1, tzinfo=UTC), sg_total=sg)]

    # Field of three players with skills 2.0, 0.0, -2.0 → field mean 0.0.
    provider = _PerPlayerProvider({1: 2.0, 2: 0.0, 3: -2.0})
    extractor = FeatureExtractor(provider)  # default v2_field_relative
    extractions = await extractor.extract_field([1, 2, 3], as_of=date(2026, 6, 1))

    assert set(extractions.keys()) == {1, 2, 3}
    # Shrinkage is an identical affine transform per player, so its additive
    # prior term cancels in a field-relative margin: the ordering, the zero at
    # the middle player, and the symmetry around the mean all survive (only the
    # magnitude is scaled by the shared low-data factor).
    fr = {pid: extractions[pid].values["field_rel_sg_total"] for pid in (1, 2, 3)}
    assert fr[1] > fr[2] > fr[3]
    assert fr[2] == pytest.approx(0.0)
    assert fr[1] > 0.0 > fr[3]
    assert fr[1] == pytest.approx(-fr[3])
    # Field strength is the same for everyone; an all-thin field reads below
    # average because every player is anchored to the negative prior.
    strengths = {extractions[pid].values["field_strength"] for pid in (1, 2, 3)}
    assert len(strengths) == 1
    assert next(iter(strengths)) < 0.0
    # Unused local kept the example honest about provider shape.
    assert p1 is not None


async def test_extract_field_deduplicates_player_ids() -> None:
    provider = _StubProvider(rounds=[
        _round(rid=1, tee_time=datetime(2026, 5, 1, tzinfo=UTC), sg_total=1.0),
    ])
    extractor = FeatureExtractor(provider)
    extractions = await extractor.extract_field([5, 5, 5], as_of=date(2026, 6, 1))
    assert set(extractions.keys()) == {5}


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
    # Single round on 2026-05-25, shrunk toward each category's prior.
    played, as_of = date(2026, 5, 25), date(2026, 6, 1)
    from app.features.player import (  # noqa: PLC0415 — local to keep helper imports tidy
        SGApproachRating,
        SGAroundTheGreenRating,
        SGOffTheTeeRating,
        SGPuttingRating,
    )
    assert result.values["sg_ott_rating"] == pytest.approx(
        _expected_sg(1.1, played, as_of, SGOffTheTeeRating._prior)
    )
    assert result.values["sg_app_rating"] == pytest.approx(
        _expected_sg(1.2, played, as_of, SGApproachRating._prior)
    )
    assert result.values["sg_arg_rating"] == pytest.approx(
        _expected_sg(0.3, played, as_of, SGAroundTheGreenRating._prior)
    )
    assert result.values["sg_putt_rating"] == pytest.approx(
        _expected_sg(0.4, played, as_of, SGPuttingRating._prior)
    )
    assert result.values["sg_total_rating"] == pytest.approx(
        _expected_sg(3.0, played, as_of, SGTotalRating._prior)
    )
    # Only one round → recent_mean == baseline_mean → form_index == 0.
    assert result.values["form_index"] == pytest.approx(0.0)
