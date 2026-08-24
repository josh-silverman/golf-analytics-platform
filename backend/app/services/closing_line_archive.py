"""Immutable pre-event capture of the sportsbook outright market (A5).

The forward record currently grades the served board against one named
baseline: the field base rate. That is the easy bar. The bar a bettor
actually has to clear is the market's own price, and the market's price is
only evidence if it was recorded *before* the event — a line looked up
afterwards is not a prediction, it is a result.

This module captures it. One immutable snapshot per ``(calendar year,
event)`` of DataGolf's ``betting-tools/outrights`` feed across all five
markets, holding every book's American price, DataGolf's own baseline line,
the consensus across books, and the de-vigged probability that consensus
implies. First capture wins, the same contract as the board and matchup
archives.

**Raw prices are the record; the de-vigged probability is a convenience.**
Every book's quote is stored exactly as the feed gave it, so a later fix to
the de-vig math (or a different de-vig entirely) can be recomputed from the
archive rather than being pinned to whatever ``services/betting.py`` did on
the day of capture. Only the raw side is load-bearing.

**The start guard**, and why it is here for the same reason it is on board
capture (see ``services/board_capture``). DataGolf keeps serving
``betting-tools/outrights`` after a field tees off — verified against the
live feed on 2026-08-20, which returned a full 50-player BMW Championship
board while round one was under way. Those are in-play prices, and they
carry no marker distinguishing them from pre-event ones. Because capture is
first-write-wins, a snapshot taken after tee-off is pinned forever and would
silently turn the market baseline into a post-hoc one, which is precisely the
failure this archive exists to rule out. So the same dual signal applies:
the event must still be ``UPCOMING`` *and* today must be strictly before its
start date.

That guard is why the cron runs Wednesday rather than Thursday morning. The
roadmap originally said "shortly before Thursday tee-off", which would be a
truer closing line, but there is no timezone-independent hour on the start
date itself that is provably pre-tee-off (an Open Championship morning wave
is out before 07:00 UTC). The captured line is therefore a late-Wednesday
pre-event line, not the close in the strict CLV sense. Reporting must not
call it a closing line without that qualification; the honest description is
"the last pre-event market price we can capture without risking
contamination". Narrowing to a true close needs tee-time-aware gating, which
is deliberately not built.

The feed's own shapes, both verified live rather than assumed:

* ``odds`` is a **string message** for a market the books are not offering
  ("No make_cut bets being offered right now."), not an empty list. Every
  no-cut event — the FedExCup playoffs, the TOUR Championship — hits this on
  ``make_cut``, so it is a normal state and is recorded as ``offered=False``
  rather than dropping the snapshot.
* the ``datagolf`` key inside a player row is a **nested dict**
  (``{"baseline", "baseline_history_fit"}``), not a price string. It is
  DataGolf's own model line, kept separately and never mixed into the
  consensus across books, which is meant to be the market.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

from app.domain.enums import LineFeedStatus, TournamentStatus
from app.services.betting import (
    american_to_implied_prob,
    devig_field_odds,
    prob_to_american,
)
from app.services.matchup_line_record import event_slug

if TYPE_CHECKING:
    from datetime import date
    from pathlib import Path

    from redis.asyncio import Redis

    from app.domain.models import Tournament
    from app.services.catalog import CatalogService

# Our outcome keys → DataGolf's ``betting-tools/outrights`` market names.
# Deliberately duplicated from the provider rather than imported: this is the
# storage schema of an immutable archive, and it must not silently change
# shape because a serving-side mapping was edited.
MARKETS: tuple[tuple[str, str], ...] = (
    ("win_prob", "win"),
    ("top_5_prob", "top_5"),
    ("top_10_prob", "top_10"),
    ("top_20_prob", "top_20"),
    ("make_cut_prob", "make_cut"),
)

# Keys in a player row that are not a sportsbook quote.
_NON_BOOK_KEYS = frozenset({"dg_id", "player_name", "datagolf"})


@dataclass(frozen=True)
class BookPrice:
    """One book's American price on one player in one market."""

    book: str
    american: int


