from __future__ import annotations

import argparse
import hashlib
import io
import math
import subprocess
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from . import config as C

NY = ZoneInfo("America/New_York")
STAT_COLS = ["variant", "split", "group", "n_fills", "days", "markets", "mean_pt", "ci_lo_pt", "ci_hi_pt",
             "day_weight_mean_pt", "day_weight_ci_lo_pt", "day_weight_ci_hi_pt", "contract_weight_mean_pt",
             "contract_weight_ci_lo_pt", "contract_weight_ci_hi_pt", "contracts", "pnl_usd", "capital_usd", "value"]
TRADE_COLS = ["variant", "market_id", "tk", "k", "res_date", "ts", "time_ny", "taker_side", "px", "size", "p_lo", "p_mid",
              "p_hi", "our_side", "quote", "contracts", "y", "pnl_pt", "pnl_usd", "capital_usd", "dose_pt", "dose_bin",
              "p_mid_region", "sample"]


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], capture_output=True, cwd=C.REPO_DIR, check=True).stdout


def load_input() -> tuple[pd.DataFrame, str]:
    blob = git("rev-parse", f"{C.INPUT_COMMIT}:{C.INPUT_PATH}").decode().strip()
    if blob != C.INPUT_BLOB:
        raise SystemExit(f"input blob {blob} is not the registered {C.INPUT_BLOB}")
    raw = git("show", f"{C.INPUT_COMMIT}:{C.INPUT_PATH}")
    return pd.read_csv(io.BytesIO(raw), dtype={"market_id": str}), hashlib.sha256(raw).hexdigest()


def sample(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["status"] == C.STATUS_OK].reset_index(drop=True)


def oos_dates(dates) -> list[str]:
    d = sorted({str(x) for x in dates})
    return d[len(d) - math.ceil(C.OOS_SHARE * len(d)):] if d else []


def quotes(p_lo, p_hi, m: float, tick: float | None = None) -> tuple[np.ndarray, np.ndarray]:
    bid = np.asarray(p_lo, float) - m
    offer = np.asarray(p_hi, float) + m
    if tick:
        offer = np.ceil(offer / tick - 1e-7) * tick
        bid = np.floor(bid / tick + 1e-7) * tick
    lo, hi = C.POST_RANGE
    bid = np.where((bid >= lo - C.EPS) & (bid <= hi + C.EPS), bid, np.nan)
    offer = np.where((offer >= lo - C.EPS) & (offer <= hi + C.EPS), offer, np.nan)
    return bid, offer


def region(p_mid) -> np.ndarray:
    i = np.searchsorted(np.asarray(C.P_MID_EDGES), np.asarray(p_mid, float), side="right")
    return np.asarray(C.P_MID_LABELS, dtype=object)[i]


def dose_bin(dose, m: float) -> np.ndarray:
    edges = np.asarray([k * m for k in C.DOSE_MULTS]) - C.EPS
    i = np.searchsorted(edges, np.asarray(dose, float), side="right")
    return np.asarray(C.DOSE_LABELS, dtype=object)[i]


