"""Backtest CLI — measure out-of-sample model accuracy honestly.

Usage (from the backend directory):
    uv run python -m app.cli.backtest
    uv run python -m app.cli.backtest --test-events 20
    uv run python -m app.cli.backtest --test-events 20 --holdout 0.2

Walks forward over the most recent ``--test-events`` completed tournaments,
trains a calibrated GBDT on everything before them, and scores its
predictions against what actually happened. Prints per-market probability
quality (Brier / log-loss / ECE, plus a skill score versus a base-rate
baseline), ranking quality (does the winner land near the top?), and a
per-event breakdown.

Reads from the configured data provider (mock or datagolf), so the same
command reports real accuracy the moment DataGolf is plugged in. Does not
touch the model registry — it trains throwaway models purely to evaluate.
"""

from __future__ import annotations

import argparse
import asyncio
import sys


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m app.cli.backtest",
        description="Rolling-origin backtest of the golf prediction model.",
    )
    p.add_argument(
        "--test-events",
        type=int,
        default=10,
        help="Number of most-recent completed tournaments to test on (default: 10)",
    )
    p.add_argument(
        "--holdout",
        type=float,
        default=0.25,
        help="Calibration holdout fraction within the training window (default: 0.25)",
    )
    p.add_argument(
        "--half-life",
        type=int,
        default=None,
        metavar="DAYS",
        help="Recency half-life in days for training-example weighting "
        "(default: off — every example weighted equally)",
    )
    return p


def _fmt_pct(x: float) -> str:
    return f"{x * 100:5.1f}%"


async def _run(*, test_events: int, holdout: float, half_life: int | None) -> None:
    from app.config import get_settings
    from app.ml.backtest import run_backtest
    from app.ml.trainer import GBDTTrainer, TrainerConfig
    from app.providers.factory import get_data_provider
    from app.services.catalog import CatalogService
    from app.services.features import FeatureExtractor

    settings = get_settings()
    provider = get_data_provider()
    catalog = CatalogService(provider)
    extractor = FeatureExtractor(provider)
    base_trainer = (
        GBDTTrainer(TrainerConfig(recency_half_life_days=half_life))
        if half_life is not None
        else None
    )

    print("=" * 70)
    print("PGA Analytics — Rolling-origin backtest")
    print("=" * 70)
    print(f"Provider:     {settings.data_provider}")
    print(f"Test events:  {test_events} most-recent completed tournaments")
    print(f"Recency:      {f'half-life {half_life}d' if half_life else 'off (uniform)'}")
    print()
    print("Training and scoring (this evaluates out-of-sample — may take a bit)…")

    report = await run_backtest(
        catalog=catalog,
        extractor=extractor,
        base_trainer=base_trainer,
        test_events=test_events,
        holdout_fraction=holdout,
    )

    print()
    print(f"Trained through:    {report.train_through}")
    print(f"Train examples:     {report.n_train_examples}")
    print(f"Feature-set hash:   {report.feature_set_hash[:12]}")
    print(f"Test events:        {report.n_test_events}")
    print(f"Test predictions:   {report.n_test_predictions}")

    # --- Probability quality ----------------------------------------------
    print("\n" + "-" * 70)
    print("PROBABILITY QUALITY (out-of-sample)")
    print("-" * 70)
    print(
        f"{'market':<14}{'base':>8}{'brier':>9}{'logloss':>9}"
        f"{'ece':>8}{'skill':>9}"
    )
    print(f"{'':<14}{'rate':>8}{'':>9}{'':>9}{'':>8}{'vs base':>9}")
    for o in report.outcomes:
        print(
            f"{o.outcome_key:<14}"
            f"{_fmt_pct(o.base_rate):>8}"
            f"{o.brier:>9.4f}"
            f"{o.log_loss:>9.4f}"
            f"{o.ece:>8.4f}"
            f"{o.brier_skill_score:>+9.3f}"
        )
    print(
        "\n  skill = 1 − brier/base_rate_brier. Positive ⇒ beats predicting the\n"
        "  field-average rate for everyone; ≤ 0 ⇒ no edge over that baseline."
    )

    # --- Ranking quality ---------------------------------------------------
    r = report.ranking
    print("\n" + "-" * 70)
    print("RANKING QUALITY")
    print("-" * 70)
    print(f"  Spearman(win prob, finish):   {r.spearman_winprob_vs_finish:+.3f}  "
          f"(1.0 = perfect ordering, 0 = none)")
    print(f"  Mean winner predicted rank:   {r.mean_winner_predicted_rank:.1f}")
    print(f"  Median winner predicted rank: {r.median_winner_predicted_rank:.1f}")
    print(f"  Winner in our top-5:          {_fmt_pct(r.winner_in_top5_rate)}")
    print(f"  Winner in our top-10:         {_fmt_pct(r.winner_in_top10_rate)}")

    # --- Per-event breakdown ----------------------------------------------
    print("\n" + "-" * 70)
    print("PER-EVENT BREAKDOWN")
    print("-" * 70)
    print(f"{'date':<12}{'tournament':<34}{'winner rank':>12}")
    for ev in report.events:
        rank = "—" if ev.winner_predicted_rank is None else str(ev.winner_predicted_rank)
        name = ev.tournament_name[:32]
        print(f"{str(ev.start_date):<12}{name:<34}{rank:>12}")

    print("\nDone.")


def main() -> None:
    args = _build_parser().parse_args()
    try:
        asyncio.run(
            _run(
                test_events=args.test_events,
                holdout=args.holdout,
                half_life=args.half_life,
            )
        )
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        print(f"\nBacktest could not run: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