@dataclass(frozen=True)
class PlayerLine:
    """Every captured price for one player in one market.

    ``consensus_american`` is the median across real books taken in
    probability space (the only meaningful average for odds), so one book's
    outlier cannot skew it. ``devigged_prob`` is that consensus after the
    field-normalization de-vig; both are derived from ``prices`` and can be
    recomputed.
    """

    dg_id: int
    prices: tuple[BookPrice, ...]
    dg_baseline: int | None = None
    dg_baseline_history_fit: int | None = None
    consensus_american: int | None = None
    devigged_prob: float | None = None


@dataclass(frozen=True)
class MarketLines:
    """One market's captured board, or the record that it was not offered."""

    market: str  # our outcome key, e.g. "win_prob"
    dg_market: str  # DataGolf's name, e.g. "win"
    offered: bool
    lines: tuple[PlayerLine, ...] = ()
    books_offering: tuple[str, ...] = ()
    last_updated: str | None = None
    # The feed's own message when ``offered`` is false, kept verbatim so a
    # later reader can tell "no cut at this event" from "feed was broken".
    detail: str | None = None
    # A ``LineFeedStatus`` value: whether this market is what the parser
    # expected. ``None`` only on snapshots written before the field existed.
    status: str | None = None
    # Values that were numeric (or otherwise present) but could not be an
    # American price, so were refused rather than stored. Non-zero means the
    # feed's odds format probably changed.
    prices_rejected: int = 0
    # Lines that carried DataGolf's own baseline. Zero across a priced market
    # means the ``datagolf`` object changed shape, not that coverage is thin.
    baseline_rows: int = 0


@dataclass(frozen=True)
class ClosingLineSnapshot:
    """The full pre-event outright board for one event, captured once."""

    event_name: str
    year: int  # calendar year at capture; joins like the matchup archive
    captured_at: str  # ISO timestamp
    markets: tuple[MarketLines, ...]
    # Resolved from the catalog at capture time. Stored because the feed gives
    # only a name, and the grader needs the id to join to a board snapshot.
    tournament_id: int | None = None
    tournament_start_date: str | None = None
    # Worst status across the offered markets — the one field a scheduled run
    # or `archive-inspect` needs to read. ``None`` only on snapshots written
    # before the field existed.
    status: str | None = None

    @property
    def is_clean(self) -> bool:
        """True when nothing about this capture needs a human to look at it."""
        if self.status is None:
            return False  # written before the check existed; unknowable now
        try:
            return LineFeedStatus(self.status).is_clean
        except ValueError:
            return False  # a status from a newer build than this one

    @property
    def slug(self) -> str:
        return event_slug(self.event_name)

    def market(self, key: str) -> MarketLines | None:
        for m in self.markets:
            if m.market == key:
                return m
        return None


# American odds are undefined between -100 and +100: a positive price is the
# profit on a 100 stake, a negative one the stake needed to win 100, and even
# money is exactly ±100. A value inside that band is therefore not a price
# that got rounded oddly, it is a price in some other format. This is
# arithmetic rather than a tuned threshold, so it cannot fire spuriously.
_MIN_ABS_AMERICAN = 100

# Values that mean "this book is not pricing this player". Absent, not wrong.
_UNPRICED = frozenset({"", "NA", "N/A", "-", "NONE", "NULL"})


def _parse_american(raw: Any) -> tuple[int | None, bool]:
    """``(price, was_rejected)`` for one raw odds value.

    ``was_rejected`` separates "the book is not pricing this" from "the feed
    handed us something that is not an American price". Both yield no price,
    and only the second is evidence the feed changed shape — which is exactly
    the distinction that was missing when a decimal ``4.2`` became ``+4``.
    """
    if raw is None or isinstance(raw, dict | list | bool):
        return None, raw is not None
    text = str(raw).strip().replace("+", "")
    if text.upper() in _UNPRICED:
        return None, False
    try:
        value = int(round(float(text)))
    except ValueError:
        return None, True
    if abs(value) < _MIN_ABS_AMERICAN:
        # Decimal odds ("4.2"), fractional, or a probability. Never a price.
        return None, True
    return value, False


