"""Grade the completed 3M Open and pull the next event (Rocket Classic).

Grades BOTH boards against actual results:
  - DG raw pre-tournament archive  = what Path A *intends* to serve
  - served v2 SG-only board        = what production actually served (the bug)

Read-only. Writes JSON to scripts/output/.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.config import get_settings
from app.domain.enums import EntryStatus, TournamentStatus
from app.features.feature_sets import v2_field_relative
from app.ml.registry import ModelRegistry
from app.providers.factory import get_data_provider
from app.services.catalog import CatalogService, reference_today
from app.services.features import FeatureExtractor
from app.services.predictions import PathASource, PredictionService

SCRATCH = Path(__file__).parent / "output"
MK = ["win_prob", "top_5_prob", "top_10_prob", "top_20_prob", "make_cut_prob"]
THREE_M = 525


def labels(final_position, status):
    if status == EntryStatus.MADE_CUT:
        made = True
    elif status == EntryStatus.MISSED_CUT:
        made = False
    else:
        return None
    pos = final_position
    return {
        "win_prob": int(pos == 1),
        "top_5_prob": int(pos is not None and pos <= 5),
        "top_10_prob": int(pos is not None and pos <= 10),
        "top_20_prob": int(pos is not None and pos <= 20),
        "make_cut_prob": int(made),
    }


def brier(pairs):
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs) if pairs else float("nan")


async def build_service(prov, cat, settings):
    reg = ModelRegistry(Path(settings.model_registry_path))
    v2h = v2_field_relative().hash
    cands = [v for v in reg.list_versions(settings.active_model_name) if v.feature_set_hash == v2h]
    best = max(cands, key=lambda v: v.training_data_through)
    return PredictionService(
        catalog=cat,
        extractor=FeatureExtractor(prov, feature_set=v2_field_relative()),
        model=reg.load_artifact(best),
        model_name=settings.active_model_name,
        model_version_id=f"path_a@{best.version_id}",
        model_trained_through=best.training_data_through,
        path_a=PathASource(provider=prov),
    ), best


async def main() -> None:
    s = get_settings()
    prov = get_data_provider()
    raw = getattr(prov, "_provider", prov)
    cat = CatalogService(prov)
    svc, mv = await build_service(prov, cat, s)

    out = {}

    # ---------------- 1. GRADE THE 3M OPEN ----------------
    t = await cat.get_tournament(THREE_M)
    print(f"### 3M Open: status={t.status} start={t.start_date}")
    field = await cat.get_tournament_field(THREE_M)
    lab = {e.player_id: labels(e.final_position, e.status) for e in field}
    pos = {e.player_id: e.final_position for e in field}
    names = {e.player_id: None for e in field}
    graded = {k: v for k, v in lab.items() if v is not None}
    print(f"### field={len(field)} graded={len(graded)}")

    # DG raw archive = intended Path A output (pre-event, leakage-safe)
    dg = await raw.get_pretournament_full_preds(THREE_M, t.season, live=False)
    print(f"### dg archive rows={len(dg)}")

    # served board (v2 fallback, what production actually showed)
    preds = await svc.predict_tournament(THREE_M, as_of=reference_today())
    served = {o.player_id: o for o in preds.outcomes}
    for o in preds.outcomes:
        names[o.player_id] = o.player_name

    # base rates from actuals
    base = {m: sum(v[m] for v in graded.values()) / len(graded) for m in MK}

    rows = {"dg": {m: [] for m in MK}, "v2": {m: [] for m in MK}, "base": {m: [] for m in MK}}
    for pid, y in graded.items():
        d = dg.get(pid)
        o = served.get(pid)
        for m in MK:
            if d is not None:
                rows["dg"][m].append((d[m], y[m]))
            if o is not None:
                rows["v2"][m].append(
                    (
                        getattr(
                            o, m.replace("_prob", "") if m != "make_cut_prob" else "make_cut_prob"
                        )
                        if False
                        else getattr(o, m),
                        y[m],
                    )
                )
            rows["base"][m].append((base[m], y[m]))

    print("\n=== 3M OPEN BRIER (lower better) + skill vs base rate ===")
    print(
        f"{'market':<16}{'DG_raw':>10}{'served_v2':>11}{'base':>9}{'DG_skill':>10}{'v2_skill':>10}"
    )
    grades = {}
    for m in MK:
        bd, bv, bb = brier(rows["dg"][m]), brier(rows["v2"][m]), brier(rows["base"][m])
        sd = 1 - bd / bb if bb > 0 else 0.0
        sv = 1 - bv / bb if bb > 0 else 0.0
        grades[m] = {
            "dg_brier": bd,
            "v2_brier": bv,
            "base_brier": bb,
            "dg_skill": sd,
            "v2_skill": sv,
            "base_rate": base[m],
        }
        print(f"{m:<16}{bd:>10.4f}{bv:>11.4f}{bb:>9.4f}{sd:>+10.3f}{sv:>+10.3f}")

    # how the published picks actually finished
    print("\n=== PUBLISHED PICKS — ACTUAL FINISH ===")
    picks = {
        "win": [
            "Scheffler, Scottie",
            "McNealy, Maverick",
            "Kitayama, Kurt",
            "Kim, Tom",
            "Matsuyama, Hideki",
        ],
        "value_top20": [
            "Scheffler, Scottie",
            "Kim, Tom",
            "McNealy, Maverick",
            "Ghim, Doug",
            "Kohles, Ben",
        ],
        "fades": [
            "Sargent, Gordon",
            "Hojgaard, Rasmus",
            "Knapp, Jake",
            "Jaeger, Stephan",
            "Grillo, Emiliano",
        ],
    }
    name_to_pid = {v: k for k, v in names.items() if v}
    pick_results = {}
    for group, plist in picks.items():
        print(f"-- {group} --")
        pick_results[group] = []
        for nm in plist:
            pid = name_to_pid.get(nm)
            if pid is None:
                print(f"   {nm:<24} NOT IN FIELD/RESULT")
                continue
            fp = pos.get(pid)
            y = lab.get(pid)
            d = dg.get(pid, {})
            rec = {
                "name": nm,
                "final_position": fp,
                "made_cut": (y or {}).get("make_cut_prob"),
                "dg_top20": d.get("top_20_prob"),
                "dg_win": d.get("win_prob"),
            }
            pick_results[group].append(rec)
            print(
                f"   {nm:<24} finish={str(fp):<6} made_cut={rec['made_cut']} "
                f"dg_win={d.get('win_prob', 0):.3f} dg_top20={d.get('top_20_prob', 0):.3f}"
            )

    # winner + leaderboard top 10
    top10 = sorted([(p, pid) for pid, p in pos.items() if p], key=lambda x: x[0])[:10]
    print("\n=== ACTUAL TOP 10 ===")
    for p, pid in top10:
        d = dg.get(pid, {})
        print(
            f"   {p:>3}  {str(names.get(pid)):<24} dg_win={d.get('win_prob', 0):.4f} "
            f"dg_top20={d.get('top_20_prob', 0):.3f} served_win={getattr(served.get(pid), 'win_prob', 0):.4f}"
        )

    # where did DG rank the winner?
    dg_rank = sorted(dg.items(), key=lambda kv: -kv[1]["win_prob"])
    winner_pid = next((pid for pid, p in pos.items() if p == 1), None)
    if winner_pid:
        r = next((i + 1 for i, (pid, _) in enumerate(dg_rank) if pid == winner_pid), None)
        v2_rank = sorted(served.items(), key=lambda kv: -kv[1].win_prob)
        rv = next((i + 1 for i, (pid, _) in enumerate(v2_rank) if pid == winner_pid), None)
        print(f"\n### WINNER {names.get(winner_pid)}: DG win-rank={r}, served-v2 win-rank={rv}")
        out["winner"] = {"name": names.get(winner_pid), "dg_rank": r, "v2_rank": rv}

    out["three_m"] = {
        "grades": grades,
        "picks": pick_results,
        "top10": [{"pos": p, "name": names.get(pid)} for p, pid in top10],
        "n_graded": len(graded),
    }

    # ---------------- 2. NEXT EVENT ----------------
    up = await cat.list_tournaments(status=TournamentStatus.UPCOMING, limit=200)
    nxt = None
    for cand in sorted(up.items, key=lambda x: x.start_date):
        if "rocket" in cand.name.lower():
            nxt = cand
            break
    if nxt is None:
        nxt = sorted(up.items, key=lambda x: x.start_date)[0] if up.items else None
    if nxt is None:
        cur = await cat.get_current_tournament()
        nxt = cur
    print(f"\n### NEXT EVENT: id={nxt.id} {nxt.name} start={nxt.start_date} status={nxt.status}")
    out["next_event"] = {
        "id": nxt.id,
        "name": nxt.name,
        "start_date": str(nxt.start_date),
        "season": nxt.season,
        "status": str(nxt.status),
    }

    SCRATCH.mkdir(parents=True, exist_ok=True)
    with open(SCRATCH / "grade_3m_and_next.json", "w") as f:
        json.dump(out, f, indent=1, default=str)
    print(f"\nWROTE {SCRATCH / 'grade_3m_and_next.json'}")


if __name__ == "__main__":
    asyncio.run(main())
