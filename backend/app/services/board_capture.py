"""The one decision point for capturing a pre-event board.

Both capture paths go through :func:`capture_pre_event_board`: the lazy one
(a board served for an upcoming event, ``api/v1/predictions.py``) and the
scheduled one (``POST /analytics/track-record/capture-upcoming``). Sharing
it is the point — a guard that exists on only one path is a guard that a
future caller silently bypasses.

**The start guard.** A board may only be captured while the event has not
started. This matters because capture is permanent: ``persist`` is
first-write-wins, so a board written after play began is pinned forever and
poisons that event's forward record with no error and no diff. The
contamination is specific and real under Path A: ``predict_tournament``
caps feature ``as_of`` to the eve, so features stay clean, but the
DataGolf-direct probabilities are read from the *live* pre-tournament
endpoint for any not-completed event. Once the field has teed off those
numbers reflect play in progress, while the snapshot still presents itself
as a pre-event board.

Play is judged to have begun when *either* signal says so:

* ``status != UPCOMING`` — the provider's own judgment, and the only signal
  that reacts to an actual tee-off rather than to the calendar.
* ``today >= start_date`` — a calendar backstop for a provider whose status
  has not flipped yet. Strict on purpose: tee times span time zones (an
  Open Championship morning wave is under way before 07:00 UTC), so no
  same-day hour is universally safe, and "capture only on a day before the
  event" is the one rule that needs no timezone reasoning to be correct.

The cost of that strictness is that an event starting the same day the job
runs is refused rather than captured. That is the intended trade: a missing
board is recoverable by backfill, a contaminated one is permanent.

The guard deliberately lives here and not in the archive's ``persist``,
because the backfill legitimately writes boards for events that have
already finished (as reconstructions, marked ``source="backfilled"``).
Storage stays policy-free; this module holds the live-capture policy.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from app.domain.enums import TournamentStatus
from app.services.board_archive import snapshot_from_predictions

if TYPE_CHECKING:
    from datetime import date

    from app.services.board_archive import BoardArchive
    from app.services.catalog import CatalogService
    from app.services.predictions import TournamentPredictions


class CaptureOutcome(StrEnum):
    """Why a capture attempt did or did not write a snapshot."""

    CAPTURED = "captured"
    # Idempotent no-op: a snapshot for this (tournament, model version) exists.
    ALREADY_CAPTURED = "already_captured"
    # Refused by the start guard. On a scheduled run this means the capture
    # window for that event was missed, which is worth failing loudly over.
    EVENT_ALREADY_STARTED = "event_already_started"
    NO_FIELD = "no_field"
    NO_TRAINING_CUTOFF = "no_training_cutoff"
    TOURNAMENT_NOT_FOUND = "tournament_not_found"

    @property
    def is_healthy(self) -> bool:
        """True when the outcome is a normal one for a scheduled run.

        A fresh capture and an idempotent no-op are both fine; everything
        else means this event did not get a board and something should say so.
        """
        return self in (CaptureOutcome.CAPTURED, CaptureOutcome.ALREADY_CAPTURED)


async def capture_pre_event_board(
    *,
    catalog: CatalogService,
    archive: BoardArchive,
    predictions: TournamentPredictions,
    today: date,
) -> CaptureOutcome:
    """Capture ``predictions`` as an immutable pre-event board, if allowed.

    Raises whatever the catalog or archive raises; the lazy caller wraps this
    so serving never fails on archival, while the scheduled caller lets
    errors surface.
    """
    if predictions.model_trained_through is None:
        # Cannot certify the board as out-of-sample later, so it would never
        # be graded; do not pin it.
        return CaptureOutcome.NO_TRAINING_CUTOFF
    if not predictions.outcomes:
        # An event whose field is not published yet. Never pin an empty board:
        # first write wins, so the first capture must be one with a real field.
        return CaptureOutcome.NO_FIELD

    tournament = await catalog.get_tournament(predictions.tournament_id)
    if tournament is None:
        return CaptureOutcome.TOURNAMENT_NOT_FOUND

    if await archive.has(predictions.tournament_id, predictions.model_version_id):
        # Checked before the start guard on purpose: the normal retry case is
        # "already captured", and it should report that rather than a refusal.
        return CaptureOutcome.ALREADY_CAPTURED

    if tournament.status != TournamentStatus.UPCOMING or today >= tournament.start_date:
        return CaptureOutcome.EVENT_ALREADY_STARTED

    snapshot = snapshot_from_predictions(
        predictions,
        tournament_start_date=tournament.start_date,
        model_trained_through=predictions.model_trained_through,
    )
    if await archive.persist(snapshot):
        return CaptureOutcome.CAPTURED
    # Lost a first-write race with a concurrent capture; the other one stands.
    return CaptureOutcome.ALREADY_CAPTURED
