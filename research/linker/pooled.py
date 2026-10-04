"""The pooled test of the mechanism (linker/heldout2/PLAN.md, amendment 1). Counts no link; tests the mechanism.

Population: every version-3 event link of the study's links file (floor applied there; the Brazil probe left out),
whatever its day count. One observation per link-day, built exactly as the per-link verdict builds it (study._pm,
study._days: every session where both the overnight move and the gap are finite, no 30-day minimum):
    x  the direction-signed overnight move of the link's signal, points (engine.link_days x_night)
    y  the instrument's excess opening gap in bp (e_gap) / (1e4 x features.pre_window_vol), i.e. in units of the
       instrument's daily sd before 2025-10-01 (pre_window_vol is the sd of daily close-to-close LOG returns, a
       fraction; times 1e4 it is in bp). A link whose instrument has no such figure is left out and counted.
The test: through-origin slope of y on x over all link-days, errors clustered by date (engine.clustered_slope).
The mechanism holds when slope > 0 and t >= 2. Again with one row per instrument and date (x = mean x over that
instrument's links that night, y = its standardised gap that night). Reported whatever they show: without the top
theme (study.top_theme), by instrument class, by mechanism_class, trusted (score_v2 >= 0.5) against the rest (NaN
scores are "rest"), |x| >= 5 against the other nights, sessions from 2026-07-01, the control arm (built the same way).
Active against quiet: version-3 links with link-days split at the median of odds_share_nights_1pt; ties (equal to the
median) go to the quiet half; the t of the difference is (b_a - b_q) / sqrt(se_a^2 + se_q^2).

Counts: link_days, links, event_clusters (the plan's clusters: distinct "cluster" values of the links behind the
fit), date_clusters (the date groups of the clustered errors; equal to dates by construction) and dates.

Options, pooled (PLAN 7 arrays, rebuilt here from option_evidence's public helpers, from the caches only, never
fetched). Population by rule, not by cache: the link-days of section 7, i.e. the links option_evidence.load_links takes
(version-3 event links whose equity verdict is not "untestable", probe left out), each with any day at all (no 30-day
minimum). Link-months are tallied: absent from the cache (no pair file, or one chosen on another spot, or a contract's
bars missing) apart from no contract listed, strike too far, and links with months but no day on which both legs
traded. Every link-day on which both legs traded that day and the session before. Directional leg (call on an up link, put on a down link) overnight return in
bp on the plain move of the signal (leg_sign x x_night), through the origin; straddle overnight return in bp on |move|
with an intercept (the demeaned fit option_evidence.slopes uses). Clustered by date. carries: directional slope > 0 and
t >= 2; size_priced: straddle slope > 0 and t >= 2. The signal is option_evidence.signal_odds, as that module uses.

No trade, no cost, no profit. The fresh set (heldout2) runs only after its evaluation and only when no frozen file
changed (study.frozen_gate), as study.py.

Run from `research/`:
    python -m linker.pooled --study dev|heldout2 [--amended a.py,b.py]
Writes results/linker/pooled_<dev_v3|heldout2>.json and pooled_<...>_days.csv (link key, date, x, y, split columns).
"""
from __future__ import annotations

import json
import sys
from typing import Callable

import numpy as np
import pandas as pd

from s4_linked_assets import engine as en

from . import features as ft
from . import instruments as ins
from . import option_evidence as oe
from . import store
from . import study as sd
from .benchmark import OUT

BIG_MOVE = 5.0
ONE_POINT = 1.0
MIN_T = 2.0
ABSENT = "absent"   # cache_fetch: no file in the cache (as against a cached "no contract")
EMPTY_DAYS = ("key", "linker", "market", "cluster", "ticker", "direction", "date", "x", "y")


def holds(r: dict) -> bool:
    return bool(np.isfinite(r["slope"]) and np.isfinite(r["t"]) and r["slope"] > 0 and r["t"] >= MIN_T)


def link_key(l: dict) -> str:
    return f"{l['linker']}|{l['market']}|{l['ticker']}|{l['direction']}"


# ---------------------------------------------------------------- stacking (pure, given the two callables)

