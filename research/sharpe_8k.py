"""Annualized Sharpe of the two pre-registered 8-K strategies (Massive write-up, stats line).

Per-trade P&L at 21 sessions (3-6m bucket, entry 'post', 5% OTM), per $1 of stock, annualized by each window's
trade rate: Sharpe = mean / sd * sqrt(trades per year). Holds can overlap, so this is a per-trade figure, not a
daily-NAV Sharpe. Net = after the 5% premium haircut (results/*/<family>_costs_h21.csv); the ordinary-day
benchmark is gross. Run from research/ with MASSIVE_API_KEY set (warm cache: seconds).
"""
from pathlib import Path

import numpy as np
import pandas as pd

from polybridge_research.calendar import TradingCalendar
from polybridge_research.config import StudyConfig
from polybridge_research.massive import MassiveClient, load_api_key
from polybridge_research.pipeline import run_family_study

STRATEGY = {"hedge": "protective_put", "opportunity": "cash_secured_put"}
WINDOWS = {"in_sample": ("study", 2.0), "oos": ("oos", 8 / 12)}


def sharpe(x, per_year):
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    if len(x) < 3 or x.std(ddof=1) == 0:
        return len(x), np.nan
    return len(x), x.mean() / x.std(ddof=1) * np.sqrt(per_year)


def baseline(df, fam, strat):
    r = df[(df.family == fam) & (df.bucket == "3-6m") & (df.entry == "post") & (df.otm == 0.05) & (df.horizon == 21)]
    return r[strat]


if __name__ == "__main__":
    cfg, cal = StudyConfig(), TradingCalendar()
    client = MassiveClient(load_api_key(search_from=Path.cwd()))
    rows = []
    for folder, (prefix, years) in WINDOWS.items():
        st = run_family_study(client, cal, cfg, getattr(cfg, f"{prefix}_start"), getattr(cfg, f"{prefix}_end"),
                              pd.Timestamp("2026-10-02"))
        for fam, strat in STRATEGY.items():
            ev = baseline(st["results"], fam, strat).dropna()
            rate = len(ev) / years
            net = pd.read_csv(Path("results") / folder / f"{fam}_costs_h21.csv")["net_haircut_1x"]
            for label, x in (("events, net 1x", net), ("events, gross", ev),
                             ("ordinary days, gross", baseline(st["placebo_results"], fam, strat))):
                n, s = sharpe(x, rate)
                rows.append({"window": folder, "family": fam, "series": label, "n": n, "sharpe": round(s, 2)})
    print(pd.DataFrame(rows).to_string(index=False))
