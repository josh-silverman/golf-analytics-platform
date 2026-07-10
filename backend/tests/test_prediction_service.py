"""Unit tests for PredictionService."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from app.domain.enums import EntryStatus, TournamentStatus
from app.domain.models import Player, Tournament, TournamentEntry
from app.features.feature_sets import v1_baseline
from app.ml.base import ConstantModel
from app.services.predictions import (
    PredictionService,
    coherent_outcomes,
    normalize_field,
)

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

    async def extract_field(
        self, player_ids: list[int], as_of: date, *, event: object | None = None
    ) -> dict[int, _ExtractionStub]:
        return {pid: await self.extract(pid, as_of) for pid in dict.fromkeys(player_ids)}


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
    # ConstantModel returns the same numbers for every player, so after field
    # normalization the win probability is split evenly — and sums to 1.0
    # across the field (exactly one winner), not the raw 0.005 × 3.
    n = len(result.outcomes)
    assert all(o.win_prob == pytest.approx(1.0 / n) for o in result.outcomes)
    assert sum(o.win_prob for o in result.outcomes) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Missing tournament
# ---------------------------------------------------------------------------


async def test_predict_tournament_returns_none_for_unknown_tournament() -> None:
    service = _make_service()
    assert await service.predict_tournament(999, as_of=date(2026, 5, 30)) is None


async def test_predict_tournament_outcomes_are_coherent_after_normalization() -> None:
    """Every served outcome stays nested (win ≤ top-5 ≤ … ≤ make-cut).

    A model that emits only ``win_prob`` defaults the wider buckets to 0.0; the
    service lifts them for coherence, and field normalization preserves it. (The
    precise lifting rules are covered directly in ``TestCoherentOutcomes``.)
    """
    service = _make_service(model=ConstantModel({"win_prob": 0.10}))
    result = await service.predict_tournament(1, as_of=date(2026, 5, 30))
    assert result is not None
    for o in result.outcomes:
        assert o.win_prob <= o.top_5_prob <= o.top_10_prob <= o.top_20_prob <= o.make_cut_prob


async def test_predict_tournament_normalizes_win_probs_to_one() -> None:
    """The served field's win probabilities sum to ~1.0 (exactly one winner)."""
    service = _make_service(
        model=ConstantModel({
            "win_prob": 0.047, "top_5_prob": 0.012, "top_10_prob": 0.033,
            "top_20_prob": 0.096, "make_cut_prob": 0.427,
        }),
    )
    result = await service.predict_tournament(1, as_of=date(2026, 5, 30))
    assert result is not None
    assert sum(o.win_prob for o in result.outcomes) == pytest.approx(1.0)
    for o in result.outcomes:
        assert o.win_prob <= o.top_5_prob <= o.top_10_prob <= o.top_20_prob <= o.make_cut_prob


# ---------------------------------------------------------------------------
# Path A: DataGolf-direct for covered players, model for cold-start
# ---------------------------------------------------------------------------


class _StubPathAProvider:
    """Provider stub exposing only the five-market DG-preds Path A needs."""

    def __init__(self, dg: dict[int, dict[str, float]]) -> None:
        self._dg = dg

    async def get_pretournament_full_preds(
        self, event_id: int, year: int, *, live: bool = False
    ) -> dict[int, dict[str, float]]:
        return dict(self._dg)


def _path_a_service(dg: dict[int, dict[str, float]]) -> PredictionService:
    from app.services.predictions import PathASource

    return PredictionService(
        catalog=_StubCatalog(),  # type: ignore[arg-type]
        extractor=_StubExtractor(),  # type: ignore[arg-type]
        model=_RankingModel(),  # cold-start model (win ∝ sg_total_rating)
        model_name="golf_v1",
        model_version_id="path_a",
        path_a=PathASource(provider=_StubPathAProvider(dg)),  # type: ignore[arg-type]
    )


async def test_path_a_routes_covered_player_to_datagolf() -> None:
    """A DG-covered player is served DataGolf's probabilities, not the model's.

    Under the pure model, player 12 (highest SG) tops the board. Path A gives
    only player 11 a DataGolf entry with a dominant win probability, so 11 must
    now top the board — proving covered players are routed to DataGolf.
    """
    dg = {
        11: {"win_prob": 0.30, "top_5_prob": 0.5, "top_10_prob": 0.6,
             "top_20_prob": 0.8, "make_cut_prob": 0.95},
    }
    result = await _path_a_service(dg).predict_tournament(1, as_of=date(2026, 5, 30))
    assert result is not None
    assert result.outcomes[0].player_id == 11  # DG favorite, not the model's


