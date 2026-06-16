"""Rolling-origin backtest — honest, leakage-free accuracy measurement.

The single source of truth for "is the model actually sharp?". Everything
else (richer features, new architectures) is judged against the numbers this
produces. A model can look good on an in-sample holdout and still be useless
out of sample, so this walks forward in time:

    1. Pick the most recent ``test_events`` completed tournaments as the test
       window.
    2. Train a calibrated model using only data that ended strictly before the
       window opened (``train_through = first_test_event.start_date - 1``).
    3. Predict every player in each test event's field using features computed
       as of ``start_date - 1`` — the same as-of discipline training uses — so
       no future information can leak in.
    4. Score those out-of-sample predictions against what actually happened.

Metrics fall into three groups:

* **Per-outcome probability quality** — Brier, log-loss, and expected
  calibration error (ECE) for each market (win / top-5 / … / make-cut), plus a
  Brier *skill score* against a base-rate baseline so "good" is defined
  relative to predicting the field-average rate for everyone. A positive skill
  score means the model beats that naive baseline; zero or negative means it
  adds nothing.
* **Ranking quality** — does the model put the right players at the top?
  Spearman correlation between predicted win probability and actual finish,
  the average leaderboard rank of the eventual winner, and how often the winner
  landed in our predicted top-5 / top-10.
* **Per-event breakdown** — one row per test tournament for spot-checking.

This is intentionally model-agnostic: pass any ``Trainer``/feature set and it
reports comparable numbers, which is what makes it a fair A/B harness for the
feature and architecture work that follows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

import numpy as np

from app.domain.enums import EntryStatus, TournamentStatus
from app.ml.calibration import fit_calibrated, reliability_bins
from app.ml.trainer import LABEL_TO_OUTCOME_KEY, GBDTTrainer
from app.ml.training import TrainingDataBuilder, labels_from_entry
from app.services.predictions import coherent_outcomes

if TYPE_CHECKING:
    from datetime import date

    from numpy.typing import NDArray

    from app.domain.models import Tournament
    from app.ml.trainer import Trainer
    from app.services.catalog import CatalogService
    from app.services.features import FeatureExtractor


# Clip probabilities away from {0, 1} before taking logs so a confident miss
# yields a large-but-finite penalty instead of infinity.
_LOG_LOSS_EPS = 1e-15


@dataclass(frozen=True)
class OutcomeMetrics:
    """Out-of-sample probability quality for one market (e.g. ``win_prob``)."""

    outcome_key: str
    n: int
    base_rate: float
    brier: float
    log_loss: float
    ece: float
    base_rate_brier: float
    brier_skill_score: float


@dataclass(frozen=True)
class RankingMetrics:
    """How well the model orders the field, aggregated over test events."""

    n_events_scored: int
    spearman_winprob_vs_finish: float
    mean_winner_predicted_rank: float
    median_winner_predicted_rank: float
    winner_in_top5_rate: float
    winner_in_top10_rate: float


@dataclass(frozen=True)
class EventResult:
    """One test tournament's outcome — for per-event spot-checking."""

    tournament_id: int
    tournament_name: str
    start_date: date
    n_scored: int
    field_size: int
    winner_name: str | None
    winner_predicted_rank: int | None


@dataclass(frozen=True)
class BacktestReport:
    """The full leakage-free accuracy picture for one model configuration."""

    train_through: date
    n_train_examples: int
    n_test_events: int
    n_test_predictions: int
    feature_set_hash: str
    outcomes: tuple[OutcomeMetrics, ...]
    ranking: RankingMetrics
    events: tuple[EventResult, ...]


# ---------------------------------------------------------------------------
# Scoring primitives
# ---------------------------------------------------------------------------


def _log_loss(y: NDArray[np.float64], p: NDArray[np.float64]) -> float:
    p = np.clip(p, _LOG_LOSS_EPS, 1.0 - _LOG_LOSS_EPS)
    return float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))


def _brier(y: NDArray[np.float64], p: NDArray[np.float64]) -> float:
    return float(np.mean((p - y) ** 2))


def _ece(y: NDArray[np.float64], p: NDArray[np.float64], *, n_bins: int = 10) -> float:
    """Expected calibration error: count-weighted gap between predicted
    confidence and observed frequency across equal-width probability bins.
    """
    bins = reliability_bins(y, p, n_bins=n_bins)
    total = sum(b.count for b in bins)
    if total == 0:
        return 0.0
    return float(
        sum(
            (b.count / total) * abs(b.mean_predicted - b.observed_frequency)
            for b in bins
            if b.count > 0
        )
    )


