"""Forward, out-of-sample prediction-board archive.

The `/analytics/track-record` view grades the *active* model's pre-event boards
against completed events. That is leakage-free on features (as-of capped to the
eve) but **potentially in-sample on the model**: the active model was trained on
events it is now "grading," so a strong score there partly reflects memorisation.
The technical due-diligence review flagged exactly this.

This module fixes it by capturing every board **at the moment it is served for a
not-yet-completed event**, stamped with the exact model version and that model's
training cutoff. When the event later completes, the grader
(`app/services/forward_track_record.py`) admits a snapshot only if its model was
trained *strictly before* the event started — so the resulting record is
genuinely out-of-sample by construction, not just pre-event.

Storage is one immutable JSON snapshot per `(tournament_id, model_version_id)`.
Immutability is the whole point — the first pre-event capture must never be
overwritten by a later (possibly post-completion, possibly retrained) board.
Two interchangeable backends implement the async :class:`BoardArchive` protocol:
a filesystem store (local/dev/test) and a Redis store (production, where the
service's own disk is ephemeral and would drop the archive on every redeploy).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from pathlib import Path

    from redis.asyncio import Redis


@dataclass(frozen=True)
class BoardSnapshotOutcome:
    """One player's captured probabilities (no result — that's graded later)."""

    player_id: int
    win_prob: float
    top_5_prob: float
    top_10_prob: float
    top_20_prob: float
    make_cut_prob: float


@dataclass(frozen=True)
class BoardSnapshot:
    """A pre-event board captured at serving time, with provenance for OOS grading."""

    tournament_id: int
    tournament_name: str
    tournament_start_date: str  # ISO date
    model_name: str
    model_version_id: str | None
    feature_set_hash: str
    model_trained_through: str | None  # ISO date; None → cannot certify OOS
    as_of: str  # ISO date the board was predicted as-of (the eve)
    captured_at: str  # ISO timestamp of capture
    outcomes: tuple[BoardSnapshotOutcome, ...]
    # "captured" — recorded live when the board was served pre-event.
    # "backfilled" — reconstructed after the fact from the served pipeline over
    # a completed event's pre-event DataGolf archive (still leakage-free: as-of
    # capped to the eve, admitted only if trained strictly before the event).
    source: str = "captured"

    def is_out_of_sample(self, start_date: date) -> bool:
        """True iff the producing model was trained strictly before the event.

        Requires a known training cutoff; an unknown cutoff (``None``) is treated
        as NOT certifiable and excluded from the forward record.
        """
        if self.model_trained_through is None:
            return False
        return date.fromisoformat(self.model_trained_through) < start_date


def _to_json(snapshot: BoardSnapshot) -> str:
    return json.dumps(asdict(snapshot), default=str)


def _from_dict(data: dict[str, Any]) -> BoardSnapshot:
    """Rebuild a snapshot from its stored dict. Snapshots written before the
    ``source`` field existed simply default to "captured".
    """
    outcomes = tuple(BoardSnapshotOutcome(**o) for o in data.pop("outcomes", []))
    return BoardSnapshot(outcomes=outcomes, **data)


class BoardArchive(Protocol):
    """Immutable per-``(tournament, model_version)`` snapshot store."""

    async def has(self, tournament_id: int, model_version_id: str | None) -> bool: ...

    async def persist(self, snapshot: BoardSnapshot) -> bool:
        """Write a snapshot immutably. Returns ``False`` if one already exists."""
        ...

    async def list_all(self) -> list[BoardSnapshot]: ...


class FileBoardArchive:
    """Filesystem archive of immutable pre-event board snapshots."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, tournament_id: int, model_version_id: str | None) -> Path:
        version = model_version_id or "unversioned"
        return self._root / str(tournament_id) / f"{version}.json"

    async def has(self, tournament_id: int, model_version_id: str | None) -> bool:
        return self._path(tournament_id, model_version_id).exists()

    async def persist(self, snapshot: BoardSnapshot) -> bool:
        """Write a snapshot immutably. Returns False if one already exists.

        The first capture for a ``(tournament, model_version)`` wins and is never
        overwritten — that is what makes the later grade genuinely pre-event.
        """
        path = self._path(snapshot.tournament_id, snapshot.model_version_id)
        if path.exists():
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic-ish: write to a temp sibling then rename, so a crash mid-write
        # can't leave a half-snapshot that reads as a real capture.
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(_to_json(snapshot))
        tmp.rename(path)
        return True

    async def list_all(self) -> list[BoardSnapshot]:
        """Every captured snapshot across all tournaments."""
        out: list[BoardSnapshot] = []
        if not self._root.exists():
            return out
        for path in self._root.glob("*/*.json"):
            try:
                out.append(_from_dict(json.loads(path.read_text())))
            except (ValueError, TypeError):
                continue  # skip a corrupt snapshot rather than fail the whole read
        return out


