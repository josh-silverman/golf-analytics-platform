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
from datetime import timedelta
from typing import TYPE_CHECKING

from app.domain.enums import EntryStatus, TournamentStatus
from app.services.features import EventRef

if TYPE_CHECKING:
    from datetime import date

    from app.ml.base import Model
    from app.providers.base import DataProvider
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


def coherent_outcomes(preds: dict[str, float]) -> tuple[float, float, float, float, float]:
    """Coerce independently-predicted market probabilities into a coherent set.

    The per-market classifiers are trained and calibrated independently, so a
    raw prediction can be incoherent — e.g. ``win_prob`` exceeding ``top_5_prob``
    even though winning is by definition a top-5 finish. Because the outcomes
    are strictly nested (win ⊆ top-5 ⊆ top-10 ⊆ top-20 ⊆ make-cut), each wider
    bucket's probability must be at least the next-narrower bucket's.

    We enforce that by taking a running maximum outward from ``win_prob``. This
    is monotonic, idempotent, and leaves already-coherent predictions untouched
    — it only lifts a wider bucket up to its narrower neighbour when the raw
    model violated the nesting. All values are clamped to ``[0, 1]``.
    """
    win = min(max(float(preds.get("win_prob", 0.0)), 0.0), 1.0)
    top_5 = min(max(float(preds.get("top_5_prob", 0.0)), 0.0), 1.0)
    top_10 = min(max(float(preds.get("top_10_prob", 0.0)), 0.0), 1.0)
    top_20 = min(max(float(preds.get("top_20_prob", 0.0)), 0.0), 1.0)
    make_cut = min(max(float(preds.get("make_cut_prob", 0.0)), 0.0), 1.0)

    top_5 = max(top_5, win)
    top_10 = max(top_10, top_5)
    top_20 = max(top_20, top_10)
    make_cut = max(make_cut, top_20)

    return win, top_5, top_10, top_20, make_cut


# Theoretical total of each market's probabilities across a full field: exactly
# one winner, five top-5 finishers, ten top-10s, twenty top-20s. ``make_cut``
# has no fixed total (it depends on the cut rule), so it is left unnormalized.
_FIELD_TARGET_SUM: dict[str, float] = {
    "win_prob": 1.0,
    "top_5_prob": 5.0,
    "top_10_prob": 10.0,
    "top_20_prob": 20.0,
}

# Index of each market in the coherent-outcome tuple.
_MARKET_ORDER: tuple[str, ...] = (
    "win_prob", "top_5_prob", "top_10_prob", "top_20_prob", "make_cut_prob",
)


def normalize_field(
    rows: list[tuple[float, float, float, float, float]],
) -> list[tuple[float, float, float, float, float]]:
    """Scale each market across the field to its theoretical total.

    Independently-calibrated per-market classifiers don't respect the field
    constraint that exactly one player wins, five finish top-5, and so on — so
    raw win probabilities sum to well over 1.0, systematically over-pricing
    longshots. We rescale each market (win→1, top-5→5, top-10→10, top-20→20,
    each target capped at the field size) so the field sums to its true total,
    then re-enforce the nested coherence the rescale may have nudged. ``make_cut``
    is left as-is. The result is what makes both the leaderboard and any odds
    comparison honest about a player's real chances.
    """
    if not rows:
        return rows
    n = len(rows)
    # Per-market scale factor from the current field sum to the target.
    scales: dict[int, float] = {}
    for idx, market in enumerate(_MARKET_ORDER):
        target = _FIELD_TARGET_SUM.get(market)
        if target is None:
            continue
        total = sum(r[idx] for r in rows)
        if total <= 0.0:
            continue
        # Can't have more top-20s than players in a tiny field.
        scales[idx] = min(target, float(n)) / total

    normalized: list[tuple[float, float, float, float, float]] = []
    for r in rows:
        scaled = {
            _MARKET_ORDER[i]: min(r[i] * scales.get(i, 1.0), 1.0)
            for i in range(len(_MARKET_ORDER))
        }
        # Re-apply nested coherence: scaling each market by a different factor
        # can flip win above top-5 for a player who was previously tied.
        normalized.append(coherent_outcomes(scaled))
    return normalized


