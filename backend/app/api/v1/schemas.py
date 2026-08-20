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
    # Provenance split: live pre-event captures vs post-hoc backfill
    # reconstructions. One graded snapshot per tournament (live capture
    # preferred), so these two always sum to ``events``.
    events_captured: int = 0
    events_backfilled: int = 0
    players_captured: int = 0
    players_backfilled: int = 0
    # Per-market aggregates restricted to one provenance, same shape as
    # ``markets`` (which pools both). Lets a surface show captured and
    # backfilled side by side instead of presenting the pooled figure as a
    # live record. CIs are null until a pool has enough events to bootstrap.
    markets_captured: list[ForwardMarketSkillPayload] = []
    markets_backfilled: list[ForwardMarketSkillPayload] = []


class ForwardBackfillEventPayload(BaseModel):
    """One event the backfill captured, or would capture on a dry run."""

    tournament_id: int
    name: str
    start_date: date | None = None
    # Dry runs list every candidate; this flags the ones an actual run would
    # skip because a snapshot for that (tournament, model version) exists.
    already_captured: bool = False


class ForwardBackfillPayload(BaseModel):
    """Result of the admin forward track-record backfill.

    Reconstructs the pre-event board Path A *would have served* for each recent
    completed, out-of-sample event (as-of capped to the eve, DataGolf's pre-event
    archive — leakage-free) and captures it immutably, so the forward record has
    real data from day one instead of accruing only from the next live event.
    Idempotent: an event already captured is skipped, never overwritten.

    On a dry run nothing is written, ``captured`` is 0, and ``events`` lists
    every candidate (including already-captured ones, flagged) rather than only
    what was stored.
    """

    examined: int
    captured: int
    skipped: int
    events: list[ForwardBackfillEventPayload] = []
    dry_run: bool = False


class ArchiveBoardSummaryPayload(BaseModel):
    """One stored board snapshot, without its probabilities.

    Metadata only, deliberately: this is a debugging view, and the numbers it
    omits are the DataGolf-derived ones that must not end up in workflow logs.
    """

    tournament_id: int
    tournament_name: str
    tournament_start_date: str
    model_name: str
    model_version_id: str | None
    model_trained_through: str | None
    as_of: str
    captured_at: str
    source: str
    outcomes: int
    dg_direct_count: int | None
    # Derived, and the two questions this view exists to answer. ``out_of_sample``
    # is computed from the snapshot's own dates; ``canonical`` marks the snapshot
    # the grader would actually score for this tournament (see
    # ``forward_track_record.canonical_by_tournament``).
    out_of_sample: bool
    canonical: bool


class ArchiveMatchupSummaryPayload(BaseModel):
    """One stored matchup snapshot, without its prices."""

    event_name: str
    year: int
    market: str
    captured_at: str
    rows: int


class ArchiveSettlementSummaryPayload(BaseModel):
    """One pinned settlement record, summarised by status counts."""

    tournament_id: int
    tournament_name: str
    tournament_start_date: str
    provider: str
    settled_at: str
    players: int
    made_cut: int
    missed_cut: int
    # WD / DQ / unrecognised statuses — present in the pin, ungradeable.
    other: int


class ArchiveInspectPayload(BaseModel):
    """Read-only view of what the archives actually hold.

    Answers "why isn't this event graded?" without pulling the full export:
    whether a snapshot exists at all, whether its model can certify it
    out-of-sample, and whether it is the one the grader picks for its
    tournament. Whether the event has *completed* still needs the catalog, so
    that question is not answered here.
    """

    boards: int
    matchups: int
    settlements: int = 0
    board_snapshots: list[ArchiveBoardSummaryPayload] = []
    matchup_snapshots: list[ArchiveMatchupSummaryPayload] = []
    settlement_records: list[ArchiveSettlementSummaryPayload] = []


class ArchiveExportPayload(BaseModel):
    """Full dump of both forward archives (boards + matchup lines).

    Snapshots are carried as raw dicts, not typed models, on purpose: the
    archive deserializers tolerate unknown/missing keys so an export written
    by a newer build restores on an older one, and typing the envelope but
    not the entries preserves exactly that property. Content is
    deterministic (stably sorted, no timestamp) so the backup job can skip
    committing an unchanged archive.

    Contains DataGolf-derived data — personal use only, never redistribute:
    exports must only ever be committed to a private repository.
    """

    schema_version: int
    boards: list[dict[str, object]] = []
    matchups: list[dict[str, object]] = []
    settlements: list[dict[str, object]] = []


class ArchiveImportPayload(BaseModel):
    """Result of restoring an export into the live archives.

    ``*_skipped`` counts snapshots that already existed — first write wins,
    so a restore can never overwrite a live capture. ``*_errors`` counts
    entries that failed to parse (counted, not fatal: restoring most of the
    record beats restoring none of it).
    """

    boards_stored: int
    boards_skipped: int
    boards_errors: int
    matchups_stored: int
    matchups_skipped: int
    matchups_errors: int
    settlements_stored: int = 0
    settlements_skipped: int = 0
    settlements_errors: int = 0


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
