"""Forward record of DataGolf's matchup line against real sportsbook prices.

The 2019-2026 historical-odds backtest (FINDINGS.md, 2026-08-19 addendum)
showed that a fair line built from *other books'* prices no longer finds
exploitable matchup edge (2023-2026 ROI +1.3%, CI includes zero). It could not
test the line the product would actually use — DataGolf's own — because the
historical archive does not store it. The only way to get that evidence is to
capture the live feed before each event and grade it once outcomes settle.
This module is that capture-and-grade loop; the product decision (whether a
matchup surface may ever claim +EV) waits on the record it accumulates.

Capture: one immutable snapshot per (calendar year, event) of DataGolf's
``betting-tools/matchups`` feed — every 2-way tournament matchup, every book's
price, DataGolf's own line, the tie rule, and the capture timestamp. First
capture wins, the same contract as the prediction-board archive: a grade is
only meaningful if the snapshot provably predates the event.

Grade: once the event appears completed in DataGolf's historical-odds archive,
join each captured matchup to its per-side outcome and settle a flat $1 bet on
every side whose captured price beat DataGolf's de-vigged probability by more
than a threshold — both "at any book that cleared the bar" and "only at the
best available price", which is what a real bettor would take.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from pathlib import Path

    from redis.asyncio import Redis

# The live feed's market name and the bet_type the historical archive grades
# it under. Only the 72-hole market is captured: round matchups change daily,
# so a weekly pre-event snapshot cannot time-stamp them honestly.
LIVE_MARKET = "tournament_matchups"
_HIST_BET_TYPE = "72-hole Match"

# Edge thresholds graded, as EV per $1 staked. 0.02 is the headline: the
# historical backtest used the same bar, and anything under ~2 cents is noise
# against line movement between capture and bet.
THRESHOLDS = (0.0, 0.02, 0.05)
HEADLINE_THRESHOLD = 0.02

# Books tried, in coverage order, when looking up an event's settled outcomes.
# Outcomes are properties of the event, not the book; one covering book is
# enough, later ones only fill pairs the earlier ones didn't price.
_OUTCOME_BOOKS = ("bet365", "draftkings", "fanduel", "pinnacle")


@dataclass(frozen=True)
class BookQuote:
    """One book's captured prices for a matchup, American odds.

    ``book`` is DataGolf's book key; the special value "datagolf" is DataGolf's
    own model line, which is the line under test and never a bettable price.
    ``tie`` is only present where the book offers the tie as a separate bet.
    """

    book: str
    p1: int
    p2: int
    tie: int | None = None


@dataclass(frozen=True)
class MatchupRow:
    """One captured matchup: the pairing, the tie rule, and every quote."""

    p1_dg_id: int
    p1_name: str
    p2_dg_id: int
    p2_name: str
    ties: str  # the feed's tie rule text, e.g. "separate bet offered"
    quotes: tuple[BookQuote, ...]

    def quote(self, book: str) -> BookQuote | None:
        for q in self.quotes:
            if q.book == book:
                return q
        return None


@dataclass(frozen=True)
class MatchupSnapshot:
    """The full pre-event matchup board for one event, captured once."""

    event_name: str
    year: int  # calendar year at capture; joins to the archive's calendar_year
    market: str
    captured_at: str  # ISO timestamp
    feed_last_updated: str | None
    rows: tuple[MatchupRow, ...]

    @property
    def slug(self) -> str:
        return event_slug(self.event_name)


def event_slug(name: str) -> str:
    """Casefolded, punctuation-free event name for storage keys and joins.

    Both sides of every comparison are DataGolf's own ``event_name`` (live feed
    vs historical event list), so this only absorbs incidental drift.
    """
    lowered = name.casefold().strip()
    kept = [c if c.isalnum() else " " for c in lowered]
    collapsed = "_".join("".join(kept).split())
    return collapsed.removeprefix("the_")


def _parse_american(raw: Any) -> int | None:
    if raw is None:
        return None
    text = str(raw).strip().replace("+", "")
    if not text or text.upper() in ("NA", "N/A", "-", "NONE"):
        return None
    try:
        return int(round(float(text)))
    except ValueError:
        return None


def snapshot_from_feed(feed: dict[str, Any], *, year: int) -> MatchupSnapshot | None:
    """Build a snapshot from the raw ``betting-tools/matchups`` response.

    Returns ``None`` when the feed has no matchup board (off weeks return a
    message string in ``match_list`` instead of a list). Rows keep every book
    with a complete two-sided quote; a row survives only if it still has at
    least one quote, so the snapshot never stores an ungradeable husk.
    """
    raw_rows = feed.get("match_list")
    event_name = feed.get("event_name")
    if not isinstance(raw_rows, list) or not isinstance(event_name, str) or not event_name:
        return None
    rows: list[MatchupRow] = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        p1_id, p2_id = raw.get("p1_dg_id"), raw.get("p2_dg_id")
        odds = raw.get("odds")
        if not isinstance(p1_id, int) or not isinstance(p2_id, int) or not isinstance(odds, dict):
            continue
        quotes: list[BookQuote] = []
        for book, prices in odds.items():
            if not isinstance(prices, dict):
                continue
            p1, p2 = _parse_american(prices.get("p1")), _parse_american(prices.get("p2"))
            if p1 is None or p2 is None:
                continue
            tie = _parse_american(prices.get("tie"))
            quotes.append(BookQuote(book=str(book), p1=p1, p2=p2, tie=tie))
        if not quotes:
            continue
        rows.append(
            MatchupRow(
                p1_dg_id=p1_id,
                p1_name=str(raw.get("p1_player_name", "")),
                p2_dg_id=p2_id,
                p2_name=str(raw.get("p2_player_name", "")),
                ties=str(raw.get("ties", "")),
                quotes=tuple(quotes),
            )
        )
    if not rows:
        return None
    return MatchupSnapshot(
        event_name=event_name,
        year=year,
        market=str(feed.get("market") or LIVE_MARKET),
        captured_at=datetime.now(UTC).isoformat(),
        feed_last_updated=str(feed["last_updated"]) if feed.get("last_updated") else None,
        rows=tuple(rows),
    )


# ---------------------------------------------------------------------------
# Storage — same immutability contract and backends as the board archive.
# ---------------------------------------------------------------------------


def _to_json(snapshot: MatchupSnapshot) -> str:
    return json.dumps(asdict(snapshot), default=str)


def _from_dict(data: dict[str, Any]) -> MatchupSnapshot:
    """Rebuild a snapshot, dropping unknown keys and defaulting late-added
    fields, so snapshots survive schema drift in either direction (the record
    must not silently lose events across a deploy)."""
    rows = tuple(
        MatchupRow(
            quotes=tuple(BookQuote(**q) for q in r.pop("quotes", [])),
            **{k: v for k, v in r.items() if k in {f.name for f in fields(MatchupRow)}},
        )
        for r in data.pop("rows", [])
    )
    known = {f.name for f in fields(MatchupSnapshot)}
    return MatchupSnapshot(rows=rows, **{k: v for k, v in data.items() if k in known})


class MatchupArchive(Protocol):
    """Immutable per-``(year, event)`` matchup-snapshot store."""

    async def has(self, year: int, slug: str) -> bool: ...

    async def persist(self, snapshot: MatchupSnapshot) -> bool:
        """Write a snapshot immutably. Returns ``False`` if one already exists."""
        ...

    async def list_all(self) -> list[MatchupSnapshot]: ...


class FileMatchupArchive:
    """Filesystem archive — dev/tests, ephemeral on redeploying hosts."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, year: int, slug: str) -> Path:
        return self._root / str(year) / f"{slug}.json"

    async def has(self, year: int, slug: str) -> bool:
        return self._path(year, slug).exists()

    async def persist(self, snapshot: MatchupSnapshot) -> bool:
        path = self._path(snapshot.year, snapshot.slug)
        if path.exists():
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(_to_json(snapshot))
        tmp.rename(path)
        return True

    async def list_all(self) -> list[MatchupSnapshot]:
        out: list[MatchupSnapshot] = []
        if not self._root.exists():
            return out
        for path in self._root.glob("*/*.json"):
            try:
                out.append(_from_dict(json.loads(path.read_text())))
            except (ValueError, TypeError):
                continue  # skip a corrupt snapshot rather than fail the read
        return out


