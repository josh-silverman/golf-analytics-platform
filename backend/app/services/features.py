"""Feature extraction service.

The seam where raw provider data meets the feature engineering layer.
Both the training pipeline and the inference path call into this single
service, which is what enforces the train/serve parity guarantee.

Given a ``(player_id, as_of_date)``, the extractor:
1. Pulls the player's rounds from the active ``DataProvider``.
2. Filters to rounds whose tee time is on or before the as-of date.
3. Builds a ``FeatureContext`` and runs the ``FeatureRegistry``.
4. Returns the computed values plus provenance (feature-set hash,
   round count) so callers can record what they computed against.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.features.base import DatedRound, FeatureContext, FeatureRegistry
from app.features.feature_sets import v1_baseline

if TYPE_CHECKING:
    from datetime import date

    from app.features.base import FeatureSet
    from app.providers.base import DataProvider


@dataclass(frozen=True)
class FeatureExtraction:
    """One extraction's output plus the provenance the caller needs to log."""

    player_id: int
    as_of: date
    feature_set_name: str
    feature_set_hash: str
    n_rounds: int
    values: dict[str, float]


class FeatureExtractor:
    """Stateless-per-call: takes ``(player_id, as_of)`` and returns features."""

    def __init__(
        self,
        provider: DataProvider,
        feature_set: FeatureSet | None = None,
    ) -> None:
        self._provider = provider
        self._feature_set = feature_set or v1_baseline()
        # Build the registry once — topological sort is cached.
        self._registry = FeatureRegistry(self._feature_set.features)

    @property
    def feature_set(self) -> FeatureSet:
        return self._feature_set

    async def extract(self, player_id: int, as_of: date) -> FeatureExtraction:
        rounds = await self._provider.get_rounds_for_player(
            player_id, since=None, limit=500
        )
        dated: list[DatedRound] = []
        for r in rounds:
            if r.tee_time is None:
                # Skip rounds with no resolved date — without a date we
                # can't apply time decay, and skipping is safer than
                # treating "unknown" as "today".
                continue
            played_on = r.tee_time.date()
            if played_on > as_of:
                # Prevent leakage when computing features for a date
                # before some of the rounds were played.
                continue
            dated.append(DatedRound(round=r, played_on=played_on))

        context = FeatureContext(
            player_id=player_id,
            as_of_date=as_of,
            rounds=tuple(dated),
        )
        values = self._registry.compute(context)
        return FeatureExtraction(
            player_id=player_id,
            as_of=as_of,
            feature_set_name=self._feature_set.name,
            feature_set_hash=self._feature_set.hash,
            n_rounds=len(dated),
            values=values,
        )
