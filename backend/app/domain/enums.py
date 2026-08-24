from enum import StrEnum


class TournamentStatus(StrEnum):
    UPCOMING = "upcoming"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class EntryStatus(StrEnum):
    """Player's terminal status in a tournament. ``ACTIVE`` is the pre-cut state
    for in-progress events; the others are final.
    """

    ACTIVE = "active"
    MADE_CUT = "made_cut"
    MISSED_CUT = "missed_cut"
    WITHDREW = "withdrew"
    DISQUALIFIED = "disqualified"


class DgFetchStatus(StrEnum):
    """Why a board did or did not get DataGolf's own probabilities.

    Exists because a count of zero cannot answer the question. A Path A board
    with ``dg_direct_count == 0`` is either a legitimate cold-start (DataGolf
    genuinely has no numbers for this field) or a broken fetch (the live
    endpoint served a different event, or errored). Those two produce an
    identical-looking board and are worth opposite reactions, so the reason
    is recorded rather than inferred.

    The live ``/preds/pre-tournament`` endpoint takes no event parameter — it
    returns whatever event DataGolf currently features — so on a Wednesday
    before the feed has rolled over to this week's event, a capture gets
    ``FETCH_FAILED``, not ``NO_COVERAGE``.
    """

    # DataGolf returned probabilities for this event.
    OK = "ok"
    # The fetch worked and DataGolf has nothing for this field. A real
    # cold-start board: the SG-only model served everyone, correctly.
    NO_COVERAGE = "no_coverage"
    # The fetch did not produce usable data for *this* event: the live feed
    # named a different tournament, or the call errored. The resulting board
    # is degraded, and any DataGolf-baseline comparison must exclude it
    # rather than count it as a zero-coverage event.
    FETCH_FAILED = "fetch_failed"
    # Path A is not in use, so no fetch was made and the number would be
    # meaningless.
    NOT_ATTEMPTED = "not_attempted"

    @property
    def baseline_is_usable(self) -> bool:
        """True iff a DataGolf-baseline comparison may use this board.

        ``NO_COVERAGE`` is excluded as well as ``FETCH_FAILED``: an event
        DataGolf never priced contributes no baseline either way, and pooling
        it in as though DataGolf had predicted something would understate
        DataGolf rather than measure it.
        """
        return self is DgFetchStatus.OK


class LineFeedStatus(StrEnum):
    """Whether a captured outright market is what the parser expected.

    The market-line counterpart to :class:`DgFetchStatus`, and it exists for
    the same reason: a snapshot that quietly parsed less than it should looks
    identical to a healthy one, and capture is first-write-wins, so the wrong
    reading is permanent.

    Two real failure modes, both verified against the shipped parser on
    2026-08-24 and neither of which used to leave a trace:

    * A book quoting decimal odds where American was requested. DataGolf
      returns ``4.2`` rather than ``"+320"``, which the old parser rounded to
      the American price ``+4`` — an implied probability of 0.96 for every
      player in the market, stored as though it were real.
    * The ``datagolf`` object arriving flattened or absent, which read as
      ``dg_baseline: None`` on every line while the market still reported
      ``offered: True``, silently dropping DataGolf's own line.
    """

    # Every price and DataGolf's own line parsed as expected.
    OK = "ok"
    # The books are not offering this market. Normal, not a fault: every
    # no-cut event does this on make_cut.
    NOT_OFFERED = "not_offered"
    # Priced fine, but not one line carried DataGolf's baseline. Partial
    # coverage is normal — DataGolf does not model every player — so this
    # fires only when *nothing* parsed, which means shape, not coverage.
    MISSING_BASELINE = "missing_baseline"
    # At least one value was numeric but outside the range American odds can
    # occupy. Almost always an odds-format change; the values are refused
    # rather than stored, and the count is kept.
    SUSPECT_PRICES = "suspect_prices"
    # An event was named but nothing usable came back for this market.
    NO_DATA = "no_data"

    @property
    def is_clean(self) -> bool:
        """True when nothing about this market needs a human to look at it."""
        return self in (LineFeedStatus.OK, LineFeedStatus.NOT_OFFERED)


class MarketKind(StrEnum):
    WIN = "win"
    TOP_5 = "top_5"
    TOP_10 = "top_10"
    TOP_20 = "top_20"
    MAKE_CUT = "make_cut"
    MISS_CUT = "miss_cut"


class CourseType(StrEnum):
    PARKLAND = "parkland"
    LINKS = "links"
    DESERT = "desert"
    MOUNTAIN = "mountain"
    STADIUM = "stadium"
    RESORT = "resort"