def _spearman(a: NDArray[np.float64], b: NDArray[np.float64]) -> float:
    """Spearman rank correlation = Pearson correlation of the value ranks.

    Returns 0.0 when either side has no variance (e.g. every player tied),
    which is the right neutral answer for "no ordering information".
    """
    if len(a) < 2:
        return 0.0
    ra = _rankdata(a)
    rb = _rankdata(b)
    if np.std(ra) == 0 or np.std(rb) == 0:
        return 0.0
    return float(np.corrcoef(ra, rb)[0, 1])


def _rankdata(x: NDArray[np.float64]) -> NDArray[np.float64]:
    """Average-tie ranks (1-based), matching scipy.stats.rankdata's default,
    implemented with numpy so we take on no scipy dependency.
    """
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x), dtype=np.float64)
    ranks[order] = np.arange(1, len(x) + 1, dtype=np.float64)
    # Average ranks within tie groups.
    _, inv, counts = np.unique(x, return_inverse=True, return_counts=True)
    sums = np.zeros(len(counts), dtype=np.float64)
    np.add.at(sums, inv, ranks)
    return (sums / counts)[inv]


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


async def _completed_tournaments(catalog: CatalogService) -> list[Tournament]:
    """Every completed tournament, chronological by (start_date, id)."""
    items: list[Tournament] = []
    cursor: str | None = None
    while True:
        page = await catalog.list_tournaments(
            status=TournamentStatus.COMPLETED, cursor=cursor, limit=200
        )
        items.extend(page.items)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    items.sort(key=lambda t: (t.start_date, t.id))
    return items


