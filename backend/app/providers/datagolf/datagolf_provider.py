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

import asyncio
import hashlib
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from app.config import get_settings
from app.domain.enums import CourseType, EntryStatus, TournamentStatus
from app.domain.models import (
    Course,
    DataFreshness,
    OutrightOdds,
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

# The historical-raw-data endpoints throttle far more aggressively than the
# light reference endpoints — measured at ~17 requests per rolling window
# before a 429, versus 35+ for the player list. A training run sweeps every
# event in the schedule through this endpoint, so we pace those calls below the
# limit rather than relying on reactive retry once already throttled. Set to
# ~7.5/min: a full-archive sweep at 15/min was observed to clip the limit and
# exhaust the retry budget mid-run, so we trade a slower sweep for reliability.
_ROUNDS_MIN_INTERVAL_S = 8.0

# How many seasons of *events* to surface when no season is specified —
# governs ``list_tournaments`` (and therefore the training set: every
# completed event in this span becomes training examples) and how far back
# ``_find_tournament`` searches. Each extra season is ~40 more events of
# throttled fetching per training run, but also ~40 more winners — the win
# market's scarcest label. Must stay ≤ ``_MAX_ROUNDS_SEASONS - 2`` so the
# oldest event still gets a full 730-day feature window (see features.py).
# Exposed as ``default_schedule_seasons`` so the caching wrapper folds it
# into the ``list_tournaments`` cache key — changing the span must
# invalidate cached schedules, not serve the old span until TTL expiry.
_SCHEDULE_SEASONS = 3

# How many seasons of history ``get_rounds_for_player`` enumerates when the
# caller gives no ``since`` (bootstrap smoke-check, player-page round list).
# The feature pipeline always passes an explicit ``since``, so this only
# bounds ad-hoc lookups.
_HISTORY_SEASONS = 2

# Hard cap on how far back ``get_rounds_for_player`` will enumerate seasons
# when a caller passes an explicit ``since``. Protects against a distant
# ``since`` turning one player lookup into a decade of throttled schedule and
# event fetches; DataGolf's SG-categorized archive is also sparse before ~2017.
# Must cover _SCHEDULE_SEASONS plus the 2-year feature window, or the oldest
# training events silently get truncated windows.
_MAX_ROUNDS_SEASONS = 5


class _RetryTransport(httpx.AsyncBaseTransport):
    """Wraps a transport and retries 429s and transient network errors.

    DataGolf rate-limits request bursts and, over a long training sweep of the
    schedule and many events, occasionally drops a connection mid-request
    (``RemoteProtocolError`` / connect / read errors). Either way a single
    transient failure must back off and retry rather than abort a 40-minute
    run. Centralising it here means *every* endpoint the provider calls is
    resilient. ``Retry-After`` is honoured for 429s when present; otherwise
    backoff is 2·2^n seconds capped at 30s.
    """

    def __init__(
        self, inner: httpx.AsyncBaseTransport, *, max_attempts: int = 5
    ) -> None:
        self._inner = inner
        self._max_attempts = max_attempts

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        for attempt in range(self._max_attempts):
            last = attempt == self._max_attempts - 1
            try:
                response = await self._inner.handle_async_request(request)
            except httpx.TransportError:
                # Connection dropped/timed out before a response — transient on
                # DataGolf's long archive endpoints. Re-raise on the last try.
                if last:
                    raise
                await asyncio.sleep(min(2.0 * (2**attempt), 30.0))
                continue
            if response.status_code != 429 or last:
                return response
            await response.aread()
            await response.aclose()
            retry_after = response.headers.get("Retry-After")
            delay = (
                float(retry_after)
                if retry_after and retry_after.replace(".", "", 1).isdigit()
                else min(2.0 * (2**attempt), 30.0)
            )
            await asyncio.sleep(delay)
        # Unreachable: the loop always returns or raises on the last attempt.
        raise RuntimeError("retry transport exhausted without returning")

    async def aclose(self) -> None:
        await self._inner.aclose()

# Our outcome keys → DataGolf ``betting-tools/outrights`` market names.
_DG_MARKET = {
    "win_prob": "win",
    "top_5_prob": "top_5",
    "top_10_prob": "top_10",
    "top_20_prob": "top_20",
    "make_cut_prob": "make_cut",
}

# Keys in an outrights ``odds`` row that are NOT a sportsbook quote — excluded
# when computing the consensus line across books.
_NON_BOOK_KEYS = frozenset({"dg_id", "player_name", "datagolf"})


def _american_str_to_int(raw: Any) -> int | None:
    """Parse a DataGolf American-odds string like ``"+1200"`` / ``"-150"``."""
    if raw is None:
        return None
    text = str(raw).strip().replace("+", "")
    if not text or text.upper() in ("NA", "N/A", "-"):
        return None
    try:
        return int(round(float(text)))
    except ValueError:
        return None


def _consensus_american(row: dict[str, Any]) -> int | None:
    """Median American odds across the real books quoting a player.

    The median is taken in *probability* space (the only meaningful average for
    odds) and converted back, so a single book's outlier line can't skew the
    consensus. DataGolf's own model baseline is excluded — we want the market.
    """
    probs: list[float] = []
    for key, val in row.items():
        if key in _NON_BOOK_KEYS:
            continue
        odds = _american_str_to_int(val)
        if odds is None:
            continue
        probs.append(100.0 / (odds + 100.0) if odds >= 0 else (-odds) / (-odds + 100.0))
    if not probs:
        return None
    probs.sort()
    mid = len(probs) // 2
    median_p = probs[mid] if len(probs) % 2 else (probs[mid - 1] + probs[mid]) / 2.0
    median_p = min(max(median_p, 1e-4), 0.9999)
    # prob → American
    if median_p >= 0.5:
        return round(-median_p / (1.0 - median_p) * 100)
    return round((1.0 - median_p) / median_p * 100)


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


def _event_dates(ev: dict[str, Any], season: int) -> tuple[date, date]:
    """Resolve (start, end) for a schedule event.

    The live ``get-schedule`` gives an ISO ``start_date`` (``"2026-06-04"``) and
    no end date, so end is the start + 3 days (the standard Thu–Sun, 4-round
    week). Falls back to the documented ``"Apr 11 - 14"`` range string if a
    payload ever ships that shape instead.
    """
    iso = ev.get("start_date")
    if iso:
        try:
            start = date.fromisoformat(str(iso)[:10])
            return start, start + timedelta(days=3)
        except ValueError:
            pass
    return _parse_dg_date_range(ev.get("date", "Jan 1 - 4"), season)


def _parse_dg_status(
    raw_status: Any, start: date, end: date, today: date
) -> TournamentStatus:
    """Prefer DataGolf's own ``status`` field, refining "upcoming" by date.

    DataGolf labels events ``"completed"`` or ``"upcoming"``; it has no distinct
    "in progress" value, so an "upcoming" event whose Thu–Sun window contains
    today is promoted to IN_PROGRESS. Unknown values fall back to date logic.
    """
    s = str(raw_status or "").strip().lower()
    if s == "completed":
        return TournamentStatus.COMPLETED
    if s in ("in_progress", "active", "live"):
        return TournamentStatus.IN_PROGRESS
    if s in ("upcoming", "scheduled", "future"):
        if start <= today <= end:
            return TournamentStatus.IN_PROGRESS
        return TournamentStatus.UPCOMING
    return _derive_status(start, end, today)


# ---------------------------------------------------------------------------
# Result parsing helpers
# ---------------------------------------------------------------------------


def _parse_fin_text(fin_text: Any) -> tuple[int | None, EntryStatus]:
    """Map DataGolf's ``fin_text`` to ``(final_position, status)``.

    DataGolf reports a player's finish as a short string: ``"1"`` (winner),
    ``"T5"`` (tied 5th), ``"CUT"``/``"MC"`` (missed cut), ``"WD"`` (withdrew),
    ``"DQ"`` (disqualified). Training labels depend entirely on this mapping —
    if we can't recover the finishing position there are no win/top-N labels,
    so this is the seam that makes a real-data model possible.

    Unknown/empty values are treated as a made-cut finish with no position
    (so the player still counts toward the field but contributes no positive
    bucket label) rather than silently dropping them.
    """
    if fin_text is None:
        return None, EntryStatus.MADE_CUT
    token = str(fin_text).strip().upper()
    if token in ("CUT", "MC", "MDF"):
        return None, EntryStatus.MISSED_CUT
    if token in ("WD", "DQ", "DNS", "DNF"):
        return None, EntryStatus.WITHDREW
    # Ties are prefixed with 'T' (e.g. "T12"); strip it before parsing.
    digits = token[1:] if token.startswith("T") else token
    try:
        position = int(digits)
    except ValueError:
        return None, EntryStatus.MADE_CUT
    return position, EntryStatus.MADE_CUT


def _round_datetime(start_date: date, round_num: int) -> datetime:
    """Approximate a round's calendar date from the event start + round offset.

    DataGolf's per-round payload doesn't carry a reliable per-round date, but
    the feature pipeline *requires* one — rounds with no ``tee_time`` are
    dropped (no date ⇒ no time-decay weighting), which previously meant every
    real-data round was silently discarded. A standard 4-round event runs on
    consecutive days from the Thursday start, so start + (round−1) days is
    accurate enough for recency weighting. Noon UTC keeps the date stable
    across timezone conversions.
    """
    base = datetime(start_date.year, start_date.month, start_date.day, 12, 0, tzinfo=UTC)
    return base + timedelta(days=round_num - 1)


def _field_from_rows(
    rows: list[dict[str, Any]], tournament_id: int
) -> list[TournamentEntry]:
    """Rebuild a completed event's field from historical rows.

    Each entry carries the real ``dg_id`` as ``player_id`` and a finishing
    position/status parsed from ``fin_text`` — the two things the previous
    fallback got wrong, and the two things training and prediction depend on.
    """
    entries: list[TournamentEntry] = []
    seen: set[int] = set()
    for row in rows:
        dg_id: int | None = row.get("dg_id")
        if not dg_id or dg_id in seen:
            continue
        seen.add(dg_id)
        position, status = _parse_fin_text(row.get("fin_text"))
        entries.append(
            TournamentEntry(
                id=_entry_id(tournament_id, dg_id),
                tournament_id=tournament_id,
                player_id=dg_id,
                status=status,
                final_position=position,
                final_score_to_par=None,
                official_money_cents=None,
            )
        )
    return entries


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

    # Folded into the caching wrapper's ``list_tournaments`` key — see
    # ``_SCHEDULE_SEASONS``.
    default_schedule_seasons = _SCHEDULE_SEASONS

    def __init__(
        self,
        *,
        api_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = get_settings()
        self._api_key = api_key or self._settings.datagolf_api_key
        if not self._api_key:
            raise RuntimeError(
                "DATA_PROVIDER=datagolf requires DATAGOLF_API_KEY to be set.\n"
                "  Local:  export DATAGOLF_API_KEY=<your-key>\n"
                "  Fly.io: fly secrets set DATAGOLF_API_KEY=<your-key>\n"
                "  Vercel: set in Environment Variables"
            )
        # ``transport`` is injected by tests (httpx.MockTransport) so the
        # provider can be exercised against recorded DataGolf payloads without
        # a live key or network. Production passes None → real HTTP. Either way
        # it's wrapped in a retrying transport so a rate-limit 429 on any
        # endpoint backs off instead of aborting a long training sweep.
        inner = transport or httpx.AsyncHTTPTransport()
        self._http = httpx.AsyncClient(
            base_url=_BASE_URL,
            params={"file_format": "json", "key": self._api_key},
            timeout=30.0,
            transport=_RetryTransport(inner),
        )
        # In-process memory cache — avoids duplicate API calls within the same
        # request when multiple services call the same provider method.
        # Redis TTL (via CachingProviderWrapper) handles cross-request caching.
        self._player_cache: list[Player] | None = None
        self._schedule_cache: dict[int, list[Tournament]] = {}
        self._course_cache: dict[str, Course] = {}
        # Raw per-event rounds, keyed by (event_id, year). An event's historical
        # rows are immutable and get requested once per player during a field
        # extraction (120+ players × ~47 events) — caching collapses that
        # thousands-of-calls fan-out to one fetch per event, which is the
        # difference between sailing through and tripping DataGolf's rate limit.
        self._event_rows_cache: dict[tuple[int, int], list[dict[str, Any]]] = {}
        # Pace calls to the strict historical-raw-data endpoint. Disabled when a
        # transport is injected (tests/offline) so the suite stays instant —
        # a MockTransport has no rate limit to respect.
        self._rounds_min_interval = 0.0 if transport is not None else _ROUNDS_MIN_INTERVAL_S
        self._rounds_throttle_lock = asyncio.Lock()
        self._rounds_last_request = 0.0
        # Which (event_id) actually carry SG-categorized raw data per year, from
        # the light ``event-list`` endpoint. Lets ``_event_rows`` skip events
        # absent from the archive without spending a throttled request on a 400.
        self._valid_events_cache: dict[int, set[int]] = {}

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    async def aclose(self) -> None:
        """Close the underlying HTTP client.

        Production closes this via the FastAPI lifespan; exposing it directly
        lets tests (and any ad-hoc caller) release the client deterministically
        instead of leaving it for the garbage collector to reap after the event
        loop has closed.
        """
        await self._http.aclose()

    async def __aenter__(self) -> DataGolfProvider:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

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
        # A season DataGolf doesn't have (e.g. a future year) returns 400 — treat
        # it as "no events" so a lookup that probes adjacent years doesn't crash.
        if r.status_code == 400:
            self._schedule_cache[season] = []
            return []
        r.raise_for_status()

        # DataGolf returns either a list directly or {"schedule": [...]}
        raw_parsed: Any = r.json()
        events: list[dict[str, Any]] = (
            raw_parsed if isinstance(raw_parsed, list) else raw_parsed.get("schedule", [])
        )
        today = date.today()
        tournaments: list[Tournament] = []
        for ev in events:
            # ``event_id`` arrives as a string ("6") in the live schedule.
            event_id_raw = ev.get("event_id")
            if event_id_raw in (None, "", 0):
                continue
            try:
                event_id = int(str(event_id_raw))
            except ValueError:
                continue
            raw_course = ev.get("course", "Unknown Course")
            start, end = _event_dates(ev, season)
            status = _parse_dg_status(ev.get("status"), start, end, today)
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
        target_seasons = (
            [season]
            if season
            else [today.year - i for i in range(_SCHEDULE_SEASONS)]
        )
        all_tournaments: list[Tournament] = []
        for yr in target_seasons:
            all_tournaments.extend(await self._fetch_schedule(yr))

        if status is not None:
            all_tournaments = [t for t in all_tournaments if t.status == status]

        # Sort: most recent start date first
        all_tournaments.sort(key=lambda t: t.start_date, reverse=True)
        return _paginate(all_tournaments, cursor, limit)

    async def get_tournament(self, tournament_id: int) -> Tournament | None:
        return await self._find_tournament(tournament_id)

    async def _find_tournament(self, tournament_id: int) -> Tournament | None:
        """Locate a tournament across recent seasons (for its date + year).

        Searches the configured history window first (newest → oldest) so
        training events from older seasons resolve, then peeks one year ahead
        for an early-rolled-over schedule.
        """
        today = date.today()
        years = [today.year - i for i in range(_SCHEDULE_SEASONS)] + [today.year + 1]
        for yr in years:
            for t in await self._fetch_schedule(yr):
                if t.id == tournament_id:
                    return t
        return None

    async def get_tournament_field(self, tournament_id: int) -> list[TournamentEntry]:
        """Field for a tournament.

        For the live/current event the ``/field-updates`` endpoint gives the
        in-progress field (status ACTIVE, no finishing position yet). For any
        completed event we rebuild the field from the historical rounds payload
        so each entry carries the *real* ``dg_id`` and a parsed finishing
        position — without which training has no labels and prediction can't
        match players.
        """
        # Live field first — only returns the single current event.
        try:
            r = await self._http.get("/field-updates", params={"tour": "pga"})
            r.raise_for_status()
            body = r.json()
            if isinstance(body, dict) and body.get("event_id") == tournament_id:
                field: list[dict[str, Any]] = body.get("field", [])
                live = [
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
                if live:
                    return live
        except httpx.HTTPError:
            pass

        # Completed event: rebuild from historical rows (real ids + positions).
        tournament = await self._find_tournament(tournament_id)
        year = tournament.start_date.year if tournament else date.today().year
        rows = await self._event_rows(tournament_id, year)
        return _field_from_rows(rows, tournament_id)

    # -----------------------------------------------------------------------
    # Rounds  —  GET /historical-raw-data/rounds
    # -----------------------------------------------------------------------

    async def _event_rows(self, tournament_id: int, year: int) -> list[dict[str, Any]]:
        """Raw per-player rows from ``/historical-raw-data/rounds`` for an event.

        Each row is one player and carries ``dg_id``, ``fin_text`` and nested
        ``round_1``…``round_4`` objects. Returns ``[]`` for a missing event so
        callers can fall through to other years.

        Results are memoised per ``(event_id, year)`` for the provider's
        lifetime: an event's archived rows never change, and a field extraction
        asks for the same event once per player, so without this the same event
        would be re-fetched 100+ times.
        """
        cache_key = (tournament_id, year)
        cached = self._event_rows_cache.get(cache_key)
        if cached is not None:
            return cached

        # Skip a throttled request for events the archive doesn't carry: if we
        # have the valid-event set for this year and this id isn't in it, it has
        # no SG raw data (it would 400 or return empty). An empty set means the
        # event-list lookup is unavailable → fall through and let the fetch (and
        # its 400/404 handling) decide, preserving the old behaviour.
        valid = await self._valid_event_ids(year)
        if valid and tournament_id not in valid:
            self._event_rows_cache[cache_key] = []
            return []

        rows = await self._fetch_event_rows(tournament_id, year)
        self._event_rows_cache[cache_key] = rows
        return rows

    async def _valid_event_ids(self, year: int) -> set[int]:
        """PGA event ids with SG-categorized raw data for ``year``.

        Sourced from the light ``historical-raw-data/event-list`` endpoint (one
        cached call, generous limit). Returns an empty set on any failure, which
        callers treat as "unknown → don't filter" so a shape change degrades to
        the old sweep-and-skip-400 behaviour rather than training on nothing.
        """
        cached = self._valid_events_cache.get(year)
        if cached is not None:
            return cached
        try:
            r = await self._http.get("/historical-raw-data/event-list")
            r.raise_for_status()
            rows: Any = r.json()
        except (httpx.HTTPError, ValueError):
            self._valid_events_cache[year] = set()
            return set()
        ids = {
            int(row["event_id"])
            for row in rows
            if isinstance(row, dict)
            and row.get("tour") == "pga"
            and row.get("sg_categories") == "yes"
            and row.get("event_id") is not None
            and int(row.get("calendar_year", 0)) == year
        }
        self._valid_events_cache[year] = ids
        return ids

    async def _throttle_rounds(self) -> None:
        """Space out historical-raw-data calls to stay under the endpoint limit."""
        if self._rounds_min_interval <= 0.0:
            return
        async with self._rounds_throttle_lock:
            loop = asyncio.get_event_loop()
            wait = self._rounds_min_interval - (loop.time() - self._rounds_last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._rounds_last_request = loop.time()

    async def _fetch_event_rows(
        self, tournament_id: int, year: int
    ) -> list[dict[str, Any]]:
        """Single HTTP fetch of one event's rows (429s retried by the transport)."""
        await self._throttle_rounds()
        r = await self._http.get(
            "/historical-raw-data/rounds",
            params={"tour": "pga", "event_id": tournament_id, "year": year},
        )
        # The historical archive doesn't contain every scheduled event: an event
        # without posted raw data returns 404, and an event_id absent from the
        # archive for that calendar year returns 400 ("event number N is not
        # available …"). Both mean "no rounds here" — skip rather than aborting
        # a training run that iterates the schedule.
        if r.status_code in (400, 404):
            return []
        r.raise_for_status()
        body: Any = r.json()
        # DataGolf returns {"event_id": N, "year": Y, "scores": [...]} (older
        # payloads used "data"); accept either, or a bare list.
        rows: Any = (
            (body.get("scores") or body.get("data") or [])
            if isinstance(body, dict)
            else body
        )
        return [row for row in rows if isinstance(row, dict)]

    def _rounds_from_rows(
        self,
        rows: list[dict[str, Any]],
        tournament_id: int,
        start_date: date,
    ) -> list[Round]:
        """Build dated ``Round`` objects from raw event rows.

        Critically sets ``tee_time`` (from the event start + round offset) so
        the feature pipeline keeps the rounds instead of dropping them.
        """
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
                strokes = rnd_data.get("score")
                if strokes is None:
                    strokes = rnd_data.get("strokes")
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
                        score_to_par=int(rnd_data.get("score_to_par", int(strokes) - 72)),
                        tee_time=_round_datetime(start_date, rnum),
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
        """All rounds for a tournament, dated from the event's start date."""
        tournament = await self._find_tournament(tournament_id)
        if tournament is not None:
            rows = await self._event_rows(tournament_id, tournament.start_date.year)
            return self._rounds_from_rows(rows, tournament_id, tournament.start_date)

        # No schedule hit — try recent years and date from Jan 1 of the hit year.
        today = date.today()
        for yr in (today.year, today.year - 1, today.year - 2):
            rows = await self._event_rows(tournament_id, yr)
            if rows:
                return self._rounds_from_rows(rows, tournament_id, date(yr, 1, 1))
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
        need to iterate over recent tournaments. We fetch the relevant seasons'
        schedules and pull rounds for each completed event, filtering by player.

        When ``since`` is given, seasons are enumerated from ``since.year``
        through the current year (capped at ``_MAX_ROUNDS_SEASONS``), so a
        historical as-of date gets its full trailing window — a caller asking
        for "two years before March 2025" must see 2023/2024 events, which a
        today-relative span would never fetch. Without ``since`` the span
        falls back to ``_HISTORY_SEASONS`` recent seasons to bound API calls.
        The Redis cache (TTL=3600s) ensures a given player's rounds are not
        re-fetched on every request.
        """
        today = date.today()
        if since is not None:
            first_year = max(since.year, today.year - _MAX_ROUNDS_SEASONS + 1)
            target_seasons = list(range(today.year, first_year - 1, -1))
        else:
            target_seasons = [today.year - i for i in range(_HISTORY_SEASONS)]

        # Collect completed/in-progress tournaments sorted newest-first
        all_tournaments: list[Tournament] = []
        for yr in target_seasons:
            events = await self._fetch_schedule(yr)
            all_tournaments.extend(
                t for t in events
                if t.status in (TournamentStatus.COMPLETED, TournamentStatus.IN_PROGRESS)
            )
        all_tournaments.sort(key=lambda t: t.start_date, reverse=True)

        player_rounds: list[Round] = []
        for tournament in all_tournaments:
            if len(player_rounds) >= limit:
                break
            if since and tournament.end_date < since:
                continue
            target = _entry_id(tournament.id, player_id)
            rows = await self._event_rows(tournament.id, tournament.start_date.year)
            event_rounds = self._rounds_from_rows(
                rows, tournament.id, tournament.start_date
            )
            player_rounds.extend(
                rnd for rnd in event_rounds if rnd.entry_id == target
            )

        # Newest first — by actual round date now that rounds are dated, so
        # rounds from different events interleave correctly for time decay.
        player_rounds.sort(
            key=lambda r: r.tee_time or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
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

    # -----------------------------------------------------------------------
    # Real sportsbook odds  —  GET /betting-tools/outrights
    # -----------------------------------------------------------------------

    async def get_outright_odds(self, market: str) -> OutrightOdds | None:
        """Live outright odds for the current event, as a consensus across books.

        ``market`` is one of our outcome keys (``"win_prob"`` …); it's mapped to
        DataGolf's market name. Each player's line is the median across the
        books quoting them (DataGolf's own baseline excluded), keyed by
        ``dg_id`` so the betting service can match it to the simulated field.

        The endpoint only ever returns the single current/upcoming event, so the
        caller is responsible for deciding whether those odds apply to the
        tournament it's pricing (it does this by matching player ids).
        """
        dg_market = _DG_MARKET.get(market)
        if dg_market is None:
            return None
        try:
            r = await self._http.get(
                "/betting-tools/outrights",
                params={
                    "tour": "pga",
                    "market": dg_market,
                    "odds_format": "american",
                },
            )
            r.raise_for_status()
        except httpx.HTTPError:
            return None
        body: Any = r.json()
        if not isinstance(body, dict):
            return None
        rows: Any = body.get("odds", [])
        if not isinstance(rows, list):
            return None
        odds: dict[int, int] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            dg_id = row.get("dg_id")
            if not dg_id:
                continue
            consensus = _consensus_american(row)
            if consensus is not None:
                odds[int(dg_id)] = consensus
        if not odds:
            return None
        return OutrightOdds(
            event_name=str(body.get("event_name", "")),
            market=dg_market,
            last_updated=body.get("last_updated"),
            odds=odds,
        )
