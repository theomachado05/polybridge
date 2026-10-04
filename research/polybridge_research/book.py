"""Trading metrics of a pre-registered 8-K rule run as a book: equity curve, drawdown, turnover, Sharpe, net of costs.

One trade per event at the registered cell (baseline expiry bucket, tradeable entry, registered OTM distance, one
horizon), each sized at $1 of stock notional, net of the 5% premium haircut each way (costs.cost_table). The curve
books each trade on its exit date. Holds overlap, so Sharpe is per trade annualised by the window's trade rate (as in
sharpe_8k.py), not a daily-NAV figure, and drawdown is in percent of one trade's notional.
"""
import numpy as np
import pandas as pd

from .config import StudyConfig
from .costs import cost_table


def trades(results: pd.DataFrame, priced, strategy: str, horizon, cfg: StudyConfig) -> pd.DataFrame:
    """Per-trade gross and net P&L with entry and exit dates, sorted by exit."""
    r = results[(results.bucket == cfg.baseline_bucket) & (results.entry == cfg.entry) & (results.otm == cfg.otm_pct)
                & (results.horizon == horizon)]
    if r.empty or not priced:
        return pd.DataFrame(columns=["ticker", "event_date", "entry_date", "exit_date", "gross", "net"])
    ct = cost_table(r, priced, strategy, horizon, cfg, client=None, multipliers=(1,))
    keys = ["ticker", "event_date", "family"]
    t = ct.merge(r[keys + ["entry_date", "exit_date"]], on=keys, how="left")
    t = t.rename(columns={"net_haircut_1x": "net"}).dropna(subset=["net", "exit_date"])
    return t[["ticker", "event_date", "entry_date", "exit_date", "gross", "net"]].sort_values("exit_date").reset_index(drop=True)


def metrics(t: pd.DataFrame, years: float, horizon_sessions: int = 21, per_year: float | None = None) -> dict:
    """Book statistics for one trade list over a window of `years`; `per_year` overrides the trade rate used to annualise."""
    n = len(t)
    if n == 0:
        return {"trades": 0}
    x = t["net"].to_numpy(float)
    eq = np.cumsum(x)
    dd = eq - np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:]
    per_year = n / years if per_year is None else per_year
    sd = x.std(ddof=1) if n > 2 else np.nan
    return {"trades": n, "trades_per_year": per_year,
            "mean_net_pct": 100 * x.mean(), "hit_rate": float((x > 0).mean()),
            "total_net_pct": 100 * eq[-1], "annual_return_pct": 100 * x.mean() * per_year,
            "annual_vol_pct": 100 * sd * np.sqrt(per_year) if n > 2 else np.nan,
            "sharpe_net": x.mean() / sd * np.sqrt(per_year) if n > 2 and sd > 0 else np.nan,
            "max_drawdown_pct": 100 * dd.min(), "worst_trade_pct": 100 * x.min(),
            "avg_open_positions": per_year * horizon_sessions / 252,
            "turnover_x_per_year": per_year / max(per_year * horizon_sessions / 252, 1e-9)}


def book_table(study: dict, cfg: StudyConfig, strategy_for: dict, years: float, horizon=21):
    """Events and ordinary days for each family: (stats frame, {(family, kind): trade list}).

    Ordinary days are a fixed-size sample, so their figures are annualised at the filings' trade rate: the same book,
    had it traded ordinary days as often as filings arrive. Their drawdown is over the whole sample and not comparable."""
    rows, lists = [], {}
    for fam, strat in strategy_for.items():
        rate = None
        for kind, res_key, pr_key in (("filings", "results", "priced"), ("ordinary days", "placebo_results", "placebo_priced")):
            res = study[res_key]
            res = res[res.family == fam]
            pr = [p for p in study[pr_key] if str(getattr(p.family, "value", p.family)) == fam]
            t = trades(res, pr, strat, horizon, cfg)
            lists[(fam, kind)] = t
            hs = horizon if horizon != "exp" else 63
            m = metrics(t, years, hs, per_year=rate)
            if kind == "filings":
                rate = m.get("trades_per_year")
            rows.append({"family": fam, "strategy": strat, "series": kind, **m})
    return pd.DataFrame(rows).set_index(["family", "series"]), lists
