"""Response envelopes — doc 03 §2 ("Response Shape Conventions").

Every list endpoint returns ``data + page + meta``. Single-resource endpoints
skip the data wrapper but keep ``meta`` so the frontend's "Predictions
generated 2 hours ago, model v3.2" line is always available.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003

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