def fills(ok: pd.DataFrame, m: float, through: float = 0.0, tick: float | None = None, variant: str = "primary",
          at_print: bool = False, oos: list[str] | None = None) -> tuple[pd.DataFrame, dict]:
    d = ok.copy()
    side = d["side"].astype(str).str.upper()
    px = d["px"].astype(float).to_numpy()
    if at_print:
        bid = np.where(side == "SELL", px, np.nan)
        offer = np.where(side == "BUY", px, np.nan)
    else:
        bid, offer = quotes(d["p_lo"], d["p_hi"], m, tick)
    hit_offer = (side == "BUY").to_numpy() & np.isfinite(offer) & (px >= np.nan_to_num(offer) + through - C.EPS)
    hit_bid = (side == "SELL").to_numpy() & np.isfinite(bid) & (px <= np.nan_to_num(bid) - through + C.EPS)
    d["our_side"] = np.where(hit_offer, "offer", np.where(hit_bid, "bid", ""))
    d["quote"] = np.where(hit_offer, offer, np.where(hit_bid, bid, np.nan))
    d = d[hit_offer | hit_bid].copy()
    size = pd.to_numeric(d["size"], errors="coerce")
    y = pd.to_numeric(d["y"], errors="coerce")
    no_size, no_y = ~(size > 0), y.isna()
    info = {"prints_through_quote": int(len(d)), "dropped_no_size": int(no_size.sum()),
            "dropped_no_result": int((no_y & ~no_size).sum())}
    d = d[~no_size & ~no_y].copy()
    y = y[d.index].astype(int)
    if not y.isin([0, 1]).all():
        raise ValueError("y must be 0 or 1")
    sell = (d["our_side"] == "offer").to_numpy()
    q = d["quote"].to_numpy(float)
    d["contracts"] = np.minimum(size[d.index].to_numpy(float), C.QUOTE_SIZE)
    pnl = np.where(sell, q - y.to_numpy(), y.to_numpy() - q)
    d["y"] = y
    d["pnl_pt"] = 100.0 * pnl
    d["pnl_usd"] = pnl * d["contracts"]
    d["capital_usd"] = np.where(sell, 1.0 - q, q) * d["contracts"]
    dose = np.where(sell, d["px"].to_numpy(float) - d["p_hi"].to_numpy(float),
                    d["p_lo"].to_numpy(float) - d["px"].to_numpy(float))
    d["dose_pt"] = 100.0 * dose
    d["dose_bin"] = dose_bin(dose, m) if len(d) and not at_print else ""
    d["p_mid_region"] = region(d["p_mid"]) if len(d) else ""
    d["res_date"] = d["res_date"].astype(str)
    d["sample"] = np.where(d["res_date"].isin(oos or []), "out-of-sample", "in-sample")
    d["time_ny"] = [datetime.fromtimestamp(int(t), NY).strftime("%Y-%m-%d %H:%M:%S") for t in d["ts"]]
    d["taker_side"] = d["side"].astype(str).str.upper()
    d["variant"] = variant
    d = d.sort_values(["res_date", "ts", "market_id"]).reset_index(drop=True)
    return d[TRADE_COLS], info


def cluster_boot(values, clusters, weights=None, draws: int = C.BOOT_DRAWS, seed: int = C.SEED) -> tuple[float, float]:
    v = np.asarray(values, float)
    if len(v) == 0:
        return float("nan"), float("nan")
    w = np.ones_like(v) if weights is None else np.asarray(weights, float)
    keys, inv = np.unique(np.asarray(clusters).astype(str), return_inverse=True)
    s = np.bincount(inv, weights=v * w, minlength=len(keys))
    n = np.bincount(inv, weights=w, minlength=len(keys))
    idx = np.random.default_rng(seed).integers(0, len(keys), size=(draws, len(keys)))
    lo, hi = np.percentile(s[idx].sum(1) / n[idx].sum(1), [2.5, 97.5])
    return float(lo), float(hi)


def day_weight(values, clusters, draws: int = C.BOOT_DRAWS, seed: int = C.SEED) -> tuple[float, float, float]:
    v = np.asarray(values, float)
    if len(v) == 0:
        return float("nan"), float("nan"), float("nan")
    keys, inv = np.unique(np.asarray(clusters).astype(str), return_inverse=True)
    dm = np.bincount(inv, weights=v, minlength=len(keys)) / np.bincount(inv, minlength=len(keys))
    idx = np.random.default_rng(seed).integers(0, len(keys), size=(draws, len(keys)))
    lo, hi = np.percentile(dm[idx].mean(1), [2.5, 97.5])
    return float(dm.mean()), float(lo), float(hi)


