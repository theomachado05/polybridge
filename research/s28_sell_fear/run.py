"""S28 / H3 (METHOD.md): sell the put after H1 filings when fear is high. python -m s28_sell_fear.run"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from polybridge_research.analysis import difference_board
from polybridge_research.calendar import TradingCalendar
from polybridge_research.config import StudyConfig
from polybridge_research.massive import MassiveClient, load_api_key
from polybridge_research.pipeline import run_family_study

FEAR = 0.14
HEADS = (21, 42, "exp")
RESULTS = Path(__file__).resolve().parent.parent / "results" / "s28_sell_fear"
WINDOWS = {"2022 (discovery)": ("2022-01-01", "2022-12-31", 1.0), "2024-25 (seen)": ("2024-01-01", "2025-12-31", 2.0),
           "2026 (seen)": ("2026-01-01", "2026-08-31", 8 / 12)}


def high_fear(res: pd.DataFrame) -> pd.DataFrame:
    """Keep events whose implied move at entry (post, baseline bucket) is >= FEAR; the key is (ticker, event_date)."""
    e = res[(res.entry == "post") & (res.horizon == 21) & (res.otm == 0.05) & (res.bucket == "3-6m")]
    keys = e.loc[e.implied_move >= FEAR, ["ticker", "event_date"]].drop_duplicates()
    return res.merge(keys, on=["ticker", "event_date"], how="inner")


def h3(ev, pl, cfg, years):
    d = difference_board(ev, pl, cfg, level=cfg.confirmatory_level, strategies=["cash_secured_put"]) if len(ev) and len(pl) else pd.DataFrame()
    ok = [h for h in HEADS if len(d) and ((d.horizon == h) & (d.ci_lo > 0)).any()]
    testable = int(d[d.horizon.isin(HEADS)].ci_lo.notna().sum()) if len(d) else 0
    verdict = "PASS" if len(ok) >= 2 else ("NULL" if testable >= 2 else "INSUFFICIENT")
    r = ev[(ev.bucket == "3-6m") & (ev.entry == "post") & (ev.otm == 0.05) & (ev.horizon == 21)]["cash_secured_put"].dropna()
    rp = pl[(pl.bucket == "3-6m") & (pl.entry == "post") & (pl.otm == 0.05) & (pl.horizon == 21)]["cash_secured_put"].dropna()
    sh = lambda x: float(x.mean() / x.std(ddof=1) * np.sqrt(len(r) / years)) if len(x) > 2 and x.std(ddof=1) > 0 else float("nan")
    return d, verdict, ok, len(r), sh(r), sh(rp)


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    cfg, cal = StudyConfig(), TradingCalendar()
    client = MassiveClient(load_api_key(search_from=Path.cwd()))
    out = []
    for name, (s, e, yrs) in WINDOWS.items():
        st = run_family_study(client, cal, cfg, s, e, pd.Timestamp("2026-10-02"))
        ev = st["results"][st["results"].family == "hedge"]
        pl = st["placebo_results"][st["placebo_results"].family == "hedge"]
        for scope, (a, b) in {"high fear": (high_fear(ev), high_fear(pl)), "all H1": (ev, pl)}.items():
            d, v, ok, n, s_ev, s_pl = h3(a, b, cfg, yrs)
            print(f"\n== {name} | {scope}: {v} (above zero at {ok}); events at 21: {n}; Sharpe {s_ev:.2f} vs ordinary {s_pl:.2f}")
            if len(d):
                print((d[d.horizon.isin([5, 10, 21, 42, 63, "exp"])][["horizon", "n_a", "n_b", "difference", "ci_lo", "ci_hi"]]
                       .set_index("horizon") * [1, 1, 100, 100, 100]).round(2).to_string())
                d.assign(window=name, scope=scope).to_csv(RESULTS / f"{name.split()[0]}_{scope.replace(' ', '_')}.csv", index=False)
            out.append({"window": name, "scope": scope, "verdict": v, "above_zero_at": ok, "events_21": n,
                        "sharpe_events": s_ev, "sharpe_ordinary": s_pl})
    (RESULTS / "verdicts.json").write_text(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
