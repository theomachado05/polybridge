from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt

import numpy as np
import pandas as pd

from leadlag_replication.closures import EARLY_CLOSES

from .config import PARAMS, TZ

RTH_START, RTH_END, RTH_END_EARLY = 570, 960, 780


def pm_at(points: list[tuple[int, float]], t: pd.Timestamp, stale_min: int = PARAMS.pm_stale_min) -> float:
    ts = int(t.timestamp())
    best = None
    for tt, p in points:
        if tt <= ts and (best is None or tt >= best[0]):
            best = (tt, p)
    if best is None or ts - best[0] > stale_min * 60:
        return float("nan")
    return 100.0 * best[1]


def et_instant(day: pd.Timestamp, hm: tuple[int, int]) -> pd.Timestamp:
    return (pd.Timestamp(day).normalize().tz_localize(TZ) + pd.Timedelta(hours=hm[0], minutes=hm[1])).tz_convert("UTC")


def session_measures(bars: pd.DataFrame, sessions: list[pd.Timestamp], early_closes=EARLY_CLOSES) -> pd.DataFrame:
    et = bars.index.tz_convert(TZ)
    day = et.normalize().tz_localize(None)
    mins = et.hour * 60 + et.minute
    bars = bars.assign(_day=day, _min=mins)
    groups = {d: g for d, g in bars.groupby("_day")}
    rows = []
    for d in sessions:
        g = groups.get(pd.Timestamp(d))
        r = {"day": pd.Timestamp(d), "rth_close": np.nan, "t_close": pd.NaT, "open_px": np.nan, "px_1000": np.nan,
             "px_0800": np.nan, "vol5_usd": np.nan, "vol5_pre_usd": np.nan}
        if g is not None:
            end = RTH_END_EARLY if pd.Timestamp(d).strftime("%Y-%m-%d") in early_closes else RTH_END
            rth = g[(g["_min"] >= RTH_START) & (g["_min"] < end)]
            if len(rth):
                r["rth_close"] = float(rth["close"].iloc[-1])
                r["t_close"] = rth.index[-1] + pd.Timedelta(minutes=1)
                if rth["_min"].iloc[0] <= RTH_START + PARAMS.open_tol_min:
                    r["open_px"] = float(rth["open"].iloc[0])
                b959 = rth[rth["_min"] == RTH_START + 29]
                if len(b959) and np.isfinite(r["open_px"]):
                    r["px_1000"] = float(b959["close"].iloc[0])
                o5 = rth[rth["_min"] < RTH_START + 5]
                r["vol5_usd"] = float((o5["volume"] * o5["close"]).sum()) if len(o5) else np.nan
            cut = 8 * 60
            pre = g[(g["_min"] + 1 <= cut) & (g["_min"] + 1 >= cut - PARAMS.pre_tol_min)]
            if len(pre):
                r["px_0800"] = float(pre["close"].iloc[-1])
            p5 = g[(g["_min"] >= cut) & (g["_min"] < cut + 5)]
            r["vol5_pre_usd"] = float((p5["volume"] * p5["close"]).sum()) if len(p5) else 0.0
        rows.append(r)
    return pd.DataFrame(rows).set_index("day")


def fit_rate(x, g) -> dict:
    x, g = np.asarray(x, float), np.asarray(g, float)
    n_nz = int((x != 0).sum())
    sxx = float((x ** 2).sum())
    if n_nz == 0 or sxx <= 0:
        return {"rate": float("nan"), "se": float("nan"), "t": float("nan"), "n_nonzero": n_nz}
    rate = float((x * g).sum() / sxx)
    e = g - rate * x
    h = x ** 2 / sxx
    adj = e / np.clip(1 - h, 1e-8, None)
    se = sqrt(float((x ** 2 * adj ** 2).sum())) / sxx
    return {"rate": rate, "se": se, "t": rate / se if se > 0 else float("nan"), "n_nonzero": n_nz}


def gate(x, g, n_min: int = PARAMS.n_min, t_min: float = PARAMS.t_min) -> tuple[bool, dict]:
    f = fit_rate(x, g)
    ok = f["n_nonzero"] >= n_min and np.isfinite(f["rate"]) and f["rate"] > 0 and np.isfinite(f["t"]) and f["t"] >= t_min
    return bool(ok), f


def hedge_fraction(e_bp: float, p=PARAMS) -> float:
    if not np.isfinite(e_bp) or e_bp > -p.min_gap_bp:
        return 0.0
    return p.target_coverage * min(1.0, -e_bp / p.full_size_gap_bp)


@dataclass
class RecordStore:
    market: list = field(default_factory=list)
    x: list = field(default_factory=list)
    g: list = field(default_factory=list)
    known_at: list = field(default_factory=list)

    def add(self, market: str, x: float, g: float, known_at: pd.Timestamp) -> None:
        self.market.append(market)
        self.x.append(float(x))
        self.g.append(float(g))
        self.known_at.append(pd.Timestamp(known_at))

    def available(self, as_of: pd.Timestamp, market: str | None = None) -> tuple[np.ndarray, np.ndarray]:
        if not self.x:
            return np.array([]), np.array([])
        ka = np.array([k.value for k in self.known_at])
        m = ka <= pd.Timestamp(as_of).value
        if market is not None:
            m &= np.array(self.market) == market
        return np.asarray(self.x)[m], np.asarray(self.g)[m]


@dataclass(frozen=True)
class Variant:
    name: str
    gating: bool = True
    premarket: bool = False
    unwind_close: bool = False