def _price(raw: Any) -> int | None:
    """The price alone, for callers that do not track rejections."""
    return _parse_american(raw)[0]


def _consensus(prices: tuple[BookPrice, ...]) -> int | None:
    """Median book price, averaged in probability space then converted back."""
    probs = [american_to_implied_prob(p.american) for p in prices]
    if not probs:
        return None
    median = statistics.median(probs)
    if not 0.0 < median < 1.0:
        return None
    return prob_to_american(median)


def _market_from_feed(feed: dict[str, Any], *, market: str, dg_market: str) -> MarketLines:
    """Build one market's captured board from a raw outrights response.

    A market the books are not offering comes back with ``odds`` as a message
    string; that is recorded rather than treated as an error.
    """
    raw_rows = feed.get("odds")
    last_updated = str(feed["last_updated"]) if feed.get("last_updated") else None
    if not isinstance(raw_rows, list):
        return MarketLines(
            market=market,
            dg_market=dg_market,
            offered=False,
            last_updated=last_updated,
            detail=str(raw_rows) if raw_rows else "market not offered",
            status=LineFeedStatus.NOT_OFFERED.value,
        )

    lines: list[PlayerLine] = []
    rejected = 0
    baseline_rows = 0
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        dg_id = row.get("dg_id")
        if not isinstance(dg_id, int):
            continue
        prices: list[BookPrice] = []
        for book, value in sorted(row.items()):
            if book in _NON_BOOK_KEYS:
                continue
            american, was_rejected = _parse_american(value)
            # A refused value is counted, never stored. Storing it is how a
            # decimal 4.2 became an American +4 and a 0.96 implied
            # probability; dropping it silently is how nobody found out.
            rejected += int(was_rejected)
            if american is not None:
                prices.append(BookPrice(book=str(book), american=american))
        dg = row.get("datagolf")
        if not isinstance(dg, dict):
            # Flattened, absent, or some other shape. Counted as a rejection
            # only when it held something, so a row DataGolf simply does not
            # model is not mistaken for a shape change.
            rejected += int(dg is not None)
            dg = {}
        # DataGolf's own line is quoted in the same units as the books, so a
        # format change shows up here too and counts as the same evidence.
        baseline, baseline_bad = _parse_american(dg.get("baseline"))
        _, history_bad = _parse_american(dg.get("baseline_history_fit"))
        rejected += int(baseline_bad) + int(history_bad)
        if baseline is not None:
            baseline_rows += 1
        if not prices and baseline is None:
            continue
        lines.append(
            PlayerLine(
                dg_id=dg_id,
                prices=tuple(prices),
                dg_baseline=baseline,
                dg_baseline_history_fit=_price(dg.get("baseline_history_fit")),  # noqa: E501
                consensus_american=_consensus(tuple(prices)),
            )
        )
    if not lines:
        return MarketLines(
            market=market,
            dg_market=dg_market,
            offered=False,
            last_updated=last_updated,
            detail="no priced players in feed",
            status=(LineFeedStatus.SUSPECT_PRICES if rejected else LineFeedStatus.NO_DATA).value,
            prices_rejected=rejected,
        )

    # De-vig the consensus across the field it was quoted on. Markets with a
    # known theoretical total (one winner, five top-5s, …) normalize to it;
    # make_cut has no fixed total and strips a flat margin instead.
    consensus = {ln.dg_id: ln.consensus_american for ln in lines}
    devigged = devig_field_odds(
        {pid: odds for pid, odds in consensus.items() if odds is not None},
        outcome_key=market,
    )
    lines = [
        PlayerLine(
            dg_id=ln.dg_id,
            prices=ln.prices,
            dg_baseline=ln.dg_baseline,
            dg_baseline_history_fit=ln.dg_baseline_history_fit,
            consensus_american=ln.consensus_american,
            devigged_prob=devigged.get(ln.dg_id),
        )
        for ln in lines
    ]
    books = feed.get("books_offering")
    # Precedence: a refused price is the louder signal, because it means the
    # feed handed us something that is not a price at all. A market with no
    # baseline at all is the second — partial baseline coverage is normal, so
    # only a total absence is evidence of shape rather than of coverage.
    if rejected:
        status = LineFeedStatus.SUSPECT_PRICES
    elif baseline_rows == 0:
        status = LineFeedStatus.MISSING_BASELINE
    else:
        status = LineFeedStatus.OK
    return MarketLines(
        market=market,
        dg_market=dg_market,
        offered=True,
        lines=tuple(sorted(lines, key=lambda ln: ln.dg_id)),
        books_offering=tuple(str(b) for b in books) if isinstance(books, list) else (),
        last_updated=last_updated,
        status=status.value,
        prices_rejected=rejected,
        baseline_rows=baseline_rows,
    )


