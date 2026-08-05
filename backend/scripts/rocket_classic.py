"""Simple pre-tournament analysis for the Rocket Classic (event 524).

Pulls DataGolf's pre-event probabilities (the intended Path-A output), the
de-vigged sportsbook market, and SG skill ratings / decompositions. Read-only.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.providers.factory import get_data_provider
from app.services.catalog import CatalogService

SCRATCH = Path(__file__).parent / "output"
EVENT = 524
MK = ["win_prob", "top_5_prob", "top_10_prob", "top_20_prob", "make_cut_prob"]


def implied(american: int) -> float:
    return -american / (-american + 100.0) if american < 0 else 100.0 / (american + 100.0)


async def main() -> None:
    prov = get_data_provider()
    raw = getattr(prov, "_provider", prov)
    cat = CatalogService(prov)

    t = await cat.get_tournament(EVENT)
    print(f"### {t.name} | start={t.start_date} | status={t.status}")

    dg = await raw.get_pretournament_full_preds(EVENT, t.season, live=True)
    field = await cat.get_tournament_field(EVENT)
    fids = {e.player_id for e in field}
    print(f"### field={len(field)} dg_rows={len(dg)} covered={len(fids & set(dg))}")

    # market
    odds = {}
    for m in MK:
        b = await raw.get_outright_odds(m)
        odds[m] = b.odds if b else {}
    print(f"### win odds available for {len(odds['win_prob'])} players")

    # skill + decomposition
    sk, dec = {}, {}
    try:
        r = await raw._http.get("/preds/skill-ratings", params={"display": "value"})
        r.raise_for_status()
        body = r.json()
        for row in body.get("players", body) if isinstance(body, dict) else body:
            if row.get("dg_id"):
                sk[int(row["dg_id"])] = row
    except Exception as e:
        print("skill fetch failed:", e)
    try:
        r = await raw._http.get("/preds/player-decompositions", params={"tour": "pga"})
        r.raise_for_status()
        body = r.json()
        for row in body.get("players", body) if isinstance(body, dict) else body:
            if row.get("dg_id"):
                dec[int(row["dg_id"])] = row
    except Exception as e:
        print("decomp fetch failed:", e)

    names = {}
    for pid in dg:
        names[pid] = (
            sk.get(pid, {}).get("player_name") or dec.get(pid, {}).get("player_name") or str(pid)
        )

    # de-vig market to DG field totals
    dgsum = {m: sum(v.get(m, 0) for v in dg.values()) for m in MK}
    mksum = {m: sum(implied(a) for a in odds[m].values()) for m in MK}
    fair = {}
    for pid in dg:
        fair[pid] = {}
        for m in MK:
            a = odds[m].get(pid)
            if a is not None and mksum[m] > 0:
                fair[pid][m] = implied(a) * dgsum[m] / mksum[m]

    infield = [pid for pid in dg if pid in fids] or list(dg)

    print("\n=== TOP 10 WIN (DataGolf raw) ===")
    for pid in sorted(infield, key=lambda p: -dg[p]["win_prob"])[:10]:
        s = sk.get(pid, {})
        print(
            f"{names[pid][:24]:<24} win={dg[pid]['win_prob']:.3f} mkt={fair[pid].get('win_prob', float('nan')):.3f} "
            f"t20={dg[pid]['top_20_prob']:.3f} mc={dg[pid]['make_cut_prob']:.3f} "
            f"sg_tot={s.get('sg_total')} ott={s.get('sg_ott')} app={s.get('sg_app')} putt={s.get('sg_putt')}"
        )

    print("\n=== TOP 12 TOP-20 (DataGolf raw) ===")
    for pid in sorted(infield, key=lambda p: -dg[p]["top_20_prob"])[:12]:
        print(
            f"{names[pid][:24]:<24} t20={dg[pid]['top_20_prob']:.3f} mkt={fair[pid].get('top_20_prob', float('nan')):.3f} "
            f"sg_tot={sk.get(pid, {}).get('sg_total')}"
        )

    print("\n=== TOP 10 MAKE-CUT (DataGolf raw) ===")
    for pid in sorted(infield, key=lambda p: -dg[p]["make_cut_prob"])[:10]:
        print(
            f"{names[pid][:24]:<24} mc={dg[pid]['make_cut_prob']:.3f} mkt={fair[pid].get('make_cut_prob', float('nan')):.3f}"
        )

    def edge(pid, m):
        return dg[pid][m] - fair[pid][m] if m in fair.get(pid, {}) else None

    print("\n=== VALUE: DG above market, top-20 market (mkt>0.05) ===")
    c = [p for p in infield if fair.get(p, {}).get("top_20_prob", 0) > 0.05]
    for pid in sorted(c, key=lambda p: -(edge(p, "top_20_prob") or -9))[:10]:
        d = dec.get(pid, {})
        print(
            f"{names[pid][:24]:<24} edge={edge(pid, 'top_20_prob'):+.3f} dg={dg[pid]['top_20_prob']:.3f} "
            f"mkt={fair[pid]['top_20_prob']:.3f} sg_tot={sk.get(pid, {}).get('sg_total')} "
            f"fit={d.get('total_fit_adjustment')} hist={d.get('total_course_history_adjustment')}"
        )

    print("\n=== FADES: market above DG, top-20 market (mkt>0.08) ===")
    c2 = [p for p in infield if fair.get(p, {}).get("top_20_prob", 0) > 0.08]
    for pid in sorted(c2, key=lambda p: edge(p, "top_20_prob") or 9)[:10]:
        print(
            f"{names[pid][:24]:<24} edge={edge(pid, 'top_20_prob'):+.3f} dg={dg[pid]['top_20_prob']:.3f} "
            f"mkt={fair[pid]['top_20_prob']:.3f} sg_tot={sk.get(pid, {}).get('sg_total')}"
        )

    print("\n=== SG DECOMP — DG top 6 win ===")
    for pid in sorted(infield, key=lambda p: -dg[p]["win_prob"])[:6]:
        s, d = sk.get(pid, {}), dec.get(pid, {})
        print(
            f"{names[pid][:20]:<20} ott={s.get('sg_ott')} app={s.get('sg_app')} arg={s.get('sg_arg')} "
            f"putt={s.get('sg_putt')} tot={s.get('sg_total')} dist={s.get('driving_dist')} "
            f"acc={s.get('driving_acc')} | fit={d.get('total_fit_adjustment')} hist={d.get('total_course_history_adjustment')} "
            f"distadj={d.get('driving_distance_adjustment')}"
        )

    payload = {
        "event": {"id": EVENT, "name": t.name, "start": str(t.start_date), "field": len(field)},
        "players": [
            {
                "pid": pid,
                "name": names[pid],
                "dg": dg[pid],
                "fair": fair.get(pid, {}),
                "skill": sk.get(pid, {}),
                "decomp": dec.get(pid, {}),
            }
            for pid in infield
        ],
    }
    SCRATCH.mkdir(parents=True, exist_ok=True)
    with open(SCRATCH / "rocket_classic.json", "w") as f:
        json.dump(payload, f, indent=1, default=str)
    print(f"\nWROTE {SCRATCH / 'rocket_classic.json'}")


if __name__ == "__main__":
    asyncio.run(main())
