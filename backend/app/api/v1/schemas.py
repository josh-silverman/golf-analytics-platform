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
