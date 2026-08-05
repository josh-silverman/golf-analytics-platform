"""Lead-analyst data pull for the 3M Open — runs the real Path A pipeline and
dumps every model output + market comparison + SG feature evidence to JSON.

Read-only. No registry/model changes. Output: scripts/output/3m_open_analysis.json
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.domain.enums import TournamentStatus
from app.features.feature_sets import v2_field_relative
from app.ml.registry import ModelRegistry
from app.providers.factory import get_data_provider
from app.services.catalog import CatalogService, reference_today
from app.services.features import EventRef, FeatureExtractor
from app.services.predictions import PathASource, PredictionService

OUT = Path(__file__).parent / "output" / "3m_open_analysis.json"
MARKETS = ["win_prob", "top_5_prob", "top_10_prob", "top_20_prob", "make_cut_prob"]


def _american_to_implied(american: int) -> float:
    if american < 0:
        return -american / (-american + 100.0)
    return 100.0 / (american + 100.0)


async def main() -> None:
    settings = get_settings()
    provider = get_data_provider()
    raw = getattr(provider, "_provider", provider)  # unwrap caching wrapper
    catalog = CatalogService(provider)
    registry = ModelRegistry(Path(settings.model_registry_path))

    # --- find the 3M Open (upcoming) ---
    up = await catalog.list_tournaments(status=TournamentStatus.UPCOMING, limit=200)
    target = None
    for t in up.items:
        if "3m" in t.name.lower() or "3m open" in t.name.lower():
            target = t
            break
    if target is None:
        # fall back: current tournament
        target = await catalog.get_current_tournament()
    if target is None:
        print(json.dumps({"error": "3M Open not found", "upcoming": [t.name for t in up.items]}))
        return
    print(
        f"TARGET: id={target.id} name={target.name} start={target.start_date} status={target.status}"
    )

    # --- build the Path A prediction service (mirror deps) ---
    v2_hash = v2_field_relative().hash
    cands = [
        v
        for v in registry.list_versions(settings.active_model_name)
        if v.feature_set_hash == v2_hash
    ]
    best = max(cands, key=lambda v: v.training_data_through)
    cold_model = registry.load_artifact(best)
    extractor = FeatureExtractor(provider, feature_set=v2_field_relative())
    service = PredictionService(
        catalog=catalog,
        extractor=extractor,
        model=cold_model,
        model_name=settings.active_model_name,
        model_version_id=f"path_a@{best.version_id}",
        model_trained_through=best.training_data_through,
        path_a=PathASource(provider=provider),
    )

    as_of = reference_today()
    preds = await service.predict_tournament(target.id, as_of=as_of)

    # --- what Path A actually serves for covered players (DG live full preds) ---
    dg_full = await raw.get_pretournament_full_preds(target.id, target.season, live=True)

    # --- sportsbook consensus odds per market (the market) ---
    odds_by_market: dict[str, dict[int, int]] = {}
    for m in MARKETS:
        board = await raw.get_outright_odds(m)
        odds_by_market[m] = board.odds if board else {}

    # --- SG skill decompositions (feature evidence) via direct DG calls ---
    skill_ratings: dict[int, dict[str, Any]] = {}
    try:
        r = await raw._http.get("/preds/skill-ratings", params={"display": "value"})
        r.raise_for_status()
        body = r.json()
        rows = body.get("players", body) if isinstance(body, dict) else body
        for row in rows if isinstance(rows, list) else []:
            dgid = row.get("dg_id")
            if dgid:
                skill_ratings[int(dgid)] = row
    except Exception as e:  # noqa: BLE001
        print("skill-ratings fetch failed:", e)

    decomps: dict[int, dict[str, Any]] = {}
    try:
        r = await raw._http.get("/preds/player-decompositions", params={"tour": "pga"})
        r.raise_for_status()
        body = r.json()
        rows = body.get("players", body) if isinstance(body, dict) else body
        for row in rows if isinstance(rows, list) else []:
            dgid = row.get("dg_id")
            if dgid:
                decomps[int(dgid)] = row
    except Exception as e:  # noqa: BLE001
        print("decompositions fetch failed:", e)

    # --- v2 SG features per player (our own SG evidence) ---
    field = await catalog.get_tournament_field(target.id)
    pids = [e.player_id for e in field]
    is_completed = target.status == TournamentStatus.COMPLETED
    extractions = await extractor.extract_field(
        pids, as_of, event=EventRef(event_id=target.id, season=target.season, live=not is_completed)
    )

    # --- assemble per-player records ---
    players_out = []
    for o in preds.outcomes:
        pid = o.player_id
        ex = extractions.get(pid)
        feats = ex.values if ex else {}
        covered = pid in dg_full  # player_id == dg_id in this codebase
        rec: dict[str, Any] = {
            "player_id": pid,
            "name": o.player_name,
            "covered_by_dg": covered,
            "served": {
                "win": o.win_prob,
                "top_5": o.top_5_prob,
                "top_10": o.top_10_prob,
                "top_20": o.top_20_prob,
                "make_cut": o.make_cut_prob,
            },
            "features_v2": {k: round(v, 4) for k, v in feats.items()},
            "skill_ratings": skill_ratings.get(pid, {}),
            "decomposition": decomps.get(pid, {}),
            "market_implied": {},
            "market_american": {},
        }
        for m in MARKETS:
            am = odds_by_market.get(m, {}).get(pid)
            if am is not None:
                rec["market_american"][m] = am
                rec["market_implied"][m] = round(_american_to_implied(am), 4)
        players_out.append(rec)

    result = {
        "tournament": {
            "id": target.id,
            "name": target.name,
            "start_date": str(target.start_date),
            "season": target.season,
            "status": str(target.status),
            "as_of": str(as_of),
        },
        "model_version_id": preds.model_version_id,
        "model_trained_through": str(preds.model_trained_through),
        "field_size": len(preds.outcomes),
        "n_covered": sum(1 for r in players_out if r["covered_by_dg"]),
        "n_cold_start": sum(1 for r in players_out if not r["covered_by_dg"]),
        "n_with_win_odds": len(odds_by_market.get("win_prob", {})),
        "players": players_out,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(result, f, indent=1, default=str)
    print(
        f"WROTE {OUT}  field={len(players_out)} covered={result['n_covered']} "
        f"cold={result['n_cold_start']} win_odds={result['n_with_win_odds']}"
    )


if __name__ == "__main__":
    asyncio.run(main())
