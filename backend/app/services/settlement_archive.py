"""Immutable per-tournament settlement records — what actually happened.

The forward grader used to re-read results from the live provider on every
request, which made the historical record dependent on DataGolf being
reachable, still subscribed, and still returning the same results it
returned last week: a provider-side data revision would have silently
changed a published number with no diff and no alarm. This module pins the
results instead. On the first grade of a completed event, the field's final
positions and entry statuses are written here immutably (first write wins,
same contract as the board archive), and every later grade reads this
record rather than the provider. The provider is consulted only to *create*
a missing settlement, never to re-read one that exists.

**Initial pinning, a deliberate decision (Josh, 2026-08-20):** the events
graded before this module existed have no settlement records, so the first
grading run after it ships writes settlements for all of them from the
provider's *current* view — for events that finished weeks earlier. That is
the best available evidence (DataGolf's settled results for completed
events are stable in practice), but it is a reconstruction of settlement
truth, not a capture made at settlement time, and ``settled_at`` records
when the pin happened, not when the event settled. This is accepted rather
than accidental.

Entry statuses are stored as their ``EntryStatus`` string values. A stored
status that a future build no longer recognises is treated as ungradeable
for that player (like WD/DQ/active today), never guessed at.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from app.domain.enums import EntryStatus

if TYPE_CHECKING:
    from pathlib import Path

    from redis.asyncio import Redis

    from app.domain.models import Tournament, TournamentEntry


@dataclass(frozen=True)
class SettlementEntry:
    """One player's settled result: position and terminal status."""

    player_id: int
    final_position: int | None
    status: str  # EntryStatus value ("made_cut", "missed_cut", "withdrew", …)

    def entry_status(self) -> EntryStatus | None:
        """The stored status as an ``EntryStatus``, or ``None`` if this build
        does not recognise it (graded as ungradeable, never guessed)."""
        try:
            return EntryStatus(self.status)
        except ValueError:
            return None


@dataclass(frozen=True)
class SettlementRecord:
    """A completed tournament's pinned results, written once."""

    tournament_id: int
    tournament_name: str
    tournament_start_date: str  # ISO date
    provider: str  # data-provider name the results were read from
    settled_at: str  # ISO timestamp of the pin — not of the event settling
    entries: tuple[SettlementEntry, ...]


def settlement_from_field(
    tournament: Tournament,
    field: list[TournamentEntry],
    *,
    provider: str,
) -> SettlementRecord:
    """Build the record to pin from a provider-read field."""
    return SettlementRecord(
        tournament_id=tournament.id,
        tournament_name=tournament.name,
        tournament_start_date=tournament.start_date.isoformat(),
        provider=provider,
        settled_at=datetime.now(UTC).isoformat(),
        entries=tuple(
            SettlementEntry(
                player_id=e.player_id,
                final_position=e.final_position,
                status=e.status.value,
            )
            for e in field
        ),
    )


def _to_json(record: SettlementRecord) -> str:
    return json.dumps(asdict(record), default=str)


def _from_dict(data: dict[str, Any]) -> SettlementRecord:
    """Rebuild a record, dropping unknown keys and defaulting late-added
    fields, so settlements survive schema drift in either direction — the
    pinned results must not silently vanish across a deploy."""
    entries = tuple(
        SettlementEntry(**{k: v for k, v in e.items() if k in _ENTRY_FIELDS})
        for e in data.pop("entries", [])
    )
    known = {f.name for f in fields(SettlementRecord)}
    return SettlementRecord(entries=entries, **{k: v for k, v in data.items() if k in known})


_ENTRY_FIELDS = {f.name for f in fields(SettlementEntry)}


class SettlementArchive(Protocol):
    """Immutable per-tournament settlement store, first write wins."""

    async def has(self, tournament_id: int) -> bool: ...

    async def get(self, tournament_id: int) -> SettlementRecord | None: ...

    async def persist(self, record: SettlementRecord) -> bool:
        """Write a record immutably. Returns ``False`` if one already exists."""
        ...

    async def list_all(self) -> list[SettlementRecord]: ...


class FileSettlementArchive:
    """Filesystem settlements — dev/tests, ephemeral on redeploying hosts."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, tournament_id: int) -> Path:
        return self._root / f"{tournament_id}.json"

    async def has(self, tournament_id: int) -> bool:
        return self._path(tournament_id).exists()

    async def get(self, tournament_id: int) -> SettlementRecord | None:
        path = self._path(tournament_id)
        if not path.exists():
            return None
        try:
            return _from_dict(json.loads(path.read_text()))
        except (ValueError, TypeError):
            return None

    async def persist(self, record: SettlementRecord) -> bool:
        path = self._path(record.tournament_id)
        if path.exists():
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic-ish, same as the board archive: a crash mid-write must not
        # leave a half-record that reads as pinned truth.
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(_to_json(record))
        tmp.rename(path)
        return True

    async def list_all(self) -> list[SettlementRecord]:
        out: list[SettlementRecord] = []
        if not self._root.exists():
            return out
        for path in self._root.glob("*.json"):
            try:
                out.append(_from_dict(json.loads(path.read_text())))
            except (ValueError, TypeError):
                continue
        return out


class RedisSettlementArchive:
    """Redis settlements — production, immutability via ``SET … NX``."""

    _PREFIX = "pga:settlement_archive:"

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def _key(self, tournament_id: int) -> str:
        return f"{self._PREFIX}{tournament_id}"

    async def has(self, tournament_id: int) -> bool:
        return bool(await self._redis.exists(self._key(tournament_id)))

    async def get(self, tournament_id: int) -> SettlementRecord | None:
        raw = await self._redis.get(self._key(tournament_id))
        if not raw:
            return None
        try:
            return _from_dict(json.loads(raw))
        except (ValueError, TypeError):
            return None

    async def persist(self, record: SettlementRecord) -> bool:
        ok = await self._redis.set(self._key(record.tournament_id), _to_json(record), nx=True)
        return bool(ok)

    async def list_all(self) -> list[SettlementRecord]:
        keys = [key async for key in self._redis.scan_iter(match=f"{self._PREFIX}*")]
        if not keys:
            return []
        out: list[SettlementRecord] = []
        for raw in await self._redis.mget(keys):
            if not raw:
                continue
            try:
                out.append(_from_dict(json.loads(raw)))
            except (ValueError, TypeError):
                continue
        return out
