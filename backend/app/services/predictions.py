"""Prediction service — runs the active model over a tournament's field.

Orchestrates the four collaborators the predictions endpoint needs:
the catalog (player + tournament lookups), the feature extractor (per-player
feature computation as of a date), the trained model (probabilities), and
the model's identity (name + version_id) so the response can report which
model produced these numbers.

The service is intentionally stateless per call so the lru_cache on the
dependency layer can safely return the same instance to concurrent
requests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date

    from app.ml.base import Model
    from app.services.catalog import CatalogService
    from app.services.features import FeatureExtractor


# Output keys the leaderboard cares about. ``Model.predict`` is free to
# return additional keys; the service maps these explicitly so callers
# don't need to know about every key a model might expose.
_OUTCOME_KEYS: tuple[str, ...] = (
    "win_prob",
    "top_5_prob",
    "top_10_prob",
    "top_20_prob",
    "make_cut_prob",
)


@dataclass(frozen=True)
class PlayerOutcome:
    """One player's predicted outcome distribution for the tournament."""

    player_id: int
    player_name: str
    win_prob: float
    top_5_prob: float
    top_10_prob: float
    top_20_prob: float
    make_cut_prob: float


@dataclass(frozen=True)
class TournamentPredictions:
    """Full prediction response for one tournament."""

    tournament_id: int
    tournament_name: str
    as_of: date
    model_name: str
    model_version_id: str | None  # None when the fallback model is in use
    feature_set_hash: str
    outcomes: tuple[PlayerOutcome, ...]


class PredictionService:
    """Runs a model over a tournament field and returns a sorted leaderboard."""

    def __init__(
        self,
        *,
        catalog: CatalogService,
        extractor: FeatureExtractor,
        model: Model,
        model_name: str,
        model_version_id: str | None,
    ) -> None:
        self._catalog = catalog
        self._extractor = extractor
        self._model = model
        self._model_name = model_name
        self._model_version_id = model_version_id

    async def predict_tournament(
        self,
        tournament_id: int,
        *,
        as_of: date,
    ) -> TournamentPredictions | None:
        """Score every player in ``tournament_id``'s field as of ``as_of``.

        Returns ``None`` if the tournament doesn't exist so the endpoint
        can translate to a 404 without raising from the service layer.
        """
        tournament = await self._catalog.get_tournament(tournament_id)
        if tournament is None:
            return None

        field = await self._catalog.get_tournament_field(tournament_id)
        outcomes: list[PlayerOutcome] = []
        for entry in field:
            player = await self._catalog.get_player(entry.player_id)
            if player is None:
                # Stale entry referencing a deleted player — skip rather
                # than fail the whole request.
                continue
            extraction = await self._extractor.extract(entry.player_id, as_of)
            preds = self._model.predict(extraction.values)
            outcomes.append(
                PlayerOutcome(
                    player_id=player.id,
                    player_name=player.full_name,
                    win_prob=float(preds.get("win_prob", 0.0)),
                    top_5_prob=float(preds.get("top_5_prob", 0.0)),
                    top_10_prob=float(preds.get("top_10_prob", 0.0)),
                    top_20_prob=float(preds.get("top_20_prob", 0.0)),
                    make_cut_prob=float(preds.get("make_cut_prob", 0.0)),
                )
            )

        # Sort by win probability descending — the natural leaderboard order.
        outcomes.sort(key=lambda o: o.win_prob, reverse=True)

        return TournamentPredictions(
            tournament_id=tournament.id,
            tournament_name=tournament.name,
            as_of=as_of,
            model_name=self._model_name,
            model_version_id=self._model_version_id,
            feature_set_hash=self._extractor.feature_set.hash,
            outcomes=tuple(outcomes),
        )


# Re-exported for callers that want to know which outcome keys the service
# extracts from a model's prediction dict.
OUTCOME_KEYS: tuple[str, ...] = _OUTCOME_KEYS
