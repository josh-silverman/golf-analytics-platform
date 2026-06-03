"""Pydantic domain models — the contract every data provider must produce.

These models are the lingua franca between providers (mock, DataGolf) and the
rest of the application. SQLAlchemy ORM models in ``app/db/models.py`` mirror
this shape, and the API serializes these directly out the door.

The "shots" table from earlier schema designs is intentionally absent: DataGolf
exposes round-level SG aggregates, not shot-level data (doc 03 §1).
"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import CourseType, EntryStatus, MarketKind, TournamentStatus


class DomainModel(BaseModel):
    """Base for every domain model. Frozen so instances are hashable and safe
    to pass between async tasks; ORM-mode on so SQLAlchemy rows convert in
    one line.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True)


# --- Reference entities ------------------------------------------------------


class Player(DomainModel):
    id: int
    dg_id: int | None = Field(default=None, description="DataGolf's player id")
    full_name: str
    country: str = Field(description="ISO 3166-1 alpha-3 country code")
    dob: date | None = None
    turned_pro: int | None = Field(default=None, description="Year")


class Course(DomainModel):
    id: int
    name: str
    location: str
    par: int = Field(ge=68, le=73)
    yardage: int = Field(ge=5000, le=8500)
    course_type: CourseType
    avg_score: float | None = Field(
        default=None,
        description="Historical mean round score; null until the course has rounds",
    )


# --- Tournament-scoped entities ---------------------------------------------


class Tournament(DomainModel):
    id: int
    course_id: int
    name: str
    season: int = Field(ge=1900, le=2100)
    start_date: date
    end_date: date
    purse: int | None = Field(default=None, description="USD, integer dollars")
    field_strength: float | None = Field(
        default=None,
        description="Mean overall rating of the field, weighted; null until set",
    )
    status: TournamentStatus


class TournamentEntry(DomainModel):
    """A player's participation in one tournament. Distinct from rounds so the
    player–tournament cardinality (1:1) is separate from player–round (1:4).
    """

    id: int
    tournament_id: int
    player_id: int
    status: EntryStatus
    final_position: int | None = None
    final_score_to_par: int | None = None
    official_money_cents: int | None = Field(
        default=None,
        description="Earnings in USD cents to keep an integer type",
    )


# --- Round (the granular unit — see doc 03 §1) ------------------------------


class Round(DomainModel):
    """One player's one round in one tournament.

    Strokes-gained values are round-level aggregates from DataGolf. We do not
    rebuild SG from shot data; DataGolf publishes the values directly.
    """

    id: int
    entry_id: int
    round_number: int = Field(ge=1, le=4)

    score: int = Field(ge=55, le=95)
    score_to_par: int = Field(ge=-20, le=25)
    tee_time: datetime | None = None

    # Strokes gained (round totals, in strokes)
    sg_ott: float
    sg_app: float
    sg_arg: float
    sg_putt: float
    sg_t2g: float
    sg_total: float

    # Other round-level stats
    driving_distance_avg: float | None = None
    fairways_hit: int | None = None
    gir: int | None = Field(default=None, description="Greens in regulation")
    putts: int | None = None


# --- Betting -----------------------------------------------------------------


class BettingLine(DomainModel):
    id: int
    tournament_id: int
    player_id: int
    book_name: str
    market: MarketKind
    decimal_odds: float = Field(gt=1.0)
    implied_prob: float = Field(ge=0.0, le=1.0)
    captured_at: datetime


# --- Skill snapshots (computed, not raw — included so providers may surface
#     them once skill ratings exist; mock will leave these out in Phase 1) ----


class PlayerSkillSnapshot(DomainModel):
    """As-of-date skill estimate. The as-of-date pattern prevents leakage when
    generating features for an event starting after ``as_of_date``.
    """

    id: int
    player_id: int
    as_of_date: date
    sg_ott_rating: float
    sg_app_rating: float
    sg_arg_rating: float
    sg_putt_rating: float
    overall_rating: float
    form_index: float
    rating_variance: float


# --- Pagination & metadata --------------------------------------------------


class Page[T](BaseModel):
    """Cursor-paginated envelope. Methods that can return large result sets
    use this so adding pagination later doesn't break every caller.
    """

    items: list[T]
    next_cursor: str | None = None
    total: int | None = Field(
        default=None,
        description="Best-effort total; may be None if the source can't compute it cheaply",
    )


class DataFreshness(BaseModel):
    """Per-resource last successful sync timestamp. Surfaced at ``/meta/data-freshness``."""

    sources: dict[str, datetime]