@dataclass(frozen=True)
class PathASource:
    """Path A serving: DataGolf-direct for covered players, SG-only for cold-start.

    When attached to a :class:`PredictionService`, each player's raw five-market
    probabilities come from DataGolf's own pre-event predictions if DataGolf
    covers them, and from the service's model (the v2 SG-only model) otherwise.
    Both sources then flow through the *same* ``coherent_outcomes`` +
    ``normalize_field`` steps, so the mixed-source board is coherent and
    field-consistent by construction.

    This is the "Path A" decision: on covered players DataGolf's probabilities
    match or beat the stacked model on every market (and clearly beat it on
    win/top-5), so we serve them directly rather than through a model that has
    largely absorbed them; the SG-only model earns its keep only where DataGolf
    has no coverage (cold-start).
    """

    provider: DataProvider  # supplies get_pretournament_full_preds for the event


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
    # Actual result, populated only once the event is graded (completed). Lets
    # the leaderboard show a predicted-vs-actual "report card". ``None`` before.
    final_position: int | None = None
    made_cut: bool | None = None


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
    # Training cutoff of the serving model — the date used to certify a captured
    # board as out-of-sample (event started strictly after this). Under Path A
    # this is the cold-start model's cutoff; the DG-direct part is inherently a
    # frozen pre-event snapshot. ``None`` when unknown (e.g. fallback model).
    model_trained_through: date | None = None


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
        path_a: PathASource | None = None,
        model_trained_through: date | None = None,
    ) -> None:
        self._catalog = catalog
        self._extractor = extractor
        self._model = model
        self._model_name = model_name
        self._model_version_id = model_version_id
        self._model_trained_through = model_trained_through
        # When set, covered players are served DataGolf-direct and ``model`` acts
        # as the cold-start (SG-only) fallback. When None, ``model`` serves the
        # whole field (the classic single-model path).
        self._path_a = path_a

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

        # Predict as the model would have *before* the event: never use data past
        # its eve. For upcoming events this is just ``as_of`` (today); for
        # in-progress/completed events it caps at start_date − 1, so the board —
        # and the report card / track record built on it — is a genuine
        # pre-event prediction rather than hindsight.
        as_of = min(as_of, tournament.start_date - timedelta(days=1))

        field = await self._catalog.get_tournament_field(tournament_id)
        # Actual results per player (meaningful once the event is graded; all
        # ``None`` while it's upcoming/in-progress). Used for the report card.
        actual_by_player: dict[int, tuple[int | None, bool | None]] = {}
        for entry in field:
            if entry.status == EntryStatus.MADE_CUT:
                made: bool | None = True
            elif entry.status == EntryStatus.MISSED_CUT:
                made = False
            else:
                made = None
            actual_by_player[entry.player_id] = (entry.final_position, made)
        # Field-aware extraction over the whole field once, so field-relative
        # features compare each player to the actual field (and match training).
        # External DG predictions: the archive has completed events; an upcoming/
        # in-progress event isn't archived yet, so read the live endpoint for it.
        is_completed = tournament.status == TournamentStatus.COMPLETED
        extractions = await self._extractor.extract_field(
            [entry.player_id for entry in field],
            as_of,
            event=EventRef(
                event_id=tournament.id,
                season=tournament.season,
                live=not is_completed,
            ),
        )
        # Path A: DataGolf's own five-market probabilities for the whole field,
        # fetched once (archive for completed events, live for upcoming). Empty
        # dict → every player cold-starts to the SG-only model.
        dg_full: dict[int, dict[str, float]] = {}
        if self._path_a is not None:
            dg_full = await self._path_a.provider.get_pretournament_full_preds(
                tournament.id, tournament.season, live=not is_completed
            )

        # First pass: per-player coherent probabilities, keeping the player so we
        # can rebuild outcomes after the field-level normalization step.
        players: list[tuple[int, str]] = []
        coherent_rows: list[tuple[float, float, float, float, float]] = []
        for entry in field:
            player = await self._catalog.get_player(entry.player_id)
            if player is None:
                # Stale entry referencing a deleted player — skip rather
                # than fail the whole request.
                continue
            extraction = extractions[entry.player_id]
            if self._path_a is not None:
                # Covered → DataGolf-direct; cold-start → SG-only model.
                dg = dg_full.get(entry.player_id)
                preds = dg if dg is not None else self._model.predict(extraction.values)
            else:
                preds = self._model.predict(extraction.values)
            players.append((player.id, player.full_name))
            coherent_rows.append(coherent_outcomes(preds))

        # Field normalization: rescale each market so the field sums to its true
        # total (one winner, five top-5s, …) instead of the >100% the
        # independent classifiers produce. Without this, longshots are
        # systematically over-priced and the betting edge shows phantom value.
        normalized = normalize_field(coherent_rows)

        outcomes: list[PlayerOutcome] = [
            PlayerOutcome(
                player_id=pid,
                player_name=name,
                win_prob=win,
                top_5_prob=top_5,
                top_10_prob=top_10,
                top_20_prob=top_20,
                make_cut_prob=make_cut,
                final_position=actual_by_player.get(pid, (None, None))[0],
                made_cut=actual_by_player.get(pid, (None, None))[1],
            )
            for (pid, name), (win, top_5, top_10, top_20, make_cut) in zip(
                players, normalized, strict=True
            )
        ]

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
            model_trained_through=self._model_trained_through,
        )


# Re-exported for callers that want to know which outcome keys the service
# extracts from a model's prediction dict.
OUTCOME_KEYS: tuple[str, ...] = _OUTCOME_KEYS
