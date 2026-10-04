"""After the freeze: outcomes, mid-variant prices, scoring, SUMMARY.md, stats.json, chart.png, .done (METHOD.md 2, 4, 5, 10)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from arbscan import datasrc as ds

from . import analysis as A
from . import config as C
from . import core
from .core import ET

GAMMA = "https://gamma-api.polymarket.com"


def _jl(x):
    if isinstance(x, list):
        return x
    try:
        return json.loads(x) if isinstance(x, str) else []
    except ValueError:
        return []


def daily_closes(massive, tk: str) -> dict[str, float]:
    d = massive.get(f"/v2/aggs/ticker/{tk}/range/1/day/2026-01-02/2026-08-31", {"adjusted": "false", "limit": 5000})
    out = {}
    for b in (d or {}).get("results") or []:
        day = datetime.fromtimestamp(b["t"] / 1000, timezone.utc).astimezone(ET).date().isoformat()
        out[day] = float(b["c"])
    return out


def fmt(x, pct=True):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "n/a"
    return f"{100 * x:+.2f}" if pct else f"{x:.3f}"


def ci(s: dict) -> str:
    if not s or not s.get("n"):
        return "n = 0"
    return f"{fmt(s['mean'])} pt [{fmt(s['ci_lo'])}, {fmt(s['ci_hi'])}]"


def finish(st, out, rows, commit):
    uni = pd.DataFrame(rows).set_index("id")
    trades = pd.read_csv(out / "trades_frozen.csv", dtype={"market_id": str})
    evals = pd.read_csv(out / "prints_evaluated.csv", dtype={"market_id": str})
    need = sorted(set(trades["market_id"]) | set(evals["market_id"]))
    st.log(f"outcome fetch starts (after freeze): {len(need)} markets")
    meta = {}
    for mid in need:
        m = st.http.get_json(f"{GAMMA}/markets/{mid}") or {}
        en, rate, ex = core.fee_params(m)
        toks = _jl(m.get("clobTokenIds"))
        outs = [str(o).lower() for o in _jl(m.get("outcomes"))]
        yes_tok = toks[outs.index("yes")] if "yes" in outs and len(toks) == len(outs) else (toks[0] if toks else "")
        meta[mid] = {"y": core.outcome_from_gamma(m), "fee_enabled": en, "fee_rate": rate, "fee_exp": ex, "yes_tok": yes_tok}
    closes = {tk: daily_closes(st.massive, tk) for tk in sorted(uni["tk"].unique())}
    for df in (trades, evals):
        for c in ("y", "fee_enabled", "fee_rate", "fee_exp"):
            df[c] = [meta.get(m, {}).get(c) for m in df["market_id"]]
    trades["close_D"] = [closes.get(tk, {}).get(d) for tk, d in zip(trades["tk"], trades["res_date"])]
    trades["y_close"] = [None if c is None or np.isnan(c) else int(c > k) for c, k in zip(trades["close_D"], trades["k"])]
    unresolved = int(trades["y"].isna().sum())
    tr = trades[trades["y"].notna()].copy()
    tr["y"] = tr["y"].astype(int)
    prim_all = tr[tr["tau"].round(4) == round(C.TAU, 4)]
    dis = prim_all[prim_all["y_close"].notna() & (prim_all["y_close"] != prim_all["y"])]
    st.log(f"outcomes joined: unresolved trades {unresolved}; settlement disagreements (primary) {len(dis)}")

    mid_rows = []
    for mid, g in evals[evals["status"] == "ok"].groupby("market_id"):
        u = uni.loc[mid]
        tok = meta[mid]["yes_tok"] or u["tok"]
        pts = ds.clob_history(st.http, tok, int(u["w0"]) - C.MID_MAX_AGE, int(u["w1"]))
        t = core.mid_variant_trade(g.sort_values("ts").to_dict("records"), pts)
        if t is not None and meta[mid]["y"] is not None:
            mid_rows.append({**t, "market_id": mid, "res_date": u["res_date"], "tk": u["tk"], **meta[mid]})
    mid_df = pd.DataFrame(mid_rows)

    ev = evals.copy()
    ev["y"] = pd.to_numeric(ev["y"], errors="coerce")
    res = A.score(tr, ev, mid_df if len(mid_df) else None)
    prim = res.pop("primary_trades")
    p, sec = res["primary"], res["secondary"]
    full = A.add_pnl(tr, C.TICK)
    full.to_csv(out / "trades.csv", index=False)
    ev.to_csv(out / "prints_evaluated.csv", index=False)
    stats = {"verdict": p["verdict"], "primary": p, "secondary": sec, "unresolved_trades": unresolved,
             "settlement_disagreements": dis[["market_id", "tk", "k", "res_date", "y", "y_close", "close_D"]].to_dict("records"),
             "scope": dict(st.scope), "requests": st.requests(), "commit": commit}
    (out / "stats.json").write_text(json.dumps(stats, indent=1, default=str))
    chart(prim, ev, out / "chart.png")
    (out / "SUMMARY.md").write_text(summary_md(stats, prim))
    st.log(f"report written; requests {st.requests()}; verdict {p['verdict']}")
    (out / ".done").write_text(datetime.now(ET).isoformat())


def chart(prim: pd.DataFrame, ev: pd.DataFrame, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.2))
    if len(prim):
        s = prim.sort_values(["res_date", "ts"])
        ax[0].plot(np.arange(1, len(s) + 1), 100 * s["net"].cumsum().values, color="#0072B2")
        ax[0].axhline(0, color="0.6", lw=0.8)
        ax[0].set_xlabel("trade number (time order)")
        ax[0].set_ylabel("cumulative net P&L, pt per $1 contract")
        ax[0].set_title(f"Primary rule, {len(s)} trades, mean {100 * s['net'].mean():+.1f} pt")
    ok = ev[(ev["status"] == "ok") & ev["y"].notna()]
    if len(ok):
        for col, lab, colr in (("p_mid", "option p_mid", "#0072B2"), ("px", "PM print price", "#D55E00")):
            r = core.reliability(ok[col].values, ok["y"].values)
            ax[1].plot([b["mean_p"] for b in r], [b["freq_y"] for b in r], "o-", label=lab, color=colr)
        ax[1].plot([0, 1], [0, 1], color="0.6", lw=0.8)
        ax[1].set_xlabel("forecast probability")
        ax[1].set_ylabel("share resolving YES")
        ax[1].set_title(f"Calibration over {len(ok)} evaluated prints")
        ax[1].legend(frameon=False)
    for a in ax:
        a.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def summary_md(s: dict, prim: pd.DataFrame) -> str:
    p, sec = s["primary"], s["secondary"]
    lines = [f"# P2 options-anchored Polymarket taker: {p['verdict']}", ""]
    lines.append(f"Verdict: **{p['verdict']}**. Primary rule (tau = 0.05, entry = taker print + 1c, Polymarket fee, hold to "
                 f"settlement): mean net P&L {ci(p)} per $1 contract, 95% day-cluster bootstrap CI (10,000 draws), "
                 f"{p['n']} trades on {p.get('days', 0)} resolution days. Pass rule: lower bound > 0 with >= 100 trades on >= 30 days.")
    lines.append("")
    if p.get("n"):
        mde = p.get("mde_80")
        lines.append(f"Precision: approximate SE {fmt(p.get('se_approx'))} pt, so the MDE at 80% power is about {fmt(mde)} pt. "
                     f"The estimate is {abs(p['mean']) / mde:.1f}x that MDE. "
                     + ("It lands near the MDE, so a significant estimate here is likely to overstate the true edge (type-M); "
                        "if the true edge were 2 pt, a significant estimate would overstate it about 2x."
                        if abs(p["mean"]) < 1.5 * mde else "It is well above the MDE, so the type-M inflation is modest, though "
                        "a selected gap still shrinks out of sample."))
        lines.append("")
    lines += ["## Results", "", "| variant | n trades | days | mean net, pt per $1 | 95% CI (day clusters) |", "|---|---|---|---|---|"]

    def row(name, x, days_key="clusters"):
        if not x or not x.get("n"):
            return f"| {name} | 0 | | | |"
        return f"| {name} | {x['n']} | {x.get(days_key, x.get('days', ''))} | {fmt(x['mean'])} | [{fmt(x['ci_lo'])}, {fmt(x['ci_hi'])}] |"

    lines.append(row("**primary** (tau 0.05, +1c, fee)", p, "days"))
    lines.append(row("secondary: +2c slippage", sec["tick_0.02"]))
    lines.append(row("secondary: no tick", sec["tick_0.00"]))
    lines.append(row("secondary: tau 0.03", sec["tau_0.03"]))
    lines.append(row("secondary: tau 0.10", sec["tau_0.10"]))
    lines.append(row("secondary: gross (no fee, no tick)", sec["gross_no_fee_no_tick"]))
    lines.append(row("secondary: ticker-day clusters", sec["ticker_day_cluster"]))
    lines.append(row("secondary: mid variant (prices-history mid +/- 2.5c)", sec["mid_variant"]))
    ew = sec["equal_weight_per_day"]
    if ew.get("n_days"):
        lines.append(f"| secondary: equal weight per day | | {ew['n_days']} | {fmt(ew['mean'])} | [{fmt(ew['ci_lo'])}, {fmt(ew['ci_hi'])}] |")
    lines += ["", "Secondary rows are pre-registered (METHOD.md section 5) and never change the verdict.", "",
              "## Splits (primary rule)", "", "| split | group | n | days | mean, pt | 95% CI |", "|---|---|---|---|---|---|"]
    for col, d in sec["splits"].items():
        for k, x in d.items():
            lines.append(f"| {col} | {k} | {x['n']} | {x['clusters']} | {fmt(x['mean'])} | [{fmt(x['ci_lo'])}, {fmt(x['ci_hi'])}] |")
    cal = sec.get("calibration")
    if cal:
        lines += ["", "## Signal check", "",
                  f"Over {cal['n_prints']} evaluated prints with a usable spread ({cal['n_markets']} markets), the Brier score of the "
                  f"option p_mid is {cal['brier_option_p_mid']:.4f} against {cal['brier_print_price']:.4f} for the PM print price."]
    cap = sec["capacity"]
    lines += ["", "## Capacity", "",
              f"Taking half of each qualifying print: {cap['shares']:.0f} shares, ${cap['dollars_deployed']:,.0f} deployed and "
              f"${cap['dollars_pnl']:,.0f} net P&L over the whole window (median print size {cap['median_print_size']} shares)."]
    lines += ["", "## Settlement", "",
              f"Unresolved trades dropped: {s['unresolved_trades']}. Primary trades where the Polymarket resolution disagrees with the "
              f"Massive close vs K: {len(s['settlement_disagreements'])} (kept as resolved by Polymarket)."]
    sc = s["scope"]
    lines += ["", "## Scope", "", "```", json.dumps(sc, indent=1), "```", "",
              "## Caveats", "",
              "- Copy-the-taker: being first to the stale quote is assumed; if faster bots already take these quotes, the sign can "
              "survive while our share does not. Capacity is bounded by print sizes.",
              "- Option-mid noise and winner's curse: selecting on the gap shrinks the realised edge out of sample.",
              "- Outcomes on one day share the market move, so the effective sample is closer to the number of days than to the number of trades.",
              "- The fresh window (Jan 20 to Aug 14 2026) differs in regime from the seen lead (Aug to Oct 2026).",
              "", f"Commit {s['commit']}. Requests: {s['requests']}. Files: stats.json, trades.csv, trades_frozen.csv, "
              "prints_evaluated.csv, universe.csv, kill_test.json, chart.png, RUN_LOG.md."]
    return "\n".join(lines) + "\n"