def stat_row(f: pd.DataFrame, variant: str, split: str, group: str) -> dict:
    row = {c: "" for c in STAT_COLS}
    row.update(variant=variant, split=split, group=group, n_fills=len(f), days=f["res_date"].nunique(),
               markets=f["market_id"].nunique())
    if not len(f):
        return row
    lo, hi = cluster_boot(f["pnl_pt"], f["res_date"])
    dw, dlo, dhi = day_weight(f["pnl_pt"], f["res_date"])
    clo, chi = cluster_boot(f["pnl_pt"], f["res_date"], weights=f["contracts"])
    row.update(contract_weight_ci_lo_pt=clo, contract_weight_ci_hi_pt=chi, mean_pt=float(f["pnl_pt"].mean()), ci_lo_pt=lo, ci_hi_pt=hi, day_weight_mean_pt=dw,
               day_weight_ci_lo_pt=dlo, day_weight_ci_hi_pt=dhi,
               contract_weight_mean_pt=float(100.0 * f["pnl_usd"].sum() / f["contracts"].sum()),
               contracts=float(f["contracts"].sum()), pnl_usd=float(f["pnl_usd"].sum()),
               capital_usd=float(f["capital_usd"].sum()))
    return row


def stat_block(f: pd.DataFrame, variant: str, full: bool) -> list[dict]:
    rows = [stat_row(f, variant, "all", "all")]
    for s in ("offer", "bid"):
        rows.append(stat_row(f[f["our_side"] == s], variant, "side", s))
    for s in ("in-sample", "out-of-sample"):
        rows.append(stat_row(f[f["sample"] == s], variant, "sample", s))
    if full:
        for tk in sorted(f["tk"].unique()):
            rows.append(stat_row(f[f["tk"] == tk], variant, "ticker", tk))
        for lab in C.P_MID_LABELS:
            rows.append(stat_row(f[f["p_mid_region"] == lab], variant, "p_mid_region", lab))
        for lab in C.DOSE_LABELS:
            rows.append(stat_row(f[f["dose_bin"] == lab], variant, "dose", lab))
        for s in ("offer", "bid"):
            for lab in C.DOSE_LABELS:
                rows.append(stat_row(f[(f["dose_bin"] == lab) & (f["our_side"] == s)], variant, f"dose_{s}", lab))
    return rows


def days_per_year(all_dates: list[str]) -> float:
    span = (date.fromisoformat(all_dates[-1]) - date.fromisoformat(all_dates[0])).days + 1
    return len(all_dates) * 365.25 / span


def book(f: pd.DataFrame, all_dates: list[str]) -> tuple[pd.DataFrame, dict]:
    g = f.groupby("res_date")
    daily = pd.DataFrame({"pnl_usd": g["pnl_usd"].sum(), "capital_usd": g["capital_usd"].sum(),
                          "contracts": g["contracts"].sum(), "n_fills": g.size()}).reindex(all_dates).fillna(0.0)
    daily.index.name = "res_date"
    cum = daily["pnl_usd"].cumsum().to_numpy()
    peak = np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:]
    daily["cum_pnl_usd"] = cum
    daily["drawdown_usd"] = cum - peak
    pnl = daily["pnl_usd"].to_numpy()
    sd = float(np.std(pnl, ddof=1)) if len(pnl) > 1 else float("nan")
    dpy = days_per_year(all_dates)
    bankroll = float(daily["capital_usd"].max())
    months = daily["pnl_usd"].groupby(daily.index.str[:7]).sum()
    best_day = int(np.argmax(pnl))
    ex = np.delete(pnl, best_day)
    sd_ex = float(np.std(ex, ddof=1)) if len(ex) > 1 else float("nan")
    by_mkt = f.groupby("market_id")["pnl_usd"].sum() if len(f) else pd.Series(dtype=float)
    total = float(pnl.sum())
    m = {
        "resolution_dates_in_sample": len(all_dates), "dates_with_fills": int((daily["n_fills"] > 0).sum()),
        "days_per_year": dpy, "total_pnl_usd": total, "total_capital_usd": float(daily["capital_usd"].sum()),
        "return_on_capital": total / float(daily["capital_usd"].sum()) if daily["capital_usd"].sum() else float("nan"),
        "bankroll_usd": bankroll, "sharpe": float(pnl.mean() / sd * math.sqrt(dpy)) if sd and sd > 0 else float("nan"),
        "max_drawdown_usd": float(daily["drawdown_usd"].min()),
        "max_drawdown_share_of_bankroll": float(daily["drawdown_usd"].min() / bankroll) if bankroll else float("nan"),
        "worst_month": str(months.idxmin()), "worst_month_pnl_usd": float(months.min()),
        "worst_month_share_of_bankroll": float(months.min() / bankroll) if bankroll else float("nan"),
        "winning_dates": int((pnl > 0).sum()), "losing_dates": int((pnl < 0).sum()),
        "best_date": all_dates[best_day], "best_date_pnl_usd": float(pnl[best_day]),
        "worst_date": all_dates[int(np.argmin(pnl))], "worst_date_pnl_usd": float(pnl.min()),
        "sharpe_without_best_date": float(ex.mean() / sd_ex * math.sqrt(dpy)) if sd_ex and sd_ex > 0 else float("nan"),
        "best_market_share_of_pnl": float(by_mkt.max() / total) if len(by_mkt) and total else float("nan"),
    }
    return daily.reset_index(), m