def stack(links: list[dict], days_of: Callable[[dict], tuple[np.ndarray, np.ndarray, np.ndarray]],
          vol_of: Callable[[str], float]) -> tuple[pd.DataFrame, dict]:
    """One row per link-day with finite x and y_raw; y = y_raw / (1e4 x vol). Links without a finite positive vol are
    left out and counted, as are links with no link-day."""
    rows, no_vol, no_days = [], [], []
    vols: dict[str, float] = {}
    for l in links:
        tk = str(l["ticker"])
        v = vols.setdefault(tk, vol_of(tk))
        if not (np.isfinite(v) and v > 0):
            no_vol.append(link_key(l))
            continue
        x, g, d = (np.asarray(a) for a in days_of(l))
        ok = np.isfinite(x.astype(float)) & np.isfinite(g.astype(float))
        if not ok.any():
            no_days.append(link_key(l))
            continue
        base = {"key": link_key(l), **{k: l.get(k) for k in ("linker", "market", "cluster", "ticker", "direction")}}
        for xi, gi, di in zip(x[ok], g[ok], d[ok]):
            rows.append({**base, "date": str(di), "x": float(xi), "y": float(gi) / (1e4 * v)})
    df = pd.DataFrame(rows, columns=list(EMPTY_DAYS)) if not rows else pd.DataFrame(rows)
    return df, {"links_in": len(links), "left_out_no_vol": len(no_vol), "left_out_no_vol_keys": no_vol,
                "links_with_no_link_day": len(no_days), "pre_window_vol": {k: v for k, v in sorted(vols.items())}}


# ---------------------------------------------------------------- statistics (pure)

def event_clusters(df: pd.DataFrame) -> int:
    """Distinct event clusters (the links file's "cluster" column) behind the rows; 0 without the column."""
    return int(df["cluster"].dropna().astype(str).nunique()) if len(df) and "cluster" in df else 0


def fit(df: pd.DataFrame, x: str = "x", y: str = "y") -> dict:
    """Through-origin slope of y on x, errors clustered by date, with counts and the same-sign share on |x| >= 1."""
    if not len(df):
        return {"slope": float("nan"), "se": float("nan"), "t": float("nan"), "link_days": 0, "links": 0, "event_clusters": 0,
                "date_clusters": 0, "dates": 0, "same_sign_share_1pt": float("nan"), "nights_1pt": 0, "holds": False}
    xs, ys, g = df[x].to_numpy(float), df[y].to_numpy(float), df.date.astype(str).to_numpy()
    c = en.clustered_slope(xs, ys, g)
    big = np.isfinite(xs) & np.isfinite(ys) & (np.abs(xs) >= ONE_POINT)
    r = {"slope": c["slope"], "se": c["se"], "t": c["t"], "link_days": int(c["n"]),
         "links": int(df["key"].nunique()) if "key" in df else int(df["links"].sum()),
         "event_clusters": event_clusters(df), "date_clusters": int(c.get("clusters", 0)),
         "dates": int(df.date.nunique()), "same_sign_share_1pt": float(np.mean(np.sign(xs[big]) == np.sign(ys[big]))) if big.any() else float("nan"),
         "nights_1pt": int(big.sum())}
    return {**r, "holds": holds(r)}


