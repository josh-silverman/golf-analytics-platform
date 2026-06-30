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
    from collections.abc import Callable
    from datetime import date

    from app.domain.models import Tournament, TournamentEntry
    from app.providers.datagolf.datagolf_provider import DataGolfProvider
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

    # Pre-2024 seasons reachable only through the historical archive (get-schedule
    # 400s for them). Deliberately bounded to 2021–2023 for this validation step:
    # the 365-day recency weighting makes pre-2021 examples nearly zero-weight, so
    # going further back is unlikely to pay for the throttled fetch cost.
    _ARCHIVE_SEASONS: tuple[int, ...] = (2023, 2022, 2021)

    def __init__(
        self,
        *,
        catalog: CatalogService,
        extractor: FeatureExtractor,
        use_historical_archive: bool = False,
        archive_provider: DataGolfProvider | None = None,
    ) -> None:
        self._catalog = catalog
        self._extractor = extractor
        # OFF by default → existing behaviour unchanged. When True (and an
        # archive-enabled provider is supplied) the builder ALSO emits examples
        # from the 2021–2023 archive, with year-correct fields (the event_id
        # collision means get_tournament_field(id) can't be used for them).
        self._use_historical_archive = use_historical_archive
        self._archive_provider = archive_provider

    async def build(
        self,
        *,
        through: date,
        season: int | None = None,
        page_size: int = 200,
        on_event: Callable[[str, int, int], None] | None = None,
    ) -> TrainingData:
        """Walk completed tournaments through ``through`` and emit examples.

        For each tournament whose ``end_date`` is on or before ``through``,
        we evaluate every player's features as of ``start_date - 1`` —
        strictly before any round in that tournament was played — and pair
        them with binary outcome labels from the entry. Players who were
        not actually in the field, or whose entry lacks a final position
        despite ``MADE_CUT`` status, are skipped rather than treated as
        zeros: bad data should be loud, not silently mislabeled.

        ``on_event`` is an optional progress hook called once per completed
        event with ``(phase, tournament_id, running_example_count)`` — purely
        for observability (the build is CPU-bound and otherwise silent for
        minutes). It defaults to ``None`` so production behaviour is unchanged.
        """
        examples: list[TrainingExample] = []

        # --- Current path: get-schedule (2024+), unchanged ------------------
        cursor: str | None = None
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
                field = await self._catalog.get_tournament_field(tournament.id)
                examples.extend(await self._examples_for_event(tournament, field))
                if on_event is not None:
                    on_event("schedule", tournament.id, len(examples))
            if page.next_cursor is None:
                break
            cursor = page.next_cursor

        # --- Archive path: 2021–2023 from historical-raw-data (opt-in) ------
        # Year-correct fields come straight from _fetch_historical_training_events
        # (NOT get_tournament_field, which would mis-resolve the recurring
        # event_id to the most recent season). Only events on/before ``through``
        # are emitted, so a backtest's train cutoff is still respected.
        if self._use_historical_archive and self._archive_provider is not None:
            for yr in self._ARCHIVE_SEASONS:
                tournaments, fields = (
                    await self._archive_provider._fetch_historical_training_events(yr)  # noqa: SLF001
                )
                for tournament in tournaments:
                    if tournament.end_date > through:
                        continue
                    field = fields.get(tournament.id, [])
                    examples.extend(await self._examples_for_event(tournament, field))
                    if on_event is not None:
                        on_event(f"archive:{yr}", tournament.id, len(examples))

        return TrainingData(
            examples=tuple(examples),
            feature_set_hash=self._extractor.feature_set.hash,
            through_date=through,
        )

    async def _examples_for_event(
        self, tournament: Tournament, field: list[TournamentEntry]
    ) -> list[TrainingExample]:
        """Build training examples for one event's field (shared by both paths).

        Features are computed as of ``start_date - 1`` over the whole field at
        once (so field-relative features see the true field), and paired with
        binary outcome labels. Players with no resolved outcome are skipped —
        bad data should be loud, not silently mislabeled.
        """
        if not field:
            return []
        as_of = tournament.start_date - timedelta(days=1)
        extractions = await self._extractor.extract_field(
            [entry.player_id for entry in field], as_of
        )
        out: list[TrainingExample] = []
        for entry in field:
            if entry.status == EntryStatus.ACTIVE:
                continue
            if entry.status == EntryStatus.MADE_CUT and entry.final_position is None:
                continue
            extraction = extractions[entry.player_id]
            out.append(
                TrainingExample(
                    player_id=entry.player_id,
                    tournament_id=tournament.id,
                    as_of=as_of,
                    features=dict(extraction.values),
                    labels=labels_from_entry(entry),
                )
            )
        return out
