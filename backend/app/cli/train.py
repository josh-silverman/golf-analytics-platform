"""Training CLI — activate a calibrated model from the command line.

Usage (from the backend directory):
    uv run python -m app.cli.train
    uv run python -m app.cli.train --through 2024-12-31
    uv run python -m app.cli.train --through 2024-12-31 --name golf_v1 --no-activate

Options:
    --through DATE     Use data up to this date (default: today)
    --name    NAME     Model name to register (default: golf_v1)
    --no-activate      Register but do not set as active model
    --season  YEAR     Limit training data to one season
    --feature-set SET  v2 (14-feature SG-only) or v3 (18-feature, adds the
                       DataGolf meta-features). Default: v2.

This runs train_calibrated_and_register against the configured data provider and
writes the artifact to model_registry_path (see app/config.py).  After it
completes, the /predictions and /analytics/calibration endpoints pick up the
new model automatically on the next request.

Note that --feature-set defaults to v2 while the registered active model is v3.
Activating a model whose feature set differs from the current active one changes
what the serving layer computes, so that is refused unless you pass
--allow-feature-set-change.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.providers.base import DataProvider


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
    p.add_argument(
        "--use-historical-archive",
        action="store_true",
        help="Also train on the 2021-2023 DataGolf historical archive "
        "(get-schedule 400s for those years). Off by default — existing "
        "behaviour is unchanged unless explicitly opted in.",
    )
    p.add_argument(
        "--feature-set",
        choices=("v2", "v3"),
        default="v2",
        help="Feature set to train: v2 (14-feature SG-only) or v3 (18-feature, "
        "adds the DataGolf meta-features). Default: v2. The registered active "
        "model is v3, so training without this flag produces a different "
        "feature set than production serves.",
    )
    p.add_argument(
        "--allow-feature-set-change",
        action="store_true",
        help="Permit activating a model whose feature set differs from the "
        "currently active one. Without this, such an activation is refused: it "
        "silently changes what the serving layer computes.",
    )
    return p


async def _train(
    *,
    through: date,
    name: str,
    season: int | None,
    activate: bool,
    use_historical_archive: bool = False,
    feature_set: str = "v2",
    allow_feature_set_change: bool = False,
) -> None:
    # Lazy imports — keep the import fast for --help.
    from app.config import get_settings
    from app.features.feature_sets import v2_field_relative, v3_dg_preds
    from app.ml.calibration import train_calibrated_and_register
    from app.ml.registry import ModelRegistry
    from app.ml.training import TrainingDataBuilder
    from app.providers.factory import get_data_provider
    from app.services.catalog import CatalogService
    from app.services.features import FeatureExtractor

    settings = get_settings()
    fs = v3_dg_preds() if feature_set == "v3" else v2_field_relative()
    print(f"Registry:  {settings.model_registry_path}")
    print(f"Provider:  {settings.data_provider}")
    print(f"Features:  {feature_set} ({len(fs.features)} features, {fs.hash[:12]})")
    print(f"Training through: {through} | season filter: {season or 'all'}")
    archive_label = (
        f"on ({min(TrainingDataBuilder._ARCHIVE_SEASONS)}-"
        f"{max(TrainingDataBuilder._ARCHIVE_SEASONS)})"
        if use_historical_archive
        else "off"
    )
    print(f"Archive:   {archive_label}")
    print()

    registry = ModelRegistry(Path(settings.model_registry_path))

    # Guard the activation *before* spending an hour training. Activating a
    # model whose feature set differs from the active one repoints the serving
    # extractor (deps._feature_set_for_active_model resolves by hash), so
    # running this command with its v2 default against a v3 production model
    # would quietly swap the whole feature pipeline.
    if activate:
        current = registry.get_active(name)
        if (
            current is not None
            and current.feature_set_hash != fs.hash
            and not allow_feature_set_change
        ):
            print(
                f"\nRefusing to activate: {name} is currently active as "
                f"{current.version_id} on feature set {current.feature_set_hash[:12]}, "
                f"but this run trains {feature_set} ({fs.hash[:12]}).\n"
                f"Activating would change what the serving layer computes.\n"
                f"Re-run with --feature-set matching the active model, or with "
                f"--no-activate, or with --allow-feature-set-change if the swap "
                f"is intended.",
                file=sys.stderr,
            )
            raise SystemExit(2)

    # When the archive is opted in we need an archive-enabled DataGolfProvider
    # (it lifts the rounds-season cap and reaches pre-2024 events) for BOTH the
    # feature windows and the builder's archive_provider. Otherwise use the
    # configured provider unchanged, so default behaviour is identical.
    archive_provider = None
    provider: DataProvider
    if use_historical_archive:
        from app.cache.redis import redis_client
        from app.providers.datagolf.datagolf_provider import DataGolfProvider

        archive_provider = DataGolfProvider(redis=redis_client, archive_enabled=True)
        provider = archive_provider
    else:
        provider = get_data_provider()

    builder = TrainingDataBuilder(
        catalog=CatalogService(provider),
        extractor=FeatureExtractor(provider, feature_set=fs),
        use_historical_archive=use_historical_archive,
        archive_provider=archive_provider,
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
    through = date.fromisoformat(args.through) if args.through else date.today()
    try:
        asyncio.run(
            _train(
                through=through,
                name=args.name,
                season=args.season,
                activate=not args.no_activate,
                use_historical_archive=args.use_historical_archive,
                feature_set=args.feature_set,
                allow_feature_set_change=args.allow_feature_set_change,
            )
        )
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