def per_instrument(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (ticker, date): x = mean x over that instrument's links that night; y = its standardised gap (the
    same on every link of the ticker that night)."""
    if not len(df):
        return pd.DataFrame(columns=["ticker", "date", "x", "y", "links"])
    return df.groupby(["ticker", "date"], as_index=False).agg(x=("x", "mean"), y=("y", "first"), links=("key", "nunique"))


def fit_per_instrument(df: pd.DataFrame) -> dict:
    p = per_instrument(df)
    r = fit(p.assign(key=p.ticker)) if len(p) else fit(p)
    r["instruments"] = r.pop("links")
    r["links"] = int(df["key"].nunique()) if len(df) else 0
    r["event_clusters"] = event_clusters(df)
    r["instrument_days"] = r.pop("link_days")
    return r


def active_mask(shares: pd.Series) -> tuple[pd.Series, float]:
    """True for links strictly above the median share (ties go to the quiet half); NaN shares are neither (False)."""
    med = float(shares.median())
    return (shares > med).fillna(False), med


def diff_t(a: dict, b: dict) -> float:
    den = float(np.hypot(a["se"], b["se"]))
    return float((a["slope"] - b["slope"]) / den) if np.isfinite(den) and den > 0 else float("nan")


def split(df: pd.DataFrame, col: str) -> dict:
    return {str(k): fit(g) for k, g in df.groupby(col, dropna=False)} if len(df) else {}


# ---------------------------------------------------------------- options (rebuilt from option_evidence helpers)

def cache_fetch(kind: str, *a):
    """option_evidence's fetch, from the caches only: a missing file is an absent link-month, never fetched."""
    if kind == "splits":
        return store.npz(f"splits_{a[0]}.npz")
    if kind == "pair":
        tk, m, spot = a
        c = store.npz(f"optpair_{tk}_{m}.npz")
        if c is None or "spot" not in c or not np.isclose(float(c["spot"]), spot, rtol=1e-9, equal_nan=True):
            return ABSENT                    # option_evidence would choose (fetch) again: not in the cache
        if not str(c["call"]):
            return None                      # cached: no contract listed
        return {"month": m, "expiry": str(c["expiry"]), "strike": float(str(c["strike"])), "spot": spot, "call": str(c["call"]), "put": str(c["put"])}
    c = store.npz(f"opt_{a[0].replace('O:', '')}.npz")
    return ABSENT if c is None else c


MONTH_TALLY = ("months", "absent_from_cache", "no_contract", "strike_too_far")


def option_days(link: dict, sess: pd.DataFrame, pm: dict | None, dayb: dict | None, fetch=cache_fetch,
                tally: dict | None = None) -> pd.DataFrame:
    """Per-day arrays of option_evidence.link_evidence for one link, on the days both legs traded on that day and the
    session before: xp = the plain move of the signal (leg_sign x x_night), r_dir and r_str in bp. tally, if given,
    counts the link's months and why a month gives nothing (MONTH_TALLY); absent_from_cache lists link|month."""
    tally = {} if tally is None else tally
    cols = ["date", "xp", "r_dir", "r_str"]
    if pm is None or len(pm["t"]) == 0 or dayb is None:
        return pd.DataFrame(columns=cols)
    days = list(sess.day)
    x = oe.night_moves(pm, link["direction"], sess)
    live = [d for d, v in zip(days, x) if np.isfinite(v)]
    if not live:
        return pd.DataFrame(columns=cols)
    sp = fetch("splits", link["ticker"])
    mon = np.array([d[:7] for d in days])
    r_call, r_put, r_str = (np.full(len(days), np.nan) for _ in range(3))
    life = oe.months_between(live[0], live[-1])
    for m in life:
        spot = oe.raw_spot_before(dayb["day"], dayb["c"], m, sp)
        tally["months"] = tally.get("months", 0) + 1
        pr = fetch("pair", link["ticker"], m, spot)
        cb = pb = None
        if pr is not None and not isinstance(pr, str) and not oe.strike_too_far(float(pr["strike"]), spot):
            cb, pb = fetch("bars", pr["call"], m, pr["expiry"]), fetch("bars", pr["put"], m, pr["expiry"])
        why = ("absent_from_cache" if ABSENT in (pr, cb, pb) else "no_contract" if pr is None
               else "strike_too_far" if cb is None else "")
        if why:
            tally[why] = tally.get(why, 0) + 1
            if why == "absent_from_cache":
                tally.setdefault("absent_keys", []).append(f"{link['ticker']}|{link.get('market')}|{m}")
            continue
        inm = mon == m
        ex = [str(e) for e in np.asarray(sp["execution_date"], dtype=str) if str(e)[:7] == m] if sp is not None else []
        if ex:
            inm = inm & (np.array(days) < min(ex))
        r_call[inm], r_put[inm] = oe.overnight(days, cb)[inm], oe.overnight(days, pb)[inm]
        r_str[inm] = oe.straddle_overnight(days, cb, pb)[inm]
    up = link["direction"] == "up_on_yes"
    xp = np.where(np.isfinite(x) & np.isin(mon, life), (1.0 if up else -1.0) * x, np.nan)
    r_dir = r_call if up else r_put
    ok = np.isfinite(xp) & np.isfinite(r_dir) & np.isfinite(r_str)
    return pd.DataFrame({"date": np.array(days)[ok], "xp": xp[ok], "r_dir": 1e4 * r_dir[ok], "r_str": 1e4 * r_str[ok]})


