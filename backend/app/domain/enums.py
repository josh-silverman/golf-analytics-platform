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
