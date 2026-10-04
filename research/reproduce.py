"""Reproduce the headline numbers of note/NOTE.md from committed result files. Offline: no API key, no network.

    make reproduce                         (from the repo root)
    cd research && python reproduce.py     (the same; --no-write checks only and leaves note/TABLES.md and the figures)

One line per claim: MATCH or MISMATCH, the note's value, the value found here, how it was found and the source file.
  RECOMPUTED  from the study's committed trade list or rows, with the study's own functions and seeds where it has them
  READ        from the study's committed stats file (the committed files do not hold what a recomputation needs)
  NO SOURCE   no committed result file holds this number; listed, not checked, and not counted as a match
The note's value is typed here next to a quote from the note; if the quote is no longer in the note the line fails.
Exit status 1 on any MISMATCH. The script also writes note/TABLES.md and, through note_figures.py, note/figures/*.png.
No study is rerun and no result file is changed.
"""
from __future__ import annotations

import argparse
import csv
import json
import socket
import sys
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
R = HERE / "results"
NOTE = REPO / "note" / "NOTE.md"
TABLES = REPO / "note" / "TABLES.md"
for _p in (HERE, HERE / "arb"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


@contextmanager
def no_network():
    def blocked(*a, **k):
        raise RuntimeError("reproduce.py is offline: a network call was attempted")
    saved = {(o, k): getattr(o, k) for o, k in ((socket.socket, "connect"), (socket.socket, "connect_ex"), (socket, "getaddrinfo"), (socket, "create_connection"))}
    try:
        for o, k in saved:
            setattr(o, k, blocked)
        yield
    finally:
        for (o, k), f in saved.items():
            setattr(o, k, f)


def norm(s: str) -> str:
    return " ".join(str(s).replace("−", "-").replace("×", "x").split())


def rel(p: Path) -> str:
    return str(Path(p).resolve().relative_to(REPO))


def truthy(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower().isin(["true", "1", "1.0"])


class Checks:
    def __init__(self) -> None:
        self.note = norm(NOTE.read_text())
        self.rows: list[dict] = []

    def add(self, sec: str, claim: str, note: str, got: str, source, how: str, quote: str | None = None, ok: bool | None = None,
            detail: str = "") -> None:
        q = norm(quote if quote is not None else note)
        if q not in self.note:
            status, got = "MISMATCH", f"{got} (quote not found in the note: \"{q}\")"
        else:
            status = "MATCH" if (norm(note) == norm(got) if ok is None else bool(ok)) else "MISMATCH"
            got = f"{got} ({detail})" if status == "MISMATCH" and detail else got
        src = ", ".join(rel(s) for s in (source if isinstance(source, (list, tuple)) else [source]))
        self.rows.append({"status": status, "sec": sec, "claim": claim, "note": norm(note), "got": norm(got), "how": how, "source": src})

    def nosource(self, sec: str, claim: str, note: str, why: str) -> None:
        self.rows.append({"status": "NO SOURCE", "sec": sec, "claim": claim, "note": norm(note), "got": why, "how": "-", "source": "-"})

    def error(self, sec: str, e: Exception) -> None:
        self.rows.append({"status": "MISMATCH", "sec": sec, "claim": "section failed to run", "note": "-", "got": f"{type(e).__name__}: {e}",
                          "how": "-", "source": "-"})

    def print(self) -> None:
        for r in self.rows:
            print(f"{r['status']:9} | {r['sec']:22} | {r['claim']} | note: {r['note']} | here: {r['got']} | {r['how']} | {r['source']}")
        n = {k: sum(r["status"] == k for r in self.rows) for k in ("MATCH", "MISMATCH", "NO SOURCE")}
        how = {k: sum(r["status"] != "NO SOURCE" and r["how"] == k for r in self.rows) for k in ("RECOMPUTED", "READ")}
        print(f"\n{len(self.rows)} claims: {n['MATCH']} MATCH, {n['MISMATCH']} MISMATCH, {n['NO SOURCE']} NO SOURCE "
              f"({how['RECOMPUTED']} recomputed from trade lists or rows, {how['READ']} read from stats files).")

    @property
    def mismatches(self) -> int:
        return sum(r["status"] == "MISMATCH" for r in self.rows)


def ci(lo: float, hi: float, d: int = 2) -> str:
    return f"[{lo:+.{d}f}, {hi:+.{d}f}]"


REC, READ = "RECOMPUTED", "READ"


def accuracy(c: Checks) -> None:
    from fresh_accuracy import stats as st
    from fresh_accuracy.config import PARAMS

    sec, src = "accuracy", R / "fresh_accuracy" / "rows.csv"

    def scored(path: Path) -> pd.DataFrame:
        df = pd.read_csv(path, low_memory=False)
        d = df[(df.status == "scored") & truthy(df.clean) & (df.pm_mid != PARAMS.placeholder) & df.outcome.isin([0, 1])].copy()
        d["d_B"] = st.brier_diff(d.pm_mid, d.p_mid, d.outcome)
        d["d_L"] = st.log_diff(d.pm_mid, d.p_mid, d.outcome)
        return d

    def boot(d: pd.DataFrame, cluster: str = "res_date") -> dict:
        return st.cluster_boot({"d_B": d.d_B.values, "d_L": d.d_L.values}, d[cluster].values)

    sc = scored(src)
    b = boot(sc)
    B, L = b["d_B"], b["d_L"]
    c.add(sec, "scored rows", "7,111 scored rows", f"{len(sc):,} scored rows", src, REC)
    c.add(sec, "markets", "4,561 Polymarket", f"{sc.market_id.nunique():,} Polymarket", src, REC, quote="from 4,561 Polymarket")
    c.add(sec, "markets (summary)", "4,561 fresh Polymarket stock markets", f"{sc.market_id.nunique():,} fresh Polymarket stock markets", src, REC)
    c.add(sec, "resolution dates", "89 resolution dates", f"{sc.res_date.nunique()} resolution dates", src, REC)
    c.add(sec, "Brier: Polymarket, options", "0.0938 | 0.0831", f"{((sc.pm_mid - sc.outcome) ** 2).mean():.4f} | "
          f"{((sc.p_mid.clip(0, 1) - sc.outcome) ** 2).mean():.4f}", src, REC, quote="| Brier | 0.0938 | 0.0831 |")
    c.add(sec, "Brier difference, 95% date-cluster CI", "+0.0108 [+0.0064, +0.0158]", f"{B['mean']:+.4f} {ci(*B['ci95'], d=4)}", src, REC)
    c.add(sec, "Brier difference (summary)", "Brier difference +0.0108, 95% CI +0.0064 to +0.0158",
          f"Brier difference {B['mean']:+.4f}, 95% CI {B['ci95'][0]:+.4f} to {B['ci95'][1]:+.4f}", src, REC)
    c.add(sec, "log score: Polymarket, options", "0.3044 | 0.2726", f"{st.log_score(sc.pm_mid, sc.outcome).mean():.4f} | "
          f"{st.log_score(sc.p_mid.clip(0, 1), sc.outcome).mean():.4f}", src, REC, quote="| Log score | 0.3044 | 0.2726 |")
    c.add(sec, "log score difference, 95% CI", "+0.0318 [+0.0170, +0.0471]", f"{L['mean']:+.4f} {ci(*L['ci95'], d=4)}", src, REC)

    subs = {"daily": sc[sc.kind == "daily"], "weekly": sc[sc.kind == "weekly"], "S1": sc[sc.snapshot == "S1"], "S2": sc[sc.snapshot == "S2"]}
    los = {k: boot(v) for k, v in subs.items()}
    low = min([x[k]["ci95"][0] for x in los.values() for k in ("d_B", "d_L")] + [B["cw_ci95"][0], L["cw_ci95"][0]])
    c.add(sec, "holds on daily, weekly, both snapshots, equal weight per date", "holds (every interval above 0)",
          f"lowest lower bound of the 10 intervals {low:+.4f}", src, REC,
          quote="holds on daily and weekly markets, at both snapshots, with equal weight per date", ok=low > 0)

    by_date = sc.groupby("res_date").d_B.sum().sort_values(ascending=False)
    t5 = boot(sc[~sc.res_date.isin(by_date.index[:5])])["d_B"]
    c.add(sec, "Brier difference without the five most influential dates (the five largest date sums; rule not in any committed file)",
          "+0.0064 [+0.0036, +0.0093]", f"{t5['mean']:+.4f} {ci(*t5['ci95'], d=4)}", src, REC)
    sym = boot(sc[sc.p_mid.between(0.02, 0.98)])["d_B"]
    c.add(sec, "Brier difference with a symmetric price filter (options also in [0.02, 0.98]; rule not in any committed file)",
          "+0.0077 [+0.0038, +0.0125]", f"{sym['mean']:+.4f} {ci(*sym['ci95'], d=4)}", src, REC,
          detail=f"{int(sc.p_mid.between(0.02, 0.98).sum()):,} rows; the study's bootstrap, {PARAMS.draws:,} draws, seed {PARAMS.seed}")
    age = float(sc.pm_age_s.mean())
    c.add(sec, "age of the Polymarket price at the snapshot, mean seconds", "about 47 seconds",
          f"about {age:.0f} seconds (option quote: {sc.opt_quote_age_s.mean():.0f}; difference {age - sc.opt_quote_age_s.mean():.0f})", src, REC,
          ok=round(age) == 47)
    young = sc[sc.pm_age_s <= 30]
    yb = boot(young)["d_B"]
    c.add(sec, "rows with a Polymarket price 30 seconds old or less", "(669 rows)",
          f"({len(young)} rows) at 30 s or less; {int((sc.pm_age_s < 30).sum())} strictly under 30 s", src, REC, ok=len(young) == 669)
    c.add(sec, "on those rows the gap is not significant", "the gap is not significant", f"{yb['mean']:+.4f} {ci(*yb['ci95'], d=4)}", src, REC,
          ok=yb["ci95"][0] <= 0 <= yb["ci95"][1])
    enc = st.logit_cluster(np.column_stack([st.logit(sc.p_mid), st.logit(sc.pm_mid)]), sc.outcome.values, sc.res_date.values)
    c.add(sec, "encompassing logit", "options +0.85 [+0.63, +1.07], Polymarket +0.30 [+0.15, +0.45]",
          f"options {enc['coef'][1]:+.2f} {ci(*enc['ci95'][1])}, Polymarket {enc['coef'][2]:+.2f} {ci(*enc['ci95'][2])}", src, REC)
    fl = st.ols_cluster(sc.p_mid - 0.5, sc.pm_mid - sc.p_mid, sc.res_date.values)
    c.add(sec, "slope of Polymarket minus options on options minus 0.5", "slope -0.105 [-0.133, -0.076]",
          f"slope {fl['coef'][1]:+.3f} {ci(*fl['ci95'][1], d=3)}", src, REC, detail=f"unrounded {fl['coef'][1]:+.5f} {ci(*fl['ci95'][1], d=5)}")

    ksrc = R / "fresh_accuracy" / "kalshi_rows.csv"
    kb = boot(scored(ksrc))["d_B"]
    c.add(sec, "Kalshi index markets against options: equivalence margin", "±0.003 Brier margin", f"±{PARAMS.tost_margin:.3f} Brier margin",
          HERE / "fresh_accuracy" / "config.py", READ)
    c.add(sec, "Kalshi minus options, Brier, 90% CI", "90% CI +0.0001 to +0.0025", f"90% CI {kb['ci90'][0]:+.4f} to {kb['ci90'][1]:+.4f}", ksrc, REC)


def s11(c: Checks) -> None:
    from s11_bundles import config as cfg
    from s11_bundles.run import boot, perf

    sec, src = "S11", R / "s11_bundles" / "trades.csv"
    T = pd.read_csv(src, low_memory=False)
    v = T[T.study == "violation"]
    v1 = v[v.cost_mult == 1.0]
    ver1, ver2 = v1[v1.prints == "verified"], v[(v.cost_mult == 2.0) & (v.prints == "verified")]
    m, lo, hi, n, nd = boot(ver1.assign(_p=ver1.pnl_close * 100), "_p")
    c.add(sec, "print-verified violations", "99 violations", f"{n} violations", src, REC)
    c.add(sec, "net points per trade, 1x costs", "+3.89 points per trade at 1x costs (95% interval over dates +2.49 to +5.43, 71 dates)",
          f"{m:+.2f} points per trade at 1x costs (95% interval over dates {lo:+.2f} to {hi:+.2f}, {nd} dates)", src, REC)
    m2 = boot(ver2.assign(_p=ver2.pnl_close * 100), "_p")[0]
    c.add(sec, "net points per trade, 2x costs", "+4.34 at 2x costs", f"{m2:+.2f} at 2x costs", src, REC)
    c.add(sec, "violations a mid-price backtest would trade", "Of 1,425 violations", f"Of {len(v1):,} violations", src, REC)
    c.add(sec, "of those, no print at that price", "965 had no print", f"{int((v1.prints == 'not verified').sum())} had no print", src, REC)
    c.add(sec, "out-of-sample trades", "Out of sample there were 11 trades", f"Out of sample there were {int((ver1.segment == 'OOS').sum())} trades", src, REC)
    pf = perf(ver1.assign(_pnl=ver1.pnl_close * cfg.CONTRACTS, _cap=ver1.capital * cfg.CONTRACTS), "_pnl", "_cap")
    c.add(sec, "dollars a year at 100 contracts a leg", "about $385 a year", f"about ${pf['net_pnl']:,.0f} a year", src, REC)


LADDER = R / "ladder_replay"
RULES = {"registered": LADDER / "trades_fresh.csv", "year-checked": LADDER / "order_check" / "trades_fresh.csv"}
_NUM = ("t_entry", "edge", "print_size", "size", "fill_rich", "fill_cheap", "fee_rich", "fee_cheap", "capital_per", "payoff", "lock_end",
        "lock_days", "pnl_points", "pnl_usd", "capital_usd", "pnl_usd_uncapped")


def ladder_trades(path: Path) -> list[dict]:
    rows = []
    with path.open(newline="") as f:
        for r in csv.DictReader(f):
            for k in _NUM:
                r[k] = float(r[k])
            r["settled"] = r["settled"] == "True"
            rows.append(r)
    return rows


def split(rows: list[dict], seg: str) -> list[dict]:
    from ladder_replay import config as cfg
    if seg == "all":
        return rows
    return [r for r in rows if (r["date"] < cfg.S11_OOS_START) == (seg == "in")]


def monthly_returns(rows: list[dict]) -> tuple[list[str], np.ndarray]:
    from ladder_replay.replay import NY
    months: dict[str, list[float]] = {}
    for r in rows:
        x = months.setdefault(datetime.fromtimestamp(r["lock_end"], NY).strftime("%Y-%m"), [0.0, 0.0])
        x[0] += r["pnl_usd"]
        x[1] += r["capital_usd"]
    ks = sorted(months)
    keys, vals, y, mo = [], [], int(ks[0][:4]), int(ks[0][5:])
    while f"{y:04d}-{mo:02d}" <= ks[-1]:
        k = f"{y:04d}-{mo:02d}"
        keys.append(k)
        vals.append(months[k][0] / months[k][1] if k in months and months[k][1] > 0 else 0.0)
        y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
    return keys, np.array(vals)


def window_days(seg: str) -> int:
    from ladder_replay import config as cfg
    a, b, s = (date.fromisoformat(x) for x in (cfg.WINDOW_START, cfg.WINDOW_END, cfg.S11_OOS_START))
    return {"all": (b - a).days, "in": (s - a).days, "out": (b - s).days}[seg]


def book(rows: list[dict], seg: str) -> dict:
    from ladder_replay.replay import metrics
    m = metrics(rows)
    keys, mr = monthly_returns(rows)
    sd = float(mr.std(ddof=1)) if len(mr) > 2 else float("nan")
    sharpe = float(mr.mean() / sd * np.sqrt(12)) if sd and sd > 0 else float("nan")
    same_nan = sharpe != sharpe and m["sharpe_monthly"] != m["sharpe_monthly"]
    assert same_nan or abs(sharpe - m["sharpe_monthly"]) < 1e-9, "monthly series differs from replay.metrics"
    days = window_days(seg)
    m.update(vol_ann=sd * np.sqrt(12), worst_month=float(mr.min()), worst_month_key=keys[int(mr.argmin())], window_days=days,
             first_month=keys[0], last_month=keys[-1],
             turnover=m["capital_usd"] / m["peak_capital_locked"] / (days / 365), locked_at_entry_usd=sum(r["size"] * r["edge"] for r in rows))
    rk, rr = monthly_returns([r for r in rows if r["settled"]])
    rsd = float(rr.std(ddof=1)) if len(rr) > 2 else float("nan")
    m.update(res_months=len(rr), res_last_month=rk[-1], res_vol_ann=rsd * np.sqrt(12), res_worst_month=float(rr.min()),
             res_worst_month_key=rk[int(rr.argmin())], res_sharpe=float(rr.mean() / rsd * np.sqrt(12)) if rsd and rsd > 0 else float("nan"))
    return m


def ladder(c: Checks) -> dict:
    sec = "ladder replay"
    sc = pd.read_csv(LADDER / "settlement_check.csv")
    fr = sc[sc.universe == "fresh"]
    c.add(sec, "fresh pairs with the same event definition and source", "680 of 861 fresh pairs", f"{int(truthy(fr.nested).sum())} of {len(fr)} fresh pairs",
          LADDER / "settlement_check.csv", REC)
    with (LADDER / "manual_sample.csv").open(newline="") as f:
        n_hand = sum(1 for _ in csv.DictReader(f))
    c.add(sec, "pairs drawn for the hand check", "a hand check of 20 random pairs", f"a hand check of {n_hand} random pairs", LADDER / "manual_sample.csv", READ)

    books = {(rule, seg): book(split(ladder_trades(p), seg), seg) for rule, p in RULES.items() for seg in ("all", "in", "out")}
    reg, yc, out = books["registered", "all"], books["year-checked", "all"], books["year-checked", "out"]

    def row(m: dict) -> str:
        return f"{m['trades']} / {m['dates']} | {m['pnl_points_mean']:+.2f} {ci(m['ci_lo'], m['ci_hi'])} | {m['losers']}"

    c.add(sec, "rule as registered: trades / dates | net points, 95% date CI | losing trades", "650 / 221 | +2.47 [-1.14, +6.26] | 74", row(reg),
          RULES["registered"], REC)
    c.add(sec, "year-checked: trades / dates | net points, 95% date CI | losing trades", "562 / 211 | +8.82 [+6.73, +11.13] | 0", row(yc),
          RULES["year-checked"], REC)
    c.add(sec, "year-checked, from 22 July 2026: trades | net points, 95% date CI | losing trades", "102 | +9.20 [+4.86, +14.01] | 0",
          f"{out['trades']} | {out['pnl_points_mean']:+.2f} {ci(out['ci_lo'], out['ci_hi'])} | {out['losers']}", RULES["year-checked"], REC)
    c.add(sec, "year-checked (summary)", "+8.82 points per trade [+6.73, +11.13], 562 trades",
          f"{yc['pnl_points_mean']:+.2f} points per trade {ci(yc['ci_lo'], yc['ci_hi'])}, {yc['trades']} trades", RULES["year-checked"], REC)

    t_reg, t_yc = ladder_trades(RULES["registered"]), ladder_trades(RULES["year-checked"])
    lose = [r for r in t_reg if r["pnl_usd"] < -1e-9]
    c.add(sec, "ladders holding the registered rule's losing trades", "All 74 losing trades came from 3 ladders",
          f"All {len(lose)} losing trades came from {len({r['event'] for r in lose})} ladders", RULES["registered"], REC)
    both = [r for r in t_yc if r["payoff"] == 2.0]
    c.add(sec, "trades where both legs paid", "30 trades where the event fell between the two dates", f"{len(both)} trades where the event fell between the two dates",
          RULES["year-checked"], REC)
    c.add(sec, "median edge locked in at entry", "the median edge locked in at entry is 1.6 points",
          f"the median edge locked in at entry is {100 * float(np.median([r['edge'] for r in t_yc])):.1f} points", RULES["year-checked"], REC)
    rest = float(np.mean([r["pnl_points"] for r in t_yc if r["payoff"] != 2.0]))
    c.add(sec, "mean without those trades", "without those 30 trades the mean is 3.4 points", f"without those {len(both)} trades the mean is {rest:.1f} points",
          RULES["year-checked"], REC)
    c.add(sec, "return on capital, Sharpe on monthly returns, drawdown", "earned 8.5% on capital, with a Sharpe of 4.2 on monthly returns and no drawdown",
          f"earned {100 * yc['cap_weighted_return']:.1f}% on capital, with a Sharpe of {yc['sharpe_monthly']:.1f} on monthly returns and "
          f"{'no drawdown' if yc['max_dd_usd'] == 0 else 'a drawdown of $%.0f' % yc['max_dd_usd']}", RULES["year-checked"], REC)

    lp = pd.read_csv(LADDER / "live_pairs.csv")
    lb = lp[truthy(lp.has_books)]
    lt = json.loads((LADDER / "live_totals.json").read_text())
    t_ny = pd.Timestamp(lt["snapshot_utc"]).tz_convert("America/New_York")
    c.add(sec, "live sweep: date ladders and time", "34 live date ladders at 01:57 ET", f"{lt['date_ladders']} live date ladders at {t_ny:%H:%M} ET",
          LADDER / "live_totals.json", READ)
    c.add(sec, "live sweep: violations after fees", "found 0 violations after fees", f"found {int((lb.edge_top > 0).sum())} violations after fees",
          LADDER / "live_pairs.csv", REC)
    gaps = sorted(-100 * lb.edge_top)
    c.add(sec, "live sweep: median distance from an arbitrage (live.py's rule: the upper of the two middle pairs)",
          "the median pair was 10.5 points from an arbitrage", f"the median pair was {gaps[len(gaps) // 2]:.1f} points from an arbitrage",
          LADDER / "live_pairs.csv", REC, detail=f"the average of the two middle pairs is {float(np.median(gaps)):.1f}")

    s11p = book(ladder_trades(LADDER / "order_check" / "trades_s11.csv"), "all")
    both_files = [RULES["year-checked"], LADDER / "order_check" / "trades_s11.csv"]
    c.add(sec, "capacity: fresh sample, dollars a year at the 100-contract cap", "about $1,480 a year", f"about ${yc['pnl_usd']:,.0f} a year",
          RULES["year-checked"], REC)
    c.add(sec, "capacity: of it locked in at entry", "$530 of it locked in at entry", f"${yc['locked_at_entry_usd']:,.0f} of it locked in at entry",
          RULES["year-checked"], REC)
    c.add(sec, "capacity: peak capital (nearest $100)", "peak capital near $3,000", f"peak capital ${yc['peak_capital_locked']:,.0f}", RULES["year-checked"], REC,
          ok=round(yc["peak_capital_locked"], -2) == 3000)
    c.add(sec, "capacity: median trade, fresh and seen pairs", "the median trade was 19 to 25 contracts",
          f"the median trade was {yc['median_size']:.0f} to {s11p['median_size']:.0f} contracts", both_files, REC)
    tot = yc["pnl_usd"] + s11p["pnl_usd"]
    c.add(sec, "capacity: fresh plus seen pairs (nearest $100)", "about $3,300 a year", f"${tot:,.0f} a year", both_files, REC, ok=round(tot, -2) == 3300)
    return books


def s21(c: Checks) -> None:
    from s21_options_anchor import config as cfg
    from s21_options_anchor import run as s21run
    from s21_options_anchor.checks import placebo
    from s7_weekend_straddle.run import boot_diff, boot_mean

    sec = "S21"
    res, s18 = R / "s21_options_anchor", R / "s18_price_market_calibration"
    src = [res / "anchors.csv", s18 / "prints_markets.csv"]
    a = pd.read_csv(res / "anchors.csv", dtype={"market": str})
    pm = pd.read_csv(s18 / "prints_markets.csv")
    pm = pm[pm.asset_class.isin(cfg.ASSET_CLASSES)].copy()
    pm["market"] = pm.market.astype(str)
    keep = ["market", "status", "ticker", "level", "direction", "end_session", "anchor_day", "expiry", "days_expiry_after_end", "k_lo", "k_hi",
            "zero_bid_leg", "stepped", "p_lo", "p_mid", "p_hi", "anchor_lower", "anchor_central", "central_lo", "central_hi"]
    d_all = pm.merge(a[keep], on="market", how="left")
    d_all["status"] = d_all.status.fillna("dropped in parsing")
    d_all["zero_bid_leg"] = truthy(d_all.zero_bid_leg)
    d = d_all[d_all.status == "ok"].copy()

    buckets, _ = s21run.t1(d, "central")
    top = next(r for r in buckets if r["gap_bucket"] == "+10 or more")
    c.add(sec, "buyers 10 or more points above the reference", "lost 29.8 points per contract [-40.1, -18.3] (53 markets, 29 events)",
          f"lost {-top['buyers_pnl_points']:.1f} points per contract {ci(top['ci_lo'], top['ci_hi'], d=1)} ({top['markets']} markets, {top['events']} events)",
          src, REC)
    sets = s21run.book_sets(d_all)
    taken, left = sets[cfg.PRIMARY][1], sets["U-left"][1]
    t = boot_mean(s21run.by_event(taken, "sell_pnl_points"))
    c.add(sec, "selling tickets 5 or more points above the reference", "earned +22.3 points [+10.3, +33.1] on 60 markets in 33 events",
          f"earned {t[0]:+.1f} points {ci(t[1], t[2], d=1)} on {len(taken)} markets in {taken.event.nunique()} events", src, REC,
          detail=f"unrounded {t[0]:+.4f} {ci(t[1], t[2], d=4)}")
    le = boot_mean(s21run.by_event(left, "sell_pnl_points"))
    c.add(sec, "the tickets it left", "against +3.1 [-1.5, +7.9] on the tickets it left", f"against {le[0]:+.1f} {ci(le[1], le[2], d=1)} on the tickets it left",
          src, REC)
    df = boot_diff(s21run.by_event(taken, "sell_pnl_points"), s21run.by_event(left, "sell_pnl_points"))
    c.add(sec, "taken minus left", "taken minus left +19.2 [+5.8, +31.5]", f"taken minus left {df[0]:+.1f} {ci(df[1], df[2], d=1)}", src, REC)
    s = d[d.sell_pnl_points.notna()]
    prim = next(b for b in cfg.BOOKS if b.id == cfg.PRIMARY)
    p = placebo(s.sell_price.to_numpy(), s.anchor_central.to_numpy(), s.sell_pnl_points.to_numpy(), prim.threshold)
    c.add(sec, "anchors shuffled across markets", "no anchor-shuffle reached that gap",
          f"{p['share_at_least_observed'] * p['draws']:.0f} of {p['draws']} shuffles reached it", src, REC, ok=p["share_at_least_observed"] == 0)
    c.add(sec, "markets out of sample", "only 2 markets were out of sample", f"only {int((taken.segment == 'OOS').sum())} markets were out of sample", src, REC)


def touch(c: Checks) -> None:
    from s21_options_anchor import engine as eg
    from s7_weekend_straddle.run import boot_mean
    from touch_fresh import config as cfg

    sec, src = "touch fresh", R / "touch_fresh" / "markets.csv"
    d = pd.read_csv(src)
    for k in ("in_band", "B0", "strict"):
        d[k] = truthy(d[k])
    strict = d[d.strict]
    c.add(sec, "fresh markets under S21's rules", "only 32 fresh markets in 4 events", f"only {len(strict)} fresh markets in {strict.event.nunique()} events", src, REC)
    c.add(sec, "pre-set minimum", "below the pre-set 30 markets in 15 events", f"below the pre-set {cfg.MIN_MARKETS} markets in {cfg.MIN_EVENTS} events",
          HERE / "touch_fresh" / "config.py", READ, ok=(len(strict) >= cfg.MIN_MARKETS, strict.event.nunique() < cfg.MIN_EVENTS) == (True, True)
          and (cfg.MIN_MARKETS, cfg.MIN_EVENTS) == (30, 15))
    c.add(sec, "secondary sample", "(142 markets, 85 events)", f"({len(d)} markets, {d.event.nunique()} events)", src, REC)
    base = d[d.status.eq("ok") & d.sell_prints.fillna(0).gt(0) & d.in_band & d.outcome.notna()]

    def stat(s: pd.DataFrame, col: str) -> tuple[float, float, float, int]:
        s = s[s[col].notna()]
        return (*boot_mean({str(e): list(v) for e, v in s.groupby("event")[col]}), len(s))

    b0 = stat(base[base.B0], "sell_pnl")
    c.add(sec, "markets that met the sell rule", "only 7 markets met the sell rule: -15.4 points per contract [-48.8, +21.8]",
          f"only {b0[3]} markets met the sell rule: {b0[0]:+.1f} points per contract {ci(b0[1], b0[2], d=1)}", src, REC)
    u = stat(base, "sell_pnl")
    c.add(sec, "unfiltered seller book", "the unfiltered seller book at -2.6 [-19.0, +11.5]", f"the unfiltered seller book at {u[0]:+.1f} {ci(u[1], u[2], d=1)}", src, REC)
    h = stat(base, "hedged_pnl")
    c.add(sec, "delta-hedged unfiltered book", "A delta-hedged unfiltered book earned +10.5 [-0.1, +20.0]",
          f"A delta-hedged unfiltered book earned {h[0]:+.1f} {ci(h[1], h[2], d=1)}", src, REC)
    s = base[base.move_dir.notna() & base.sell_pnl.notna()]
    b, _ = eg.ols_cluster(s.sell_pnl.to_numpy(), s.move_dir.to_numpy()[:, None] * 100, s.event.to_numpy())
    c.add(sec, "seller P&L per 1% move toward the level", "seller returns fell 2.3 points for each 1%", f"seller returns fell {-b[1]:.1f} points for each 1%", src, REC)


def failed(c: Checks) -> None:
    sec = "what failed"
    oos, ins = R / "oos", R / "in_sample"
    h2 = pd.read_csv(oos / "opportunity_pass_check.csv").set_index("horizon").loc["21"]
    c.add(sec, "8-K study, out of sample, H2 at the 21-session horizon", "H2 -0.021 [-0.076, +0.020]",
          f"H2 {h2.pnl_difference:+.3f} {ci(h2.ci_lo, h2.ci_hi, d=3)}", oos / "opportunity_pass_check.csv", READ,
          detail=f"unrounded {h2.pnl_difference:+.5f} {ci(h2.ci_lo, h2.ci_hi, d=5)}")
    v_in = {(ins / f"{k}_verdict.txt").read_text().strip() for k in ("hedge", "opportunity")}
    c.add(sec, "8-K study, in-sample verdicts", "NULL in-sample", f"{'/'.join(sorted(v_in))} in-sample", [ins / "hedge_verdict.txt", ins / "opportunity_verdict.txt"], READ)
    h1 = pd.read_csv(oos / "hedge_pass_check.csv")
    c.add(sec, "8-K study, out of sample, H1 events", "out of sample H1 3 events", f"out of sample H1 {int(h1.n_events.max())} events",
          oos / "hedge_pass_check.csv", READ)
    cmp_ = pd.read_csv(oos / "opportunity_in_sample_vs_oos.csv")
    k = cmp_[cmp_.edge_oos.notna()]
    c.add(sec, "8-K study, H2 sign in sample against out of sample", "H2 sign reversed",
          f"in sample {', '.join(f'{x:+.4f}' for x in k.edge_in_sample)}; out of sample {', '.join(f'{x:+.4f}' for x in k.edge_oos)}",
          oos / "opportunity_in_sample_vs_oos.csv", READ, ok=bool(((k.edge_in_sample > 0) & (k.edge_oos < 0)).all()))

    import leadlag_replication.analysis as la
    src = R / "leadlag_replication" / "results.csv"
    rows = pd.read_csv(src)
    u = la.usable(rows)
    s1 = la._s1(u, "gap_spy_bp")
    c.add(sec, "overnight relation on new markets: slope and date-permutation p", "10 new markets +0.63 bp per pp (p = 0.126)",
          f"{rows.market.nunique()} new markets {s1['b']:+.2f} bp per pp (p = {s1['p_perm']:.3f})", src, REC)
    c.add(sec, "overnight relation on new markets: verdict", "did not replicate", la.verdict(s1)[0].replace("does not replicate", "did not replicate"), src, REC)
    orig = pd.read_csv(R / "pm_vs_premarket" / "rows_primary.csv")
    c.add(sec, "closures in the original panel", "(380 closures)", f"({len(orig)} closures)", R / "pm_vs_premarket" / "rows_primary.csv", REC)

    import macro_panel.analysis as ma
    src = R / "macro_panel" / "results.csv"
    rows = pd.read_csv(src)
    p = ma.primary(ma.usable(rows))
    c.add(sec, "macro panel: slope, clustered CI, date-permutation p", "+0.81 [-0.14, +1.76], perm p = 0.053",
          f"{p['b']:+.2f} {ci(*p['ci'])}, perm p = {p['p_perm']:.3f}", src, REC)
    c.add(sec, "macro panel: markets and verdict", "36 rule-selected US macro markets | does not hold", f"{rows.market.nunique()} rule-selected US macro markets | {ma.verdict(p)[0]}",
          src, REC, quote="Same, on 36 rule-selected US macro markets | does not hold")

    import pm_vs_premarket.stats as ps
    q = orig[np.isfinite(orig.g) & np.isfinite(orig.b_0800) & np.isfinite(orig.x_0800)]
    o = ps.ols_cluster(q.g.values, np.column_stack([np.ones(len(q)), q.b_0800.values, q.x_0800.values]), q.closure.astype(str).values)
    cc, se = float(o["beta"][2]), float(o["se"][2])
    c.add(sec, "Polymarket beyond the 08:00 pre-market SPY move", "08:00: -0.60 bp per pp [-2.64, +1.44]",
          f"08:00: {cc:+.2f} bp per pp {ci(cc - 1.96 * se, cc + 1.96 * se)}", R / "pm_vs_premarket" / "rows_primary.csv", REC)
    tj = json.loads((R / "pm_vs_premarket" / "tests.json").read_text())
    c.add(sec, "Polymarket beyond pre-market SPY: verdict", "no", tj["verdict"], R / "pm_vs_premarket" / "tests.json", READ,
          quote="Polymarket adds information beyond pre-market SPY | no |", ok=tj["verdict"].startswith("no evidence"))

    import reopen_taker.config as RC
    import reopen_taker.core as rc
    src = R / "reopen_taker" / "trades.csv"
    td = pd.read_csv(src)
    pr = td[td.tau == RC.TAU]
    s = rc.summarize(pr.pnl_t1, pr.closure)
    c.add(sec, "trade toward options at weekend reopenings", "NULL | -0.40 pt [-4.68, +3.74], 402 trades",
          f"{rc.verdict(s['n'], s['clusters'], s['lo'], s['hi'])} | {100 * s['mean']:+.2f} pt {ci(100 * s['lo'], 100 * s['hi'])}, {s['n']} trades", src, REC)
    c.add("foundation", "median Polymarket trade size (taker prints at those reopenings)", "a median trade of about 20 shares",
          f"a median trade of about {pr['size'].median():.0f} shares", src, REC)

    import pm_taker_v2.config as V2
    src = R / "pm_taker_v2" / "trades.csv"
    n = int((pd.read_csv(src).tau == V2.TAU).sum())
    c.add(sec, "all weekdays, fresh 2026 window", "insufficient trades | 40 of 100 required", f"insufficient trades | {n} of {V2.MIN_TRADES} required", src, REC,
          ok=(n, V2.MIN_TRADES) == (40, 100) and json.loads((R / "pm_taker_v2" / "stats.json").read_text())["verdict"] == "INSUFFICIENT")

    src = R / "strategy_backtest" / "daily.csv"
    d = pd.read_csv(src)
    is_, out = d[d.segment == "IS"], d[d.segment == "OOS"]

    def sharpe(col: str) -> float:
        r = d[col].pct_change()[d.segment == "IS"]
        return float(r.mean() / r.std(ddof=1) * np.sqrt(252))

    c.add(sec, "closed-market overlay on a long SPY book", "in sample -$7,318, Sharpe 1.148 vs 1.151; no out-of-sample trade",
          f"in sample -${-is_.primary_hedge_net_1x.sum():,.0f}, Sharpe {sharpe('primary_1x'):.3f} vs {sharpe('bh'):.3f}; "
          f"{'no' if int((out.primary_f != 0).sum()) == 0 else int((out.primary_f != 0).sum())} out-of-sample trade", src, REC)

    src = R / "WEEKEND_SCORECARD.md"
    verdicts = [ln.split("|")[-2].strip() for ln in src.read_text().splitlines() if ln.startswith("| **S")]
    bad = ("not a pass", "null", "too few", "no trade", "does not replicate")
    fail_n = sum(any(b in v.lower() for b in bad) for v in verdicts)
    c.add(sec, "weekend and cross-venue studies: none passes its own rule", "none passes its own rule", f"{fail_n} of {len(verdicts)} scorecard rows carry a failing verdict",
          src, READ, ok=fail_n == len(verdicts) and len(verdicts) > 0)
    studies = sorted({int(p.name.split("_")[0][1:]) for p in R.iterdir() if p.is_dir() and p.name[0] == "s" and p.name.split("_")[0][1:].isdigit()})
    in_card = sorted({int(v.split("**S")[1].split(" ")[0]) for v in src.read_text().splitlines() if v.startswith("| **S")})
    c.add(sec, "weekend and cross-venue studies: how many", "14 weekend and cross-venue strategies scored",
          f"{len(studies)} study numbers have a results folder ({', '.join(f'S{i}' for i in range(1, 24) if i not in studies)} have none); the scorecard holds "
          f"{len(in_card)} of them", [src, R], READ, ok=len(in_card) == 14)


def unsourced(c: Checks) -> None:
    why = "no committed result file under research/results holds it"
    c.nosource("system", "live recorder latency", "39 µs at the median and 3.9 ms at p99 (58,610 decisions; the C++ call itself is 158 ns", why)
    c.nosource("system", "library size", "17 families, 1,386 presets", "stated in README.md and docs/design.md; not a research result, not checked here")
    c.nosource("ladder replay", "outcome of the hand check", "found no pair wrongly called nested", "a judgement recorded in results/ladder_replay/manual_check.md; code cannot recompute it")
    c.nosource("what failed", "number of tests run", "about 40 tests", "no committed file counts the tests")


def tables(books: dict) -> str:
    from ladder_replay import config as cfg
    cols = [(r, s) for r in ("registered", "year-checked") for s in ("in", "out", "all")]
    seg_name = {"in": "in-sample", "out": "out-of-sample", "all": "whole sample"}
    head = "| | " + " | ".join(f"{'Rule as registered' if r == 'registered' else 'Year-checked'}, {seg_name[s]}" for r, s in cols) + " |"

    def usd(x: float) -> str:
        return f"${x:,.0f}" if x >= 0 else f"-${-x:,.0f}"

    def pct(x: float, d: int = 1) -> str:
        return "n/a" if x != x else f"{100 * x:.{d}f}%"

    lines = [
        ("Trades", lambda m: f"{m['trades']}"),
        ("Entry dates (New York)", lambda m: f"{m['dates']}"),
        ("Net points per trade", lambda m: f"{m['pnl_points_mean']:+.2f}"),
        ("95% interval (dates resampled)", lambda m: ci(m["ci_lo"], m["ci_hi"])),
        ("Losing trades", lambda m: f"{m['losers']}"),
        ("Total dollars, net", lambda m: usd(m["pnl_usd"])),
        ("Return on locked capital", lambda m: pct(m["cap_weighted_return"])),
        ("Annualised return", lambda m: pct(m["ann_return_locked"], 0)),
        ("Volatility, annualised", lambda m: pct(m["vol_ann"])),
        ("Sharpe", lambda m: f"{m['sharpe_monthly']:.2f}"),
        ("Months in the Sharpe", lambda m: f"{m['months']} ({m['first_month']} to {m['last_month']})"),
        ("Worst month", lambda m: f"{100 * m['worst_month']:+.1f}% ({m['worst_month_key']})"),
        ("Sharpe, resolved trades only", lambda m: f"{m['res_sharpe']:.2f} ({m['res_months']} months to {m['res_last_month']})"),
        ("Volatility, resolved trades only", lambda m: pct(m["res_vol_ann"])),
        ("Worst month, resolved trades only", lambda m: f"{100 * m['res_worst_month']:+.1f}% ({m['res_worst_month_key']})"),
        ("Maximum drawdown", lambda m: f"{usd(m['max_dd_usd'])} ({pct(m['max_dd_over_peak_capital'])})"),
        ("Turnover a year", lambda m: f"{m['turnover']:.1f}x"),
        ("Capital put into trades", lambda m: usd(m["capital_usd"])),
        ("Most capital locked at once", lambda m: usd(m["peak_capital_locked"])),
        ("Median days locked", lambda m: f"{m['median_lock_days']:.1f}"),
        ("Median trade, contracts", lambda m: f"{m['median_size']:.0f}"),
        ("Trades not yet resolved", lambda m: f"{m['unsettled']}"),
    ]
    body = [head, "|" + "---|" * (len(cols) + 1)] + ["| " + name + " | " + " | ".join(f(books[k]) for k in cols) + " |" for name, f in lines]
    d_in, d_out = window_days("in"), window_days("out")
    note = (
        f"Definitions: fresh date ladders of `research/ladder_replay/`, {cfg.WINDOW_START} to {cfg.WINDOW_END} (end excluded); in-sample is entries before "
        f"{cfg.S11_OOS_START} ({d_in} days) and out-of-sample is entries from that date ({d_out} days), the cut S11 fixed before this replay; every figure is net of "
        f"one tick against us on each leg and both taker fees, at min(print sizes, {cfg.MAX_CONTRACTS}) contracts, held to resolution, with the "
        f"{books['year-checked', 'all']['unsettled']} unresolved year-checked trades valued at their guaranteed floor; a point is one cent per contract; the interval is a "
        f"{cfg.N_BOOT}-draw bootstrap over entry dates (seed {cfg.BOOT_SEED}); return on locked capital = net dollars / capital put into trades; annualised return = net "
        "dollars / (capital x days locked / 365); monthly return = net dollars of the trades resolving in a New York month / their capital (0 for a month with no "
        "resolution), volatility = its standard deviation x sqrt(12), Sharpe = its mean / standard deviation x sqrt(12) with no risk-free rate, worst month = its "
        "minimum, and because an unresolved trade is booked at its floor in the month its market ends, the study's series runs past the run date (4 October 2026) "
        "to the month shown, so the \"resolved trades only\" rows repeat the three figures on resolved trades and stop at the last month with a resolution (they "
        "are computed here, not by the study); maximum drawdown = largest peak-to-trough fall of cumulative net dollars by resolution time, in dollars and as a share of the most capital locked at "
        "once; turnover = capital put into trades / most capital locked at once, per 365 days of the column's window; **the year-checked run re-derives each rung's "
        "year (amendment 5) and was fixed after the registered run and after its losing trades had been seen, so only the registered columns are confirmatory.**"
    )
    return ("# Tables for the quant note\n\nWritten by `research/reproduce.py` (`make reproduce`) from the committed trade lists "
            "`research/results/ladder_replay/trades_fresh.csv` (rule as registered) and `research/results/ladder_replay/order_check/trades_fresh.csv` "
            "(year-checked), with `ladder_replay.replay.metrics`. Do not edit by hand.\n\n## Date-ladder book: in-sample and out-of-sample, net of costs\n\n"
            + "\n".join(body) + "\n\n" + note + "\n")


def run(write: bool = True) -> Checks:
    c = Checks()
    books = None
    with no_network():
        for f in (accuracy, s11, ladder, s21, touch, failed, unsourced):
            try:
                out = f(c)
                books = out if f is ladder else books
            except Exception as e:
                c.error(f.__name__, e)
        if write and books is not None:
            import note_figures
            from ladder_replay import config as cfg
            assert note_figures.OOS_START == cfg.S11_OOS_START
            TABLES.write_text(tables(books))
            for p in note_figures.main():
                print(f"wrote {rel(p)}")
            print(f"wrote {rel(TABLES)}\n")
    return c


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--no-write", action="store_true", help="check the claims only; do not write note/TABLES.md or the figures")
    a = ap.parse_args(argv)
    c = run(write=not a.no_write)
    c.print()
    return 1 if c.mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
