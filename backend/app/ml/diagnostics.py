"""Read-only diagnostics for the rolling-origin backtest.

Re-runs the *exact* training + scoring path the backtest uses — the same
``TrainingDataBuilder``, the same ``fit_calibrated``, the same per-market
``model.predict`` + ``coherent_outcomes`` — but instead of collapsing to
aggregate metrics it records **one row per (tournament, player)**: predicted
probabilities, predicted rank, actual finish + percentile, per-market error,
and the full feature vector fed to inference. Companion outputs capture the
calibration report the model already carries and a global permutation
feature-importance table.

Strictly observational. Nothing here mutates training, features, labels,
calibration, inference, or any production code path — it imports and *calls*
them read-only so future feature experiments can be judged on measured
per-player error instead of intuition. Run via ``python -m app.cli.diagnose``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import numpy as np

from app.domain.enums import EntryStatus
from app.ml.backtest import _completed_tournaments
from app.ml.calibration import fit_calibrated
from app.ml.trainer import LABEL_TO_OUTCOME_KEY, GBDTTrainer
from app.ml.training import TrainingData, TrainingDataBuilder, labels_from_entry
from app.services.predictions import coherent_outcomes

if TYPE_CHECKING:
    from datetime import date

    from app.ml.calibration import CalibrationReport
    from app.ml.trainer import Trainer
    from app.services.catalog import CatalogService
    from app.services.features import FeatureExtractor

# Market keys in the fixed nested order coherent_outcomes returns.
_MARKETS: tuple[str, ...] = tuple(LABEL_TO_OUTCOME_KEY.values())
# Label key (win/top_5/…) for each market key (win_prob/top_5_prob/…).
_MARKET_TO_LABEL: dict[str, str] = {v: k for k, v in LABEL_TO_OUTCOME_KEY.items()}

# One scored player while building an event's rows:
# (player_id, labels, final_position, coherent probs, feature values).
_Scored = tuple[int, dict[str, int], "int | None", dict[str, float], dict[str, float]]


@dataclass(frozen=True)
class DiagnosticRow:
    """One (tournament, player) prediction-vs-outcome record."""

    tournament_id: int
    tournament: str
    start_date: date
    player_id: int
    player: str
    # Coherent predicted probabilities (exactly what the backtest scores).
    probs: dict[str, float]
    predicted_rank: int  # rank by win prob within the scored field (1 = top)
    made_cut: bool
    actual_finish: int | None  # final position; None when missed cut
    field_size: int
    finishing_percentile: float  # placement / field_size (lower = better finish)
    rank_error: int  # predicted_rank − actual placement (large + ⇒ under-ranked)
    labels: dict[str, int]  # realized binary outcomes per market
    sq_error: dict[str, float]  # (prob − label)² per market
    features: dict[str, float]  # the exact vector fed to inference


@dataclass(frozen=True)
class DiagnosticResult:
    """Everything the diagnostic export contains."""

    rows: tuple[DiagnosticRow, ...]
    feature_names: tuple[str, ...]
    calibration: CalibrationReport
    importances: dict[str, dict[str, float]]  # market → {feature → importance}
    train_through: date
    n_train_examples: int
    feature_set_hash: str
    meta: dict[str, Any] = field(default_factory=dict)


async def run_diagnostics(
    *,
    catalog: CatalogService,
    extractor: FeatureExtractor,
    base_trainer: Trainer | None = None,
    test_events: int = 10,
    holdout_fraction: float = 0.25,
) -> DiagnosticResult:
    """Train the baseline and record per-player predictions on the test window.

    Mirrors ``run_backtest`` exactly (same data split, same model, same
    coherence step) so the rows describe the real backtested model — it simply
    keeps every per-player prediction rather than reducing to aggregates.
    """
    base_trainer = base_trainer or GBDTTrainer()

    completed = await _completed_tournaments(catalog)
    if len(completed) <= test_events:
        raise ValueError(
            f"Need more than {test_events} completed tournaments; found {len(completed)}."
        )
    test = completed[-test_events:]
    train_through = test[0].start_date - timedelta(days=1)

    builder = TrainingDataBuilder(catalog=catalog, extractor=extractor)
    train_data: TrainingData = await builder.build(through=train_through)
    if len(train_data) == 0:
        raise ValueError("No training examples before the test window.")
    fit = fit_calibrated(base_trainer, train_data, holdout_fraction=holdout_fraction)
    model = fit.model

    rows: list[DiagnosticRow] = []
    for tournament in test:
        as_of = tournament.start_date - timedelta(days=1)
        tfield = await catalog.get_tournament_field(tournament.id)
        extractions = await extractor.extract_field(
            [e.player_id for e in tfield], as_of
        )

        # Scored players + their coherent probabilities (same filter as backtest).
        scored: list[_Scored] = []
        for entry in tfield:
            if entry.status == EntryStatus.ACTIVE:
                continue
            if entry.status == EntryStatus.MADE_CUT and entry.final_position is None:
                continue
            ex = extractions[entry.player_id]
            probs = dict(zip(_MARKETS, coherent_outcomes(model.predict(ex.values)), strict=True))
            scored.append(
                (entry.player_id, labels_from_entry(entry), entry.final_position,
                 probs, dict(ex.values))
            )

        if not scored:
            continue

        made_cut_positions = [
            e.final_position for e in tfield if e.final_position is not None
        ]
        worst_placement = (max(made_cut_positions) if made_cut_positions else len(tfield)) + 1
        n_scored = len(scored)

        # Predicted rank by win prob, descending (1 = our top pick) — matches backtest.
        order = sorted(range(n_scored), key=lambda i: scored[i][3]["win_prob"], reverse=True)
        predicted_rank = {idx: rank for rank, idx in enumerate(order, start=1)}

        for i, (pid, labels, finish, probs, feats) in enumerate(scored):
            placement = finish if finish is not None else worst_placement
            player = await catalog.get_player(pid)
            rows.append(
                DiagnosticRow(
                    tournament_id=tournament.id,
                    tournament=tournament.name,
                    start_date=tournament.start_date,
                    player_id=pid,
                    player=player.full_name if player else f"#{pid}",
                    probs=probs,
                    predicted_rank=predicted_rank[i],
                    made_cut=finish is not None,
                    actual_finish=finish,
                    field_size=n_scored,
                    finishing_percentile=placement / n_scored,
                    rank_error=predicted_rank[i] - placement,
                    labels=labels,
                    sq_error={
                        m: (probs[m] - labels[_MARKET_TO_LABEL[m]]) ** 2 for m in _MARKETS
                    },
                    features=feats,
                )
            )

    feature_names = fit.feature_names
    importances = _permutation_importances(model, rows, feature_names)

    return DiagnosticResult(
        rows=tuple(rows),
        feature_names=feature_names,
        calibration=model.report,
        importances=importances,
        train_through=train_through,
        n_train_examples=len(train_data),
        feature_set_hash=extractor.feature_set.hash,
        meta={"n_test_events": len(test), "n_rows": len(rows)},
    )


def _permutation_importances(
    model: Any, rows: list[DiagnosticRow], feature_names: tuple[str, ...]
) -> dict[str, dict[str, float]]:
    """Global per-market permutation importance on the out-of-sample test rows.

    Read-only: introspects the already-fitted base estimators and measures how
    much each feature matters to *test-set* Brier. SHAP would give per-row
    attributions but isn't installed; this is the available stand-in. Any market
    whose estimator can't be scored (e.g. single-class) is skipped, not fatal.
    """
    if not rows:
        return {}
    from sklearn.inspection import permutation_importance

    x = np.array(
        [[r.features.get(n, 0.0) for n in feature_names] for r in rows],
        dtype=np.float64,
    )
    base = model._base  # noqa: SLF001 — read-only introspection of the fitted model
    out: dict[str, dict[str, float]] = {}
    for market in _MARKETS:
        estimator = base._estimators.get(market)  # noqa: SLF001
        if estimator is None:
            continue
        y = np.array([r.labels[_MARKET_TO_LABEL[market]] for r in rows], dtype=np.int_)
        if len(np.unique(y)) < 2:
            continue
        try:
            result = permutation_importance(
                estimator, x, y, scoring="neg_brier_score",
                n_repeats=5, random_state=0,
            )
        except Exception:  # noqa: S112,BLE001 — importance is best-effort; skip a market that won't score
            continue
        out[market] = {
            name: float(imp)
            for name, imp in zip(feature_names, result.importances_mean, strict=True)
        }
    return out