def options_fit(o: pd.DataFrame) -> dict:
    """Directional through the origin; straddle on |xp| with an intercept (demeaned, as option_evidence.slopes)."""
    base = {"link_days": int(len(o)), "links": int(o.key.nunique()) if len(o) else 0, "event_clusters": event_clusters(o),
            "date_clusters": int(o.date.nunique()) if len(o) else 0, "dates": int(o.date.nunique()) if len(o) else 0}
    if not len(o):
        nan = {"slope": float("nan"), "se": float("nan"), "t": float("nan")}
        return {"directional": {**nan, **base, "carries": False}, "straddle": {**nan, **base, "intercept_bp": float("nan"), "size_priced": False}}
    g, x, a = o.date.astype(str).to_numpy(), o.xp.to_numpy(float), np.abs(o.xp.to_numpy(float))
    yd, ys = o.r_dir.to_numpy(float), o.r_str.to_numpy(float)
    d = en.clustered_slope(x, yd, g)
    s = en.clustered_slope(a - a.mean(), ys - ys.mean(), g)
    dr = {k: d[k] for k in ("slope", "se", "t")} | base | {"date_clusters": int(d.get("clusters", 0))}
    sr = {k: s[k] for k in ("slope", "se", "t")} | base | {"date_clusters": int(s.get("clusters", 0)),
                                                           "intercept_bp": float(ys.mean() - s["slope"] * a.mean()) if np.isfinite(s["slope"]) else float("nan")}
    return {"directional": {**dr, "carries": holds(dr)}, "straddle": {**sr, "size_priced": holds(sr)}}


def options_stack(links: list[dict], sess: pd.DataFrame, fetch=cache_fetch,
                  odds_of: Callable[[dict], dict | None] = oe.signal_odds,
                  day_of: Callable[[str], dict | None] = lambda tk: store.npz(f"day_{tk}.npz")) -> tuple[pd.DataFrame, dict]:
    """Stack option_days over the section-7 links (option_evidence.load_links), with the population tally."""
    rows, tally, none = [], {}, []
    for l in links:
        o = option_days(l, sess, odds_of(l), day_of(str(l["ticker"])), fetch, tally)
        if len(o):
            rows.append(o.assign(key=link_key(l), cluster=l.get("cluster")))
        else:
            none.append(link_key(l))
    cols = ["date", "xp", "r_dir", "r_str", "key", "cluster"]
    opt = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=cols)
    pop = {"rule": "PLAN 7 links (option_evidence.load_links: v3 event, equity verdict not untestable, probe out), any day count",
           "links": len(links), "links_with_an_option_day": len(rows), "links_with_no_option_day": len(none),
           "link_months": tally.get("months", 0), "link_months_absent_from_cache": tally.get("absent_from_cache", 0),
           "link_months_no_contract": tally.get("no_contract", 0), "link_months_strike_too_far": tally.get("strike_too_far", 0),
           "absent_from_cache_keys": tally.get("absent_keys", []), "links_with_no_option_day_keys": none}
    return opt, pop


# ---------------------------------------------------------------- the run