# Worst-first, so the roll-up reports the loudest problem across the five
# markets. NOT_OFFERED is absent deliberately: a market the books do not offer
# is a fact about the event, not a fault, and letting it outrank OK would make
# every no-cut event look degraded.
_STATUS_SEVERITY = (
    LineFeedStatus.SUSPECT_PRICES,
    LineFeedStatus.NO_DATA,
    LineFeedStatus.MISSING_BASELINE,
)


def markets_from_feeds(feeds: dict[str, dict[str, Any]]) -> tuple[MarketLines, ...]:
    """Parse all five markets. Separate from ``snapshot_from_feeds`` because a
    run where *nothing* survived still needs to report why: "no market was
    priced" and "every price was in the wrong format" are different failures
    and only one of them is worth retrying."""
    return tuple(
        _market_from_feed(feeds.get(dg_market, {}), market=market, dg_market=dg_market)
        for market, dg_market in MARKETS
    )


def _worst_status(markets: tuple[MarketLines, ...]) -> LineFeedStatus:
    present = {m.status for m in markets}
    for candidate in _STATUS_SEVERITY:
        if candidate.value in present:
            return candidate
    return LineFeedStatus.OK


def snapshot_from_feeds(
    feeds: dict[str, dict[str, Any]],
    *,
    year: int,
    tournament_id: int | None = None,
    tournament_start_date: date | None = None,
) -> ClosingLineSnapshot | None:
    """Build a snapshot from ``{dg_market: raw response}``.

    Returns ``None`` when no market named an event (an off week, or a feed
    outage across the board). A snapshot survives as long as *one* market was
    offered, since a no-cut event legitimately has only four.
    """
    event_name = ""
    for _, dg_market in MARKETS:
        name = feeds.get(dg_market, {}).get("event_name")
        if isinstance(name, str) and name:
            event_name = name
            break
    if not event_name:
        return None

    markets = markets_from_feeds(feeds)
    if not any(m.offered for m in markets):
        return None
    return ClosingLineSnapshot(
        event_name=event_name,
        year=year,
        captured_at=datetime.now(UTC).isoformat(),
        markets=markets,
        status=_worst_status(markets).value,
        tournament_id=tournament_id,
        tournament_start_date=(
            tournament_start_date.isoformat() if tournament_start_date else None
        ),
    )


# ---------------------------------------------------------------------------
# Storage — same immutability contract and backends as the other archives.
# ---------------------------------------------------------------------------


def _to_json(snapshot: ClosingLineSnapshot) -> str:
    return json.dumps(asdict(snapshot), default=str)


