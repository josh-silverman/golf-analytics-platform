"""Response envelopes — doc 03 §2 ("Response Shape Conventions").

Every list endpoint returns ``data + page + meta``. Single-resource endpoints
skip the data wrapper but keep ``meta`` so the frontend's "Predictions
generated 2 hours ago, model v3.2" line is always available.
"""

from __future__ import annotations

from datetime import date, datetime  # noqa: TC003

from pydantic import BaseModel, Field


class PageMeta(BaseModel):
    next_cursor: str | None = None
    has_more: bool
    total: int | None = None


class ResponseMeta(BaseModel):
    as_of: datetime = Field(description="When the underlying data was last refreshed")
    source: str = Field(description="Identifier of the data source (e.g. 'mock', 'datagolf')")


class ListEnvelope[T](BaseModel):
    """Envelope used by every paginated list endpoint."""

    data: list[T]
    page: PageMeta
    meta: ResponseMeta


class SingleEnvelope[T](BaseModel):
    """Envelope used by every single-resource read."""

    data: T
    meta: ResponseMeta


class FeatureExtractionPayload(BaseModel):
    """Body of ``GET /players/{id}/features`` — feature values + provenance.

    ``feature_set_hash`` is what model_versions records, so a prediction can
    be marked stale when the underlying feature definitions change.
    """

    player_id: int
    as_of: date
    feature_set: str
    feature_set_hash: str
    n_rounds: int = Field(description="How many rounds were used in the computation")
    values: dict[str, float]


class PlayerOutcomePayload(BaseModel):
    """One row in the prediction leaderboard."""

    player_id: int
    player_name: str
    win_prob: float = Field(ge=0.0, le=1.0)
    top_5_prob: float = Field(ge=0.0, le=1.0)
    top_10_prob: float = Field(ge=0.0, le=1.0)
    top_20_prob: float = Field(ge=0.0, le=1.0)
    make_cut_prob: float = Field(ge=0.0, le=1.0)


class TournamentPredictionsPayload(BaseModel):
    """Body of ``GET /predictions/{tournament_id}``.

    ``model_version_id`` is null when the registry has no active version
    and the fallback ConstantModel is being served — that signal is what
    the frontend uses to surface "no trained model yet" in the UI.
    """

    tournament_id: int
    tournament_name: str
    as_of: date
    model_name: str
    model_version_id: str | None = None
    feature_set_hash: str
    outcomes: list[PlayerOutcomePayload]


class ReliabilityBinPayload(BaseModel):
    """One point of a reliability diagram (``mean_predicted`` vs observed)."""

    lower: float
    upper: float
    mean_predicted: float
    observed_frequency: float
    count: int


class OutcomeCalibrationPayload(BaseModel):
    """Calibration evidence for one outcome, raw vs isotonic-calibrated."""

    outcome_key: str
    brier_raw: float
    brier_calibrated: float
    bins_raw: list[ReliabilityBinPayload]
    bins_calibrated: list[ReliabilityBinPayload]


class CalibrationReportPayload(BaseModel):
    """Body of ``GET /analytics/calibration`` — the active model's held-out
    reliability diagnostics, the evidence behind every probability it serves."""

    model_name: str
    model_version_id: str
    n_calibration_examples: int
    outcomes: list[OutcomeCalibrationPayload]


class SimulationOutcomePayload(BaseModel):
    """One player's MC-derived outcome distribution.

    ``expected_score`` is the per-round strokes-to-par derived from the
    player's skill rating — the raw input to the simulation, exposed here
    so the frontend can show skill rankings alongside outcome probabilities.
    """

    player_id: int
    player_name: str
    win_prob: float = Field(ge=0.0, le=1.0)
    top_5_prob: float = Field(ge=0.0, le=1.0)
    top_10_prob: float = Field(ge=0.0, le=1.0)
    top_20_prob: float = Field(ge=0.0, le=1.0)
    make_cut_prob: float = Field(ge=0.0, le=1.0)
    expected_score: float


class TournamentSimulationPayload(BaseModel):
    """Body of ``GET /simulations/{tournament_id}``."""

    tournament_id: int
    tournament_name: str
    as_of: date
    n_iterations: int
    score_std: float
    outcomes: list[SimulationOutcomePayload]


class BettingLinePayload(BaseModel):
    """One player's edge analysis for a single outcome market."""

    player_id: int
    player_name: str
    model_prob: float = Field(ge=0.0, le=1.0)
    implied_prob: float = Field(ge=0.0, le=1.0)
    american_odds: int
    edge: float
    ev_per_dollar: float
    kelly_fraction: float = Field(ge=0.0)


class BettingBoardPayload(BaseModel):
    """Body of ``GET /betting/edge/{tournament_id}``.

    ``outcome_key`` identifies which market (win, top-5 …) the lines cover.
    ``n_positive_ev`` is a quick summary of how many players show +EV so the
    frontend can badge the nav link without parsing the full list.
    """

    tournament_id: int
    tournament_name: str
    outcome_key: str
    n_positive_ev: int
    lines: list[BettingLinePayload]


# ---------------------------------------------------------------------------
# Benchmark — our model vs. DataGolf's published projections
# ---------------------------------------------------------------------------


class BenchmarkPlayerRow(BaseModel):
    """One player's side-by-side probability comparison."""

    player_id: int
    player_name: str
    # Our model
    our_win_prob: float = Field(ge=0.0, le=1.0)
    our_top_10_prob: float = Field(ge=0.0, le=1.0)
    our_make_cut_prob: float = Field(ge=0.0, le=1.0)
    # DataGolf's published projections (null when not using DataGolf provider)
    dg_win_prob: float | None = None
    dg_top_10_prob: float | None = None
    dg_make_cut_prob: float | None = None
    # Difference (our – DG, positive means we are more bullish)
    win_diff: float | None = None


class BenchmarkPayload(BaseModel):
    """Body of ``GET /analytics/benchmark``.

    ``dg_available`` is False when the mock provider is active — the frontend
    renders a "Connect DataGolf API" callout in that case.

    Brier scores are null until a completed tournament is selected AND the
    provider supports historical odds (i.e. real outcomes are available).
    """

    tournament_id: int
    tournament_name: str
    model_name: str
    model_version_id: str | None = None
    dg_available: bool
    dg_last_updated: str | None = None
    rows: list[BenchmarkPlayerRow]
