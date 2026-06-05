"""Training CLI — activate a calibrated model from the command line.

Usage (from the backend directory):
    uv run python -m app.cli.train
    uv run python -m app.cli.train --through 2024-12-31
    uv run python -m app.cli.train --through 2024-12-31 --name golf_v1 --no-activate

Options:
    --through DATE    Use data up to this date (default: today)
    --name    NAME    Model name to register (default: golf_v1)
    --no-activate     Register but do not set as active model
    --season  YEAR    Limit training data to one season

This runs train_calibrated_and_register against the configured data provider and
writes the artifact to model_registry_path (see app/config.py).  After it
completes, the /predictions and /analytics/calibration endpoints pick up the
new model automatically on the next request.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m app.cli.train",
        description="Fit and register a calibrated golf prediction model.",
    )
    p.add_argument(
        "--through",
        metavar="YYYY-MM-DD",
        default=None,
        help="Latest date to include in training data (default: today)",
    )
    p.add_argument(
        "--name",
        default="golf_v1",
        help="Model registry name (default: golf_v1)",
    )
    p.add_argument(
        "--season",
        type=int,
        default=None,
        help="Restrict training data to one calendar season",
    )
    p.add_argument(
        "--no-activate",
        action="store_true",
        help="Register without marking the version active",
    )
    return p


async def _train(
    *,
    through: date,
    name: str,
    season: int | None,
    activate: bool,
) -> None:
    # Lazy imports — keep the import fast for --help.
    from app.config import get_settings
    from app.ml.calibration import train_calibrated_and_register
    from app.ml.registry import ModelRegistry
    from app.ml.training import TrainingDataBuilder
    from app.providers.factory import get_data_provider
    from app.services.catalog import CatalogService
    from app.services.features import FeatureExtractor

    settings = get_settings()
    print(f"Registry:  {settings.model_registry_path}")
    print(f"Provider:  {settings.data_provider}")
    print(f"Training through: {through} | season filter: {season or 'all'}")
    print()

    provider = get_data_provider()
    registry = ModelRegistry(Path(settings.model_registry_path))
    builder = TrainingDataBuilder(
        catalog=CatalogService(provider),
        extractor=FeatureExtractor(provider),
    )

    print("Building training data and fitting calibrated model...")
    version = await train_calibrated_and_register(
        builder=builder,
        registry=registry,
        through=through,
        name=name,
        season=season,
        activate=activate,
    )

    print(f"\nRegistered  {name} @ {version.version_id}")
    print(f"Features    {version.feature_set_hash}")
    print(f"Through     {version.training_data_through}")
    print(f"Active      {'yes' if activate else 'no'}")
    print("\nMetrics:")
    for k, v in sorted(version.metrics.items()):
        print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")


def main() -> None:
    args = _build_parser().parse_args()
    through = (
        date.fromisoformat(args.through) if args.through else date.today()
    )
    try:
        asyncio.run(
            _train(
                through=through,
                name=args.name,
                season=args.season,
                activate=not args.no_activate,
            )
        )
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
