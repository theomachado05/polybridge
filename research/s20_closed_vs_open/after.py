"""S20, looked at AFTER the run (not pre-registered; reported under that heading only).

1. The gap between what takers paid to buy YES and what takers received for selling it, in the same market and window:
   a direct reading of "a wider spread on the weekend" that the pre-registered T3 pointed to.
2. The bug hunt behind every book with a Sharpe above 3: months counted, the best event's share, the book without it.

Run from `research/`:  python -m s20_closed_vs_open.after
"""
from __future__ import annotations

import sys

import pandas as pd

from s6_monday_fade.run import write_csv
from s7_weekend_straddle.run import boot_mean

from . import config as cfg
from .run import ALL, RESULTS, by_event

GROUPS = (ALL, *cfg.CLASS_GROUPS)


def gap_rows(tr: pd.DataFrame) -> list[dict]:
    d = tr[(tr.rule == "B") & (tr.status == "in") & tr.buy_price.notna() & tr.sell_price.notna()].copy()
    d["gap"] = 100 * (d.buy_price - d.sell_price)
    out = []
    for g in GROUPS:
        s = d if g == ALL else d[d.group == g]
        for w in cfg.WINDOWS:
            x = s[s.window == w]
            b = boot_mean(by_event(x, "gap"))
            out.append({"look": "gap between buyers' and sellers' traded price, same market and window", "scope": g, "windows": w, "markets": len(x),
                        "events": int(x.event.nunique()), "estimate": b[0], "ci_lo": b[1], "ci_hi": b[2]})
        for a, b_ in (("W1", "D1"), ("W2", "D1"), ("W1", "W2")):
            j = s[s.window == a].set_index("market").join(s[s.window == b_].set_index("market")[["gap"]].rename(columns={"gap": "other"}), how="inner")
            j["diff"] = j.gap - j.other
            b = boot_mean(by_event(j, "diff"))
            out.append({"look": "the same gap, difference on markets with both sides printed in both windows", "scope": g, "windows": f"{a}-{b_}", "markets": len(j),
                        "events": int(j.event.nunique()), "estimate": b[0], "ci_lo": b[1], "ci_hi": b[2]})
    return out


def hunt_rows(tr: pd.DataFrame, books: pd.DataFrame) -> list[dict]:
    out = []
    hi = books[(books.sharpe > 3) & (books.fee_mult == 1.0)]
    for r in hi.itertuples():
        out.append({"look": "book with a Sharpe above 3", "rule": r.rule, "windows": r.window, "scope": r.scope, "segment": r.segment, "markets": int(r.trades),
                    "months": int(r.months), "sharpe": r.sharpe, "pnl": r.pnl, "best_event_pnl": r.best_event, "worst_event_pnl": r.worst_event,
                    "pnl_without_best_event": r.pnl - r.best_event, "fewer_than_six_months": bool(r.months < 6)})
    return out


def split_rows(tr: pd.DataFrame) -> list[dict]:
    """What separates rule A from rule B in the open week: the markets that resolved during it, against the rest."""
    a, b = tr[(tr.rule == "A") & (tr.window == "D1")].set_index("market"), tr[(tr.rule == "B") & (tr.window == "D1")].set_index("market")
    b = b[(b.status == "in") & b.buy_pnl_points.notna()]
    during = a.status.reindex(b.index) == "resolved before or during the window"
    out = []
    for name, s in (("open-week buyers in markets that resolved during that week", b[during]), ("open-week buyers in markets still open after it", b[~during])):
        x = boot_mean(by_event(s, "buy_pnl_points"))
        out.append({"look": name, "scope": ALL, "windows": "D1", "markets": len(s), "events": int(s.event.nunique()), "estimate": x[0], "ci_lo": x[1], "ci_hi": x[2],
                    "mean_traded_price": float(100 * s.buy_price.mean()), "share_yes": float(100 * s.outcome.mean())})
    return out


def main() -> int:
    tr, books = pd.read_csv(RESULTS / "trades.csv"), pd.read_csv(RESULTS / "books.csv")
    rows = gap_rows(tr) + split_rows(tr) + hunt_rows(tr, books)
    write_csv(RESULTS / "after_the_run.csv", rows)
    for r in rows:
        if r["look"].startswith(("gap", "the same gap")):
            print(f"{r['look'][:46]:46} | {r['scope'][:20]:20} | {r['windows']:5} | n {r['markets']:4d} ev {r['events']:3d} | {r['estimate']:6.2f} [{r['ci_lo']:6.2f},{r['ci_hi']:6.2f}]")
        elif r["look"].startswith("open-week"):
            print(f"{r['look']:60} | n {r['markets']:4d} ev {r['events']:3d} | paid {r['mean_traded_price']:5.1f} yes {r['share_yes']:5.1f} | {r['estimate']:6.2f} [{r['ci_lo']:6.2f},{r['ci_hi']:6.2f}]")
        elif r["rule"] == "B":
            print(f"sharpe>3 | B {r['windows']} {r['scope'][:24]:24} {r['segment']:3} | n {r['markets']:4d} months {r['months']:2d} | sharpe {r['sharpe']:5.2f} | pnl {r['pnl']:7.0f} | "
                  f"best event {r['best_event_pnl']:6.0f} | without it {r['pnl_without_best_event']:7.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