async def run_backtest(
    *,
    catalog: CatalogService,
    extractor: FeatureExtractor,
    base_trainer: Trainer | None = None,
    test_events: int = 10,
    holdout_fraction: float = 0.25,
) -> BacktestReport:
    """Walk-forward backtest over the most recent ``test_events`` tournaments.

    Trains a calibrated per-market GBDT on data ending before the test window
    and scores coherence-corrected probabilities against what actually happened.
    ``base_trainer`` and ``extractor`` are injected so the same harness can A/B
    different feature sets and model families.
    """
    base_trainer = base_trainer or GBDTTrainer()

    completed = await _completed_tournaments(catalog)
    if len(completed) <= test_events:
        raise ValueError(
            f"Need more than {test_events} completed tournaments to backtest; "
            f"found {len(completed)}."
        )

    test = completed[-test_events:]
    train_through = test[0].start_date - timedelta(days=1)

    # --- Train once on everything before the test window ---
    builder = TrainingDataBuilder(catalog=catalog, extractor=extractor)
    train_data = await builder.build(through=train_through)
    if len(train_data) == 0:
        raise ValueError("No training examples before the test window.")
    fit = fit_calibrated(
        base_trainer, train_data, holdout_fraction=holdout_fraction
    )
    model = fit.model
    n_train_examples = len(train_data)

    # --- Predict & collect outcomes across the test window -----------------
    # Per-outcome accumulators.
    y_by_outcome: dict[str, list[float]] = {k: [] for k in LABEL_TO_OUTCOME_KEY.values()}
    p_by_outcome: dict[str, list[float]] = {k: [] for k in LABEL_TO_OUTCOME_KEY.values()}

    event_results: list[EventResult] = []
    spearmans: list[float] = []
    winner_ranks: list[int] = []
    n_predictions = 0

    for tournament in test:
        as_of = tournament.start_date - timedelta(days=1)
        field = await catalog.get_tournament_field(tournament.id)
        # Field-aware extraction over the whole field once — same path the
        # prediction service uses, so the backtest scores what production serves.
        extractions = await extractor.extract_field(
            [entry.player_id for entry in field], as_of
        )

        # Served probabilities per player for this event.
        served_by_player = {
            pid: dict(
                zip(
                    LABEL_TO_OUTCOME_KEY.values(),
                    coherent_outcomes(model.predict(ex.values)),
                    strict=True,
                )
            )
            for pid, ex in extractions.items()
        }

        # Per-event rows for ranking metrics.
        ev_win_probs: list[float] = []
        ev_finish_goodness: list[float] = []
        winner_player_id: int | None = None
        winner_idx: int | None = None
        n_scored = 0

        # Worst placement used for missed-cut players in the ranking metric.
        made_cut_positions = [
            e.final_position
            for e in field
            if e.final_position is not None
        ]
        worst_placement = (max(made_cut_positions) if made_cut_positions else len(field)) + 1

        for entry in field:
            # Only score players with a resolved outcome.
            if entry.status == EntryStatus.ACTIVE:
                continue
            if entry.status == EntryStatus.MADE_CUT and entry.final_position is None:
                continue

            labels = labels_from_entry(entry)
            served = served_by_player[entry.player_id]
            win = served["win_prob"]
            for label_key, outcome_key in LABEL_TO_OUTCOME_KEY.items():
                y_by_outcome[outcome_key].append(float(labels[label_key]))
                p_by_outcome[outcome_key].append(served[outcome_key])

            placement = (
                entry.final_position
                if entry.final_position is not None
                else worst_placement
            )
            if labels["win"] == 1:
                winner_player_id = entry.player_id
                winner_idx = len(ev_win_probs)  # index of this row in the per-event lists
            ev_win_probs.append(win)
            ev_finish_goodness.append(-float(placement))  # higher = better finish
            n_scored += 1
            n_predictions += 1

        # Ranking metrics for this event.
        winner_rank: int | None = None
        if n_scored >= 3:
            spearmans.append(
                _spearman(
                    np.array(ev_win_probs, dtype=np.float64),
                    np.array(ev_finish_goodness, dtype=np.float64),
                )
            )
        if winner_idx is not None:
            # Rank of the winner on our predicted-win-prob leaderboard (1-based).
            order = np.argsort(-np.array(ev_win_probs, dtype=np.float64), kind="mergesort")
            winner_rank = int(np.where(order == winner_idx)[0][0]) + 1
            winner_ranks.append(winner_rank)

        winner_name: str | None = None
        if winner_player_id is not None:
            player = await catalog.get_player(winner_player_id)
            winner_name = player.full_name if player else None

        event_results.append(
            EventResult(
                tournament_id=tournament.id,
                tournament_name=tournament.name,
                start_date=tournament.start_date,
                n_scored=n_scored,
                field_size=len(field),
                winner_name=winner_name,
                winner_predicted_rank=winner_rank,
            )
        )

    # --- Aggregate per-outcome metrics -------------------------------------
    outcome_metrics: list[OutcomeMetrics] = []
    for outcome_key in LABEL_TO_OUTCOME_KEY.values():
        y = np.array(y_by_outcome[outcome_key], dtype=np.float64)
        p = np.array(p_by_outcome[outcome_key], dtype=np.float64)
        if len(y) == 0:
            continue
        base_rate = float(np.mean(y))
        base_brier = float(np.mean((base_rate - y) ** 2))
        model_brier = _brier(y, p)
        skill = 0.0 if base_brier == 0.0 else 1.0 - model_brier / base_brier
        outcome_metrics.append(
            OutcomeMetrics(
                outcome_key=outcome_key,
                n=len(y),
                base_rate=base_rate,
                brier=model_brier,
                log_loss=_log_loss(y, p),
                ece=_ece(y, p),
                base_rate_brier=base_brier,
                brier_skill_score=skill,
            )
        )

    ranking = RankingMetrics(
        n_events_scored=len(spearmans),
        spearman_winprob_vs_finish=float(np.mean(spearmans)) if spearmans else 0.0,
        mean_winner_predicted_rank=float(np.mean(winner_ranks)) if winner_ranks else 0.0,
        median_winner_predicted_rank=float(np.median(winner_ranks)) if winner_ranks else 0.0,
        winner_in_top5_rate=(
            float(np.mean([r <= 5 for r in winner_ranks])) if winner_ranks else 0.0
        ),
        winner_in_top10_rate=(
            float(np.mean([r <= 10 for r in winner_ranks])) if winner_ranks else 0.0
        ),
    )

    return BacktestReport(
        train_through=train_through,
        n_train_examples=n_train_examples,
        n_test_events=len(test),
        n_test_predictions=n_predictions,
        feature_set_hash=extractor.feature_set.hash,
        outcomes=tuple(outcome_metrics),
        ranking=ranking,
        events=tuple(event_results),
    )
