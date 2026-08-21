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
