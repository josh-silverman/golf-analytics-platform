"""Read-only backtest diagnostics CLI.

Usage (from the backend directory, inside the container):
    uv run python -m app.cli.diagnose
    uv run python -m app.cli.diagnose --test-events 10 --out-dir diagnostics

Re-runs the current baseline through the rolling backtest path and exports,
for every player in every evaluated tournament, the predicted probabilities,
predicted rank, actual finish + percentile, per-market error, and the exact
feature vector fed to inference — plus the model's calibration report and a
global permutation feature-importance table.

This is strictly observational: it trains a throwaway model (identical to the
backtest) and writes CSV/JSON. It does not touch the model registry, training,
features, labels, calibration, inference, or any production code path.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.ml.diagnostics import DiagnosticResult

_MARKETS = ("win_prob", "top_5_prob", "top_10_prob", "top_20_prob", "make_cut_prob")
_LABEL_OF = {
    "win_prob": "win", "top_5_prob": "top_5", "top_10_prob": "top_10",
    "top_20_prob": "top_20", "make_cut_prob": "made_cut",
}


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m app.cli.diagnose",
        description="Read-only per-player diagnostics export for the rolling backtest.",
    )
    p.add_argument("--test-events", type=int, default=10,
                   help="Most-recent completed tournaments to evaluate (default: 10)")
    p.add_argument("--holdout", type=float, default=0.25,
                   help="Calibration holdout fraction (default: 0.25)")
    p.add_argument("--out-dir", default="diagnostics",
                   help="Directory for exported files (default: ./diagnostics)")
    return p


def _write_predictions(result: DiagnosticResult, path: Path) -> None:
    cols = [
        "tournament_id", "tournament", "start_date", "player_id", "player",
        "predicted_rank", "made_cut", "actual_finish", "field_size",
        "finishing_percentile", "rank_error",
    ]
    for m in _MARKETS:
        cols += [f"{m}", f"{m}_label", f"{m}_sqerr"]
    cols += [f"feat_{n}" for n in result.feature_names]

    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in result.rows:
            row = [
                r.tournament_id, r.tournament, r.start_date.isoformat(),
                r.player_id, r.player, r.predicted_rank, int(r.made_cut),
                "" if r.actual_finish is None else r.actual_finish,
                r.field_size, f"{r.finishing_percentile:.4f}", r.rank_error,
            ]
            for m in _MARKETS:
                row += [f"{r.probs[m]:.6f}", r.labels[_LABEL_OF[m]], f"{r.sq_error[m]:.6f}"]
            row += [f"{r.features.get(n, 0.0):.6f}" for n in result.feature_names]
            w.writerow(row)


def _write_importances(result: DiagnosticResult, path: Path) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["market", *result.feature_names])
        for market, imps in result.importances.items():
            w.writerow([market, *(f"{imps.get(n, 0.0):.6f}" for n in result.feature_names)])


def _write_calibration(result: DiagnosticResult, path: Path) -> None:
    payload = {
        "n_calibration_examples": result.calibration.n_calibration_examples,
        "outcomes": [
            {
                "outcome_key": o.outcome_key,
                "brier_raw": o.brier_raw,
                "brier_calibrated": o.brier_calibrated,
                "bins_calibrated": [
                    {
                        "lower": b.lower, "upper": b.upper,
                        "mean_predicted": b.mean_predicted,
                        "observed_frequency": b.observed_frequency, "count": b.count,
                    }
                    for b in o.bins_calibrated
                ],
            }
            for o in result.calibration.outcomes
        ],
    }
    path.write_text(json.dumps(payload, indent=2))


async def _run(*, test_events: int, holdout: float, out_dir: str) -> None:
    from app.config import get_settings
    from app.ml.diagnostics import run_diagnostics
    from app.providers.factory import get_data_provider
    from app.services.catalog import CatalogService
    from app.services.features import FeatureExtractor

    settings = get_settings()
    provider = get_data_provider()
    catalog = CatalogService(provider)
    extractor = FeatureExtractor(provider)

    print("=" * 70)
    print("PGA Analytics — Read-only backtest diagnostics")
    print("=" * 70)
    print(f"Provider:     {settings.data_provider}")
    print(f"Test events:  {test_events} most-recent completed tournaments")
    print("Training + scoring (read-only; exports per-player rows)…\n")

    result = await run_diagnostics(
        catalog=catalog, extractor=extractor,
        test_events=test_events, holdout_fraction=holdout,
    )

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_predictions(result, out / "predictions.csv")
    _write_importances(result, out / "importances.csv")
    _write_calibration(result, out / "calibration.json")

    print(f"Trained through:   {result.train_through}")
    print(f"Train examples:    {result.n_train_examples}")
    print(f"Feature-set hash:  {result.feature_set_hash[:12]}")
    print(f"Rows exported:     {len(result.rows)} (players × test events)")
    print(f"\nWrote:\n  {out / 'predictions.csv'}\n  {out / 'importances.csv'}"
          f"\n  {out / 'calibration.json'}")
    print("\nDone.")


def main() -> None:
    args = _build_parser().parse_args()
    try:
        asyncio.run(_run(test_events=args.test_events, holdout=args.holdout,
                         out_dir=args.out_dir))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        print(f"\nDiagnostics could not run: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
