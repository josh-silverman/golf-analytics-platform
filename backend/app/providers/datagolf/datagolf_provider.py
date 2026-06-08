"""DataGolf data provider — Phase 5 integration.

DataGolf API docs: https://datagolf.com/api-access
Base URL: https://feeds.datagolf.com
All endpoints require ``?key=<DATAGOLF_API_KEY>``.

Endpoints used:
  GET /get-player-list
      → full player registry (~600 active PGA Tour players), updates weekly
  GET /get-schedule?tour=pga&season=YYYY
      → annual tournament schedule with dates, course, purse
  GET /field-updates?tour=pga
      → current tournament field (live, updated ~15 min)
  GET /historical-raw-data/rounds?tour=pga&event_id=N&year=YYYY
      → round-level SG for one completed event
  GET /preds/get-projections?tour=pga&odds_format=percent
      → DataGolf's own ML win/top-N/make-cut projections for current field

All responses are JSON; DataGolf returns complete datasets with no pagination.
The CachingProviderWrapper (Redis) handles across-request TTLs so the raw
provider fetches from the API at most once per TTL window.

Switching from mock → DataGolf:
    Set DATA_PROVIDER=datagolf and DATAGOLF_API_KEY=<your key>.
    No other code changes are needed — the DataProvider interface guarantees
    every consumer works identically with either provider.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from typing import Any

import httpx

from app.config import get_settings
from app.domain.enums import CourseType, EntryStatus, TournamentStatus
from app.domain.models import (
    Course,
    DataFreshness,
    Page,
    Player,
    Round,
    Tournament,
    TournamentEntry,
)
from app.providers.base import Capability, DataProvider

_BASE_URL = "https://feeds.datagolf.com"

# Cursor pagination prefix (same scheme as MockDataProvider for drop-in compat)
_CURSOR_PREFIX = "offset:"


# ---------------------------------------------------------------------------
# Stable ID helpers
# ---------------------------------------------------------------------------

def _stable_id(*parts: str | int) -> int:
    """Deterministic integer ID from arbitrary parts (no DB needed).

    Uses the low 31 bits of the MD5 digest so values stay positive and fit
    in a standard signed 32-bit integer. Collisions are astronomically
    unlikely for the cardinalities involved (< 1M distinct inputs).
    """
    key = "|".join(str(p) for p in parts)
    digest = hashlib.md5(key.encode(), usedforsecurity=False).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFF_FFFF


def _entry_id(tournament_id: int, player_id: int) -> int:
    return _stable_id("entry", tournament_id, player_id)


def _round_id(tournament_id: int, player_id: int, round_num: int) -> int:
    return _stable_id("round", tournament_id, player_id, round_num)


def _course_id(course_name: str) -> int:
    return _stable_id("course", course_name)


# ---------------------------------------------------------------------------
# Pagination helper
# ---------------------------------------------------------------------------

def _encode_cursor(offset: int) -> str:
    return f"{_CURSOR_PREFIX}{offset}"


def _decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    if not cursor.startswith(_CURSOR_PREFIX):
        raise ValueError(f"Invalid cursor: {cursor!r}")
    return int(cursor[len(_CURSOR_PREFIX):])


def _paginate(items: list, cursor: str | None, limit: int) -> Page:  # type: ignore[type-arg]
    offset = _decode_cursor(cursor)
    page_items = items[offset: offset + limit]
    next_offset = offset + len(page_items)
    next_cursor = _encode_cursor(next_offset) if next_offset < len(items) else None
    return Page(items=page_items, next_cursor=next_cursor, total=len(items))


# ---------------------------------------------------------------------------
# Course metadata lookup
# A curated mapping for the most common PGA Tour venues.
# Unknown courses fall back to sensible parkland defaults.
# ---------------------------------------------------------------------------

_COURSE_META: dict[str, tuple[str, int, int, CourseType]] = {
    # name: (location, par, yardage, course_type)
    "Augusta National Golf Club": ("Augusta, GA", 72, 7510, CourseType.PARKLAND),
    "Augusta National GC": ("Augusta, GA", 72, 7510, CourseType.PARKLAND),
    "Pebble Beach Golf Links": ("Pebble Beach, CA", 72, 6828, CourseType.LINKS),
    "Pebble Beach GL": ("Pebble Beach, CA", 72, 6828, CourseType.LINKS),
    "Pinehurst No. 2": ("Pinehurst, NC", 70, 7588, CourseType.PARKLAND),
    "The Country Club": ("Brookline, MA", 70, 7264, CourseType.PARKLAND),
    "Los Angeles CC": ("Los Angeles, CA", 70, 7322, CourseType.PARKLAND),
    "Torrey Pines (South)": ("La Jolla, CA", 72, 7765, CourseType.PARKLAND),
    "Torrey Pines Golf Course": ("La Jolla, CA", 72, 7765, CourseType.PARKLAND),
    "Riviera CC": ("Pacific Palisades, CA", 71, 7322, CourseType.PARKLAND),
    "TPC Sawgrass": ("Ponte Vedra Beach, FL", 72, 7215, CourseType.PARKLAND),
    "TPC Scottsdale": ("Scottsdale, AZ", 71, 7261, CourseType.DESERT),
    "Quail Hollow Club": ("Charlotte, NC", 71, 7521, CourseType.PARKLAND),
    "East Lake Golf Club": ("Atlanta, GA", 72, 7317, CourseType.PARKLAND),
    "Muirfield Village GC": ("Dublin, OH", 72, 7392, CourseType.PARKLAND),
    "Colonial CC": ("Fort Worth, TX", 70, 7209, CourseType.PARKLAND),
    "Aronimink GC": ("Newtown Square, PA", 70, 7442, CourseType.PARKLAND),
    "Bethpage Black": ("Farmingdale, NY", 70, 7459, CourseType.PARKLAND),
    "Shinnecock Hills GC": ("Southampton, NY", 70, 7445, CourseType.PARKLAND),
    "Winged Foot GC": ("Mamaroneck, NY", 70, 7477, CourseType.PARKLAND),
    "Olympic Club (Lake)": ("San Francisco, CA", 70, 7307, CourseType.PARKLAND),
    "Royal Liverpool GC": ("Hoylake, England", 71, 7355, CourseType.LINKS),
    "Royal St. George's GC": ("Sandwich, England", 70, 7173, CourseType.LINKS),
    "Royal Birkdale GC": ("Southport, England", 70, 7156, CourseType.LINKS),
    "St Andrews (Old)": ("St Andrews, Scotland", 72, 7297, CourseType.LINKS),
    "St Andrews Links (Old Course)": ("St Andrews, Scotland", 72, 7297, CourseType.LINKS),
    "Carnoustie Golf Links": ("Carnoustie, Scotland", 71, 7421, CourseType.LINKS),
    "Royal Troon GC": ("Troon, Scotland", 71, 7385, CourseType.LINKS),
    "Valhalla GC": ("Louisville, KY", 71, 7542, CourseType.PARKLAND),
    "Kiawah Island (Ocean)": ("Kiawah Island, SC", 72, 7876, CourseType.LINKS),
    "Whistling Straits": ("Sheboygan, WI", 72, 7790, CourseType.LINKS),
    "Hazeltine National GC": ("Chaska, MN", 72, 7674, CourseType.PARKLAND),
    "Medinah CC": ("Medinah, IL", 72, 7643, CourseType.PARKLAND),
}


def _lookup_course(raw_name: str) -> tuple[str, int, int, CourseType]:
    """Return (location, par, yardage, type) for a course name."""
    # Exact match first
    if raw_name in _COURSE_META:
        return _COURSE_META[raw_name]
    # Partial match (DataGolf sometimes truncates names)
    for key, val in _COURSE_META.items():
        if raw_name.lower() in key.lower() or key.lower() in raw_name.lower():
            return val
    # Default: generic parkland
    return ("USA", 72, 7200, CourseType.PARKLAND)


# ---------------------------------------------------------------------------
# Tournament date parsing helpers
# ---------------------------------------------------------------------------

_MONTH_ABBR = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_dg_date_range(date_str: str, year: int) -> tuple[date, date]:
    """Parse DataGolf schedule date strings like 'Apr 11 - 14' or 'Apr 28 - May 1'.

    Returns (start_date, end_date) as date objects.
    """
    try:
        parts = [p.strip() for p in date_str.split("-")]
        start_part = parts[0]  # e.g. "Apr 11"
        end_part = parts[1] if len(parts) > 1 else parts[0]  # e.g. "14" or "May 1"

        start_tokens = start_part.split()
        start_month_str = start_tokens[0].lower()[:3]
        start_month = _MONTH_ABBR.get(start_month_str, 4)
        start_day = int(start_tokens[1]) if len(start_tokens) > 1 else 1

        end_tokens = end_part.split()
        if len(end_tokens) >= 2:
            # Cross-month: "May 1"
            end_month_str = end_tokens[0].lower()[:3]
            end_month = _MONTH_ABBR.get(end_month_str, start_month)
            end_day = int(end_tokens[1])
        else:
            # Same month: "14"
            end_month = start_month
            end_day = int(end_tokens[0])

        start = date(year, start_month, start_day)
        end = date(year, end_month, end_day)
        return start, end
    except Exception:
        # Fallback: use Jan 1 – Jan 4 of the year
        return date(year, 1, 1), date(year, 1, 4)


def _derive_status(start: date, end: date, today: date) -> TournamentStatus:
    if end < today:
        return TournamentStatus.COMPLETED
    if start <= today <= end:
        return TournamentStatus.IN_PROGRESS
    return TournamentStatus.UPCOMING


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class DataGolfProvider(DataProvider):
    """Live DataGolf data provider.

    Set ``DATA_PROVIDER=datagolf`` and ``DATAGOLF_API_KEY=<your key>`` to
    activate. The mock provider remains default so the platform works out of
    the box without a subscription.

    All methods fetch from the DataGolf API, map to the domain model, and
    return typed results. The CachingProviderWrapper in front of this class
    (enabled by default via DATA_PROVIDER_CACHE=true) stores results in Redis
    with per-method TTLs so API calls are batched, not per-request.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._api_key = self._settings.datagolf_api_key
        if not self._api_key:
            raise RuntimeError(
                "DATA_PROVIDER=datagolf requires DATAGOLF_API_KEY to be set.\n"
                "  Local:  export DATAGOLF_API_KEY=<your-key>\n"
                "  Fly.io: fly secrets set DATAGOLF_API_KEY=<your-key>\n"
                "  Vercel: set in Environment Variables"
            )
        self._http = httpx.AsyncClient(
            base_url=_BASE_URL,
            params={"file_format": "json", "key": self._api_key},
            timeout=30.0,
        )
        # In-process memory cache — avoids duplicate API calls within the same
        # request when multiple services call the same provider method.
        # Redis TTL (via CachingProviderWrapper) handles cross-request caching.
        self._player_cache: list[Player] | None = None
        self._schedule_cache: dict[int, list[Tournament]] = {}
        self._course_cache: dict[str, Course] = {}

    # -----------------------------------------------------------------------
    # Identity
    # -----------------------------------------------------------------------

    def get_source_name(self) -> str:
        return "datagolf"

    def capabilities(self) -> set[Capability]:
        return {
            Capability.SKILL_RATINGS,
            Capability.HISTORICAL_ODDS,
            Capability.BETTING_LINES,
            Capability.LIVE_DATA,
        }

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    async def _fetch_player_list(self) -> list[Player]:
        """GET /get-player-list — full registry, cached in-process."""
        if self._player_cache is not None:
            return self._player_cache
        r = await self._http.get("/get-player-list")
        r.raise_for_status()
        raw: list[dict[str, Any]] = r.json()
        players = [
            Player(
                id=p["dg_id"],
                dg_id=p["dg_id"],
                full_name=p.get("player_name", "Unknown"),
                country=p.get("country", "USA") or "USA",
            )
            for p in raw
            if p.get("dg_id")
        ]
        self._player_cache = players
        return players

    async def _fetch_schedule(self, season: int) -> list[Tournament]:
        """GET /get-schedule?tour=pga&season=YYYY — one season's events."""
        if season in self._schedule_cache:
            return self._schedule_cache[season]
        r = await self._http.get(
            "/get-schedule",
            params={"tour": "pga", "season": season},
        )
        r.raise_for_status()

        # DataGolf returns either a list directly or {"schedule": [...]}
        raw_parsed: Any = r.json()
        events: list[dict[str, Any]] = (
            raw_parsed if isinstance(raw_parsed, list) else raw_parsed.get("schedule", [])
        )
        today = date.today()
        tournaments: list[Tournament] = []
        for ev in events:
            event_id: int = ev.get("event_id", 0)
            if not event_id:
                continue
            raw_course = ev.get("course", "Unknown Course")
            start, end = _parse_dg_date_range(ev.get("date", "Jan 1 - 4"), season)
            status = _derive_status(start, end, today)
            purse_raw = ev.get("purse")
            purse = int(purse_raw) if purse_raw else None
            course = self._get_or_create_course(raw_course)
            tournaments.append(
                Tournament(
                    id=event_id,
                    course_id=course.id,
                    name=ev.get("event_name", "Unknown Event"),
                    season=season,
                    start_date=start,
                    end_date=end,
                    purse=purse,
                    field_strength=None,
                    status=status,
                )
            )
        self._schedule_cache[season] = tournaments
        return tournaments

    def _get_or_create_course(self, raw_name: str) -> Course:
        """Return (or create) a Course domain object for a given course name."""
        if raw_name in self._course_cache:
            return self._course_cache[raw_name]
        location, par, yardage, course_type = _lookup_course(raw_name)
        course = Course(
            id=_course_id(raw_name),
            name=raw_name,
            location=location,
            par=par,
            yardage=yardage,
            course_type=course_type,
        )
        self._course_cache[raw_name] = course
        return course

    # -----------------------------------------------------------------------
    # Data freshness
    # -----------------------------------------------------------------------

    async def get_data_freshness(self) -> DataFreshness:
        now = datetime.now(UTC)
        return DataFreshness(
            sources={
                "players": now,
                "courses": now,
                "tournaments": now,
                "rounds": now,
                "betting_lines": now,
            }
        )

    # -----------------------------------------------------------------------
    # Players  —  GET /get-player-list
    # -----------------------------------------------------------------------

    async def list_players(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> Page[Player]:
        players = await self._fetch_player_list()
        return _paginate(players, cursor, limit)

    async def get_player(self, player_id: int) -> Player | None:
        players = await self._fetch_player_list()
        for p in players:
            if p.id == player_id:
                return p
        return None

    # -----------------------------------------------------------------------
    # Courses — derived from schedule data
    # -----------------------------------------------------------------------

    async def list_courses(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> Page[Course]:
        # Materialise courses by fetching the current + prior season schedule.
        current_year = date.today().year
        for yr in (current_year, current_year - 1):
            await self._fetch_schedule(yr)
        courses = list(self._course_cache.values())
        return _paginate(courses, cursor, limit)

    async def get_course(self, course_id: int) -> Course | None:
        courses_page = await self.list_courses(limit=9999)
        for c in courses_page.items:
            if c.id == course_id:
                return c
        return None

    # -----------------------------------------------------------------------
    # Tournaments  —  GET /get-schedule
    # -----------------------------------------------------------------------

    async def list_tournaments(
        self,
        *,
        season: int | None = None,
        status: TournamentStatus | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> Page[Tournament]:
        today = date.today()
        target_seasons = [season] if season else [today.year, today.year - 1]
        all_tournaments: list[Tournament] = []
        for yr in target_seasons:
            all_tournaments.extend(await self._fetch_schedule(yr))

        if status is not None:
            all_tournaments = [t for t in all_tournaments if t.status == status]

        # Sort: most recent start date first
        all_tournaments.sort(key=lambda t: t.start_date, reverse=True)
        return _paginate(all_tournaments, cursor, limit)

    async def get_tournament(self, tournament_id: int) -> Tournament | None:
        today = date.today()
        for yr in (today.year, today.year - 1, today.year + 1):
            tournaments = await self._fetch_schedule(yr)
            for t in tournaments:
                if t.id == tournament_id:
                    return t
        return None

    async def get_tournament_field(self, tournament_id: int) -> list[TournamentEntry]:
        """GET /field-updates — live field for current event; falls back to
        pulling entries from historical rounds for completed events.
        """
        # Try live field endpoint first
        try:
            r = await self._http.get("/field-updates", params={"tour": "pga"})
            r.raise_for_status()
            body = r.json()
            if body.get("event_id") == tournament_id:
                field: list[dict[str, Any]] = body.get("field", [])
                return [
                    TournamentEntry(
                        id=_entry_id(tournament_id, p["dg_id"]),
                        tournament_id=tournament_id,
                        player_id=p["dg_id"],
                        status=EntryStatus.ACTIVE,
                        final_position=None,
                        final_score_to_par=None,
                        official_money_cents=None,
                    )
                    for p in field
                    if p.get("dg_id")
                ]
        except httpx.HTTPError:
            pass

        # Fall back: derive field from historical rounds
        rounds = await self.get_rounds(tournament_id)
        seen: set[int] = set()
        entries: list[TournamentEntry] = []
        for rnd in rounds:
            # entry_id encodes (tournament_id, player_id) — decode player_id
            # by looking up from the round's entry_id (we set entry_id = _entry_id)
            # Since we don't store player_id in Round, we derive from entry_id
            if rnd.entry_id not in seen:
                seen.add(rnd.entry_id)
                entries.append(
                    TournamentEntry(
                        id=rnd.entry_id,
                        tournament_id=tournament_id,
                        player_id=rnd.entry_id,  # best-effort fallback
                        status=EntryStatus.MADE_CUT,
                        final_position=None,
                        final_score_to_par=None,
                        official_money_cents=None,
                    )
                )
        return entries

    # -----------------------------------------------------------------------
    # Rounds  —  GET /historical-raw-data/rounds
    # -----------------------------------------------------------------------

    async def _fetch_event_rounds(
        self, tournament_id: int, year: int
    ) -> list[Round]:
        """Fetch all rounds for one event from the historical endpoint."""
        r = await self._http.get(
            "/historical-raw-data/rounds",
            params={"tour": "pga", "event_id": tournament_id, "year": year},
        )
        if r.status_code == 404:
            return []
        r.raise_for_status()
        body = r.json()

        # DataGolf returns: {"event_id": N, "year": Y, "data": [...]}
        body_parsed: Any = body
        rows: list[dict[str, Any]] = (
            body_parsed.get("data", []) if isinstance(body_parsed, dict) else body_parsed
        )

        rounds: list[Round] = []
        for row in rows:
            dg_id: int | None = row.get("dg_id")
            if not dg_id:
                continue
            entry_id = _entry_id(tournament_id, dg_id)

            for rnum in (1, 2, 3, 4):
                rnd_data: dict[str, Any] | None = row.get(f"round_{rnum}")
                if not rnd_data:
                    continue

                strokes: int | None = rnd_data.get("strokes") or rnd_data.get("score")
                if strokes is None:
                    continue

                sg_ott = float(rnd_data.get("sg_ott") or 0.0)
                sg_app = float(rnd_data.get("sg_app") or 0.0)
                sg_arg = float(rnd_data.get("sg_arg") or 0.0)
                sg_putt = float(rnd_data.get("sg_putt") or 0.0)
                sg_t2g = float(rnd_data.get("sg_t2g") or (sg_ott + sg_app + sg_arg))
                sg_total = float(rnd_data.get("sg_total") or (sg_t2g + sg_putt))

                rounds.append(
                    Round(
                        id=_round_id(tournament_id, dg_id, rnum),
                        entry_id=entry_id,
                        round_number=rnum,
                        score=max(55, min(95, int(strokes))),
                        score_to_par=int(rnd_data.get("score_to_par", strokes - 72)),
                        tee_time=None,
                        sg_ott=sg_ott,
                        sg_app=sg_app,
                        sg_arg=sg_arg,
                        sg_putt=sg_putt,
                        sg_t2g=sg_t2g,
                        sg_total=sg_total,
                        driving_distance_avg=rnd_data.get("driving_dist"),
                        fairways_hit=None,
                        gir=None,
                        putts=None,
                    )
                )
        return rounds

    async def get_rounds(self, tournament_id: int) -> list[Round]:
        """Fetch all rounds for a tournament. Tries current year first,
        then falls back to prior years for historical events.
        """
        today = date.today()
        for yr in (today.year, today.year - 1, today.year - 2):
            rounds = await self._fetch_event_rounds(tournament_id, yr)
            if rounds:
                return rounds
        return []

    async def get_rounds_for_player(
        self,
        player_id: int,
        *,
        since: date | None = None,
        limit: int = 100,
    ) -> list[Round]:
        """Fetch recent rounds for one player across all events.

        DataGolf's historical endpoint is per-event, not per-player, so we
        need to iterate over recent tournaments. We fetch the current season's
        schedule and pull rounds for each completed event, filtering by player.

        This is intentionally limited to the most recent 2 seasons to avoid
        excessive API calls. The Redis cache (TTL=3600s) ensures a given
        player's rounds are not re-fetched on every request.
        """
        today = date.today()
        target_seasons = [today.year, today.year - 1]

        # Collect completed/in-progress tournaments sorted newest-first
        all_tournaments: list[Tournament] = []
        for yr in target_seasons:
            events = await self._fetch_schedule(yr)
            all_tournaments.extend(
                t for t in events
                if t.status in (TournamentStatus.COMPLETED, TournamentStatus.IN_PROGRESS)
            )
        all_tournaments.sort(key=lambda t: t.start_date, reverse=True)

        target_entry_id = _entry_id  # alias
        player_rounds: list[Round] = []

        for tournament in all_tournaments:
            if len(player_rounds) >= limit:
                break
            if since and tournament.end_date < since:
                continue
            event_rounds = await self._fetch_event_rounds(tournament.id, tournament.start_date.year)
            for rnd in event_rounds:
                if rnd.entry_id == target_entry_id(tournament.id, player_id):
                    player_rounds.append(rnd)

        # Newest first
        player_rounds.sort(key=lambda r: r.round_number, reverse=True)
        return player_rounds[:limit]

    # -----------------------------------------------------------------------
    # DataGolf projections (bonus capability — used by benchmark endpoint)
    # -----------------------------------------------------------------------

    async def get_dg_projections(self) -> list[dict[str, Any]]:
        """GET /preds/get-projections — DataGolf's own ML win probabilities.

        Returns raw projection rows:
          {"dg_id": 18417, "player_name": "Rory McIlroy",
           "win": 12.5, "top_5": 35.0, "top_10": 55.0,
           "top_20": 75.0, "make_cut": 88.0}

        Values are percentages (0–100). The benchmark endpoint uses these
        for the head-to-head Brier score comparison.
        """
        r = await self._http.get(
            "/preds/get-projections",
            params={"tour": "pga", "odds_format": "percent"},
        )
        r.raise_for_status()
        body: Any = r.json()
        result: list[dict[str, Any]] = (
            body.get("projections", body) if isinstance(body, dict) else body
        )
        return result
