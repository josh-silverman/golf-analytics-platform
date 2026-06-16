"""Bootstrap & validation CLI — run once when switching to DataGolf.

Usage (from the backend directory, inside the container):
    uv run python -m app.cli.bootstrap                 # validate + train
    uv run python -m app.cli.bootstrap --skip-train    # validate only
    docker compose exec api uv run python -m app.cli.bootstrap

What it does, against whatever provider DATA_PROVIDER selects:
    1. Confirms the provider is reachable (player list).
    2. Fetches the season schedule and summarises event statuses.
    3. Fetches the live field for the current event (best-effort).
    4. **Validates training readiness** on a completed event end-to-end —
       finishing positions parse into labels, and a player's rounds come back
       dated with SG present. These checks catch a DataGolf response-shape
       drift loudly here, instead of as a silently-useless model after
       training.
    5. (Unless --skip-train) trains and registers the calibrated model.

Runs against mock too, so you can exercise the whole flow before buying a key.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.models import Tournament
    from app.providers.base import DataProvider


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m app.cli.bootstrap",
        description="Validate the data provider and train the first model.",
    )
    p.add_argument(
        "--through",
        metavar="YYYY-MM-DD",
        default=None,
        help="Latest date to include in training data (default: today)",
    )
    p.add_argument("--name", default="golf_v1", help="Model name (default: golf_v1)")
    p.add_argument(
        "--skip-train",
        action="store_true",
        help="Only validate provider + data readiness; skip training",
    )
    return p


async def _validate_training_readiness(
    provider: DataProvider, tournament: Tournament
) -> None:
    """Deep-check one completed event against what the model pipeline needs.

    Each check prints ✔/⚠ with remediation guidance so a DataGolf response
    shape drift is caught loudly here rather than as a silently-useless model.
    """
    # --- Check 1: field has finishing positions (training labels) ----------
    try:
        field = await provider.get_tournament_field(tournament.id)
    except Exception as exc:
        print(f"   ⚠  Could not fetch field for {tournament.name}: {exc}\n", file=sys.stderr)
        return

    if not field:
        print(f"   ⚠  Completed event {tournament.name} returned an empty field.\n",
              file=sys.stderr)
        return

    with_positions = [e for e in field if e.final_position is not None]
    missed = [e for e in field if e.status.value == "missed_cut"]
    if with_positions:
        print(
            f"   ✔  Field labels OK — {len(with_positions)}/{len(field)} entries "
            f"have a finishing position, {len(missed)} missed the cut"
        )
    else:
        print(
            "   ⚠  NO finishing positions parsed — training would have no\n"
            "      win/top-N labels. DataGolf's 'fin_text' may have changed shape;\n"
            "      check _parse_fin_text in datagolf_provider.py.",
            file=sys.stderr,
        )

    # --- Check 2: a player's rounds are dated + carry SG (features) ---------
    made_cut = next(
        (e for e in field if e.status.value == "made_cut" and e.final_position),
        None,
    )
    if made_cut is None:
        print("   ℹ  No made-cut player to deep-check rounds against\n")
        return

    try:
        rounds = await provider.get_rounds_for_player(made_cut.player_id, limit=20)
    except Exception as exc:
        print(f"   ⚠  Could not fetch rounds: {exc}\n", file=sys.stderr)
        return

    if not rounds:
        print(
            "   ⚠  A made-cut player returned ZERO rounds — features will be empty.\n"
            "      Check the historical-rounds parse in datagolf_provider.py.\n",
            file=sys.stderr,
        )
        return

    dated = [r for r in rounds if r.tee_time is not None]
    has_sg = any(r.sg_total != 0.0 for r in rounds)
    if len(dated) == len(rounds) and has_sg:
        print(
            f"   ✔  Rounds OK — {len(rounds)} rounds, all dated, SG present.\n"
            "   ✔  Training readiness validated.\n"
        )
        return
    if len(dated) != len(rounds):
        print(
            f"   ⚠  {len(rounds) - len(dated)}/{len(rounds)} rounds have no tee_time —\n"
            "      the feature pipeline DROPS undated rounds, so features would be\n"
            "      empty. Check _round_datetime wiring in datagolf_provider.py.",
            file=sys.stderr,
        )
    if not has_sg:
        print(
            "   ⚠  All SG values are zero — check the sg_* keys in the\n"
            "      historical-rounds payload.",
            file=sys.stderr,
        )
    print()


async def _run(*, through: date, name: str, skip_train: bool) -> None:
    from app.config import get_settings
    from app.providers.factory import get_data_provider

    settings = get_settings()
    print("=" * 62)
    print("PGA Analytics — Bootstrap & validation")
    print("=" * 62)
    print(f"Provider: {settings.data_provider}\n")

    if settings.data_provider == "datagolf" and not settings.datagolf_api_key:
        print(
            "❌  DATA_PROVIDER=datagolf but DATAGOLF_API_KEY is not set.\n"
            "    Get a key at https://datagolf.com/api-access\n",
            file=sys.stderr,
        )
        sys.exit(1)

    provider = get_data_provider()

    # 1. Players
    print("── Step 1: Fetching player list …")
    try:
        players = await provider.list_players(limit=9999)
        print(f"   ✔  {len(players.items)} players returned\n")
    except Exception as exc:
        print(f"   ❌  Failed to fetch players: {exc}", file=sys.stderr)
        sys.exit(1)

    # 2. Schedule
    print("── Step 2: Fetching schedule …")
    today = date.today()
    completed: list[Tournament] = []
    try:
        sched = await provider.list_tournaments(season=today.year, limit=9999)
        in_progress = [t for t in sched.items if t.status.value == "in_progress"]
        upcoming = [t for t in sched.items if t.status.value == "upcoming"]
        completed = [t for t in sched.items if t.status.value == "completed"]
        print(
            f"   ✔  {len(sched.items)} events in {today.year}: "
            f"{len(in_progress)} in-progress, {len(upcoming)} upcoming, "
            f"{len(completed)} completed\n"
        )
    except Exception as exc:
        print(f"   ⚠  Schedule fetch failed (non-fatal): {exc}\n", file=sys.stderr)
        in_progress = []

    # 3. Live field
    print("── Step 3: Fetching live field …")
    try:
        if in_progress:
            field = await provider.get_tournament_field(in_progress[0].id)
            print(f"   ✔  {len(field)} players in {in_progress[0].name}\n")
        else:
            print("   ℹ  No in-progress event right now — skipping\n")
    except Exception as exc:
        print(f"   ⚠  Field fetch failed (non-fatal): {exc}\n", file=sys.stderr)

    # 4. Validate training readiness
    print("── Step 4: Validating training readiness …")
    if completed:
        await _validate_training_readiness(provider, completed[0])
    else:
        print("   ℹ  No completed events yet — skipping deep validation\n")

    # 5. Train
    if skip_train:
        print("── Step 5: Skipped (--skip-train)")
        print("\n✔  Bootstrap complete — provider + data readiness validated.")
        return

    print("── Step 5: Training calibrated model …")
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
            builder=builder, registry=registry, through=through, name=name,
            season=None, activate=True,
        )
        print(f"   ✔  Registered {name} @ {version.version_id[:12]} (active)")
        for k, v in sorted(version.metrics.items()):
            val = f"{v:.4f}" if isinstance(v, float) else str(v)
            print(f"        {k}: {val}")
    except Exception as exc:
        print(f"   ❌  Training failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print("\n✔  Bootstrap complete — the platform is live on real data.")


def main() -> None:
    args = _build_parser().parse_args()
    through = date.fromisoformat(args.through) if args.through else date.today()
    try:
        asyncio.run(_run(through=through, name=args.name, skip_train=args.skip_train))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
