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

**The DataGolf-fetch refusal.** DataGolf's live pre-tournament endpoint
serves whatever event it currently features, with no event parameter. On a
Wednesday before it has rolled over to this week's event, a capture gets
nothing back for the event it asked about — and the resulting board is a
whole-field cold-start that looks exactly like a legitimate one, pinned
forever. The fetch status (``domain.enums.DgFetchStatus``) is recorded on
every snapshot so the two stay distinguishable after the fact, and the
first scheduled run of the evening passes ``allow_degraded=False`` so it
refuses rather than pinning one. The retry captures regardless, labelled:
a board with an honest ``fetch_failed`` stamp is worth more than a missing
week, and A4b excludes it from the DataGolf comparison by reading the
stamp rather than inferring from a zero count.

The guard deliberately lives here and not in the archive's ``persist``,
because the backfill legitimately writes boards for events that have
already finished (as reconstructions, marked ``source="backfilled"``).
Storage stays policy-free; this module holds the live-capture policy.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from app.domain.enums import DgFetchStatus, TournamentStatus
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
    # The DataGolf fetch for this event unambiguously failed (the live feed
    # named a different tournament, or errored), so the board would be pinned
    # permanently as a whole-field cold-start that never was one. Refused on
    # the first run of the evening so the retry gets a real chance; the retry
    # passes ``allow_degraded=True`` and captures the labelled board instead,
    # because a labelled degraded board beats no board at all.
    DG_FETCH_FAILED = "dg_fetch_failed"
    NO_FIELD = "no_field"
    NO_TRAINING_CUTOFF = "no_training_cutoff"
    TOURNAMENT_NOT_FOUND = "tournament_not_found"

    @property
    def is_healthy(self) -> bool:
        """True when the outcome is a normal one for a scheduled run.

        A fresh capture and an idempotent no-op are both fine; everything
        else means this event did not get a board and something should say so.
        ``DG_FETCH_FAILED`` is deliberately *not* healthy — it is deferred,
        not fine, and only the caller knows whether a retry is still coming.
        See ``is_retryable``.
        """
        return self in (CaptureOutcome.CAPTURED, CaptureOutcome.ALREADY_CAPTURED)

    @property
    def is_retryable(self) -> bool:
        """True when a later run this same evening could still succeed.

        Only the DataGolf-fetch refusal qualifies: nothing was written, so
        first-write-wins has not closed the door, and the feed may well roll
        over before the retry. Every other unhealthy outcome is terminal for
        the week — the start guard will not un-fire, and a missing field will
        not appear at 23:30.
        """
        return self is CaptureOutcome.DG_FETCH_FAILED


async def capture_pre_event_board(
    *,
    catalog: CatalogService,
    archive: BoardArchive,
    predictions: TournamentPredictions,
    today: date,
    allow_degraded: bool = True,
) -> CaptureOutcome:
    """Capture ``predictions`` as an immutable pre-event board, if allowed.

    ``allow_degraded=False`` additionally refuses a board whose DataGolf fetch
    unambiguously failed, so a retry later the same evening can still capture
    a real one. It defaults to ``True`` because every caller other than the
    first scheduled run of the evening would rather have a labelled degraded
    board than none: the lazy serving path cannot retry at all, and the last
    run before the window closes is the last chance.

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

    if (
        not allow_degraded
        and getattr(predictions, "dg_fetch_status", None) is DgFetchStatus.FETCH_FAILED
    ):
        # Checked after the start guard, so an event that is out of the window
        # reports the reason that actually matters. Nothing is written, which
        # is the whole point: first-write-wins would otherwise let a degraded
        # 21:00 capture block the 23:30 retry from doing better.
        return CaptureOutcome.DG_FETCH_FAILED

    snapshot = snapshot_from_predictions(
        predictions,
        tournament_start_date=tournament.start_date,
        model_trained_through=predictions.model_trained_through,
    )
    if await archive.persist(snapshot):
        return CaptureOutcome.CAPTURED
    # Lost a first-write race with a concurrent capture; the other one stands.
    return CaptureOutcome.ALREADY_CAPTURED