VARIANTS = {
    "primary": Variant("primary"),
    "V1_premarket": Variant("V1_premarket", premarket=True),
    "V2_no_gating": Variant("V2_no_gating", gating=False),
    "V3_unwind_close": Variant("V3_unwind_close", unwind_close=True),
    "V4_expanded": Variant("V4_expanded"),
}


def market_rate(store: RecordStore, market: str, as_of: pd.Timestamp, v: Variant, p=PARAMS) -> tuple[float, str, dict]:
    x, g = store.available(as_of, market)
    if v.gating:
        ok, f = gate(x, g, p.n_min, p.t_min)
        return (f["rate"] if ok else float("nan")), ("own" if ok else "gated_out"), f
    f = fit_rate(x, g)
    if f["n_nonzero"] >= p.n_min:
        return f["rate"], "own", f
    xa, ga = store.available(as_of)
    fp = fit_rate(xa, ga)
    if fp["n_nonzero"] >= p.n_min:
        return fp["rate"], "pooled", fp
    return float("nan"), "none", f


def run_loop(days: list[pd.Timestamp], meas: pd.DataFrame, markets: list[dict], part: dict, pm: dict,
             v: Variant, p=PARAMS) -> tuple[pd.DataFrame, pd.DataFrame]:
    sign = {m["market_slug"]: int(m["sign"]) for m in markets}
    store = RecordStore()
    out = []
    for i in range(1, len(days)):
        prev, d = days[i - 1], days[i]
        mp, md = meas.loc[prev], meas.loc[d]
        t_close = mp["t_close"] if pd.notna(mp["t_close"]) else et_instant(prev, (16, 0))
        t_sig = et_instant(d, p.sig_pre_hm if v.premarket else p.sig_hm)
        t_sig_train = et_instant(d, p.sig_hm)
        gap = 1e4 * (md["open_px"] / mp["rth_close"] - 1) if np.isfinite(md["open_px"]) and np.isfinite(mp["rth_close"]) else np.nan
        best_f, best = 0.0, None
        trusted, new_records = [], []
        for slug in part.get(d, []):
            pts = pm.get((slug, prev.strftime("%Y-%m-%d")))
            if not pts or isinstance(pts, Exception):
                continue
            pc = pm_at(pts, t_close, p.pm_stale_min)
            x_train = sign[slug] * (pm_at(pts, t_sig_train, p.pm_stale_min) - pc)
            x_sig = x_train if not v.premarket else sign[slug] * (pm_at(pts, t_sig, p.pm_stale_min) - pc)
            if np.isfinite(x_train) and np.isfinite(gap):
                new_records.append((slug, round(x_train, 9)))
            if not np.isfinite(x_sig):
                continue
            rate, src, fit = market_rate(store, slug, t_close, v, p)
            if not np.isfinite(rate):
                continue
            e = rate * round(x_sig, 9)
            f = hedge_fraction(e, p)
            trusted.append(f"{slug}:{src}:{rate:.2f}:{e:+.1f}")
            if f > best_f:
                best_f, best = f, {"market": slug, "rate": rate, "x": x_sig, "E_bp": e, "src": src, "t": fit.get("t")}
        entry = md["px_0800"] if v.premarket else md["open_px"]
        exit_ = md["rth_close"] if v.unwind_close else md["px_1000"]
        traded = best_f > 0 and np.isfinite(entry) and np.isfinite(exit_)
        out.append({"day": d, "closure": prev.strftime("%Y-%m-%d"), "n_part": len(part.get(d, [])),
                    "n_trusted": len(trusted), "trusted": ";".join(trusted), "f": best_f if traded else 0.0,
                    "f_signal": best_f, "skipped_missing_px": bool(best_f > 0 and not traded),
                    "driver": best["market"] if best else "", "rate": best["rate"] if best else np.nan,
                    "x_pp": best["x"] if best else np.nan, "E_bp": best["E_bp"] if best else np.nan,
                    "entry_px": entry, "exit_px": exit_, "gap_bp": gap})
        t_open = et_instant(d, (9, 30))
        for slug, x in new_records:
            store.add(slug, x, gap, t_open)
    rec = pd.DataFrame({"market": store.market, "x_pp": store.x, "gap_bp": store.g, "known_at": store.known_at})
    return pd.DataFrame(out).set_index("day"), rec


def books(days: list[pd.Timestamp], close: pd.Series, divs: pd.Series, sig: pd.DataFrame, cost_entry_bp: float,
          cost_exit_bp: float, book_usd: float = PARAMS.book_usd) -> pd.DataFrame:
    shares = book_usd / float(close.loc[days[0]])
    rows, div_cash, hedge_cash = [], 0.0, 0.0
    for i, d in enumerate(days):
        gross = cost = notional = 0.0
        if i > 0:
            div_cash += shares * float(divs.get(d, 0.0))
            s = sig.loc[d]
            if s["f"] > 0:
                q = s["f"] * shares
                notional = q * s["entry_px"]
                gross = -q * (s["exit_px"] - s["entry_px"])
                cost = notional * cost_entry_bp / 1e4 + q * s["exit_px"] * cost_exit_bp / 1e4
                hedge_cash += gross - cost
        long_v = shares * float(close.loc[d])
        rows.append({"day": d, "bh": long_v + div_cash, "strat": long_v + div_cash + hedge_cash,
                     "hedge_gross": gross, "hedge_cost": cost, "hedge_net": gross - cost, "notional": notional,
                     "traded_usd": notional + q * s["exit_px"] if notional else 0.0})
    return pd.DataFrame(rows).set_index("day")
