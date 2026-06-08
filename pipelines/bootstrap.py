"""Bootstrap pipeline — first-time setup when switching to DataGolf.

Run this once after setting DATAGOLF_API_KEY to verify the API connection,
warm the data cache, and train the first production model.

Usage (from the repo root):
    # With uv (recommended)
    cd backend && uv run python -m pipelines.bootstrap

    # Or: docker compose exec api python -m pipelines.bootstrap

    # With custom date cutoff:
    cd backend && uv run python -m pipelines.bootstrap --through 2025-12-31

What it does:
    1. Validates DATAGOLF_API_KEY and DATA_PROVIDER=datagolf are set.
    2. Fetches the player list from DataGolf — prints count as a smoke test.
    3. Fetches the current season schedule — prints event count.
    4. Fetches the current tournament field (live).
    5. Trains a calibrated GBDT model on historical round data and registers
       it as the active version.

After this script completes the full platform is live:
    /predictions/{id}   — our model's win probabilities
    /simulations/{id}   — Monte Carlo outcomes
    /betting/edge/{id}  — Kelly-sized +EV lines
    /analytics/benchmark/{id} — our model vs. DataGolf head-to-head
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m pipelines.bootstrap",
        description="Verify DataGolf API and train the first production model.",
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
        "--skip-train",
        action="store_true",
        help="Only verify API connectivity; skip model training",
    )
    return p


async def _run(*, through: date, name: str, skip_train: bool) -> None:
    import os

    from app.config import get_settings
    from app.providers.factory import get_data_provider

    settings = get_settings()

    # ------------------------------------------------------------------
    # 1. Validate environment
    # ------------------------------------------------------------------
    print("=" * 60)
    print("PGA Analytics — Bootstrap")
    print("=" * 60)

    if settings.data_provider != "datagolf":
        print(
            "\n❌  DATA_PROVIDER is not set to 'datagolf'.\n"
            "    Set it in your .env or shell:\n"
            "      export DATA_PROVIDER=datagolf\n",
            file=sys.stderr,
        )
        sys.exit(1)

    if not settings.datagolf_api_key:
        print(
            "\n❌  DATAGOLF_API_KEY is not set.\n"
            "    Get a key at https://datagolf.com/api-access then:\n"
            "      export DATAGOLF_API_KEY=<your-key>\n"
            "    On Fly.io:  fly secrets set DATAGOLF_API_KEY=<your-key>\n",
            file=sys.stderr,
        )
        sys.exit(1)

    key_preview = settings.datagolf_api_key[:6] + "…"
    print(f"\n✔  DATA_PROVIDER = datagolf")
    print(f"✔  DATAGOLF_API_KEY = {key_preview} (set)")
    print(f"   Training through: {through}")
    print(f"   Model name:       {name}\n")

    # ------------------------------------------------------------------
    # 2. Smoke-test the API — player list
    # ------------------------------------------------------------------
    print("── Step 1: Fetching player list …")
    provider = get_data_provider()
    try:
        players_page = await provider.list_players(limit=9999)
        print(f"   ✔  {len(players_page.items)} players returned from DataGolf\n")
    except Exception as exc:
        print(f"   ❌  Failed to fetch players: {exc}", file=sys.stderr)
        print(
            "       Check your DATAGOLF_API_KEY and network connectivity.",
            file=sys.stderr,
        )
        sys.exit(1)

    # ------------------------------------------------------------------
    # 3. Smoke-test — schedule
    # ------------------------------------------------------------------
    print("── Step 2: Fetching current season schedule …")
    today = date.today()
    try:
        sched = await provider.list_tournaments(season=today.year, limit=9999)
        print(f"   ✔  {len(sched.items)} events in {today.year} season")
        in_progress = [t for t in sched.items if t.status.value == "in_progress"]
        upcoming = [t for t in sched.items if t.status.value == "upcoming"]
        completed = [t for t in sched.items if t.status.value == "completed"]
        print(
            f"      in-progress: {len(in_progress)}  "
            f"upcoming: {len(upcoming)}  "
            f"completed: {len(completed)}\n"
        )
    except Exception as exc:
        print(f"   ⚠  Schedule fetch failed (non-fatal): {exc}\n", file=sys.stderr)

    # ------------------------------------------------------------------
    # 4. Smoke-test — live field (best-effort)
    # ------------------------------------------------------------------
    print("── Step 3: Fetching live field …")
    try:
        if in_progress:
            field = await provider.get_tournament_field(in_progress[0].id)
            print(f"   ✔  {len(field)} players in current field ({in_progress[0].name})\n")
        else:
            print("   ℹ  No in-progress tournament right now — skipping field check\n")
    except Exception as exc:
        print(f"   ⚠  Field fetch failed (non-fatal): {exc}\n")

    # ------------------------------------------------------------------
    # 5. Train the model
    # ------------------------------------------------------------------
    if skip_train:
        print("── Step 4: Skipped (--skip-train)\n")
        print("✔  Bootstrap complete — API connection verified.")
        return

    print("── Step 4: Training calibrated GBDT model …")
    print("   (This fetches historical round data from DataGolf — may take a few minutes)")
    try:
        from app.ml.calibration import train_calibrated_and_register
        from app.ml.registry import ModelRegistry
        from app.ml.training import TrainingDataBuilder
        from app.services.catalog import CatalogService
        from app.services.features import FeatureExtractor

        registry = ModelRegistry(Path(settings.model_registry_path))
        builder = TrainingDataBuilder(
            catalog=CatalogService(provider),
            extractor=FeatureExtractor(provider),
        )

        version = await train_calibrated_and_register(
            builder=builder,
            registry=registry,
            through=through,
            name=name,
            season=None,
            activate=True,
        )

        print(f"\n   ✔  Model registered:   {name} @ {version.version_id[:12]}")
        print(f"      Feature hash:       {version.feature_set_hash[:12]}")
        print(f"      Training through:   {version.training_data_through}")
        print("      Metrics:")
        for k, v in sorted(version.metrics.items()):
            val = f"{v:.4f}" if isinstance(v, float) else str(v)
            print(f"        {k}: {val}")

    except Exception as exc:
        print(f"\n   ❌  Model training failed: {exc}", file=sys.stderr)
        print(
            "       The API connection is confirmed; re-run without --skip-train\n"
            "       once the issue is resolved, or run:\n"
            "         uv run python -m app.cli.train\n",
            file=sys.stderr,
        )
        sys.exit(1)

    print(
        "\n✔  Bootstrap complete!\n"
        "\n   The platform is now live on real DataGolf data:\n"
        "     /predictions/{id}          — our model's win probabilities\n"
        "     /simulations/{id}          — Monte Carlo outcomes\n"
        "     /betting/edge/{id}         — Kelly-sized +EV lines\n"
        "     /analytics/benchmark/{id}  — our model vs. DataGolf head-to-head\n"
    )


def main() -> None:
    args = _build_parser().parse_args()
    through = date.fromisoformat(args.through) if args.through else date.today()
    try:
        asyncio.run(
            _run(
                through=through,
                name=args.name,
                skip_train=args.skip_train,
            )
        )
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
