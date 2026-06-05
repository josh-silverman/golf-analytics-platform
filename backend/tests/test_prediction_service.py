"""Unit tests for PredictionService."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from app.domain.enums import EntryStatus, TournamentStatus
from app.domain.models import Player, Tournament, TournamentEntry
from app.features.feature_sets import v1_baseline
from app.ml.base import ConstantModel
from app.services.predictions import PredictionService

_TOURNAMENT = Tournament(
    id=1,
    course_id=1,
    name="The Demo",
    season=2026,
    start_date=date(2026, 6, 1),
    end_date=date(2026, 6, 4),
    purse=10_000_000,
    field_strength=None,
    status=TournamentStatus.UPCOMING,
)

_PLAYERS = [
    Player(id=10, dg_id=None, full_name="Alice Ace", country="USA",
           dob=None, turned_pro=2018),
    Player(id=11, dg_id=None, full_name="Bob Birdie", country="USA",
           dob=None, turned_pro=2019),
    Player(id=12, dg_id=None, full_name="Cara Chip", country="GBR",
           dob=None, turned_pro=2020),
]

_FIELD = [
    TournamentEntry(
        id=i, tournament_id=1, player_id=p.id,
        status=EntryStatus.ACTIVE, final_position=None,
        final_score_to_par=None, official_money_cents=None,
    )
    for i, p in enumerate(_PLAYERS, start=1)
]


@dataclass
class _ExtractionStub:
    values: dict[str, float]

    @property
    def feature_set_hash(self) -> str:
        return v1_baseline().hash


class _StubCatalog:
    """Catalog stub: knows about one tournament and three players."""

    source_name = "stub"

    def __init__(self, *, tournament: Tournament | None = _TOURNAMENT) -> None:
        self._tournament = tournament

    async def get_tournament(self, tournament_id: int) -> Tournament | None:
        return self._tournament if tournament_id == 1 else None

    async def get_tournament_field(
        self, tournament_id: int
    ) -> list[TournamentEntry]:
        return list(_FIELD) if tournament_id == 1 else []

    async def get_player(self, player_id: int) -> Player | None:
        for p in _PLAYERS:
            if p.id == player_id:
                return p
        return None


class _StubExtractor:
    """Returns deterministic features keyed off the player_id."""

    def __init__(self) -> None:
        self.feature_set = v1_baseline()

    async def extract(self, player_id: int, as_of: date) -> _ExtractionStub:
        # Different SG values per player so we can verify the model
        # actually receives them.
        return _ExtractionStub(values={"sg_total_rating": float(player_id) / 10.0})


class _RankingModel(ConstantModel):
    """Predicts win_prob proportional to the player's sg_total_rating feature."""

    def __init__(self) -> None:
        super().__init__({})

    def predict(self, features: dict[str, float]) -> dict[str, float]:
        sg = features.get("sg_total_rating", 0.0)
        # Squash to [0,1] so the schema's bounds pass.
        win = max(0.0, min(0.99, sg / 5.0))
        return {
            "win_prob": win,
            "top_5_prob": win * 5,
            "top_10_prob": win * 10,
            "top_20_prob": min(0.99, win * 20),
            "make_cut_prob": 0.65,
        }


def _make_service(
    *,
    model: ConstantModel | None = None,
    catalog: _StubCatalog | None = None,
    model_version_id: str | None = "abc123def456",
) -> PredictionService:
    return PredictionService(
        catalog=catalog or _StubCatalog(),  # type: ignore[arg-type]
        extractor=_StubExtractor(),  # type: ignore[arg-type]
        model=model or _RankingModel(),
        model_name="golf_v1",
        model_version_id=model_version_id,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_predict_tournament_returns_one_outcome_per_field_member() -> None:
    service = _make_service()
    result = await service.predict_tournament(1, as_of=date(2026, 5, 30))
    assert result is not None
    assert len(result.outcomes) == 3
    assert {o.player_id for o in result.outcomes} == {10, 11, 12}


async def test_predict_tournament_sorts_by_win_prob_desc() -> None:
    """Higher player_id → higher feature → higher win_prob in the stub."""
    service = _make_service()
    result = await service.predict_tournament(1, as_of=date(2026, 5, 30))
    assert result is not None
    win_probs = [o.win_prob for o in result.outcomes]
    assert win_probs == sorted(win_probs, reverse=True)
    # Top of leaderboard is the player with the highest feature value (id 12).
    assert result.outcomes[0].player_id == 12


async def test_predict_tournament_records_model_provenance() -> None:
    service = _make_service(model_version_id="abc123def456")
    result = await service.predict_tournament(1, as_of=date(2026, 5, 30))
    assert result is not None
    assert result.model_name == "golf_v1"
    assert result.model_version_id == "abc123def456"
    assert result.feature_set_hash == v1_baseline().hash


async def test_predict_tournament_records_as_of() -> None:
    service = _make_service()
    target = date(2026, 5, 30)
    result = await service.predict_tournament(1, as_of=target)
    assert result is not None
    assert result.as_of == target


# ---------------------------------------------------------------------------
# Fallback / null model_version_id
# ---------------------------------------------------------------------------


async def test_predict_tournament_with_fallback_model_reports_null_version() -> None:
    service = _make_service(
        model=ConstantModel({"win_prob": 0.005, "top_5_prob": 0.05,
                             "top_10_prob": 0.10, "top_20_prob": 0.20,
                             "make_cut_prob": 0.65}),
        model_version_id=None,
    )
    result = await service.predict_tournament(1, as_of=date(2026, 5, 30))
    assert result is not None
    assert result.model_version_id is None
    # ConstantModel returns the same numbers for every player.
    assert all(o.win_prob == pytest.approx(0.005) for o in result.outcomes)


# ---------------------------------------------------------------------------
# Missing tournament
# ---------------------------------------------------------------------------


async def test_predict_tournament_returns_none_for_unknown_tournament() -> None:
    service = _make_service()
    assert await service.predict_tournament(999, as_of=date(2026, 5, 30)) is None


async def test_predict_tournament_uses_outcome_keys_from_model() -> None:
    """Model returns only win_prob → other outcomes default to 0.0."""
    service = _make_service(model=ConstantModel({"win_prob": 0.10}))
    result = await service.predict_tournament(1, as_of=date(2026, 5, 30))
    assert result is not None
    o = result.outcomes[0]
    assert o.win_prob == pytest.approx(0.10)
    assert o.top_5_prob == 0.0
    assert o.make_cut_prob == 0.0