def _from_dict(data: dict[str, Any]) -> ClosingLineSnapshot:
    """Rebuild a snapshot, dropping unknown keys and defaulting late-added
    fields, so snapshots survive schema drift in either direction."""
    markets: list[MarketLines] = []
    for raw_market in data.pop("markets", []):
        lines = tuple(
            PlayerLine(
                prices=tuple(BookPrice(**p) for p in raw_line.pop("prices", [])),
                **{k: v for k, v in raw_line.items() if k in {f.name for f in fields(PlayerLine)}},
            )
            for raw_line in raw_market.pop("lines", [])
        )
        markets.append(
            MarketLines(
                market=str(raw_market.get("market", "")),
                dg_market=str(raw_market.get("dg_market", "")),
                offered=bool(raw_market.get("offered", False)),
                lines=lines,
                books_offering=tuple(str(b) for b in raw_market.get("books_offering") or ()),
                last_updated=raw_market.get("last_updated"),
                detail=raw_market.get("detail"),
                status=raw_market.get("status"),
                prices_rejected=int(raw_market.get("prices_rejected") or 0),
                baseline_rows=int(raw_market.get("baseline_rows") or 0),
            )
        )
    known = {f.name for f in fields(ClosingLineSnapshot)}
    return ClosingLineSnapshot(
        markets=tuple(markets), **{k: v for k, v in data.items() if k in known}
    )


class ClosingLineArchive(Protocol):
    """Immutable per-``(year, event)`` outright-line store."""

    async def has(self, year: int, slug: str) -> bool: ...

    async def persist(self, snapshot: ClosingLineSnapshot) -> bool:
        """Write a snapshot immutably. Returns ``False`` if one already exists."""
        ...

    async def list_all(self) -> list[ClosingLineSnapshot]: ...


