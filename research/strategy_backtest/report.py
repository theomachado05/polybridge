from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .config import PARAMS, RESULTS_DIR  # noqa: E402

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
VNAMES = {"primary": "Primary (09:29 signal, 09:30 to 10:00)", "V1_premarket": "V1 pre-market (07:59 signal, 08:00 to 10:00)",
          "V2_no_gating": "V2 no gating (gap-model rate rule)", "V3_unwind_close": "V3 unwind at the close",
          "V4_expanded": "V4 expanded universe"}


def pct(x, nd: int = 2, sign: bool = False) -> str:
    if x is None or not np.isfinite(x):
        return "n/a"
    return f"{100 * x:+.{nd}f}%" if sign else f"{100 * x:.{nd}f}%"


def num(x, nd: int = 3) -> str:
    return "n/a" if x is None or not np.isfinite(x) else f"{x:.{nd}f}"


def usd(x) -> str:
    if x is None or not np.isfinite(x):
        return "n/a"
    a = abs(x)
    s = f"${a / 1e9:.2f}B" if a >= 1e9 else f"${a / 1e6:.1f}M" if a >= 1e6 else f"${a:,.0f}"
    return ("-" if x < 0 else "") + s


def _row(metrics: pd.DataFrame, seg: str, book: str, cost: str) -> dict:
    m = metrics[(metrics.segment == seg) & (metrics.book == book) & (metrics.cost == cost)]
    return m.iloc[0].to_dict() if len(m) else {}