def verdict(prim: dict, ins: dict, oos: dict, stress: dict) -> tuple[str, list[tuple[str, bool, str]]]:
    def pos(r):
        return bool(r["n_fills"]) and r["mean_pt"] > 0

    def num(r):
        return f"{r['mean_pt']:+.2f} pt, {r['n_fills']} fills" if r["n_fills"] else "no fills"
    lines = [
        ("1. at least 100 fills", prim["n_fills"] >= C.MIN_FILLS, f"{prim['n_fills']} fills"),
        ("2. fills on at least 30 resolution dates", prim["days"] >= C.MIN_DAYS, f"{prim['days']} dates"),
        ("3. mean above zero, whole sample", pos(prim), num(prim)),
        ("4. 95% interval excludes zero, whole sample", bool(prim["n_fills"]) and prim["ci_lo_pt"] > 0,
         f"[{prim['ci_lo_pt']:+.2f}, {prim['ci_hi_pt']:+.2f}]" if prim["n_fills"] else "no fills"),
        ("5. mean above zero in-sample", pos(ins), num(ins)),
        ("6. mean above zero out-of-sample", pos(oos), num(oos)),
        ("7. mean above zero under the stress", pos(stress), num(stress)),
    ]
    return ("PASS" if all(ok for _, ok, _ in lines) else "FAIL"), lines


SURFACE, INK, INK2, GRID, BLUE, ORANGE = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df", "#2a78d6", "#eb6834"


def _axes(title: str, ylabel: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9, 4.4), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", color=INK, fontsize=11)
    ax.set_ylabel(ylabel, color=INK2, fontsize=9)
    ax.set_xlabel("resolution date", color=INK2, fontsize=9)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=INK2, labelsize=8, length=0)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    return plt, fig, ax


def usd(x: float, sign: bool = True) -> str:
    s = ("+" if x >= 0 else "-") if sign else ("-" if x < 0 else "")
    return f"{s}\\${abs(x):,.0f}"


def charts(daily: pd.DataFrame, daily_stress: pd.DataFrame, bm: dict, out: Path):
    x = pd.to_datetime(daily["res_date"])
    plt, fig, ax = _axes(f"Cumulative P&L of the quoting book, by resolution date (total {usd(bm['total_pnl_usd'])} "
                         f"on {usd(bm['total_capital_usd'], False)} locked)", "cumulative P&L, dollars")
    ax.axhline(0, color=INK2, lw=0.8)
    for d, col, lab in ((daily, BLUE, "primary: quote 5 points outside the band"),
                        (daily_stress, ORANGE, "stress: 7 points, print one cent through")):
        ax.plot(x, d["cum_pnl_usd"], color=col, lw=2, label=lab)
        ax.annotate(usd(d["cum_pnl_usd"].iloc[-1]), (x.iloc[-1], d["cum_pnl_usd"].iloc[-1]),
                    xytext=(6, 0), textcoords="offset points", color=INK, fontsize=8, va="center")
    ax.set_title(ax.get_title(loc="left"), loc="left", color=INK, fontsize=11, pad=26)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK2, loc="lower left", bbox_to_anchor=(0.0, 1.0), ncol=2,
              borderaxespad=0.2)
    fig.tight_layout()
    fig.savefig(out / "equity_curve.png", dpi=150, facecolor=SURFACE)
    plt.close(fig)

    plt, fig, ax = _axes(f"Drawdown of the primary quoting book (largest fall {usd(abs(bm['max_drawdown_usd']), False)})",
                         "fall from the earlier peak, dollars")
    ax.fill_between(x, daily["drawdown_usd"], 0, color=BLUE, alpha=0.25, lw=0)
    ax.plot(x, daily["drawdown_usd"], color=BLUE, lw=2)
    ax.axhline(0, color=INK2, lw=0.8)
    fig.tight_layout()
    fig.savefig(out / "drawdown.png", dpi=150, facecolor=SURFACE)
    plt.close(fig)


