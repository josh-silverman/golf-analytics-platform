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
    # Actual result once the event is graded; null beforehand.
    final_position: int | None = None
    made_cut: bool | None = None


class TrackRecordPayload(BaseModel):
    """Aggregate predicted-vs-actual accuracy over recent completed events.

    ``available`` is false until the (cached) aggregate has been computed.
    """

    available: bool
    events: int = 0
    players_graded: int = 0
    winner_in_top10_rate: float = 0.0
    mean_winner_rank: float = 0.0
    avg_top20_hit_rate: float = 0.0
    make_cut_accuracy: float = 0.0
    model_name: str | None = None
    model_version_id: str | None = None


class ForwardMarketSkillPayload(BaseModel):
    """One market's out-of-sample Brier skill with its block-bootstrap CI.

    ``ci_lower``/``ci_upper`` are ``None`` when there are too few graded events
    (< 3) to bootstrap a CI — FastAPI's encoder maps the underlying NaN to
    JSON ``null``, so this type declares what the wire actually sends rather
    than the ``float`` it was silently coerced through before.
    """

    market: str
    n: int
    base_rate: float
    brier: float
    brier_skill: float
    ci_lower: float | None
    ci_upper: float | None


class ForwardTrackRecordPayload(BaseModel):
    """Genuinely out-of-sample accuracy accumulated from captured pre-event boards.

    Distinct from ``TrackRecordPayload``: this grades *only* boards whose model
    was trained strictly before the event, so it is free of the in-sample risk
    the active-model report card carries. ``available`` is false until at least
    one completed, OOS-qualifying board has been captured.
    """

    available: bool
    events: int = 0
    players_graded: int = 0
    events_to_meaningful: int = 0
    markets: list[ForwardMarketSkillPayload] = []
    # Serving-regime split of the graded events. The record spans the
    # 2026-07-29 fix for the caching-wrapper bug that silently cold-started
    # every player, and both sides carry the same "path_a@…" model version id,
    # so these counts are the only way to tell how much of the aggregate was
    # produced by Path A actually running.
    events_path_a: int = 0
    events_cold_start_only: int = 0
    events_regime_unknown: int = 0


class ForwardBackfillEventPayload(BaseModel):
    """One event whose pre-event board was captured by the backfill run."""

    tournament_id: int
    name: str


class ForwardBackfillPayload(BaseModel):
    """Result of the admin forward track-record backfill.

    Reconstructs the pre-event board Path A *would have served* for each recent
    completed, out-of-sample event (as-of capped to the eve, DataGolf's pre-event
    archive — leakage-free) and captures it immutably, so the forward record has
    real data from day one instead of accruing only from the next live event.
    Idempotent: an event already captured is skipped, never overwritten.
    """

    examined: int
    captured: int
    skipped: int
    events: list[ForwardBackfillEventPayload] = []


class MatchupCapturePayload(BaseModel):
    """Result of the weekly matchup-line capture.

    ``captured`` is false both when this week's board was already captured
    (first capture wins, never overwritten) and when DataGolf has no matchup
    board up (off week); ``detail`` says which.
    """

    captured: bool
    event_name: str | None = None
    year: int | None = None
    matchups: int = 0
    detail: str


class MatchupThresholdPayload(BaseModel):
    """Flat-$1 record of every captured price that beat DataGolf's de-vigged
    line by more than ``min_edge`` (EV per $1)."""

    min_edge: float
    bets: int
    pnl: float
    roi: float | None


class MatchupGradedEventPayload(BaseModel):
    event_name: str
    year: int
    matchups_captured: int
    matchups_graded: int
    bets: int  # best-price strategy at the headline (2c) threshold
    pnl: float


class MatchupLineRecordPayload(BaseModel):
    """Forward record of DataGolf's matchup line vs real book prices.

    Accumulates from weekly pre-event captures graded against settled
    outcomes. This record — not the historical backtest, which cannot see
    DataGolf's line — is what decides whether a matchup surface may ever
    present an edge claim. ``available`` is false until one capture exists.
    """

    available: bool
    events_captured: int = 0
    events_graded: int = 0
    events_pending: int = 0
    matchups_graded: int = 0
    dg_line_brier: float | None = None  # vs decisive outcomes; 0.25 = coin-flip
    dg_line_n: int = 0
    any_price: list[MatchupThresholdPayload] = []
    best_price: list[MatchupThresholdPayload] = []
    events: list[MatchupGradedEventPayload] = []


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
    # "datagolf" if this line is a real sportsbook consensus, else "model".
    odds_source: str = "model"


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
    # "datagolf" when real sportsbook odds backed any line, else "model".
    odds_source: str
    lines: list[BettingLinePayload]