class FileClosingLineArchive:
    """Filesystem archive — dev/tests, ephemeral on redeploying hosts."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, year: int, slug: str) -> Path:
        return self._root / str(year) / f"{slug}.json"

    async def has(self, year: int, slug: str) -> bool:
        return self._path(year, slug).exists()

    async def persist(self, snapshot: ClosingLineSnapshot) -> bool:
        path = self._path(snapshot.year, snapshot.slug)
        if path.exists():
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(_to_json(snapshot))
        tmp.rename(path)
        return True

    async def list_all(self) -> list[ClosingLineSnapshot]:
        out: list[ClosingLineSnapshot] = []
        if not self._root.exists():
            return out
        for path in self._root.glob("*/*.json"):
            try:
                out.append(_from_dict(json.loads(path.read_text())))
            except (ValueError, TypeError):
                continue  # skip a corrupt snapshot rather than fail the read
        return out


class RedisClosingLineArchive:
    """Redis-backed archive — survives redeploys. ``SET … NX`` enforces
    first-capture-wins atomically; no TTL, the record accumulates forever."""

    _PREFIX = "pga:closing_line_archive:"

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def _key(self, year: int, slug: str) -> str:
        return f"{self._PREFIX}{year}:{slug}"

    async def has(self, year: int, slug: str) -> bool:
        return bool(await self._redis.exists(self._key(year, slug)))

    async def persist(self, snapshot: ClosingLineSnapshot) -> bool:
        ok = await self._redis.set(
            self._key(snapshot.year, snapshot.slug), _to_json(snapshot), nx=True
        )
        return bool(ok)

    async def list_all(self) -> list[ClosingLineSnapshot]:
        keys = [key async for key in self._redis.scan_iter(match=f"{self._PREFIX}*")]
        if not keys:
            return []
        out: list[ClosingLineSnapshot] = []
        for raw in await self._redis.mget(keys):
            if not raw:
                continue
            try:
                out.append(_from_dict(json.loads(raw)))
            except (ValueError, TypeError):
                continue
        return out


# ---------------------------------------------------------------------------
# Capture — the one decision point, guard included.
# ---------------------------------------------------------------------------


class OutrightFeedSource(Protocol):
    """The single provider read capture needs (duck-typed, so the capture
    tests use a stub and a feedless provider degrades instead of raising)."""

    async def fetch_live_outrights(self, market: str) -> dict[str, Any]: ...


class ClosingLineOutcome(StrEnum):
    """Why a capture attempt did or did not write a snapshot."""

    CAPTURED = "captured"
    # Idempotent no-op: this event already has a snapshot.
    ALREADY_CAPTURED = "already_captured"
    # Refused by the start guard — the capture window for this event is gone.
    EVENT_ALREADY_STARTED = "event_already_started"
    # The feed named an event the catalog does not have, so the guard cannot
    # be evaluated. Refused rather than captured: an unverifiable line is
    # exactly the one that might be in-play, and the write is permanent.
    EVENT_NOT_IN_CATALOG = "event_not_in_catalog"
    # The feed named no event at all (off week) — nothing to capture.
    NO_EVENT = "no_event"
    # An event, but not one market priced. Unhealthy: a real pre-event
    # Wednesday always has a win market up.
    NO_MARKETS = "no_markets"
    # The feed parsed, but not into what it should be — an odds format that is
    # not American, or DataGolf's baseline object changed shape. Refused on
    # the first run of the evening so the retry gets a real chance at a clean
    # one; the retry captures it labelled instead, because a stamped degraded
    # line beats no line for the week.
    FEED_SUSPECT = "feed_suspect"

    @property
    def is_healthy(self) -> bool:
        """True when the outcome is a normal one for a scheduled run.

        A fresh capture, an idempotent no-op, and a genuine off week are all
        fine. Everything else means this event's market baseline was not
        recorded and cannot be recovered later, which is worth failing over.
        """
        return self in (
            ClosingLineOutcome.CAPTURED,
            ClosingLineOutcome.ALREADY_CAPTURED,
            ClosingLineOutcome.NO_EVENT,
        )

    @property
    def is_retryable(self) -> bool:
        """True when a later run this same evening could still do better.

        Only the suspect-feed refusal qualifies: nothing was written, so
        first-write-wins has not closed the door. A started event will not
        un-start and a missing catalog entry will not appear at 23:30.
        """
        return self is ClosingLineOutcome.FEED_SUSPECT


@dataclass(frozen=True)
class ClosingLineCaptureResult:
    outcome: ClosingLineOutcome
    event_name: str | None = None
    year: int | None = None
    tournament_id: int | None = None
    tournament_start_date: str | None = None
    markets_offered: int = 0
    players: int = 0
    # A ``LineFeedStatus`` roll-up for the snapshot this run built, whether or
    # not it was stored.
    status: str | None = None
    prices_rejected: int = 0


async def _resolve_tournament(catalog: CatalogService, slug: str) -> Tournament | None:
    """Find the catalog tournament the feed's event name refers to.

    Both sides are DataGolf's own naming (the schedule feed and the betting
    feed), so slug matching only absorbs incidental punctuation drift. Scans
    upcoming and in-progress: an in-progress match is not a failure to
    resolve, it is the guard firing correctly.
    """
    for status in (TournamentStatus.UPCOMING, TournamentStatus.IN_PROGRESS):
        page = await catalog.list_tournaments(status=status, limit=200)
        for t in page.items:
            if event_slug(t.name) == slug:
                return t
    return None


async def capture_closing_lines(
    *,
    catalog: CatalogService,
    archive: ClosingLineArchive,
    source: OutrightFeedSource,
    today: date,
    allow_degraded: bool = True,
) -> ClosingLineCaptureResult:
    """Capture this week's outright market as an immutable snapshot, if allowed.

    Order of checks mirrors ``capture_pre_event_board``: the existing-snapshot
    check comes *before* the start guard, so the normal retry reports an
    idempotent no-op rather than a refusal.

    ``allow_degraded=False`` additionally refuses a snapshot whose feed did not
    parse into what it should have (``LineFeedStatus.SUSPECT_PRICES`` and the
    like), so a later run the same evening can still capture a clean one. It
    defaults to ``True`` because the last run before the window closes would
    rather have a labelled degraded line than none at all.
    """
    feeds: dict[str, dict[str, Any]] = {}
    for _, dg_market in MARKETS:
        feed = await source.fetch_live_outrights(dg_market)
        if isinstance(feed, dict):
            feeds[dg_market] = feed

    year = today.year
    draft = snapshot_from_feeds(feeds, year=year)
    if draft is None:
        # Three different failures wear the same empty result, and they want
        # different reactions: an off week is fine, an unpriced event is a
        # loud failure, and a feed whose every value was refused is worth
        # retrying because the format may be transient.
        parsed = markets_from_feeds(feeds)
        rejected = sum(m.prices_rejected for m in parsed)
        named = any(feeds.get(dg, {}).get("event_name") for _, dg in MARKETS)
        if rejected:
            return ClosingLineCaptureResult(
                outcome=ClosingLineOutcome.FEED_SUSPECT,
                event_name=next(
                    (
                        str(feeds[dg]["event_name"])
                        for _, dg in MARKETS
                        if feeds.get(dg, {}).get("event_name")
                    ),
                    None,
                ),
                year=year,
                status=LineFeedStatus.SUSPECT_PRICES.value,
                prices_rejected=rejected,
            )
        return ClosingLineCaptureResult(
            outcome=ClosingLineOutcome.NO_MARKETS if named else ClosingLineOutcome.NO_EVENT
        )

    offered = sum(1 for m in draft.markets if m.offered)
    players = max((len(m.lines) for m in draft.markets), default=0)
    rejected = sum(m.prices_rejected for m in draft.markets)

    if await archive.has(year, draft.slug):
        return ClosingLineCaptureResult(
            outcome=ClosingLineOutcome.ALREADY_CAPTURED,
            event_name=draft.event_name,
            year=year,
            markets_offered=offered,
            players=players,
            status=draft.status,
            prices_rejected=rejected,
        )

    tournament = await _resolve_tournament(catalog, draft.slug)
    if tournament is None:
        return ClosingLineCaptureResult(
            outcome=ClosingLineOutcome.EVENT_NOT_IN_CATALOG,
            event_name=draft.event_name,
            year=year,
            markets_offered=offered,
            players=players,
            status=draft.status,
            prices_rejected=rejected,
        )

    # The start guard, identical in shape to board capture's (§2.2): the
    # provider's own status *or* the calendar backstop is enough to refuse.
    if tournament.status != TournamentStatus.UPCOMING or today >= tournament.start_date:
        return ClosingLineCaptureResult(
            outcome=ClosingLineOutcome.EVENT_ALREADY_STARTED,
            event_name=draft.event_name,
            year=year,
            tournament_id=tournament.id,
            tournament_start_date=tournament.start_date.isoformat(),
            markets_offered=offered,
            players=players,
            status=draft.status,
            prices_rejected=rejected,
        )

    if not allow_degraded and not draft.is_clean:
        # Nothing written, which is the point: first-write-wins would let a
        # 21:00 capture of a mis-formatted feed block the 23:30 retry from
        # doing better. Checked after the start guard so an out-of-window
        # event still reports the reason that actually matters.
        return ClosingLineCaptureResult(
            outcome=ClosingLineOutcome.FEED_SUSPECT,
            event_name=draft.event_name,
            year=year,
            tournament_id=tournament.id,
            tournament_start_date=tournament.start_date.isoformat(),
            markets_offered=offered,
            players=players,
            status=draft.status,
            prices_rejected=rejected,
        )

    snapshot = snapshot_from_feeds(
        feeds,
        year=year,
        tournament_id=tournament.id,
        tournament_start_date=tournament.start_date,
    )
    if snapshot is None:  # pragma: no cover — draft already proved it builds
        return ClosingLineCaptureResult(outcome=ClosingLineOutcome.NO_MARKETS)
    stored = await archive.persist(snapshot)
    return ClosingLineCaptureResult(
        outcome=(ClosingLineOutcome.CAPTURED if stored else ClosingLineOutcome.ALREADY_CAPTURED),
        event_name=snapshot.event_name,
        year=year,
        tournament_id=snapshot.tournament_id,
        tournament_start_date=snapshot.tournament_start_date,
        markets_offered=offered,
        players=players,
        status=snapshot.status,
        prices_rejected=rejected,
    )
