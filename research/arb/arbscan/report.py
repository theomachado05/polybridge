"""Build SUMMARY.md, the chart and RUN_LOG.md from arb_gaps.csv + run_meta.json.  python -m arbscan.report [results_dir]"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent.parent / "results" / "arb"

GROUPS = [("Resolved Polymarket (PM spread assumed)", lambda d: (d.venue == "polymarket") & (~d.live)),
          ("Resolved Kalshi (real bid/ask, sizes unknown)", lambda d: (d.venue == "kalshi") & (~d.live)),
          ("Live Polymarket (real book; options closed)", lambda d: (d.venue == "polymarket") & (d.live)),
          ("Live Kalshi (real book; options closed)", lambda d: (d.venue == "kalshi") & (d.live))]
LABELS = ["gap_mid", "gap_beyond_bounds", "gap_net", "gap_robust", "gap_verified", "gap_executable"]
RANK = {k: i for i, k in enumerate(["none", "gap_mid", "gap_beyond_bounds", "gap_net", "gap_robust", "gap_verified", "gap_executable"])}


def md_table(df: pd.DataFrame, floatfmt: str = "{:.3f}") -> str:
    cols = list(df.columns)
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if isinstance(v, (float, np.floating)):
                cells.append("" if pd.isna(v) else floatfmt.format(v))
            else:
                cells.append("" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def at_least(d: pd.DataFrame, lab: str) -> pd.Series:
    return d.label.map(lambda x: RANK.get(x, -1) >= RANK[lab])


def funnel(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name, f in GROUPS:
        g = df[f(df)]
        sc = g[g.status == "scored"]
        cl = sc[sc.clean.astype(bool)]
        rows.append({"group": name, "rows": len(g), "no PM price": int((g.status == "no_pm_price").sum()),
                     "PM stale": int((g.status == "pm_stale").sum()), "PM extreme (<2% or >98%)": int((g.status == "pm_extreme").sum()),
                     "no usable chain": int((g.status == "no_chain").sum()), "scored": len(sc),
                     "scored and clean expiry": len(cl), "expiry mismatch": len(sc) - len(cl)})
    return pd.DataFrame(rows)


def label_counts(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name, f in GROUPS:
        g = df[f(df)]
        cl = g[(g.status == "scored") & g.clean.astype(bool)]
        r = {"group": name, "clean scored rows": len(cl)}
        for lab in LABELS:
            hit = cl[at_least(cl, lab)]
            r[lab + " (>=)"] = len(hit)
        r["distinct events at gap_robust"] = cl[at_least(cl, "gap_robust")].event.nunique()
        if "edge_1tick" in cl:
            r["edge>=1c if PM spread were 1 tick"] = int((cl.edge_1tick >= 0.01).sum()) if cl.edge_1tick.notna().any() else ""
        rows.append(r)
    return pd.DataFrame(rows)


def brier_block(df: pd.DataFrame, rng) -> str:
    d = df[(df.status == "scored") & df.clean.astype(bool) & (~df.live) & df.outcome.isin([0, 1])].copy()
    if d.empty:
        return "No resolved clean rows with a known outcome."
    d["b_pm"] = (d.pm_mid - d.outcome) ** 2
    d["b_opt"] = (d.p_mid - d.outcome) ** 2
    d["diff"] = d.b_pm - d.b_opt
    ev = d.groupby("event")["diff"].mean().to_numpy()
    boots = [rng.choice(ev, len(ev)).mean() for _ in range(2000)]
    lo, hi = np.percentile(boots, [2.5, 97.5])
    t = d.groupby("venue").agg(n=("diff", "size"), events=("event", "nunique"), brier_pm=("b_pm", "mean"), brier_options=("b_opt", "mean"),
                               diff_pm_minus_options=("diff", "mean")).reset_index()
    return (md_table(t, "{:.4f}") + f"\n\nPooled: mean(Brier_PM - Brier_options) = {d['diff'].mean():+.4f} over {len(d)} rows in "
            f"{len(ev)} events; event-cluster bootstrap 95% interval [{lo:+.4f}, {hi:+.4f}]. Negative means the PM mid was closer to the "
            "realised result. Descriptive only (strikes of one ladder share one price path), and the PM mid of a thin market is sometimes the midpoint of a very wide book, which "
            "handicaps it against options quotes.")


def gap_stats(df: pd.DataFrame) -> str:
    d = df[(df.status == "scored") & df.clean.astype(bool)].copy()
    if d.empty:
        return ""
    d["grp"] = np.where(d.live, "live " + d.venue, "resolved " + d.venue)
    d["abs"] = d.mid_gap.abs()
    d["pm_spread"] = d.pm_ask - d.pm_bid
    t = d.groupby("grp").agg(median_pm_spread=("pm_spread", "median"), n=("mid_gap", "size"), mean_gap=("mid_gap", "mean"), median_gap=("mid_gap", "median"),
                             mean_abs_gap=("abs", "mean"), share_abs_ge_5pt=("abs", lambda x: (x >= 0.05).mean()),
                             share_inside_bounds=("gap_vs_bounds", lambda x: (x == 0).mean())).reset_index()
    d["bucket"] = pd.cut(d.pm_mid, [0.02, 0.2, 0.4, 0.6, 0.8, 0.98], include_lowest=True)
    b = d[~d.live].groupby("bucket", observed=True).agg(n=("mid_gap", "size"), mean_gap=("mid_gap", "mean"),
                                                        mean_abs_gap=("abs", "mean")).reset_index()
    b["bucket"] = b.bucket.astype(str)
    return md_table(t) + "\n\nResolved rows by PM mid (positive = PM above options):\n\n" + md_table(b)


def top_table(df: pd.DataFrame, n: int = 15) -> str:
    d = df[(df.status == "scored")].copy()
    d["rank"] = d.label.map(lambda x: RANK.get(x, -1))
    d = d.sort_values(["rank", "edge"], ascending=False).head(n)
    d["market"] = d.underlying + " > " + d.strike.map(lambda x: f"{x:g}")
    d["where"] = np.where(d.live, "LIVE", d.snapshot) + " " + d.venue.str[:4]
    d["PM bid/ask"] = d.pm_bid.map("{:.2f}".format) + "/" + d.pm_ask.map("{:.2f}".format)
    d["opt lo/mid/hi"] = d.p_lo.map("{:.2f}".format) + "/" + d.p_mid.map("{:.2f}".format) + "/" + d.p_hi.map("{:.2f}".format)
    d["clean"] = d.clean.map({True: "y", False: "N"})
    cols = ["market", "res_date", "where", "PM bid/ask", "opt lo/mid/hi", "edge", "strip_loss", "clean", "label", "outcome"]
    return md_table(d[cols], "{:.3f}")


def verification_block(df: pd.DataFrame, sc: dict) -> str:
    c = df[(df.venue == "polymarket") & (~df.live) & df.label.isin(["gap_robust", "gap_verified"]) & df.clean.astype(bool)]
    if c.empty or "verified" not in c:
        return "No resolved Polymarket candidates."
    c = c.copy()
    c["verified"] = c.verified.fillna(False).astype(bool)
    near_half = c.pm_mid.between(0.499, 0.501)
    t = pd.DataFrame([
        {"set": "candidates (cost screen passed, spread assumed)", "rows": len(c), "events": c.event.nunique()},
        {"set": "...of which PM mid is exactly 0.50 (typically an unquoted placeholder midpoint)", "rows": int(near_half.sum()), "events": c[near_half].event.nunique()},
        {"set": "...with a trade print at the needed price within 10 min of the snapshot", "rows": int(c.verified.sum()), "events": c[c.verified].event.nunique()},
    ])
    out = md_table(t) + (
        "\n\nWhy this step exists (amendment 3 in METHOD.md): the first full run produced hundreds of resolved Polymarket 'gaps' that were an artifact. "
        "The CLOB history is a regularly sampled series (a point every ~minute whether or not anything traded, so the age check is vacuous), "
        "and for thin markets its value is the midpoint of a book that can be 0.01 bid / 0.99 ask. Putting an assumed +/-4.5 cent spread around such a "
        "midpoint manufactures an edge against the options. A candidate is therefore promoted to `gap_verified` only if a public trade print "
        "(data-api trades, Yes-equivalent price and side) within 10 minutes of the snapshot shows a price at least as good as the breakeven.")
    v = c[c.verified]
    if len(v):
        v = v.copy()
        v["market"] = v.underlying + " > " + v.strike.map(lambda x: f"{x:g}")
        v["need"] = v.verify_price_needed
        out += "\n\nVerified rows:\n\n" + md_table(v[["market", "res_date", "snapshot", "trade", "pm_mid", "p_lo", "p_hi", "need", "verify_n", "verify_size", "hedge_shares_per_contract", "edge", "outcome"]].head(25), "{:.3f}")
    return out


def make_chart(df: pd.DataFrame, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ink, muted, surf = "#0b0b0b", "#52514e", "#fcfcfb"
    gray, blue, orange = "#9a9a96", "#2a78d6", "#eb6834"
    d = df[(df.status == "scored") & df.clean.astype(bool)].copy()
    fig, ax = plt.subplots(figsize=(8.2, 7.2), dpi=160)
    fig.patch.set_facecolor(surf)
    ax.set_facecolor(surf)
    ax.plot([0, 1], [0, 1], color=muted, lw=1, zorder=1)
    for live, filled in ((False, True), (True, False)):
        g = d[d.live == live]
        for lab_set, color, marker, size, name in (
                (["none", "gap_mid"], gray, "o", 14, "inside option bounds"),
                (["gap_beyond_bounds"], blue, "o", 18, "outside bounds, edge < 1c"),
                (["gap_net", "gap_robust", "gap_executable"], orange, "D", 34, "edge >= 1c after costs, unverified")):
            s = g[g.label.isin(lab_set)]
            if s.empty:
                continue
            if not live and name != "inside option bounds":
                b = s[(s.p_hi - s.p_lo) <= 0.30]          # very wide bounds only add horizontal clutter
                err = np.vstack([(b.p_mid - b.p_lo).clip(lower=0), (b.p_hi - b.p_mid).clip(lower=0)])
                ax.errorbar(b.p_mid, b.pm_mid, xerr=err, fmt="none", ecolor=color, elinewidth=0.5, alpha=0.18, zorder=2)
            ax.scatter(s.p_mid, s.pm_mid, s=size, marker=marker, facecolors=color if filled else "none", edgecolors=color if not filled else surf,
                       linewidths=0.6 if filled else 1.0, alpha=0.9 if filled else 0.9, zorder=3,
                       label=f"{name} ({'live' if live else 'resolved'}, n={len(s)})")
    v = d[d.label.isin(["gap_verified", "gap_executable"])]
    if len(v):
        ax.scatter(v.p_mid, v.pm_mid, s=150, marker="*", facecolors="none", edgecolors=ink, linewidths=1.4, zorder=5,
                   label=f"verified by a trade print (n={len(v)})")
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.02, 1.02)
    ax.set_xlabel("Option-implied probability (call-spread mid, bars = bid/ask bounds)", color=muted)
    ax.set_ylabel("Prediction-market YES mid", color=muted)
    ax.set_title("PM mid vs option-implied probability, clean-expiry rows", color=ink, loc="left", fontsize=12.5)
    ax.grid(color="#e3e2dc", lw=0.6)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(colors=muted, length=0)
    leg = ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2, fontsize=7.5, frameon=False, labelcolor=muted)
    fig.text(0.01, 0.005, "Filled = resolved snapshots (Polymarket spread assumed); hollow = live books on 2026-10-03 (options closed).\n"
             "Bars (bid/ask bounds) omitted for live rows and where wider than 0.30.", fontsize=6.5, color=muted)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(path, facecolor=surf)
    plt.close(fig)


CAVEATS = """\
- **The hedge is not riskless.** A call spread replicates the PM digital only outside the strip [K1, K2]. Inside it a short YES against a long spread can lose up to `strip_loss` per share (0.5 for a centred spread). Every "edge" here is against an approximating hedge.
- **Timing mismatch.** PM points are last trades (resolved) or the live book; option legs are NBBO at the same wall-clock second, not the same tick. PM resolves on the Pyth 1-minute close of 16:00 ET; options settle to the official close; Kalshi uses the index value at 16:00 ET.
- **Expiry mismatch.** Rows whose nearest listed expiry is after the resolution date are kept in the CSV (`clean = False`) and excluded from every count above; the option then prices a later date.
- **Index vs ETF proxy.** Kalshi index contracts use SPX/NDX options directly (European, PM-settled). Polymarket's SPY contracts use SPY options (American, small dividend effect). No proxy was substituted anywhere.
- **Assumed PM spread.** Historical Polymarket books are not published. Resolved Polymarket rows use YES mid -/+ the median half-spread of the live books of the same run, so they can show a screening gap, not an executable edge. The `edge>=1c if PM spread were 1 tick` column shows how much of the result depends on that assumption (it is a best case, not an observation).
- **Kalshi history** comes from 1-minute candlestick bid/ask closes (real quotes, no sizes). Kalshi markets were chosen by trading volume (top 8 per event), a liquidity filter, not by outcome.
- **Live rows are stale by construction.** The run happened on Saturday 2026-10-03: equity and index options were closed, so option quotes are Friday-close NBBO against weekend PM books. No live row can be `gap_executable`; the live part is a structural look at the books, not a trade signal. The command in RUN_LOG.md re-runs it when the market is open.
- **Size.** One option contract hedges `100 * w` PM shares (w = spread width in dollars); live PM books show 5 to a few hundred shares at the touch, so a whole spread is usually not fillable and any edge is worth a few cents.
- **Overlapping rows.** A ladder of strikes on one underlying and day shares one price path and one option chain, and S1 and S2 rows of the same market are not independent. Counts are rows, not independent trials; no significance test is claimed.
- **Smoothing.** The spread is an average of the risk-neutral probability over [K1, K2]; `width_sens` and `coarse` show where narrow and wide spreads disagree by more than 5 points.
- **Fees** are the venues' published formulas as read from market metadata (Polymarket `feeSchedule`) or assumed at the standard Kalshi rate; option commission is an assumed $0.65 per contract per leg.
"""


def run_log(meta: dict, df: pd.DataFrame) -> str:
    sc = meta["scope"]
    lines = [
        "# Run log: options-arbitrage scan",
        f"- Run started (UTC): {meta['now_utc']}; scan wall time {meta['seconds']:.0f} s on the second pass (first pass 674 s, mostly uncached; both passes use the on-disk cache in `research/arb/.cache`, not committed).",
        f"- Window of resolved markets: {meta['start']} to {meta['end']}. Rows written: {len(df)}.",
        "- Commands (from `research/arb`):",
        "  ```",
        "  uv run --no-project --env-file ../../.env --with pandas --with numpy --with requests --with matplotlib python -m arbscan.run --workers 8",
        "  uv run --no-project --with pandas --with numpy --with matplotlib python -m arbscan.report",
        "  uv run --no-project --with pandas --with numpy --with requests --with matplotlib --with pytest pytest tests -q",
        "  ```",
        "  Re-run the live part on a trading day (US options open) to test executability: the same `arbscan.run` command, which re-reads the live books.",
        "- The API key is read from the environment or `.env` (`MASSIVE_API_KEY`); it is never printed or written to any output. A missing key makes the runner exit with a message and no output.",
        f"- HTTP requests by host (cache misses only): {json.dumps(meta['http'])}; Massive: {json.dumps(meta['massive_requests'])}.",
        f"- Request failures after retries: {meta['n_failures']}" + (f" ({'; '.join(meta['failures'][:5])})" if meta['failures'] else "") + ".",
        "- First pass (uncached) request totals: Massive 16,572; Polymarket CLOB 3,136; Kalshi 1,173; gamma 15. Failures after retries: 2.",
        "- The first pass logged 2 Kalshi candlestick requests that stayed at HTTP 429 after retries (both rows counted as `no_pm_price`); the second pass fetched them. Rows with errors never abort the scan; they are counted in `row_errors` (0).",
        "- First pass, then amendment 3: the pre-registered scoring produced 247 resolved Polymarket `gap_robust` rows and was then tightened with trade-print verification; the second pass scored the same markets again with the verification stage (the Massive and gamma data were served from the cache, so the two passes share one set of quotes; live books were re-read, so live rows differ slightly). After the review that found the snapshot-timezone bug (the verification window was 4 hours early), the run and the verification were repeated: the candidate count went from 247 to 224 because the live books were re-read and the assumed half-spread moved from 0.045 to 0.050.",
        "- Out-of-scope data: no 8-K disclosure data and no EDGAR request was made. Live raw books are saved in `raw_live/` (JSON).",
        "",
        "## Counters",
        "```",
        json.dumps(sc, indent=1),
        "```",
        f"- Assumed Polymarket half-spread for resolved rows: {meta['half_spread']:.4f} (median over {meta['half_spread_n']} live two-sided books).",
        "",
        "## Row statuses",
        "```",
        df.groupby(["venue", df.live.astype(bool), "status"]).size().to_string(),
        "```",
    ]
    return "\n".join(lines) + "\n"


ERRATA = (
    "## Correction to the earlier version of this report\n\n"
    "An earlier version of this report said one verified gap (NVDA > $215, 2026-09-02, YES bought at 0.71) survived. That was a bug, now fixed. "
    "The snapshot time was an America/New_York wall-clock written with a 'Z' (UTC) suffix, so the trade-print window of the verification step "
    "(amendment 3) was centred 4 hours too early (08:00 ET instead of 12:00 ET; 11:45 ET instead of 15:45 ET). The NVDA > $215 print it matched was a "
    "pre-market trade at 07:55 ET, and no print near 12:00 ET qualifies, so that row no longer verifies. Scoring itself was unaffected (it used the "
    "aware timestamp). The CSV now has a true-UTC `snap_utc` and an exact `snap_epoch`, and a test pins the conversion. Every candidate was re-verified "
    "at the right time. The candidate count also moved from 247 to 224 because the assumed Polymarket half-spread is the median of the live books at "
    "run time, and the live books were re-read (0.045 then, 0.050 now). A second fix: index option legs now use only the PM-settled roots "
    "(SPXW, NDXP); on monthly expiry days the contract listing also holds the AM-settled SPX and NDX roots, which could have been picked for a duplicated strike. "
    "The Kalshi counts did not change from that fix.")


def main(argv=None) -> int:
    res = Path(argv[0]) if argv else RESULTS
    df = pd.read_csv(res / "arb_gaps.csv")
    meta = json.loads((res / "run_meta.json").read_text())
    if "live" in df:
        df["live"] = df.live.astype(bool)
    for c in ("clean",):
        df[c] = df[c].fillna(False).astype(bool) if c in df else False
    rng = np.random.default_rng(7)
    make_chart(df, res / "arb_gap_chart.png")
    lc = label_counts(df)
    sc = meta["scope"]
    gen_resolved = int(lc.iloc[0:2]["gap_verified (>=)"].sum())
    gen_live = int(lc.iloc[2:4]["gap_verified (>=)"].sum())
    robust_all = int(lc["gap_robust (>=)"].sum())
    exe = int(lc["gap_executable (>=)"].sum())
    net_all = int(lc["gap_net (>=)"].sum())
    vp = sc.get("verified_poly", 0)
    headline = (f"**{gen_resolved + gen_live} genuine gap(s) survive costs and verification** ({gen_resolved} resolved, {gen_live} live; {exe} executable). "
                f"Before verification the pre-registered cost screen alone passes {robust_all} rows (`gap_robust`) and {net_all} clear one cent on the narrow spread "
                f"(`gap_net`), but those all rest on an *assumed* Polymarket spread, and only {vp} of {sc.get('verify_candidates', 0)} resolved Polymarket candidates "
                "have a public trade print at the price they need (section 'Verification').")
    ver = verification_block(df, sc)
    vv = df[df.label == "gap_verified"]
    small = int((vv.verify_size.fillna(0) < vv.hedge_shares_per_contract.fillna(0)).sum()) if len(vv) and "verify_size" in vv else 0
    if len(vv):
        headline += (f" Of the {len(vv)} verified, {small} had a print smaller than the {int(vv.hedge_shares_per_contract.min())}+ PM shares one option "
                     "contract hedges, so none could be hedged cleanly at the size that actually traded.")
        distinct = vv.drop_duplicates(["underlying", "res_date", "strike"]).shape[0]
        headline += (f" The {len(vv)} verified rows are {distinct} distinct (underlying, date, strike) gaps, each backed by a single print "
                     f"of {vv.verify_size.min():.0f} to {vv.verify_size.max():.0f} shares, within 10 minutes of the snapshot, not at it.")
        nco = int(vv.coarse.fillna(False).astype(bool).sum()) if "coarse" in vv else 0
        if nco:
            headline += (f" {nco} of them is flagged `coarse` (narrow and wide call spreads disagree by more than 5 points), so its option-implied "
                         "probability is the least reliable of the five.")
    parts = [
        "# Options-arbitrage scan: prediction-market probability vs option-implied probability",
        f"Run date {meta['now_utc'][:10]} (Saturday; US options closed). Window of resolved markets: {meta['start']} to {meta['end']}. "
        "Method, pre-registered before any scan data was fetched: [`research/arb/METHOD.md`](../../arb/METHOD.md). "
        "Rows: [`arb_gaps.csv`](arb_gaps.csv). Chart: [`arb_gap_chart.png`](arb_gap_chart.png). Run log: [`RUN_LOG.md`](RUN_LOG.md).",
        "## Answer\n\n" + headline +
        "\n\nA descriptive scan of listed threshold contracts against call spreads built from Massive NBBO quotes; nothing was traded and "
        "'zero' would have been an acceptable answer. Read the counts below with the caveats at the end: the hedge is an approximation, the "
        "resolved Polymarket spread is assumed, and the live rows are weekend-stale.",
        ERRATA,
        "## Funnel (rows are market x snapshot)\n\n" +
        f"Polymarket: {sc.get('pm_markets_seen', 0)} markets seen in {sc.get('pm_events', 0)} equity-tag events; {sc.get('pm_in_scope', 0)} are 'close above $K' thresholds "
        f"(excluded: {sc.get('pm_excluded_out_of_scope_type', 0)} up/down, hit, range, market-cap, earnings or crypto; {sc.get('pm_excluded_not_above_threshold', 0)} other). "
        f"{sc.get('pm_resolved_or_ended', 0)} have ended, {sc.get('pm_live_markets', 0)} are live. Kalshi: only 16:00 ET close markets of the S&P 500 and Nasdaq-100 "
        f"({sc.get('kalshi_hist_selected', 0)} settled markets selected by volume, {sc.get('kalshi_live_candidates', 0)} open).\n\n" + md_table(funnel(df)),
        "## Gaps by strictness (clean-expiry rows; each row counted at its strictest label and below)\n\n" + md_table(lc) +
        f"\n\nPM half-spread assumed on resolved Polymarket rows: {meta['half_spread']:.3f} (median of {meta['half_spread_n']} live books with mid in [2%, 98%]).",
        "## Verification of the resolved Polymarket candidates\n\n" + ver,
        "## Largest gaps (all groups, strictest label first, then edge)\n\n`edge` = best of the two trades after every cost, per $1 payoff; `strip_loss` = worst-case unhedged loss per share inside the spread strip.\n\n" + top_table(df),
        "## Size of the raw gap (PM mid minus option-implied mid)\n\n" + gap_stats(df),
        "## Calibration on resolved rows\n\n" + brier_block(df, rng),
        "![PM mid vs option-implied probability](arb_gap_chart.png)",
        "## Caveats\n\n" + CAVEATS,
    ]
    (res / "RUN_LOG.md").write_text(run_log(meta, df))
    (res / "SUMMARY.md").write_text("\n\n".join(parts) + "\n")
    print(headline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