class RedisMatchupArchive:
    """Redis-backed archive — survives redeploys. ``SET … NX`` enforces
    first-capture-wins atomically; no TTL, the record accumulates forever."""

    _PREFIX = "pga:matchup_archive:"

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def _key(self, year: int, slug: str) -> str:
        return f"{self._PREFIX}{year}:{slug}"

    async def has(self, year: int, slug: str) -> bool:
        return bool(await self._redis.exists(self._key(year, slug)))

    async def persist(self, snapshot: MatchupSnapshot) -> bool:
        ok = await self._redis.set(
            self._key(snapshot.year, snapshot.slug), _to_json(snapshot), nx=True
        )
        return bool(ok)

    async def list_all(self) -> list[MatchupSnapshot]:
        keys = [key async for key in self._redis.scan_iter(match=f"{self._PREFIX}*")]
        if not keys:
            return []
        out: list[MatchupSnapshot] = []
        for raw in await self._redis.mget(keys):
            if not raw:
                continue
            try:
                out.append(_from_dict(json.loads(raw)))
            except (ValueError, TypeError):
                continue
        return out


# ---------------------------------------------------------------------------
# Settlement and pricing math.
# ---------------------------------------------------------------------------


def implied_prob(american: int) -> float:
    if american >= 0:
        return 100.0 / (american + 100.0)
    return -american / (-american + 100.0)