def load(study: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(version-3 event links, control-arm links) from results/linker/<name>_links.csv, the probe left out."""
    df = pd.read_csv(OUT / f"{sd.out_name(study)}_links.csv")
    keep = ~df.probe.astype(str).str.lower().isin(("true", "1"))
    v3 = df[df.linker.astype(str).str.startswith("v3") & (df.kind.astype(str) == sd.EVENT) & keep]
    ctrl = df[(df.linker.astype(str) == sd.CONTROL) & keep]
    return v3.reset_index(drop=True), ctrl.reset_index(drop=True)


def _num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def run(study: str, px: sd.Prices | None = None, write: bool = True) -> dict:
    px = px or sd.Prices()
    v3, ctrl = load(study)
    cache: dict = {}

    def days_of(l: dict):
        asset = px.asset(str(l["ticker"]))
        pm = sd._pm(json.loads(l["signal"]), l.get("market"), cache)
        if asset is None or pm is None:
            return np.array([]), np.array([]), np.array([])
        return sd._days(pm, 1 if l["direction"] == "up_on_yes" else -1, px, asset)

    th = sd.top_theme(v3)
    s3, c3 = stack(v3.to_dict("records"), days_of, ft.pre_window_vol)
    sc, cc = stack(ctrl.to_dict("records"), days_of, ft.pre_window_vol)
    info = {link_key(r): r for r in v3.to_dict("records")}
    if len(s3):
        s3["theme"] = s3.key.map(lambda k: info[k].get("theme"))
        s3["instrument_class"] = s3.ticker.map(ins.class_of)
        s3["mechanism_class"] = s3.key.map(lambda k: info[k].get("mechanism_class")).fillna("none")
        s3["trusted"] = s3.key.map(lambda k: _num(info[k].get("score_v2")) >= sd.TRUST_SCORE)
        s3["big_night"] = s3.x.abs() >= BIG_MOVE
        s3["since_cutoff"] = s3.date >= sd.CUTOFF
        share = pd.Series({k: _num(info[k].get("odds_share_nights_1pt")) for k in s3.key.unique()})
        act, med = active_mask(share)
        s3["half"] = np.where(s3.key.map(share).isna(), "no share", np.where(s3.key.map(act), "active", "quiet"))
    else:
        med = float("nan")
    a = fit(s3[s3.half == "active"]) if len(s3) else fit(s3)
    q = fit(s3[s3.half == "quiet"]) if len(s3) else fit(s3)

    opt, opt_pop = options_stack(oe.load_links(study), px.sess)

    out = {"study": sd.out_name(study), "note": "development figures are not evidence" if study == "dev" else "",
           "y_units": "excess opening gap / daily sd of close-to-close log returns before 2025-10-01 (pre_window_vol x 1e4, bp)",
           "population": {"v3": {k: v for k, v in c3.items() if k != "pre_window_vol"}, "control": {k: v for k, v in cc.items() if k != "pre_window_vol"}},
           "pooled": fit(s3), "per_instrument_and_date": fit_per_instrument(s3),
           "splits": {"top_theme": th, "without_top_theme": fit(s3[s3.theme != th]) if len(s3) else fit(s3),
                      "by_instrument_class": split(s3, "instrument_class"), "by_mechanism_class": split(s3, "mechanism_class"),
                      "trusted": fit(s3[s3.trusted]) if len(s3) else fit(s3), "rest": fit(s3[~s3.trusted]) if len(s3) else fit(s3),
                      "nights_abs_x_5_or_more": fit(s3[s3.big_night]) if len(s3) else fit(s3),
                      "other_nights": fit(s3[~s3.big_night]) if len(s3) else fit(s3),
                      "sessions_from_2026_07_01": fit(s3[s3.since_cutoff]) if len(s3) else fit(s3),
                      "control_arm": fit(sc), "control_arm_per_instrument_and_date": fit_per_instrument(sc)},
           "active_vs_quiet": {"median_share_nights_1pt": med, "ties": "to the quiet half", "active": a, "quiet": q, "t_difference": diff_t(a, q)},
           "options": {**options_fit(opt), "population": opt_pop}}
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"pooled_{sd.out_name(study)}.json").write_text(json.dumps(out, indent=1, default=float))
        both = pd.concat([s3.assign(arm="v3"), sc.assign(arm="control")], ignore_index=True)
        cols = [c for c in ("key", "arm", "ticker", "date", "x", "y", "theme", "instrument_class", "mechanism_class", "trusted",
                            "half", "big_night", "since_cutoff") if c in both]
        both[cols].to_csv(OUT / f"pooled_{sd.out_name(study)}_days.csv", index=False)
    return out


def main(argv: list[str]) -> int:
    study = argv[argv.index("--study") + 1] if "--study" in argv and argv.index("--study") + 1 < len(argv) else None
    if study not in ("dev", "heldout2"):
        print("usage: python -m linker.pooled --study dev|heldout2 [--amended a.py,b.py]")
        return 2
    why = sd.frozen_gate(study, sd._amended(argv))
    if why:
        print("refused:", why)
        return 2
    out = run(study)
    gone = out["options"]["population"]["link_months_absent_from_cache"]
    if gone:
        print(f"warning: {gone} section-7 link-months absent from the option cache; run option_evidence first", file=sys.stderr)
    print(json.dumps({k: out[k] for k in ("note", "population", "pooled", "per_instrument_and_date", "active_vs_quiet", "options")},
                     indent=1, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
