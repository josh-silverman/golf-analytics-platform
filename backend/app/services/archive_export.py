"""Export and restore of the immutable forward archives.

The production board and matchup archives live in a Render free-tier Key
Value instance, which has **no persistence**: any restart of that service
can erase the entire forward record. This module makes that survivable.

Export produces one deterministic JSON-safe document containing every board
snapshot and every matchup snapshot. Deterministic matters: a scheduled job
commits the export to a private git repository, and byte-identical output
for an unchanged archive lets that job skip empty commits — so the export
carries no timestamp and both lists are stably sorted. The git history of
those commits doubles as an independent witness that each prediction
existed before its event.

Import re-seeds an archive from an export document. It rides the archives'
own first-write-wins contract (`persist` refuses existing keys), so a
restore is idempotent and can never overwrite a snapshot that survived in
the live store — importing an old dump onto a newer archive only fills
gaps. Entries that fail to parse are counted, not fatal: restoring most of
a record beats restoring none of it.

The export contains DataGolf-derived data. DataGolf's terms are personal
use only, no redistribution — the committed dump must live in a PRIVATE
repository, never the public one.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from app.services.board_archive import _from_dict as _board_from_dict
from app.services.matchup_line_record import _from_dict as _matchup_from_dict

if TYPE_CHECKING:
    from app.services.board_archive import BoardArchive
    from app.services.matchup_line_record import MatchupArchive

# Bumped when the document layout changes shape (not when snapshot fields
# drift — the snapshot deserializers already tolerate unknown/missing keys).
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ArchiveImportResult:
    """Per-archive outcome of a restore: stored, already-present, unparseable."""

    boards_stored: int
    boards_skipped: int
    boards_errors: int
    matchups_stored: int
    matchups_skipped: int
    matchups_errors: int


async def export_archives(
    *,
    boards: BoardArchive,
    matchups: MatchupArchive,
) -> dict[str, Any]:
    """Every snapshot from both archives as one deterministic document."""
    board_snaps = sorted(
        await boards.list_all(),
        key=lambda s: (s.tournament_id, s.model_version_id or ""),
    )
    matchup_snaps = sorted(await matchups.list_all(), key=lambda s: (s.year, s.slug))
    return {
        "schema_version": SCHEMA_VERSION,
        "boards": [asdict(s) for s in board_snaps],
        "matchups": [asdict(s) for s in matchup_snaps],
    }


async def import_archives(
    payload: dict[str, Any],
    *,
    boards: BoardArchive,
    matchups: MatchupArchive,
) -> ArchiveImportResult:
    """Re-seed the archives from an export document, first-write-wins."""
    b_stored = b_skipped = b_errors = 0
    for raw in payload.get("boards") or []:
        try:
            # The deserializers pop keys from their input (nested dicts too, on
            # the matchup side); deep-copy so the caller's payload survives.
            snap = _board_from_dict(copy.deepcopy(raw))
        except (ValueError, TypeError, AttributeError):
            b_errors += 1
            continue
        if await boards.persist(snap):
            b_stored += 1
        else:
            b_skipped += 1

    m_stored = m_skipped = m_errors = 0
    for raw in payload.get("matchups") or []:
        try:
            matchup_snap = _matchup_from_dict(copy.deepcopy(raw))
        except (ValueError, TypeError, AttributeError):
            m_errors += 1
            continue
        if await matchups.persist(matchup_snap):
            m_stored += 1
        else:
            m_skipped += 1

    return ArchiveImportResult(
        boards_stored=b_stored,
        boards_skipped=b_skipped,
        boards_errors=b_errors,
        matchups_stored=m_stored,
        matchups_skipped=m_skipped,
        matchups_errors=m_errors,
    )
