"""S27 (METHOD.md). Run from research/: python -m s27_liquid_8k.run"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from polybridge_research.analysis import pass_check, verdict, difference_board
from polybridge_research.calendar import TradingCalendar
from polybridge_research.config import StudyConfig
from polybridge_research.massive import MassiveClient, load_api_key
from polybridge_research.pipeline import run_family_study

START, END, LAST = "2022-01-01", "2022-12-31", pd.Timestamp("2026-10-02")
RESULTS = Path(__file__).resolve().parent.parent / "results" / "s27_liquid_8k"
STRAT = {"hedge": "protective_put", "opportunity": "cash_secured_put"}
TOP = 0.20


def fam_of(p):
    return str(getattr(p.family, "value", p.family))


def vol_table(priced, kind):
    rows = []
    for p in priced:
        if p.bucket != "3-6m":
            continue
        v = p.legs["C_K"].volume_on(p.t_pre) + p.legs["P_K"].volume_on(p.t_pre)
        rows.append({"kind": kind, "family": fam_of(p), "ticker": p.ticker, "event_date": pd.Timestamp(p.event_date), "atm_volume": v})
    return pd.DataFrame(rows)


def keep(res, liquid):
    k = res.merge(liquid[["family", "ticker", "event_date"]], on=["family", "ticker", "event_date"], how="inner")
    return k


def sharpe(res, fam, years):
    r = res[(res.family == fam) & (res.bucket == "3-6m") & (res.entry == "post") & (res.otm == 0.05) & (res.horizon == 21)][STRAT[fam]].dropna()
    if len(r) < 3 or r.std(ddof=1) == 0:
        return len(r), float("nan")
    return len(r), float(r.mean() / r.std(ddof=1) * np.sqrt(len(r) / years))


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    cfg, cal = StudyConfig(), TradingCalendar()
    client = MassiveClient(load_api_key(search_from=Path.cwd()))
    st = run_family_study(client, cal, cfg, START, END, LAST)
    vt = pd.concat([vol_table(st["priced"], "event"), vol_table(st["placebo_priced"], "placebo")], ignore_index=True)
    vt["threshold"] = vt.groupby("family")["atm_volume"].transform(lambda s: s.quantile(1 - TOP))
    vt["liquid"] = vt.atm_volume >= vt.threshold
    vt.to_csv(RESULTS / "liquidity.csv", index=False)
    out, rows = {}, []
    for fam in STRAT:
        for scope in ("liquid", "all"):
            ev = st["results"][st["results"].family == fam]
            pl = st["placebo_results"][st["placebo_results"].family == fam]
            if scope == "liquid":
                ev = keep(ev, vt[(vt.kind == "event") & vt.liquid & (vt.family == fam)])
                pl = keep(pl, vt[(vt.kind == "placebo") & vt.liquid & (vt.family == fam)])
            chk = pass_check(ev, pl, fam, cfg) if len(ev) and len(pl) else None
            n, s = sharpe(ev, fam, 1.0)
            _, s_pl = sharpe(pl, fam, 1.0) if len(pl) else (0, float("nan"))
            board = difference_board(ev, pl, cfg, level=cfg.confirmatory_level, strategies=[STRAT[fam]]) if len(ev) and len(pl) else pd.DataFrame()
            board.assign(family=fam, scope=scope).to_csv(RESULTS / f"{fam}_{scope}_difference.csv", index=False)
            v = verdict(chk)
            heads = chk["pnl"][["horizon", "n_a", "n_b", "difference", "ci_lo", "ci_hi"]].to_dict("records") if chk else []
            rows.append({"family": fam, "scope": scope, "verdict": v, "events_21": n, "sharpe_events_gross": s,
                         "sharpe_placebo_gross": s_pl, "headline": heads,
                         "ratio_ok": chk["horizons_ratio_ok"] if chk else [], "pnl_ok": chk["horizons_pnl_ok"] if chk else []})
            print(f"\n[{fam} | {scope}] verdict {v} | events at 21: {n} | Sharpe events {s:.2f} vs placebo {s_pl:.2f}")
            if len(board):
                print((board[["horizon", "n_a", "n_b", "difference", "ci_lo", "ci_hi"]].set_index("horizon") * [1, 1, 100, 100, 100]).round(2).to_string())
    (RESULTS / "verdict.json").write_text(json.dumps(rows, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