class RedisBoardArchive:
    """Redis-backed archive — survives service redeploys (the filesystem doesn't).

    Immutability is enforced by ``SET … NX`` (first write wins atomically), the
    same guarantee the filesystem backend gets from its existence check. Keys are
    ``pga:board_archive:{tournament_id}:{model_version_id}`` and hold the snapshot
    JSON; there is no TTL — the forward record must accumulate indefinitely.
    """

    _PREFIX = "pga:board_archive:"

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def _key(self, tournament_id: int, model_version_id: str | None) -> str:
        version = model_version_id or "unversioned"
        return f"{self._PREFIX}{tournament_id}:{version}"

    async def has(self, tournament_id: int, model_version_id: str | None) -> bool:
        return bool(await self._redis.exists(self._key(tournament_id, model_version_id)))

    async def persist(self, snapshot: BoardSnapshot) -> bool:
        ok = await self._redis.set(
            self._key(snapshot.tournament_id, snapshot.model_version_id),
            _to_json(snapshot),
            nx=True,
        )
        return bool(ok)

    async def list_all(self) -> list[BoardSnapshot]:
        keys = [key async for key in self._redis.scan_iter(match=f"{self._PREFIX}*")]
        if not keys:
            return []
        out: list[BoardSnapshot] = []
        for raw in await self._redis.mget(keys):
            if not raw:
                continue
            try:
                out.append(_from_dict(json.loads(raw)))
            except (ValueError, TypeError):
                continue
        return out


def snapshot_from_predictions(
    predictions: object,
    *,
    tournament_start_date: date,
    model_trained_through: date | None,
    source: str = "captured",
) -> BoardSnapshot:
    """Build a :class:`BoardSnapshot` from a ``TournamentPredictions`` result.

    Kept import-light (duck-typed) so the archive doesn't depend on the
    predictions module and vice-versa. ``source`` records whether this was a live
    capture ("captured") or a post-hoc reconstruction ("backfilled").
    """
    return BoardSnapshot(
        tournament_id=predictions.tournament_id,  # type: ignore[attr-defined]
        tournament_name=predictions.tournament_name,  # type: ignore[attr-defined]
        tournament_start_date=tournament_start_date.isoformat(),
        model_name=predictions.model_name,  # type: ignore[attr-defined]
        model_version_id=predictions.model_version_id,  # type: ignore[attr-defined]
        feature_set_hash=predictions.feature_set_hash,  # type: ignore[attr-defined]
        model_trained_through=(
            model_trained_through.isoformat() if model_trained_through else None
        ),
        as_of=predictions.as_of.isoformat(),  # type: ignore[attr-defined]
        captured_at=datetime.now(UTC).isoformat(),
        outcomes=tuple(
            BoardSnapshotOutcome(
                player_id=o.player_id,
                win_prob=o.win_prob,
                top_5_prob=o.top_5_prob,
                top_10_prob=o.top_10_prob,
                top_20_prob=o.top_20_prob,
                make_cut_prob=o.make_cut_prob,
            )
            for o in predictions.outcomes  # type: ignore[attr-defined]
        ),
        source=source,
    )
