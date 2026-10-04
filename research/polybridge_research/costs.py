from __future__ import annotations

import numpy as np
import pandas as pd

from .config import StudyConfig

LEGS_FOR_STRATEGY = {"long_call": ["C_K"], "covered_call": ["C_U{otm}"], "protective_put": ["P_L{otm}"],
                     "collar": ["C_U{otm}", "P_L{otm}"], "cash_secured_put": ["P_L{otm}"]}


def half_spread(client, opt_ticker: str, day: pd.Timestamp) -> float | None:
    d = pd.Timestamp(day).strftime("%Y-%m-%d")
    lower = int(pd.Timestamp(d + " 09:30", tz="America/New_York").value)
    bound = int(pd.Timestamp(d + " 16:00", tz="America/New_York").value)
    rows = client.get(f"/v3/quotes/{opt_ticker}", {"timestamp.gte": lower, "timestamp.lte": bound, "order": "desc",
                                                   "sort": "timestamp", "limit": 1}).get("results") or []
    if not rows:
        return None
    bid, ask = float(rows[0].get("bid_price") or 0), float(rows[0].get("ask_price") or 0)
    if bid <= 0 or ask <= 0 or ask < bid:
        return None
    return (ask - bid) / 2


def cost_table(results: pd.DataFrame, priced, strategy: str, horizon, cfg: StudyConfig, client=None,
               multipliers=(1, 2)) -> pd.DataFrame:
    legs = [l.format(otm=cfg.otm_pct) for l in LEGS_FOR_STRATEGY[strategy]]
    by_key = {(pe.ticker, pe.event_date, pe.family): pe for pe in priced if pe.bucket == cfg.baseline_bucket}
    r = results[(results.bucket == cfg.baseline_bucket) & (results.entry == cfg.entry) & (results.otm == cfg.otm_pct)
                & (results.horizon == horizon)]
    rows = []
    for x in r.itertuples(index=False):
        pe = by_key[(x.ticker, x.event_date, x.family)]
        m_e = pe.marks(x.entry_date)
        premium = sum(abs(m_e[l]) for l in legs) / x.S_entry
        row = {"ticker": x.ticker, "family": x.family, "event_date": x.event_date, "gross": getattr(x, strategy), "premium_traded": premium,
               "leg_volume": sum(pe.legs[l].volume_on(x.entry_date) for l in legs)}
        for m in multipliers:
            row[f"haircut_cost_{m}x"] = premium * cfg.cost_haircut * 2 * m
            row[f"net_haircut_{m}x"] = row["gross"] - row[f"haircut_cost_{m}x"]
        spread = np.nan
        if client is not None:
            hs = [half_spread(client, pe.legs[l].ticker, d) for l in legs for d in (x.entry_date, x.exit_date)]
            if all(h is not None for h in hs):
                spread = sum(hs) / x.S_entry
        row["spread_cost"] = spread
        row["net_spread"] = row["gross"] - spread
        rows.append(row)
    cols = ["ticker", "family", "event_date", "gross", "premium_traded", *[f"haircut_cost_{m}x" for m in multipliers],
            *[f"net_haircut_{m}x" for m in multipliers], "spread_cost", "net_spread", "leg_volume"]
    return pd.DataFrame(rows, columns=cols)


def cost_summary(ct: pd.DataFrame, ct_placebo: pd.DataFrame | None = None, multipliers=(1, 2)) -> dict:
    paired = ct.dropna(subset=["gross", "spread_cost"])
    out = {"n": len(ct), "n_gross": int(ct["gross"].notna().sum()), "n_paired": len(paired),
           "gross_paired": paired["gross"].mean(), "spread_cost_paired": paired["spread_cost"].mean(),
           "net_spread_paired": (paired["gross"] - paired["spread_cost"]).mean(),
           "gross": ct["gross"].mean(), "median_leg_volume": ct["leg_volume"].median()}
    for m in multipliers:
        out[f"net_haircut_{m}x"] = ct[f"net_haircut_{m}x"].mean()
        if ct_placebo is not None:
            out[f"n_placebo_{m}x"] = int(ct_placebo[f"net_haircut_{m}x"].notna().sum())
            out[f"net_edge_{m}x"] = ct[f"net_haircut_{m}x"].mean() - ct_placebo[f"net_haircut_{m}x"].mean()
    return out
