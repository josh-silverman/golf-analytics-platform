"""Training data assembly — doc 02 §3.

Converts the historical record into ``(features, labels)`` pairs a trainer
can consume. Labels are binary outcomes derived from the tournament entry
(``win``, ``top_5``, ``top_10``, ``top_20``, ``made_cut``); features come
from the same ``FeatureExtractor`` used at inference time, evaluated at the
day before each tournament started — which is what enforces the
"no peeking at the future" rule under doc 02 §3's leakage-prevention
discipline.

Once a trainer lands, this module's output flows straight into
``Trainer.fit(data) -> Model``, which gets registered via the
``ModelRegistry``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from app.domain.enums import EntryStatus, TournamentStatus

if TYPE_CHECKING:
    from datetime import date

    from app.domain.models import TournamentEntry
    from app.services.catalog import CatalogService
    from app.services.features import FeatureExtractor


LABEL_KEYS: tuple[str, ...] = ("win", "top_5", "top_10", "top_20", "made_cut")


@dataclass(frozen=True)
class TrainingExample:
    """One ``(features, labels)`` pair with provenance for debugging.

    ``as_of`` is the date the features were computed at — strictly before
    the tournament's start date — so a single example is a clean snapshot
    that can never have leaked future information.
    """

    player_id: int
    tournament_id: int
    as_of: date
    features: dict[str, float]
    labels: dict[str, int]


@dataclass(frozen=True)
class TrainingData:
    """A built training dataset plus the metadata a trainer must record.

    ``feature_set_hash`` will end up on ``model_versions`` so a model knows
    which feature definitions it was trained against; ``through_date`` is
    the cutoff — no example was computed using rounds after this date.
    """

    examples: tuple[TrainingExample, ...]
    feature_set_hash: str
    through_date: date

    def __len__(self) -> int:
        return len(self.examples)


def labels_from_entry(entry: TournamentEntry) -> dict[str, int]:
    """Binary outcome labels derived from a completed tournament entry.

    ``made_cut`` is independent of the position-bucket labels: a player who
    missed the cut has ``final_position == None`` and therefore ``0`` for
    win/top-5/top-10/top-20 even though some of those buckets nominally
    include "did not finish". That's the right convention — for training
    against "what's the probability this player finishes top-N?", the
    answer for a player who missed the cut is "definitely not top-N".
    """
    pos = entry.final_position
    return {
        "win": 1 if pos == 1 else 0,
        "top_5": 1 if pos is not None and pos <= 5 else 0,
        "top_10": 1 if pos is not None and pos <= 10 else 0,
        "top_20": 1 if pos is not None and pos <= 20 else 0,
        "made_cut": 1 if entry.status == EntryStatus.MADE_CUT else 0,
    }


class TrainingDataBuilder:
    """Produces a ``TrainingData`` set from the historical record.

    Lifecycle: one builder per training run. The caller passes the cutoff
    date so backfills (re-running an older training) are reproducible.
    """

    def __init__(
        self,
        *,
        catalog: CatalogService,
        extractor: FeatureExtractor,
    ) -> None:
        self._catalog = catalog
        self._extractor = extractor

    async def build(
        self,
        *,
        through: date,
        season: int | None = None,
        page_size: int = 200,
    ) -> TrainingData:
        """Walk completed tournaments through ``through`` and emit examples.

        For each tournament whose ``end_date`` is on or before ``through``,
        we evaluate every player's features as of ``start_date - 1`` —
        strictly before any round in that tournament was played — and pair
        them with binary outcome labels from the entry. Players who were
        not actually in the field, or whose entry lacks a final position
        despite ``MADE_CUT`` status, are skipped rather than treated as
        zeros: bad data should be loud, not silently mislabeled.
        """
        cursor: str | None = None
        examples: list[TrainingExample] = []
        while True:
            page = await self._catalog.list_tournaments(
                season=season,
                status=TournamentStatus.COMPLETED,
                cursor=cursor,
                limit=page_size,
            )
            for tournament in page.items:
                if tournament.end_date > through:
                    continue
                as_of = tournament.start_date - timedelta(days=1)
                field = await self._catalog.get_tournament_field(tournament.id)
                # Field-aware extraction over the whole field once, so
                # field-relative features see the true field they competed in
                # — and identically to how the prediction path computes them.
                extractions = await self._extractor.extract_field(
                    [entry.player_id for entry in field], as_of
                )
                for entry in field:
                    # Need a final position (or an explicit missed cut) to
                    # produce coherent labels. Skip players whose entry is
                    # in an inconsistent state.
                    if entry.status == EntryStatus.ACTIVE:
                        continue
                    if entry.status == EntryStatus.MADE_CUT and entry.final_position is None:
                        continue
                    extraction = extractions[entry.player_id]
                    examples.append(
                        TrainingExample(
                            player_id=entry.player_id,
                            tournament_id=tournament.id,
                            as_of=as_of,
                            features=dict(extraction.values),
                            labels=labels_from_entry(entry),
                        )
                    )
            if page.next_cursor is None:
                break
            cursor = page.next_cursor

        return TrainingData(
            examples=tuple(examples),
            feature_set_hash=self._extractor.feature_set.hash,
            through_date=through,
        )