def payout(american: int) -> float:
    """Profit on a winning $1 stake."""
    return american / 100.0 if american >= 0 else 100.0 / -american


def settle(outcome: float | None, tie_rule: str, american: int) -> float | None:
    """P&L of $1 staked at ``american``, given DataGolf's graded outcome.

    Outcome semantics from the historical archive: 1 win, 0 loss, 0.5 tie,
    other fractions are dead-heat splits. What a tie does to the stake depends
    on the captured rule: dead-heat pays the fraction, void refunds, and a
    separate tie bet means both 2-way sides lose.
    """
    if outcome is None:
        return None
    o = float(outcome)
    if o == 1.0:
        return payout(american)
    if o == 0.0:
        return -1.0
    rule = tie_rule.casefold()
    if abs(o - 0.5) < 1e-9:
        if "dead" in rule:
            return 0.5 * payout(american) - 0.5
        if "separate" in rule:
            return -1.0
        return 0.0  # void / push
    return o * payout(american) - (1.0 - o)


def fair_probs(dg: BookQuote, tie_rule: str) -> tuple[float, float]:
    """(p1_win, p2_win) implied by DataGolf's line, matched to the tie rule.

    Where ties lose (separate tie bet) and DataGolf prices the tie, the win
    probabilities come from the 3-way de-vig so they leave room for the tie —
    otherwise a plain 2-way de-vig, under which ties refund or split and the
    two probabilities legitimately sum to 1.
    """
    q1, q2 = implied_prob(dg.p1), implied_prob(dg.p2)
    if "separate" in tie_rule.casefold() and dg.tie is not None:
        qt = implied_prob(dg.tie)
        total = q1 + q2 + qt
        return q1 / total, q2 / total
    total = q1 + q2
    return q1 / total, q2 / total


def bet_ev(fair_win: float, fair_lose: float, american: int) -> float:
    """EV per $1 on a side: win probability times profit minus losing mass.

    ``fair_lose`` is the probability the stake is lost — the other side plus,
    under a separate-tie rule, the tie. Refunded/split tie mass contributes
    nothing at the precision this record needs.
    """
    return fair_win * payout(american) - fair_lose


# ---------------------------------------------------------------------------
# Grading.
# ---------------------------------------------------------------------------


