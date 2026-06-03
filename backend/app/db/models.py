"""SQLAlchemy ORM models — mirror the Pydantic domain in ``app/domain/models.py``.

The shape follows the schema in ``docs/architecture/02-technical-core.md`` §1.
Notably: the shots table is omitted (DataGolf surfaces round-level SG only,
per doc 03 §1) and ML-side tables (predictions, simulation_runs, model_versions)
are deferred to Phase 2-3.

Indexing follows doc 02 §1: composite (tournament_id, player_id) on
tournament_entries, single-column indexes on FK columns, and a uniqueness
constraint on (entry_id, round_number).
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain.enums import CourseType, EntryStatus, MarketKind, TournamentStatus


def _pg_enum(enum_cls: type, name: str) -> SAEnum:
    """Build a SQLAlchemy Enum that stores the StrEnum's *values* (lowercase)
    rather than member names (uppercase), matching what Pydantic emits in
    JSON. Without this the DB has ``PARKLAND`` but the API has ``parkland``.
    """
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda e: [m.value for m in e],
    )


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    dg_id: Mapped[int | None] = mapped_column(
        BigInteger,
        unique=True,
        nullable=True,
    )
    full_name: Mapped[str] = mapped_column(String(120), index=True)
    country: Mapped[str] = mapped_column(String(3))
    dob: Mapped[date | None] = mapped_column(Date, nullable=True)
    turned_pro: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    entries: Mapped[list["TournamentEntry"]] = relationship(back_populates="player")


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    location: Mapped[str] = mapped_column(String(200))
    par: Mapped[int] = mapped_column(SmallInteger)
    yardage: Mapped[int] = mapped_column(Integer)
    course_type: Mapped[CourseType] = mapped_column(
        _pg_enum(CourseType, "course_type"),
    )
    avg_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    tournaments: Mapped[list["Tournament"]] = relationship(back_populates="course")

    __table_args__ = (
        CheckConstraint("par BETWEEN 68 AND 73", name="par_range"),
        CheckConstraint("yardage BETWEEN 5000 AND 8500", name="yardage_range"),
    )


class Tournament(Base):
    __tablename__ = "tournaments"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    season: Mapped[int] = mapped_column(SmallInteger, index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    purse: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    field_strength: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[TournamentStatus] = mapped_column(
        _pg_enum(TournamentStatus, "tournament_status"),
        index=True,
    )

    course: Mapped[Course] = relationship(back_populates="tournaments")
    entries: Mapped[list["TournamentEntry"]] = relationship(back_populates="tournament")


class TournamentEntry(Base):
    __tablename__ = "tournament_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    status: Mapped[EntryStatus] = mapped_column(
        _pg_enum(EntryStatus, "entry_status"),
    )
    final_position: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    final_score_to_par: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    official_money_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    tournament: Mapped[Tournament] = relationship(back_populates="entries")
    player: Mapped[Player] = relationship(back_populates="entries")
    rounds: Mapped[list["Round"]] = relationship(back_populates="entry")

    __table_args__ = (
        UniqueConstraint("tournament_id", "player_id", name="tournament_player"),
        Index("ix_tournament_entries_tournament_id_player_id", "tournament_id", "player_id"),
    )


class Round(Base):
    """One player's one round in one tournament.

    Strokes-gained columns store DataGolf-published round-level aggregates.
    SG components satisfy ``sg_total = sg_t2g + sg_putt`` and
    ``sg_t2g = sg_ott + sg_app + sg_arg`` (validated by the contract tests).
    """

    __tablename__ = "rounds"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("tournament_entries.id"),
        index=True,
    )
    round_number: Mapped[int] = mapped_column(SmallInteger)

    score: Mapped[int] = mapped_column(SmallInteger)
    score_to_par: Mapped[int] = mapped_column(SmallInteger)
    tee_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    sg_ott: Mapped[float] = mapped_column(Float)
    sg_app: Mapped[float] = mapped_column(Float)
    sg_arg: Mapped[float] = mapped_column(Float)
    sg_putt: Mapped[float] = mapped_column(Float)
    sg_t2g: Mapped[float] = mapped_column(Float)
    sg_total: Mapped[float] = mapped_column(Float)

    driving_distance_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    fairways_hit: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    gir: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    putts: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    entry: Mapped[TournamentEntry] = relationship(back_populates="rounds")

    __table_args__ = (
        UniqueConstraint("entry_id", "round_number", name="entry_round_number"),
        CheckConstraint("round_number BETWEEN 1 AND 4", name="round_number_range"),
    )


class BettingLine(Base):
    __tablename__ = "betting_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    book_name: Mapped[str] = mapped_column(String(50))
    market: Mapped[MarketKind] = mapped_column(_pg_enum(MarketKind, "market_kind"))
    decimal_odds: Mapped[float] = mapped_column(Float)
    implied_prob: Mapped[float] = mapped_column(Float)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "ix_betting_lines_t_p_m_b",
            "tournament_id",
            "player_id",
            "market",
            "book_name",
        ),
    )