async def test_path_a_mixed_board_is_coherent_and_normalized() -> None:
    """Mixed DG + cold-start board stays nested and field-normalized."""
    dg = {
        11: {"win_prob": 0.30, "top_5_prob": 0.5, "top_10_prob": 0.6,
             "top_20_prob": 0.8, "make_cut_prob": 0.95},
        12: {"win_prob": 0.02, "top_5_prob": 0.1, "top_10_prob": 0.2,
             "top_20_prob": 0.4, "make_cut_prob": 0.7},
        # player 10 has no DG entry → cold-start via the model
    }
    result = await _path_a_service(dg).predict_tournament(1, as_of=date(2026, 5, 30))
    assert result is not None
    for o in result.outcomes:
        assert 0.0 <= o.win_prob <= o.top_5_prob <= o.top_10_prob <= o.top_20_prob
        assert o.top_20_prob <= o.make_cut_prob <= 1.0
    assert sum(o.win_prob for o in result.outcomes) == pytest.approx(1.0)


async def test_path_a_empty_dg_serves_whole_field_from_model() -> None:
    """With no DG coverage every player cold-starts to the model (graceful)."""
    result = await _path_a_service({}).predict_tournament(1, as_of=date(2026, 5, 30))
    assert result is not None
    # Same as the pure-model path: highest-SG player (12) tops the board.
    assert result.outcomes[0].player_id == 12


# ---------------------------------------------------------------------------
# Pure functions: coherence + field normalization
# ---------------------------------------------------------------------------


class TestCoherentOutcomes:
    def test_lifts_incoherent_wider_buckets(self) -> None:
        win, top5, top10, top20, cut = coherent_outcomes({
            "win_prob": 0.047, "top_5_prob": 0.012, "top_10_prob": 0.033,
            "top_20_prob": 0.096, "make_cut_prob": 0.427,
        })
        assert win == pytest.approx(0.047)
        assert top5 == pytest.approx(0.047)   # lifted from 0.012
        assert top10 == pytest.approx(0.047)  # lifted from 0.033
        assert top20 == pytest.approx(0.096)  # already coherent
        assert cut == pytest.approx(0.427)    # already coherent

    def test_missing_keys_default_then_lift_to_win(self) -> None:
        assert coherent_outcomes({"win_prob": 0.10}) == pytest.approx(
            (0.10, 0.10, 0.10, 0.10, 0.10)
        )

    def test_clamps_to_unit_interval(self) -> None:
        win, top5, top10, top20, cut = coherent_outcomes(
            {"win_prob": -0.5, "make_cut_prob": 2.0}
        )
        assert win == 0.0
        assert cut == 1.0


class TestNormalizeField:
    def test_win_probs_sum_to_one(self) -> None:
        rows = [(0.10, 0.30, 0.50, 0.70, 0.90)] * 4  # raw win sum 0.40
        out = normalize_field(rows)
        assert sum(r[0] for r in out) == pytest.approx(1.0)

    def test_deflates_inflated_longshots(self) -> None:
        # Four players each "win" 50% → field sum 2.0 → each scaled to 0.25.
        rows = [(0.50, 0.50, 0.50, 0.50, 0.50) for _ in range(4)]
        out = normalize_field(rows)
        assert sum(r[0] for r in out) == pytest.approx(1.0)
        assert out[0][0] == pytest.approx(0.25)

    def test_preserves_win_ranking(self) -> None:
        rows = [
            (0.30, 0.40, 0.50, 0.60, 0.70),
            (0.10, 0.20, 0.30, 0.40, 0.50),
            (0.05, 0.10, 0.15, 0.20, 0.50),
        ]
        wins = [r[0] for r in normalize_field(rows)]
        assert wins[0] > wins[1] > wins[2]  # order unchanged
        assert sum(wins) == pytest.approx(1.0)

    def test_output_stays_coherent(self) -> None:
        rows = [(0.30, 0.35, 0.40, 0.45, 0.50), (0.05, 0.10, 0.15, 0.20, 0.30)]
        for win, top5, top10, top20, cut in normalize_field(rows):
            assert win <= top5 <= top10 <= top20 <= cut
            assert win >= 0.0
            assert cut <= 1.0

    def test_empty_field_is_noop(self) -> None:
        assert normalize_field([]) == []