class MatchupHistorySource(Protocol):
    """The two DataGolf historical-odds reads grading needs (duck-typed so the
    grader tests with a stub and degrades cleanly on providers without odds)."""

    async def fetch_historical_matchup_event_list(self) -> list[dict[str, Any]]: ...

    async def fetch_historical_matchups(
        self, event_id: int, year: int, book: str
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ThresholdRecord:
    """Flat-$1 record of every bet clearing one edge threshold."""

    min_edge: float
    bets: int
    pnl: float
    roi: float | None


@dataclass(frozen=True)
class GradedEvent:
    event_name: str
    year: int
    matchups_captured: int
    matchups_graded: int
    bets: int  # best-price strategy at the headline threshold
    pnl: float


@dataclass(frozen=True)
class MatchupLineRecord:
    events_captured: int
    events_graded: int
    events_pending: int
    matchups_graded: int
    # Brier of DataGolf's de-vigged 2-way probability against decisive (0/1)
    # outcomes; 0.25 is coin-flip. The sharpness measure that decides whether
    # DataGolf's line is even a credible fair-value reference.
    dg_line_brier: float | None
    dg_line_n: int
    any_price: tuple[ThresholdRecord, ...]
    best_price: tuple[ThresholdRecord, ...]
    events: tuple[GradedEvent, ...]


def _outcome_key(id_a: int, id_b: int) -> tuple[int, int]:
    return (min(id_a, id_b), max(id_a, id_b))


async def _settled_outcomes(
    source: MatchupHistorySource,
    event_id: int,
    year: int,
    wanted: set[tuple[int, int]],
) -> dict[tuple[int, int], float] | None:
    """Per-pair outcome for the lower dg_id's side, or ``None`` if the event
    has not settled in the historical archive yet."""
    found: dict[tuple[int, int], float] = {}
    completed = False
    for book in _OUTCOME_BOOKS:
        body = await source.fetch_historical_matchups(event_id, year, book)
        if body.get("event_completed") is False:
            # Settlement is a property of the event, not the book — no point
            # asking the other books this pass.
            return None
        if not body.get("event_completed"):
            continue
        completed = True
        odds = body.get("odds")
        if not isinstance(odds, list):
            continue
        for row in odds:
            if not isinstance(row, dict) or row.get("bet_type") != _HIST_BET_TYPE:
                continue
            i1, i2, out1, out2 = (
                row.get("p1_dg_id"),
                row.get("p2_dg_id"),
                row.get("p1_outcome"),
                row.get("p2_outcome"),
            )
            if i1 is None or i2 is None or out1 is None or out2 is None:
                continue
            key = _outcome_key(i1, i2)
            if key in found or key not in wanted:
                continue
            found[key] = float(out1) if i1 < i2 else float(out2)
        if wanted <= set(found):
            break
    return found if completed else None


async def compute_matchup_line_record(
    archive: MatchupArchive, source: MatchupHistorySource
) -> MatchupLineRecord | None:
    """Grade every captured snapshot whose event has settled. ``None`` until
    at least one snapshot exists."""
    snapshots = await archive.list_all()
    if not snapshots:
        return None

    hist = await source.fetch_historical_matchup_event_list()
    hist_index = {
        (event_slug(str(e.get("event_name", ""))), int(e["calendar_year"])): int(e["event_id"])
        for e in hist
        if isinstance(e, dict) and e.get("event_id") is not None and e.get("calendar_year")
    }

    any_price = {t: [0, 0.0] for t in THRESHOLDS}  # threshold -> [bets, pnl]
    best_price = {t: [0, 0.0] for t in THRESHOLDS}
    brier_sum, brier_n = 0.0, 0
    graded_events: list[GradedEvent] = []
    matchups_graded = pending = 0

    for snap in sorted(snapshots, key=lambda s: (s.year, s.slug)):
        event_id = hist_index.get((snap.slug, snap.year))
        if event_id is None:
            pending += 1
            continue
        wanted = {_outcome_key(r.p1_dg_id, r.p2_dg_id) for r in snap.rows}
        outcomes = await _settled_outcomes(source, event_id, snap.year, wanted)
        if outcomes is None:
            pending += 1
            continue

        ev_bets, ev_pnl, ev_graded = 0, 0.0, 0
        for row in snap.rows:
            dg = row.quote("datagolf")
            key = _outcome_key(row.p1_dg_id, row.p2_dg_id)
            out_low = outcomes.get(key)  # outcome for the lower dg_id's side
            if dg is None or out_low is None:
                continue
            ev_graded += 1
            fair1, fair2 = fair_probs(dg, row.ties)
            out1 = out_low if row.p1_dg_id < row.p2_dg_id else 1.0 - out_low
            # Fractional outcomes stay fractional for settlement; the Brier
            # sample only admits decisive results.
            if out1 in (0.0, 1.0):
                q1, q2 = implied_prob(dg.p1), implied_prob(dg.p2)
                brier_sum += (q1 / (q1 + q2) - out1) ** 2
                brier_n += 1
            books = [q for q in row.quotes if q.book != "datagolf"]
            for side, fair_win, fair_lose, out in (
                ("p1", fair1, 1.0 - fair1, out1),
                ("p2", fair2, 1.0 - fair2, 1.0 - out1 if out1 in (0.0, 1.0) else out1),
            ):
                prices = [getattr(q, side) for q in books]
                if not prices:
                    continue
                for threshold in THRESHOLDS:
                    for price in prices:
                        if bet_ev(fair_win, fair_lose, price) <= threshold:
                            continue
                        pnl = settle(out, row.ties, price)
                        if pnl is None:
                            continue
                        any_price[threshold][0] += 1
                        any_price[threshold][1] += pnl
                    best = max(prices, key=payout)
                    if bet_ev(fair_win, fair_lose, best) > threshold:
                        pnl = settle(out, row.ties, best)
                        if pnl is not None:
                            best_price[threshold][0] += 1
                            best_price[threshold][1] += pnl
                            if threshold == HEADLINE_THRESHOLD:
                                ev_bets += 1
                                ev_pnl += pnl
        matchups_graded += ev_graded
        graded_events.append(
            GradedEvent(
                event_name=snap.event_name,
                year=snap.year,
                matchups_captured=len(snap.rows),
                matchups_graded=ev_graded,
                bets=ev_bets,
                pnl=round(ev_pnl, 4),
            )
        )

    def _records(acc: dict[float, list[float]]) -> tuple[ThresholdRecord, ...]:
        return tuple(
            ThresholdRecord(
                min_edge=t,
                bets=int(n),
                pnl=round(pnl, 4),
                roi=round(pnl / n, 4) if n else None,
            )
            for t, (n, pnl) in acc.items()
        )

    return MatchupLineRecord(
        events_captured=len(snapshots),
        events_graded=len(graded_events),
        events_pending=pending,
        matchups_graded=matchups_graded,
        dg_line_brier=round(brier_sum / brier_n, 5) if brier_n else None,
        dg_line_n=brier_n,
        any_price=_records(any_price),
        best_price=_records(best_price),
        events=tuple(graded_events),
    )