def fmt(x, d=2):
    return "" if x == "" or x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:+.{d}f}"


def md_table(rows: list[dict]) -> str:
    out = ["| group | fills | dates | markets | mean, pt | 95% interval | equal weight per day |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        ci = f"[{fmt(r['ci_lo_pt'])}, {fmt(r['ci_hi_pt'])}]" if r["n_fills"] else ""
        dw = f"{fmt(r['day_weight_mean_pt'])} [{fmt(r['day_weight_ci_lo_pt'])}, {fmt(r['day_weight_ci_hi_pt'])}]" if r["n_fills"] else ""
        out.append(f"| {r['variant']} / {r['split']} / {r['group']} | {r['n_fills']} | {r['days']} | {r['markets']} | "
                   f"{fmt(r['mean_pt'])} | {ci} | {dw} |")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(C.RESULTS_DIR))
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    log_lines = []

    def log(msg: str):
        line = f"- {datetime.now(NY):%Y-%m-%d %H:%M:%S} NY: {msg}"
        print(line, flush=True)
        log_lines.append(line)

    head = git("rev-parse", "--short", "HEAD").decode().strip()
    log(f"run starts at commit {head}; no network; input `{C.INPUT_PATH}` at commit {C.INPUT_COMMIT[:7]}")
    df, sha = load_input()
    ok = sample(df)
    if len(df) != C.INPUT_ROWS or len(ok) != C.INPUT_OK_ROWS:
        raise SystemExit(f"row counts {len(df)}/{len(ok)} differ from the registered {C.INPUT_ROWS}/{C.INPUT_OK_ROWS}")
    all_dates = sorted(ok["res_date"].astype(str).unique())
    oos = oos_dates(all_dates)
    log(f"input read: {len(df)} rows, {len(ok)} with status ok, sha256 {sha}; {ok['market_id'].nunique()} markets, "
        f"{len(all_dates)} resolution dates {all_dates[0]} to {all_dates[-1]}; taker sides "
        f"{ok['side'].str.upper().value_counts().to_dict()}")
    log(f"out-of-sample fixed before any fill is computed: the last {len(oos)} of {len(all_dates)} dates, "
        f"{oos[0]} to {oos[-1]}")

    m = C.M_PRIMARY
    specs = [("primary_m5", dict(m=m)), ("m2", dict(m=C.M_VARIANTS[0])), ("m10", dict(m=C.M_VARIANTS[1])),
             ("stress_m7_through_1c", dict(m=m + C.STRESS_WIDEN, through=C.STRESS_THROUGH)),
             ("tick_grid_m5", dict(m=m, tick=C.TICK)), ("benchmark_every_print_at_px", dict(m=0.0, at_print=True))]
    fl, rows = {}, []
    for name, kw in specs:
        f, info = fills(ok, variant=name, oos=oos, **kw)
        fl[name] = f
        log(f"{name}: {len(f)} fills; {info}")
        rows += stat_block(f, name, full=(name == "primary_m5"))
    prim = fl["primary_m5"]
    first = prim.sort_values(["market_id", "ts"]).groupby("market_id", as_index=False).head(1)
    rows += stat_block(first.assign(variant="first_fill_per_market_m5"), "first_fill_per_market_m5", full=False)

    daily, bm = book(prim, all_dates)
    daily_s, bs = book(fl["stress_m7_through_1c"], all_dates)
    for name, mets in (("primary_m5", bm), ("stress_m7_through_1c", bs)):
        for k, v in mets.items():
            r = {c: "" for c in STAT_COLS}
            r.update(variant=name, split="book", group=k, value=v)
            rows.append(r)

    by = {(r["variant"], r["split"], r["group"]): r for r in rows}
    v, lines = verdict(by[("primary_m5", "all", "all")], by[("primary_m5", "sample", "in-sample")],
                       by[("primary_m5", "sample", "out-of-sample")], by[("stress_m7_through_1c", "all", "all")])
    for i, (text, held, numtxt) in enumerate(lines, 1):
        r = {c: "" for c in STAT_COLS}
        r.update(variant="primary_m5", split="pass_rule", group=text, value=f"{'held' if held else 'FAILED'} ({numtxt})")
        rows.append(r)
    r = {c: "" for c in STAT_COLS}
    r.update(variant="primary_m5", split="pass_rule", group="verdict", value=v)
    rows.append(r)

    pd.DataFrame(rows)[STAT_COLS].to_csv(out / "metrics.csv", index=False)
    prim.to_csv(out / "trades.csv", index=False)
    pd.concat([fl[n] for n, _ in specs[1:]]).to_csv(out / "trades_variants.csv", index=False)
    daily.to_csv(out / "daily.csv", index=False)
    charts(daily, daily_s, bm, out)

    capped = int((prim["size"] > C.QUOTE_SIZE).sum())
    cap = [
        "# S22 capacity", "",
        "All figures are for the primary rule (quotes 5 points outside the options band), over the whole five-month window.", "",
        f"- Fills: {len(prim)} on {prim['res_date'].nunique()} resolution dates in {prim['market_id'].nunique()} markets "
        f"({len(prim) / max(prim['res_date'].nunique(), 1):.1f} fills per date that had one).",
        f"- Contracts filled: {prim['contracts'].sum():,.0f} (each fill is the print's size, capped at 100).",
        f"- Filled notional at our quote price: ${(prim['contracts'] * prim['quote']).sum():,.2f}.",
        f"- Cash locked (price for a purchase, 1 minus price for a sale): ${prim['capital_usd'].sum():,.2f} in total; "
        f"the most locked for one resolution date was ${bm['bankroll_usd']:,.2f}.",
        f"- Median print size among the fills: {prim['size'].median():.2f} contracts "
        f"(mean {prim['size'].mean():.2f}, largest {prim['size'].max():,.2f}); {capped} of {len(prim)} prints were larger "
        f"than our 100 and were capped." if len(prim) else "- No fills.",
        f"- Median print size over all 970 evaluated prints: {ok['size'].median():.2f} contracts.",
        f"- Dollar P&L of the book: ${bm['total_pnl_usd']:+,.2f}.", "",
        "This is a ceiling set by what takers printed, and a low one. The file keeps only the first buy and the first sell "
        "print of each market in each clock minute, so true printed volume is somewhat larger than counted here. With our "
        "quote present, takers might have traded more (a better price) or differently; that cannot be read from prints.", ""]
    (out / "capacity.md").write_text("\n".join(cap))

    log(f"verdict on the pre-registered pass rule: {v}; " + "; ".join(f"{t}: {'held' if h else 'FAILED'} ({n})" for t, h, n in lines))
    log(f"book (primary): {({k: (round(x, 4) if isinstance(x, float) else x) for k, x in bm.items()})}")
    log(f"book (stress): {({k: (round(x, 4) if isinstance(x, float) else x) for k, x in bs.items()})}")
    if bm["sharpe"] == bm["sharpe"] and bm["sharpe"] > C.SHARPE_BUG_HUNT:
        log(f"Sharpe {bm['sharpe']:.2f} is above {C.SHARPE_BUG_HUNT}: bug hunt required (METHOD 6)")
    log("files written: metrics.csv, trades.csv, trades_variants.csv, daily.csv, equity_curve.png, drawdown.png, capacity.md")
    with (out / "RUN_LOG.md").open("a") as fh:
        if fh.tell() == 0:
            fh.write("# S22 run log\n\n")
        fh.write("\n".join(log_lines) + "\n")

    print()
    print(md_table([r for r in rows if r["split"] not in ("book", "pass_rule")]))


if __name__ == "__main__":
    main()
