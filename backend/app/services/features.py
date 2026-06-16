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
from datetime import timedelta
from typing import TYPE_CHECKING

from app.features.base import (
    DatedRound,
    FeatureContext,
    FeatureRegistry,
    FieldContext,
)
from app.features.feature_sets import v2_field_relative

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from app.features.base import FeatureSet
    from app.providers.base import DataProvider


# Fixed-width history window, measured back from the as-of date. Without an
# explicit window the provider decides how much history surfaces, and the
# DataGolf provider's calendar-season enumeration makes that *today*-relative:
# a training example early in the season window got weeks of history while a
# recent one got 18+ months, and the serve-time window stretched and shrank
# with the calendar. Pinning the window to as_of makes the feature definition
# identical for every (player, as_of) — training or serving — which is the
# same parity guarantee the rest of this module exists to enforce. Two years
# matches the intent of the provider's two-season default; beyond that, time
# decay leaves old rounds with negligible weight anyway.
_ROUNDS_WINDOW_DAYS = 730


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
        self._feature_set = feature_set or v2_field_relative()
        # Build the registry once — topological sort is cached.
        self._registry = FeatureRegistry(self._feature_set.features)

    @property
    def feature_set(self) -> FeatureSet:
        return self._feature_set

    async def _dated_rounds(
        self, player_id: int, as_of: date
    ) -> tuple[DatedRound, ...]:
        """A player's dated rounds within the window ending at ``as_of``.

        Shared by single-player and field extraction so both apply the same
        round-selection rules — the heart of train/serve parity. The window
        is enforced here (not just via ``since``) so the guarantee holds even
        if a provider over-returns.
        """
        window_start = as_of - timedelta(days=_ROUNDS_WINDOW_DAYS)
        rounds = await self._provider.get_rounds_for_player(
            player_id, since=window_start, limit=500
        )
        dated: list[DatedRound] = []
        for r in rounds:
            if r.tee_time is None:
                # Skip rounds with no resolved date — without a date we
                # can't apply time decay, and skipping is safer than
                # treating "unknown" as "today".
                continue
            played_on = r.tee_time.date()
            if played_on > as_of or played_on < window_start:
                # Outside the window: future rounds would leak; rounds older
                # than the window would make features depend on how much
                # history the provider happened to surface.
                continue
            dated.append(DatedRound(round=r, played_on=played_on))
        return tuple(dated)

    def _build_extraction(
        self,
        player_id: int,
        as_of: date,
        dated: tuple[DatedRound, ...],
        values: dict[str, float],
    ) -> FeatureExtraction:
        return FeatureExtraction(
            player_id=player_id,
            as_of=as_of,
            feature_set_name=self._feature_set.name,
            feature_set_hash=self._feature_set.hash,
            n_rounds=len(dated),
            values=values,
        )

    async def extract(self, player_id: int, as_of: date) -> FeatureExtraction:
        """Single-player extraction (no field context).

        Field-relative features fall back to their neutral value here, which
        is correct for the player-detail page where there is no field. For
        leaderboard/prediction/training use ``extract_field`` so those
        features carry real signal.
        """
        dated = await self._dated_rounds(player_id, as_of)
        context = FeatureContext(player_id=player_id, as_of_date=as_of, rounds=dated)
        values = self._registry.compute(context)
        return self._build_extraction(player_id, as_of, dated, values)

    async def extract_field(
        self, player_ids: Sequence[int], as_of: date
    ) -> dict[int, FeatureExtraction]:
        """Field-aware extraction for a whole tournament field.

        Two passes so field-relative features have something to compare to:

          1. Compute every player's absolute features in isolation.
          2. Average those across the field into a ``FieldContext``.
          3. Re-run the registry with the field attached, so field-relative
             features resolve to real margins over the field mean.

        Both the training builder and the prediction/backtest paths call this,
        which is what keeps field-relative features identical in train and
        serve. Returns ``{player_id: FeatureExtraction}``; duplicate ids are
        computed once.
        """
        unique_ids = list(dict.fromkeys(player_ids))

        # Pass 1: absolute features + cached rounds per player.
        rounds_by_player: dict[int, tuple[DatedRound, ...]] = {}
        pass1_values: dict[int, dict[str, float]] = {}
        for pid in unique_ids:
            dated = await self._dated_rounds(pid, as_of)
            rounds_by_player[pid] = dated
            ctx = FeatureContext(player_id=pid, as_of_date=as_of, rounds=dated)
            pass1_values[pid] = self._registry.compute(ctx)

        # Aggregate: field mean of every (absolute) feature across the field.
        field = self._aggregate_field(pass1_values)

        # Pass 2: recompute with the field context attached.
        result: dict[int, FeatureExtraction] = {}
        for pid in unique_ids:
            dated = rounds_by_player[pid]
            ctx = FeatureContext(
                player_id=pid, as_of_date=as_of, rounds=dated, field=field
            )
            values = self._registry.compute(ctx)
            result[pid] = self._build_extraction(pid, as_of, dated, values)
        return result

    @staticmethod
    def _aggregate_field(
        pass1_values: dict[int, dict[str, float]],
    ) -> FieldContext:
        """Field mean of every feature seen in pass 1.

        Field-relative features in pass 1 computed as their neutral 0.0 (no
        field yet); their means are harmless and unused. Aggregating every
        key keeps this generic — a new absolute feature is averaged without
        touching this code.
        """
        mean_skill: dict[str, float] = {}
        n = len(pass1_values)
        if n == 0:
            return FieldContext(mean_skill=mean_skill, field_size=0)
        keys: set[str] = set()
        for values in pass1_values.values():
            keys.update(values)
        for key in keys:
            total = sum(values.get(key, 0.0) for values in pass1_values.values())
            mean_skill[key] = total / n
        return FieldContext(mean_skill=mean_skill, field_size=n)
