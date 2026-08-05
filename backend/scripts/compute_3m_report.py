"""Compute the 3M Open analyst tables from the pulled data + DataGolf raw.

Merges DataGolf's raw pre-tournament probs (the intended Path-A output) into the
existing analysis JSON, de-vigs the sportsbook market, and prints every report
section. Read-only.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.providers.factory import get_data_provider

JSON = Path(__file__).parent / "output" / "3m_open_analysis.json"
MK = ["win_prob", "top_5_prob", "top_10_prob", "top_20_prob", "make_cut_prob"]
SHORT = {
    "win_prob": "win",
    "top_5_prob": "top_5",
    "top_10_prob": "top_10",
    "top_20_prob": "top_20",
    "make_cut_prob": "make_cut",
}


async def main() -> None:
    d = json.load(open(JSON))
    P = d["players"]
    prov = get_data_provider()
    raw = getattr(prov, "_provider", prov)
    dg = await raw.get_pretournament_full_preds(525, 2026, live=True)  # dg_id-keyed

    for p in P:
        p["dg_raw"] = dg.get(p["player_id"], {})

    # de-vig market: scale each market's implied to sum to the DG raw total
    dg_sum = {m: sum(pl["dg_raw"].get(m, 0.0) for pl in P) for m in MK}
    mkt_sum = {m: sum(pl["market_implied"].get(m, 0.0) for pl in P) for m in MK}
    for p in P:
        p["mkt_fair"] = {}
        for m in MK:
            mi = p["market_implied"].get(m)
            if mi is not None and mkt_sum[m] > 0:
                p["mkt_fair"][m] = mi * dg_sum[m] / mkt_sum[m]

    def name(p):
        return p["name"]

    def sr(p, k):
        return p["skill_ratings"].get(k)

    def dec(p, k):
        return p["decomposition"].get(k)

    print(
        "### FIELD:",
        d["tournament"]["name"],
        d["tournament"]["start_date"],
        "| field",
        len(P),
        "| served model_version",
        d["model_version_id"],
    )
    print("### DG raw sums:", {SHORT[m]: round(dg_sum[m], 2) for m in MK})
    print("### served win: max %.4f  (COLLAPSED — see bug)" % max(p["served"]["win"] for p in P))
    print()

    print("=== A. DATAGOLF RAW WIN (intended Path-A ranking) top 12 ===")
    for p in sorted(P, key=lambda x: -x["dg_raw"].get("win_prob", 0))[:12]:
        print(
            "%-22s dg_win=%.3f  mkt_fair_win=%.3f  served_win=%.4f  sg_tot=%s dist=%s"
            % (
                name(p)[:22],
                p["dg_raw"].get("win_prob", 0),
                p["mkt_fair"].get("win_prob", 0),
                p["served"]["win"],
                sr(p, "sg_total"),
                sr(p, "driving_dist"),
            )
        )
    print()

    print("=== B. TOP-20: served(v2) vs DG raw vs mkt_fair, top 15 by served ===")
    for p in sorted(P, key=lambda x: -x["served"]["top_20"])[:15]:
        print(
            "%-22s served=%.3f dg=%.3f mkt=%.3f  sg_tot=%s"
            % (
                name(p)[:22],
                p["served"]["top_20"],
                p["dg_raw"].get("top_20_prob", 0),
                p["mkt_fair"].get("top_20_prob", 0),
                sr(p, "sg_total"),
            )
        )
    print()

    print("=== C. SAFEST MAKE-CUT: top 15 by DG raw make_cut ===")
    for p in sorted(P, key=lambda x: -x["dg_raw"].get("make_cut_prob", 0))[:15]:
        print(
            "%-22s dg_mc=%.3f served_mc=%.3f mkt_mc=%.3f  sg_tot=%s"
            % (
                name(p)[:22],
                p["dg_raw"].get("make_cut_prob", 0),
                p["served"]["make_cut"],
                p["mkt_fair"].get("make_cut_prob", 0),
                sr(p, "sg_total"),
            )
        )
    print()

    def edge(p, m):
        return p["dg_raw"].get(m, 0) - p["mkt_fair"].get(m) if m in p["mkt_fair"] else None

    print("=== D. VALUE (DG raw ABOVE market) — top_20, min mkt_fair 0.05, top 12 ===")
    cand = [p for p in P if "top_20_prob" in p["mkt_fair"] and p["mkt_fair"]["top_20_prob"] > 0.05]
    for p in sorted(cand, key=lambda x: -(edge(x, "top_20_prob") or -9))[:12]:
        print(
            "%-22s edge=%+.3f  dg=%.3f mkt=%.3f  sg_tot=%s crs_hist=%s crs_fit=%s"
            % (
                name(p)[:22],
                edge(p, "top_20_prob"),
                p["dg_raw"].get("top_20_prob", 0),
                p["mkt_fair"]["top_20_prob"],
                sr(p, "sg_total"),
                dec(p, "total_course_history_adjustment"),
                dec(p, "total_fit_adjustment"),
            )
        )
    print()

    print("=== E. FADES (market ABOVE DG raw) — top_20, min mkt_fair 0.08, top 12 ===")
    cand2 = [p for p in P if "top_20_prob" in p["mkt_fair"] and p["mkt_fair"]["top_20_prob"] > 0.08]
    for p in sorted(cand2, key=lambda x: edge(x, "top_20_prob") or 9)[:12]:
        print(
            "%-22s edge=%+.3f  dg=%.3f mkt=%.3f  sg_tot=%s"
            % (
                name(p)[:22],
                edge(p, "top_20_prob"),
                p["dg_raw"].get("top_20_prob", 0),
                p["mkt_fair"]["top_20_prob"],
                sr(p, "sg_total"),
            )
        )
    print()

    print("=== F. SG DECOMP for DG-raw top 6 win ===")
    for p in sorted(P, key=lambda x: -x["dg_raw"].get("win_prob", 0))[:6]:
        print(
            "%-20s ott=%s app=%s arg=%s putt=%s tot=%s dist=%s acc=%s | crs_hist=%s dist_adj=%s"
            % (
                name(p)[:20],
                sr(p, "sg_ott"),
                sr(p, "sg_app"),
                sr(p, "sg_arg"),
                sr(p, "sg_putt"),
                sr(p, "sg_total"),
                sr(p, "driving_dist"),
                sr(p, "driving_acc"),
                dec(p, "total_course_history_adjustment"),
                dec(p, "driving_distance_adjustment"),
            )
        )

    json.dump(d, open(JSON, "w"), indent=1, default=str)


if __name__ == "__main__":
    asyncio.run(main())
