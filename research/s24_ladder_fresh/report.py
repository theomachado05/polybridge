"""S24 report: metrics.csv, equity_curve.png, drawdown.png, capacity.md, RUN_LOG.md and SUMMARY.md.

Every number is read back from the result files (trades.csv, coverage.csv, oos_cut.json) and the pull's own records.
Run from `research/`:  python -m s24_ladder_fresh.report
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from . import config as cfg  # noqa: E402
from . import engine as en  # noqa: E402
from . import notes  # noqa: E402

HERE = Path(__file__).resolve().parent
CACHE = HERE / ".cache"
RESULTS = HERE.parent / "results" / "s24_ladder_fresh"
LAST_DAY = "2026-10-04"
SETS = {"a": "Set (a): listed 2024-01 to 2025-09, $50,000+", "b": "Set (b): S11's year, $10,000 to $50,000"}


def f(x, d=2, sign=True):
    if x is None or x != x:
        return "n/a"
    return (f"{x:+.{d}f}" if sign else f"{x:.{d}f}").replace("-", "−")


def usd(x, d=0):
    if x is None or x != x:
        return "n/a"
    if d == 0 and abs(x) < 100:
        d = 2
    return f"−${abs(x):,.{d}f}" if x < 0 else f"${x:,.{d}f}"


def pct(x, d=1):
    return "n/a" if x is None or x != x else f"{100 * x:.{d}f}%".replace("-", "−")


def row(t: pd.DataFrame, tag: str) -> dict:
    """One line of metrics for a set of trades at one cost level ('1x' or '2x')."""
    if not len(t):
        return {"trades": 0}
    pts = t[f"pnl_{tag}"] * 100
    m, lo, hi, n, nd = en.boot(t.assign(_p=pts), "_p")
    tt = t.assign(_usd=t[f"usd_capped_{tag}"], _cap=t[f"capital_{tag}"] * t["size_capped"])
    pf = en.perf(tt, "_usd", "_cap", "result", LAST_DAY)
    pe = en.perf(tt, "_usd", "_cap", "entry", LAST_DAY)
    return {"trades": n, "dates": nd, "pairs": int((t.rich + ">" + t.cheap).nunique()), "events": int(t.event.nunique()),
            "net_points_per_trade": m, "ci_lo": lo, "ci_hi": hi, "median_points": float(pts.median()),
            "net_bp_of_capital": float((t[f"pnl_{tag}"] / t[f"capital_{tag}"]).mean() * 1e4),
            "entry_edge_points": float(t[f"edge_{tag}"].mean() * 100), "winners": float((pts > 0).mean()), "losers": float((pts < 0).mean()),
            "usd_capped": float(t[f"usd_capped_{tag}"].sum()), "usd_uncapped": float(t[f"usd_uncapped_{tag}"].sum()),
            "usd_per_trade_capped": float(t[f"usd_capped_{tag}"].mean()),
            "entry_edge_usd_capped": float((t[f"edge_{tag}"] * t["size_capped"]).sum()),
            "entry_edge_usd_uncapped": float((t[f"edge_{tag}"] * t["size_uncapped"]).sum()),
            "capital_base_usd": pf["capital_base"], "mean_capital_locked_usd": pf["mean_capital_locked"], "capital_days_usd": pf["capital_days"],
            "return_on_locked_capital_per_year": pf["return_on_locked_capital_per_year"],
            "median_days_locked": float(t.days_locked.median()), "mean_days_locked": float(t.days_locked.mean()), "max_days_locked": int(t.days_locked.max()),
            "sharpe": pf["sharpe"], "max_drawdown": pf["max_drawdown"], "worst_month": pf["worst_month"], "calendar_days": pf["days"],
            "sharpe_s11_convention": pe["sharpe"], "max_drawdown_s11_convention": pe["max_drawdown"], "worst_month_s11_convention": pe["worst_month"],
            "capital_base_s11_convention_usd": pe["capital_base"],
            "order_violated_at_result": int(t.broken.sum()), "open_pairs": int((t.settled_by != "result").sum()),
            "paid_one_dollar": int(((t.outcome_cheap == 1) & (t.outcome_rich == 0)).sum()),
            "median_seconds_apart": float(t.seconds_apart.median())}


SECONDARY = ("year check", "corrected rule", "corrected rule, unseen sample", "registered rule, unseen sample")


def scopes(T: pd.DataFrame) -> dict[str, pd.DataFrame]:
    out = {"pooled": T, "set a": T[T.set == "a"], "set b": T[T.set == "b"], "date ladders": T[T.kind == "date"],
           "strike ladders": T[T.kind == "strike"], "locked at entry": T[T.locked_at_entry.astype(bool)],
           "resolved pairs only": T[T.settled_by == "result"]}
    if "corrected_ok" in T:              # amendment 1: secondary rows, never the registered test
        yo, co, pu = T.year_ok.astype(bool), T.corrected_ok.astype(bool), T.partner_used.astype(bool)
        out.update({"year check": T[yo], "corrected rule": T[co], "corrected rule, unseen sample": T[co & ~pu],
                    "registered rule, unseen sample": T[~pu]})
        for s in ("a", "b"):
            out[f"corrected rule, unseen sample, set {s}"] = T[co & ~pu & (T.set == s)]
        for k in ("date", "strike"):
            out[f"corrected rule, unseen sample, {k} ladders"] = T[co & ~pu & (T.kind == k)]
    return out


def build_metrics(T: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for variant in ("W600", "W120"):
        V = T[T.variant == variant]
        for scope, S in scopes(V).items():
            if variant == "W120" and scope not in ("pooled", "set a", "set b") + SECONDARY:
                continue
            for split, col in (("trade dates", "segment"), ("calendar", "calendar_segment")):
                if split == "calendar" and (variant != "W600" or scope not in ("pooled", "set a", "set b")):
                    continue
                for seg in ("IS", "OOS", "ALL"):
                    if split == "calendar" and seg == "ALL":
                        continue
                    t = S if seg == "ALL" else S[S[col] == seg]
                    for tag in ("1x", "2x"):
                        rows.append({"variant": variant, "scope": scope, "split": split, "segment": seg, "costs": tag, **row(t, tag)})
    return pd.DataFrame(rows)


def get(M: pd.DataFrame, variant="W600", scope="pooled", split="trade dates", segment="ALL", costs="1x") -> pd.Series:
    r = M[(M.variant == variant) & (M.scope == scope) & (M.split == split) & (M.segment == segment) & (M.costs == costs)]
    return r.iloc[0]


def pass_lines(M: pd.DataFrame, scope: str = "pooled", variant: str = "W600") -> list[tuple[str, bool, str]]:
    i, o, a2 = get(M, variant, scope, segment="IS"), get(M, variant, scope, segment="OOS"), get(M, variant, scope, costs="2x")

    def above(r):
        return bool(r.trades > 0 and r.net_points_per_trade > 0 and r.ci_lo == r.ci_lo and r.ci_lo > 0)

    def show(r):
        return f"{f(r.net_points_per_trade)} [{f(r.ci_lo)}, {f(r.ci_hi)}], {int(r.trades)} trades on {int(r.dates)} dates" if r.trades else "no trades"
    return [("1. In-sample, 1×: above zero, interval excludes zero", above(i), show(i)),
            ("2. Out-of-sample, 1×: above zero, interval excludes zero", above(o), show(o)),
            ("3. The same trades at 2×: above zero", bool(a2.trades > 0 and a2.net_points_per_trade > 0), show(a2)),
            (f"4. At least {cfg.MIN_OOS_TRADES} out-of-sample trades on {cfg.MIN_OOS_DATES}+ dates",
             bool(o.trades >= cfg.MIN_OOS_TRADES and o.dates >= cfg.MIN_OOS_DATES), f"{int(o.trades)} trades on {int(o.dates) if o.trades else 0} dates")]


def curves(T: pd.DataFrame, cut: dict) -> None:
    P = T[T.variant == "W600"]
    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    fig2, ax2 = plt.subplots(figsize=(9.5, 3.4))
    for lab, t, tag, style in (("pooled, 1× costs", P, "1x", "-"), ("pooled, 2× costs", P, "2x", "--"),
                               ("set (a), 1×", P[P.set == "a"], "1x", ":"), ("set (b), 1×", P[P.set == "b"], "1x", ":")):
        if not len(t):
            continue
        pf = en.perf(t.assign(_usd=t[f"usd_capped_{tag}"], _cap=t[f"capital_{tag}"] * t["size_capped"]), "_usd", "_cap", "result", LAST_DAY)
        eq = pf["equity"]
        ax.plot(eq.index, eq - pf["capital_base"], ls=style, label=f"{lab} (most capital locked ${pf['capital_base']:,.0f})")
        ax2.plot(eq.index, -(eq.cummax() - eq) / pf["capital_base"] * 100, ls=style, label=lab)
    for s, col in (("a", "tab:green"), ("b", "tab:red")):
        if cut[s]["oos_start"]:
            for a in (ax, ax2):
                a.axvline(pd.Timestamp(cut[s]["oos_start"]), color=col, lw=0.8, ls="-.")
    for a in (ax, ax2):
        a.legend(fontsize=8)
        a.grid(alpha=0.3)
    ax.set_title("S24: cumulative P&L in dollars, 100-contract cap, booked on the day each pair settles\n"
                 "(dash-dot lines: out-of-sample starts, set (a) green, set (b) red)", fontsize=10)
    ax.set_ylabel("dollars")
    ax2.set_title("Drawdown, % of the most capital locked at once", fontsize=10)
    fig.tight_layout()
    fig2.tight_layout()
    fig.savefig(RESULTS / "equity_curve.png", dpi=120)
    fig2.savefig(RESULTS / "drawdown.png", dpi=120)
    plt.close("all")


def git_log() -> list[str]:
    try:
        out = subprocess.run(["git", "log", "--format=%h %cd %s", "--date=format:%a %H:%M", "--", "research/s24_ladder_fresh",
                              "research/results/s24_ladder_fresh"], cwd=HERE.parent.parent, capture_output=True, text=True, timeout=20).stdout
        return [x for x in out.splitlines() if x.strip()][::-1]
    except Exception:  # noqa: BLE001
        return []


def main() -> int:
    T = pd.read_csv(RESULTS / "trades.csv", dtype={"rich": str, "cheap": str})
    C = pd.read_csv(RESULTS / "coverage.csv", dtype={"rich": str, "cheap": str})
    cut = json.loads((RESULTS / "oos_cut.json").read_text())
    L = json.loads((HERE / "ladders.json").read_text())
    st = json.loads((CACHE / "pull_state.json").read_text())
    rq = json.loads((CACHE / "requests.json").read_text())
    M = build_metrics(T)
    M.to_csv(RESULTS / "metrics.csv", index=False)
    M = pd.read_csv(RESULTS / "metrics.csv")              # every number below is read back from the file
    curves(T, cut)
    P = T[T.variant == "W600"]

    # ---- the lists: built, pulled, left out
    done = set(st["done"])
    built = {}
    for s in ("a", "b"):
        bs = [(k, b) for k, b in enumerate(L["ladders"]) if b["set"] == s]
        pulled = [(k, b) for k, b in bs if k in done]
        built[s] = {"ladders": len(bs), "pairs": sum(len(b["pairs"]) for _, b in bs), "rungs": len({i for _, b in bs for i in b["legs"]}),
                    "events": len({b["event"] for _, b in bs}),
                    "pulled_ladders": len(pulled), "pulled_pairs": sum(len(b["pairs"]) for _, b in pulled),
                    "pulled_rungs": len({i for _, b in pulled for i in b["legs"]}), "pulled_events": len({b["event"] for _, b in pulled}),
                    "pulled_date": sum(b["kind"] == "date" for _, b in pulled), "pulled_strike": sum(b["kind"] == "strike" for _, b in pulled),
                    "left_ladders": len(bs) - len(pulled), "left_pairs": sum(len(b["pairs"]) for k, b in bs if k not in done),
                    "smallest_event_pulled": min((b["event_volume"] for _, b in pulled), default=float("nan")),
                    "requests": st["used"][s]}
    cov = C.groupby(["set", "state"]).size().unstack(fill_value=0)
    cov_n = {s: {k: int(cov.loc[s, k]) if (s in cov.index and k in cov.columns) else 0
                 for k in ("every print checked", "latest 20,000 prints only", "no prints served")} for s in ("a", "b")}
    pairs_with_trade = {s: int((P[P.set == s].rich + ">" + P[P.set == s].cheap).nunique()) for s in ("a", "b")}

    A1, A2 = get(M), get(M, costs="2x")
    I1, O1 = get(M, segment="IS"), get(M, segment="OOS")
    lines = pass_lines(M)
    passed = all(ok for _, ok, _ in lines)
    failed = [name for name, ok, _ in lines if not ok]
    W = get(M, "W120")
    WI, WO, W2 = get(M, "W120", segment="IS"), get(M, "W120", segment="OOS"), get(M, "W120", costs="2x")
    wl = pass_lines(M, "pooled", "W120")

    # ---- capacity.md
    sz = P.size_uncapped
    top = P.sort_values("usd_uncapped_1x", ascending=False)
    cap = ["# S24 capacity", "",
           "Every figure is read from `trades.csv` (primary trades: two prints within 10 minutes, 1× costs unless stated).", "",
           "## Size that the prints prove", "",
           "The size of a trade is the smaller of its two prints. A print proves that one taker traded that size at that price.",
           "It does not prove that a second order of the same size would have been filled, or that both legs were there at once.", "",
           "| | Contracts |", "|---|---|",
           f"| Median trade | {sz.median():,.0f} |", f"| 75th percentile | {sz.quantile(0.75):,.0f} |", f"| 95th percentile | {sz.quantile(0.95):,.0f} |",
           f"| Largest | {sz.max():,.0f} |", f"| Trades under 100 contracts | {int((sz < 100).sum())} of {len(sz)} |",
           f"| Trades under 5 contracts (Polymarket's minimum order) | {int((sz < 5).sum())} of {len(sz)} |", "",
           "## Money", "",
           "| | 100-contract cap | Full printed size |", "|---|---|---|",
           f"| Net P&L, 1× costs | {usd(A1.usd_capped)} | {usd(A1.usd_uncapped)} |",
           f"| Net P&L, 2× costs | {usd(A2.usd_capped)} | {usd(A2.usd_uncapped)} |",
           f"| Of which locked in at entry, 1× | {usd(A1.entry_edge_usd_capped)} | {usd(A1.entry_edge_usd_uncapped)} |",
           f"| Contracts traded (per leg) | {P.size_capped.sum():,.0f} | {P.size_uncapped.sum():,.0f} |", "",
           f"- The uncapped figure is an upper bound. The 5 largest trades carry {usd(top.usd_uncapped_1x.head(5).sum())} of it"
           f" ({pct(top.usd_uncapped_1x.head(5).sum() / A1.usd_uncapped) if A1.usd_uncapped else 'n/a'}).",
           f"- P&L that came from the result (the cheap rung paid $1 and the rich rung $0), not from the entry: {int(A1.paid_one_dollar)} trades.", "",
           "## Capital and how long it is locked", "",
           "A pair contract ties up about $1 (the NO side of the rich rung plus the YES side of the cheap rung) until the later rung",
           "closes. Capital is counted from the entry date to that day; pairs with a rung still open are carried to 2026-10-04.", "",
           "| | 100-contract cap |", "|---|---|",
           f"| Capital per contract, mean | ${P.capital_1x.mean():.3f} |",
           f"| Most capital locked at once | {usd(A1.capital_base_usd)} |",
           f"| Mean capital locked, every calendar day | {usd(A1.mean_capital_locked_usd)} |",
           f"| Days locked: median / mean / longest | {A1.median_days_locked:.0f} / {A1.mean_days_locked:.1f} / {int(A1.max_days_locked)} |",
           f"| Net P&L per year on the capital actually locked | {pct(A1.return_on_locked_capital_per_year)} |",
           f"| Calendar days from the first entry to the last day | {int(A1.calendar_days)} |", "",
           "## By set", "",
           "| Set | Trades | Net P&L, cap | Net P&L, full size | Most capital locked | Median days locked |", "|---|---|---|---|---|---|"]
    for s in ("a", "b"):
        r = get(M, scope=f"set {s}")
        if r.trades:
            cap.append(f"| ({s}) | {int(r.trades)} | {usd(r.usd_capped)} | {usd(r.usd_uncapped)} | {usd(r.capital_base_usd)} | {r.median_days_locked:.0f} |")
        else:
            cap.append(f"| ({s}) | 0 | | | | |")
    (RESULTS / "capacity.md").write_text("\n".join(cap) + "\n")

    # ---- RUN_LOG.md
    log = ["# S24 run log (New York time)", "", "| When | What |", "|---|---|"]
    log += [f"| {when} | {what} |" for when, what in notes.RUN_LOG]
    log += ["", "## Commits (from `git log`, oldest first; the commit that carries this file is not in its own list)", ""]
    log += [f"- `{x.split(' ', 1)[0]}` {x.split(' ', 1)[1]}" for x in git_log()] or ["- (git log not readable)"]
    log += ["", "## Requests (one worker, at most one a second; `.cache/requests.json`)", "",
            f"- In all: **{rq['n']}** of {cfg.MAX_REQUESTS}. By kind: " + ", ".join(f"{k} {v}" for k, v in rq["by"].items()) + ".",
            f"- Prints: set (a) {st['used']['a']} requests, set (b) {st['used']['b']}. The pull stopped by: {st.get('stopped_by')}.",
            f"- Recorder check: `fetch failed` lines in `research/forward/recorder.log` before the pull: {notes.RECORDER_BEFORE}; "
            f"at the end: {notes.RECORDER_AFTER}. Pauses taken: {len(rq.get('pauses', []))}.",
            "", "## Data sources", "",
            "- Catalogue: `gamma-api.polymarket.com/events` (by event volume, two start-date windows) for the lists; "
            "`gamma-api.polymarket.com/markets?id=...&closed=true` for the results.",
            "- Prints: `data-api.polymarket.com/trades`, `market=<conditionId>`, `limit=10000`, `offset=0` and `10000` (S11's call).",
            "- No one-minute price history. No Kalshi call. No key used or printed.",
            "", "## Things that went wrong or limit the result", ""]
    log += [f"- {x}" for x in notes.WENT_WRONG]
    (RESULTS / "RUN_LOG.md").write_text("\n".join(log) + "\n")

    # ---- SUMMARY.md
    def hl(r, label):
        if not r.trades:
            return f"| {label} | 0 | | | | | | | | | |"
        return (f"| {label} | {int(r.trades)} | {int(r.dates)} | {f(r.net_points_per_trade)} | [{f(r.ci_lo)}, {f(r.ci_hi)}] | {f(r.net_bp_of_capital, 0)} | "
                f"{pct(r.winners, 0)} | {usd(r.usd_capped)} | {usd(r.usd_uncapped)} | {f(r.sharpe)} | {pct(r.max_drawdown)} | {pct(r.worst_month, 2)} |")

    verdict = "PASS" if passed else "NOT A PASS"
    S = ["# S24: the ladder trade on fresh ladders", "",
         f"Method, pre-registered before any print of these markets was pulled: [`research/s24_ladder_fresh/METHOD.md`](../../s24_ladder_fresh/METHOD.md) "
         f"(commit `{notes.PREREG_COMMIT}`). The out-of-sample cut dates were committed before any P&L was computed (`{notes.CUT_COMMIT}`, "
         "[`oos_cut.json`](oos_cut.json)). Files: [`metrics.csv`](metrics.csv), [`trades.csv`](trades.csv), [`coverage.csv`](coverage.csv), "
         "[`capacity.md`](capacity.md), [`RUN_LOG.md`](RUN_LOG.md). This file is written by `report.py` from those files.", "",
         "## Answer", ""]
    S += notes.answer(locals())
    S += ["", f"**Verdict on the pre-registered rule: {verdict}.**" + ("" if passed else " Lines that fail: " + "; ".join(failed) + "."), "",
          "| Line of the pass rule (pooled primary trades) | Holds? | Number |", "|---|---|---|"]
    S += [f"| {name} | {'yes' if ok else '**no**'} | {num} |" for name, ok, num in lines]
    S += ["", "## Headline numbers", "",
          "A point is one cent per contract. Every trade is weighted equally, as in S11. Costs: each market's own taker fee "
          "(catalogue `feeSchedule`), and every fill one cent worse than the print (2×: fees doubled, two cents worse; the same trades). "
          "\"bp\" is basis points of the capital the trade ties up. Dollar P&L uses the smaller of the two printed sizes, capped at 100 "
          "contracts (\"cap\") or not (\"full size\"). Sharpe: daily P&L over every calendar day, booked on the day each pair settles, "
          "against the most capital locked at once.", "",
          "| Row | Trades | Dates | Net, points per trade | 95% interval | Net, bp of capital | Winners | P&L, cap | P&L, full size | Sharpe | Max drawdown | Worst month |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|",
          hl(I1, "Pooled, in-sample, 1×"), hl(O1, "Pooled, out-of-sample, 1×"), hl(A1, "Pooled, all, 1×"), hl(A2, "Pooled, all, 2× (same trades)")]
    for s in ("a", "b"):
        for seg, lab in (("IS", "in-sample"), ("OOS", "out-of-sample"), ("ALL", "all")):
            S.append(hl(get(M, scope=f"set {s}", segment=seg), f"Set ({s}), {lab}, 1×"))
        S.append(hl(get(M, scope=f"set {s}", costs="2x"), f"Set ({s}), all, 2×"))
    for k in ("date ladders", "strike ladders"):
        S.append(hl(get(M, scope=k), f"{k.capitalize()}, all, 1×"))
        S.append(hl(get(M, scope=k, costs="2x"), f"{k.capitalize()}, all, 2×"))
    S += ["", f"Out-of-sample starts on {cut['a']['oos_start']} in set (a) ({cut['a']['trade_dates']} trade dates) and on {cut['b']['oos_start']} in set (b) "
          f"({cut['b']['trade_dates']} trade dates): the most recent 20% of each set's trade dates.", "",
          "![Equity curve](equity_curve.png)", "", "![Drawdown](drawdown.png)", ""]
    S += ["## What was built, pulled and left out", "",
          "| Set | Ladders built | Pairs built | Ladders pulled | of which date / strike | Rungs pulled | Pairs pulled | Events pulled | Ladders left out | Pairs left out | Print requests | Smallest event pulled |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in ("a", "b"):
        b = built[s]
        S.append(f"| ({s}) | {b['ladders']:,} | {b['pairs']:,} | {b['pulled_ladders']:,} | {b['pulled_date']} / {b['pulled_strike']} | {b['pulled_rungs']:,} | "
                 f"{b['pulled_pairs']:,} | {b['pulled_events']:,} | {b['left_ladders']:,} | {b['left_pairs']:,} | {b['requests']:,} | {usd(b['smallest_event_pulled'])} |")
    S += ["", f"Ladders were pulled in the order fixed before the pull (largest event volume first, the two sets in turns). The pull stopped by: "
          f"{st.get('stopped_by')}. Requests in all: {rq['n']} of {cfg.MAX_REQUESTS}.", "",
          "**Pairs that could not be fully checked.** The API serves only a market's latest 20,000 prints.", "",
          "| Set | Pairs pulled | Every print checked | Latest 20,000 prints only (earlier life unseen) | No prints served | Pairs with at least one trade |",
          "|---|---|---|---|---|---|"]
    for s in ("a", "b"):
        S.append(f"| ({s}) | {built[s]['pulled_pairs']:,} | {cov_n[s]['every print checked']:,} | {cov_n[s]['latest 20,000 prints only']:,} | "
                 f"{cov_n[s]['no prints served']:,} | {pairs_with_trade[s]:,} |")
    S += [""]
    S += notes.body(locals())
    (RESULTS / "SUMMARY.md").write_text("\n".join(S) + "\n")
    print("\n".join(S[:60]))
    print(f"\nverdict {verdict}; failed: {failed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