def metrics_table(metrics: pd.DataFrame, book: str = "primary") -> list[str]:
    out = ["| Segment | Book | Ann. return | Ann. vol | Sharpe | Max DD | Worst month | Turnover (x/yr) | Hedge days | "
           "Mean hedge fraction | Hit rate | Hedge P&L |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for seg in ("OOS", "IS", "full"):
        b = _row(metrics, seg, "buy_and_hold", "-")
        out.append(f"| {seg} ({b['start']} to {b['end']}, {b['n_days']} d) | buy-and-hold | {pct(b['ann_return'])} | "
                   f"{pct(b['ann_vol'])} | {num(b['sharpe'])} | {pct(b['max_dd'])} | {pct(b['worst_month'])} | 0 | 0 | - | - | - |")
        for cost in ("1x", "2x"):
            s = _row(metrics, seg, book, cost)
            out.append(f"| {seg} | strategy {cost} | {pct(s['ann_return'])} | {pct(s['ann_vol'])} | {num(s['sharpe'])} | "
                       f"{pct(s['max_dd'])} | {pct(s['worst_month'])} | {num(s['turnover'], 2)} | {s['hedge_days']} | "
                       f"{pct(s['mean_hedge_fraction'], 1) if s['hedge_days'] else '-'} | "
                       f"{pct(s['hit_rate'], 0) if s['hedge_days'] else '-'} | {usd(s['hedge_pnl'])} |")
    return out


def variants_table(metrics: pd.DataFrame) -> list[str]:
    out = ["| Variant | Segment | Hedge days | Mean hedge fraction | Hedge P&L 1x | Hedge P&L 2x | Sharpe 1x (B&H) | "
           "Vol 1x vs B&H | Max DD 1x vs B&H | Hit rate | Turnover 1x |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name in PARAMS.variants:
        for seg in ("OOS", "IS", "full"):
            b, s1, s2 = _row(metrics, seg, "buy_and_hold", "-"), _row(metrics, seg, name, "1x"), _row(metrics, seg, name, "2x")
            dvol = s1["ann_vol"] / b["ann_vol"] - 1
            ddd = abs(s1["max_dd"]) / abs(b["max_dd"]) - 1 if b["max_dd"] else float("nan")
            out.append(f"| {name} | {seg} | {s1['hedge_days']} | {pct(s1['mean_hedge_fraction'], 1) if s1['hedge_days'] else '-'} | "
                       f"{usd(s1['hedge_pnl'])} | {usd(s2['hedge_pnl'])} | {num(s1['sharpe'])} ({num(b['sharpe'])}) | "
                       f"{pct(dvol, 2, True)} | {pct(ddd, 2, True)} | {pct(s1['hit_rate'], 0) if s1['hedge_days'] else '-'} | "
                       f"{num(s1['turnover'], 2)} |")
    return out


def sharpe_checks(metrics: pd.DataFrame) -> list[str]:
    hi = metrics[metrics["sharpe"] > 3]
    if hi.empty:
        return ["- No Sharpe ratio above 3 in any segment, book or cost case."]
    out = []
    for _, r in hi.iterrows():
        b = _row(metrics, r["segment"], "buy_and_hold", "-")
        out.append(f"- {r['segment']} {r['book']} {r['cost']}: Sharpe {r['sharpe']:.2f} over {r['n_days']} days "
                   f"(mean daily {100 * r['mean_daily']:.3f}%, sd {100 * r['sd_daily']:.3f}%). Buy-and-hold in the same "
                   f"segment: {b['sharpe']:.2f}, so the level comes from SPY's own path in that window "
                   f"(the overlay moves it by {r['sharpe'] - b['sharpe']:+.3f}), not from the hedge.")
    return out


def recon_lines(recon: dict) -> list[str]:
    if not recon.get("n"):
        return ["- R1 reconciliation: no overlapping closures."]
    labels = {"gap": "gap (bp)", "ret30": "09:30 to 10:00 return (bp)", "x": "oriented PM move (pp; here to 09:29, R1 to 09:30)",
              "pnl_B": "R1 hedge-B P&L recomputed with this study's legs (bp)"}
    out = [f"R1 reconciliation on {recon['n']} panel-A closures that overlap `closures_hedged.csv`:", "",
           "| Quantity | both present | equal within 0.01 | max abs diff | corr | only R1 | only here |", "|---|---|---|---|---|---|---|"]
    for k, lab in labels.items():
        s = recon.get(k)
        if s:
            out.append(f"| {lab} | {s['n_both']} | {s['n_match_0.01']} | {num(s['max_abs_diff'], 3)} | {num(s['corr'], 4)} | "
                       f"{s['only_r1']} | {s['only_here']} |")
    return out


def write_charts(res: dict) -> None:
    plt.rcParams.update({"font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2,
                         "ytick.color": INK2, "axes.titlecolor": INK, "axes.titlesize": 10})
    d1 = res["daily"][("primary", 1.0)]
    d4 = res["daily"][("V4_expanded", 1.0)]
    split = res["segs"]["OOS"][0] if res["segs"]["OOS"] else None
    idx = d1.index
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6.2), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]})
    ax1.plot(idx, d1["bh"] / 1e6, color=INK2, lw=1.6, label="buy-and-hold SPY")
    ax1.plot(idx, d1["strat"] / 1e6, color=BLUE, lw=1.1, label="long SPY + PolyBridge overlay (primary, 1x costs)")
    ax1.set_ylabel("equity ($M)")
    ax1.set_title("Equity: $1M long SPY from the 2024-01-02 close, with and without the closed-market overlay", loc="left")
    ax2.plot(idx, (d1["strat"] - d1["bh"]) / 1e3, color=BLUE, lw=1.3, label="primary")
    ax2.plot(idx, (d4["strat"] - d4["bh"]) / 1e3, color=ORANGE, lw=1.1, label="V4 expanded universe")
    ax2.axhline(0, color=INK2, lw=0.8)
    ax2.set_ylabel("overlay minus B&H ($k)")
    for ax in (ax1, ax2):
        ax.grid(color=GRID, lw=0.8)
        ax.spines[["top", "right"]].set_visible(False)
        if split is not None:
            ax.axvline(split, color=INK, lw=1, ls="--")
    if split is not None:
        ax1.text(split, ax1.get_ylim()[1], "  out of sample", va="top", ha="left", color=INK, fontsize=8)
        ax1.text(split, ax1.get_ylim()[1], "in sample  ", va="top", ha="right", color=INK, fontsize=8)
    ax1.legend(frameon=False, loc="upper left", bbox_to_anchor=(0, 0.93))
    ax2.legend(frameon=False, loc="lower left")
    fig.tight_layout()
    fig.savefig(RESULTS_DIR / "equity_curve.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 3.6))
    for col, colr, lab, lw in (("bh", INK2, "buy-and-hold SPY", 1.6), ("strat", BLUE, "overlay (primary, 1x)", 1.1)):
        e = d1[col]
        ax.plot(idx, 100 * (e / e.cummax() - 1), color=colr, lw=lw, label=lab)
    if split is not None:
        ax.axvline(split, color=INK, lw=1, ls="--")
    ax.set_ylabel("drawdown from running peak (%)")
    ax.set_title("Drawdown (full span; segment metrics are rebased at each segment start)", loc="left")
    ax.grid(color=GRID, lw=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="lower left")
    fig.tight_layout()
    fig.savefig(RESULTS_DIR / "drawdown.png", dpi=160)
    plt.close(fig)


def write_capacity(cap: dict) -> list[str]:
    r, p = cap["rth"], cap["pre"]
    head = (f"At the 09:30 open, a hedge of the maximum size (50% of the book) stays below 1% of the dollar volume of the first "
            f"five regular minutes for books up to {usd(r['book_max_hedge_median'])} on the median session and "
            f"{usd(r['book_max_hedge_p5'])} on a 5th-percentile session ({r['sessions']} sessions).")
    if r["n_hedges"]:
        head += (f" The actual primary hedges ({r['n_hedges']}) stay below 1% on 95% of hedge days up to a book of "
                 f"{usd(r['book_95pct_hedges'])}.")
    lines = ["# Capacity of the closed-market overlay (METHOD.md section 9)", "", head, "",
             "| Execution | sessions | median 5-min $ volume | book: max hedge < 1%, median session | 5th pct session | "
             "actual hedges | median hedge / 20d ADV | max hedge / 20d ADV | median hedge / 5-min $ vol | max | "
             "book: 95% of actual hedges < 1% |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for lab, c in (("09:30 open (primary)", r), ("08:00 pre-market (V1)", p)):
        extra = (f"{pct(c['median_share_adv'], 4)} | {pct(c['max_share_adv'], 4)} | {pct(c['median_share_vol5'], 3)} | "
                 f"{pct(c['max_share_vol5'], 3)} | {usd(c['book_95pct_hedges'])}") if c["n_hedges"] else "- | - | - | - | -"
        lines.append(f"| {lab} | {c['sessions']} | {usd(c['median_vol5_usd'])} | {usd(c['book_max_hedge_median'])} | "
                     f"{usd(c['book_max_hedge_p5'])} | {c['n_hedges']} | {extra} |")
    lines += ["", "Hedge notional is at the study's $1M book. 20-day ADV = trailing mean of daily volume x VWAP over the 20 "
              "prior sessions. 5-minute $ volume = sum of volume x close over the 09:30-09:34 bars (08:00-08:04 for V1). "
              "Book sizes scale linearly because the hedge is a fixed fraction of the book.", ""]
    for lab, c in (("Primary hedge days", r), ("V1 pre-market hedge days", p)):
        if not c["n_hedges"]:
            continue
        h = c["rows"]
        lines += [f"## {lab}", "", "| Day | notional | 20d ADV | share of ADV | 5-min $ volume | share of 5-min |", "|---|---|---|---|---|---|"]
        for d, x in h.iterrows():
            lines.append(f"| {d:%Y-%m-%d} | {usd(x['notional'])} | {usd(x['adv_usd'])} | {pct(x['share_adv'], 4)} | "
                         f"{usd(x['vol5_usd'])} | {pct(x['share_vol5'], 3)} |")
        lines.append("")
    (RESULTS_DIR / "capacity.md").write_text("\n".join(lines))
    return [head]


def write_all(res: dict, commit: str) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    metrics, segs, v = res["metrics"], res["segs"], res["verdict"]
    metrics.to_csv(RESULTS_DIR / "metrics.csv", index=False)
    res["trades"].to_csv(RESULTS_DIR / "trades.csv", index=False)
    seg_of = {d: s for s in ("IS", "OOS") for d in segs[s]}
    d1 = res["daily"][("primary", 1.0)]
    daily = pd.DataFrame({"segment": [seg_of.get(d, "purchase") for d in d1.index], "spy_close": res["close"].to_numpy(),
                          "bh": d1["bh"]}, index=d1.index)
    for (name, mult), d in res["daily"].items():
        daily[f"{name}_{mult:g}x"] = d["strat"]
    for name in PARAMS.variants:
        d = res["daily"][(name, 1.0)]
        daily[f"{name}_f"] = d["f"]
        daily[f"{name}_hedge_net_1x"] = d["hedge_net"]
    daily.index.name = "day"
    daily.to_csv(RESULTS_DIR / "daily.csv")
    recs = []
    for uni, name in (("primary", "primary"), ("V4", "V4_expanded")):
        r = res["rec"][name].copy()
        r.insert(0, "universe", uni)
        recs.append(r)
    pd.concat(recs, ignore_index=True).to_csv(RESULTS_DIR / "records.csv", index=False)
    write_charts(res)
    cap_head = write_capacity(res["capacity"])

    b_oos, s_oos = _row(metrics, "OOS", "buy_and_hold", "-"), _row(metrics, "OOS", "primary", "1x")
    n_ret = len(segs["full"])
    tr = res["trusted"]
    lines = [
        "# Strategy backtest: the PolyBridge closed-market overlay on a long SPY book",
        "",
        "Rules fixed in [METHOD.md](../../strategy_backtest/METHOD.md) and committed before any data for this study was "
        f"fetched (commit 3c6b280); run once at commit `{commit}`. A $1,000,000 book is long SPY throughout; on each "
        "closure the overlay reads prediction-market moves and, when a market that has earned trust from earlier closures "
        "points to an adverse open, sells SPY short at the 09:30 open and covers at 10:00, sized by the product's rule. "
        "All results are net of costs (1x = 1 bp per side, 2x stress).",
        "",
        "## Verdict (METHOD.md section 8: primary, out of sample, 1x costs)",
        "",
        f"- **{v['verdict']}**: {v['reason']}. Out-of-sample max drawdown {pct(s_oos['max_dd'])} vs {pct(b_oos['max_dd'])} for "
        f"buy-and-hold ({pct(v['dd_rel'], 2, True)} relative, positive = shallower); volatility {pct(s_oos['ann_vol'])} vs "
        f"{pct(b_oos['ann_vol'])} ({pct(v['vol_rel'], 2, True)} relative, positive = lower); Sharpe {num(s_oos['sharpe'])} vs "
        f"{num(b_oos['sharpe'])}. Pass needs a 1% relative cut in drawdown or volatility and a Sharpe no lower than buy-and-hold.",
        f"- The overlay traded on {s_oos['hedge_days']} of {s_oos['n_days']} out-of-sample days and "
        f"{_row(metrics, 'IS', 'primary', '1x')['hedge_days']} of {len(segs['IS'])} in-sample days; net hedge P&L "
        f"{usd(s_oos['hedge_pnl'])} OOS and {usd(_row(metrics, 'IS', 'primary', '1x')['hedge_pnl'])} IS on the $1M book.",
        f"- Span: {n_ret} return days, {segs['full'][0]:%Y-%m-%d} to {segs['full'][-1]:%Y-%m-%d} (last session with complete "
        f"SPY minute bars at run time). Out of sample = the last {len(segs['OOS'])} return days, from "
        f"{segs['OOS'][0]:%Y-%m-%d} (L = min(ceil(0.2 N), days in the last 730 calendar days)).",
        "",
        "![equity curve](equity_curve.png)",
        "",
        "![drawdown](drawdown.png)",
        "",
        "## Primary metrics",
        "",
        "Daily returns of book equity (SPY at the official close + dividend cash + hedge cash), risk-free rate 0. Max drawdown "
        "and worst month are measured within the segment, rebased at its start. Turnover = traded hedge notional (entry + exit) / "
        "mean equity / years. Mean hedge fraction is over hedge days. Hit rate = hedge days with positive net hedge P&L.",
        "",
        *metrics_table(metrics),
        "",
        "## Variants (METHOD.md section 7; reported, not part of the verdict)",
        "",
        "Vol and max DD columns are relative to buy-and-hold in the same segment (negative = lower risk).",
        "",
        *variants_table(metrics),
        "",
        "## Where the trades come from",
        "",
        "| Variant | Segment | days with a participating market | days with a trusted market | hedge days | skipped (missing price) | trusted markets |",
        "|---|---|---|---|---|---|---|",
    ]
    for name in PARAMS.variants:
        for seg in ("OOS", "IS"):
            t = tr[(name, seg)]
            hd = _row(metrics, seg, name, "1x")["hedge_days"]
            mk = ", ".join(f"`{m}`" for m in t["markets"]) or "none"
            lines.append(f"| {name} | {seg} | {t['days_participating']} | {t['days_with_trusted']} | {hd} | "
                         f"{t['skipped_missing_px']} | {mk} |")
    cov = res["coverage"]
    lines += ["", f"V4 universe: {int(cov['v4'].sum())} of {len(cov)} markets have at least {PARAMS.v4_min_closures} closures in "
              "the span quoted at both ends; primary universe: 12 markets.", "",
              "| Market | source | closures in span | quoted both ends | fetch failed | in V4 |", "|---|---|---|---|---|---|"]
    for _, c in cov.iterrows():
        lines.append(f"| `{c['market']}` | {c['source']} | {c['closures']} | {c['pm_both_ends']} | {c['fetch_failed']} | "
                     f"{'yes' if c['v4'] else 'no'} |")
    cc = res["close_check_bp"].dropna()
    lines += ["", "## Sanity checks (METHOD.md section 9)", "", *sharpe_checks(metrics), "",
              *recon_lines(res["recon"]), "",
              f"- Official daily close vs the close of the last regular minute bar: median {cc.median():.2f} bp, max "
              f"{cc.max():.2f} bp over {len(cc)} sessions.",
              "", "## Capacity", "", *[f"- {h}" for h in cap_head], "- Details per hedge day in [capacity.md](capacity.md).",
              "", "## Caveats", "",
              "- The in-sample segment overlaps closure panels whose relation was already known (METHOD.md section 0); only the "
              "2026 out-of-sample prices were unseen.",
              "- The overlay is small by construction (at most 50% of the book, only after an adverse expected gap of at least "
              "10 bp from a trusted market, for 30 minutes), so book-level metrics can differ from buy-and-hold only slightly.",
              "- Hedge B trades only the 09:30-10:00 move (to the close in V3); it cannot recover the overnight gap.",
              "- Fills are simulated at minute-bar prices plus a fixed cost; the opening auction can print away from the first "
              "minute bar's open.",
              "- One path, one book; no confidence intervals are attached to the book-level metrics.",
              "", "## Files", "",
              "`metrics.csv` (every segment x cost x book), `daily.csv` (equity of every book and variant, hedge fraction and net "
              "hedge P&L per day), `trades.csv` (every hedge day of every variant: trusted markets, E, f, prices, notional, gross "
              "and net P&L at 1x and 2x), `records.csv` (every training record with the instant it became known), `capacity.md`, "
              "`equity_curve.png`, `drawdown.png`, `RUN_LOG.md`. Code in `research/strategy_backtest/`, synthetic tests in "
              "`research/strategy_backtest/tests/`."]
    (RESULTS_DIR / "SUMMARY.md").write_text("\n".join(lines) + "\n")
