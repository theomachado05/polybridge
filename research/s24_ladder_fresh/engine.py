from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import config as cfg

NY = "America/New_York"


def fee(p, rate: float, exponent: float, mult: float = 1.0):
    p = np.asarray(p, dtype=float)
    return np.where((p > 0) & (p < 1), mult * rate * (p * (1.0 - p)) ** exponent, 0.0)


def yes_terms(price, side, out):
    price, side, out = np.asarray(price, float), np.asarray(side, int), np.asarray(out, int)
    return np.where(out == 1, price, 1.0 - price), np.where(out == 1, side, -side)


def ny_date(t) -> np.ndarray:
    return pd.to_datetime(np.asarray(t, dtype="int64"), unit="s", utc=True).tz_convert(NY).strftime("%Y-%m-%d").to_numpy()


def _table(arr: np.ndarray, op) -> list[np.ndarray]:
    st, k = [arr], 1
    while 2 * k <= len(arr):
        prev = st[-1]
        st.append(op(prev[:-k], prev[k:]))
        k *= 2
    return st


def _query(st: list[np.ndarray], lo: np.ndarray, hi: np.ndarray, op, empty: float) -> np.ndarray:
    out = np.full(len(lo), empty, dtype=float)
    n = hi - lo
    ok = np.flatnonzero(n > 0)
    if not len(ok):
        return out
    k = np.floor(np.log2(n[ok])).astype(int)
    for kk in np.unique(k):
        sel = ok[k == kk]
        out[sel] = op(st[kk][lo[sel]], st[kk][hi[sel] - (1 << kk)])
    return out


def first_matches(ta, pa, za, tb, pb, zb, fa: tuple[float, float], fb: tuple[float, float], window: int) -> list[dict]:
    ta, tb = np.asarray(ta, np.int64), np.asarray(tb, np.int64)
    pa, pb, za, zb = (np.asarray(x, float) for x in (pa, pb, za, zb))
    if not len(ta) or not len(tb):
        return []
    v = pa - fee(pa, *fa)
    c = pb + fee(pb, *fb)
    lo_a, hi_a = np.searchsorted(tb, ta - window, "left"), np.searchsorted(tb, ta, "right")
    qa = _query(_table(c, np.minimum), lo_a, hi_a, np.minimum, np.inf) < v - 1e-12
    lo_b, hi_b = np.searchsorted(ta, tb - window, "left"), np.searchsorted(ta, tb, "right")
    qb = _query(_table(v, np.maximum), lo_b, hi_b, np.maximum, -np.inf) > c + 1e-12
    ia, ib = np.flatnonzero(qa), np.flatnonzero(qb)
    if not len(ia) and not len(ib):
        return []
    T = np.concatenate([ta[ia], tb[ib]])
    which = np.concatenate([np.zeros(len(ia), int), np.ones(len(ib), int)])
    idx = np.concatenate([ia, ib])
    days = ny_date(T)
    out = []
    for day in np.unique(days):
        sel = np.flatnonzero(days == day)
        t0 = T[sel].min()
        best = None
        for s in sel[T[sel] == t0]:
            if which[s] == 0:
                i = int(idx[s])
                js = np.arange(lo_a[i], hi_a[i])
                js = js[c[js] < v[i] - 1e-12]
                j = int(js[-1])
            else:
                j = int(idx[s])
                iis = np.arange(lo_b[j], hi_b[j])
                iis = iis[v[iis] > c[j] + 1e-12]
                i = int(iis[-1])
            key = (abs(int(ta[i]) - int(tb[j])), -(pa[i] - pb[j]), -min(za[i], zb[j]), int(which[s]), i, j)
            if best is None or key < best[0]:
                best = (key, i, j)
        _, i, j = best
        out.append({"date": str(day), "t_entry": int(t0), "t_sale": int(ta[i]), "t_buy": int(tb[j]), "i_sale": i, "i_buy": j,
                    "sale_print": float(pa[i]), "buy_print": float(pb[j]), "size_sale": float(za[i]), "size_buy": float(zb[j])})
    return out


def fills_exist(sale_print: float, buy_print: float) -> bool:
    h = max(c["haircut"] for c in cfg.COSTS.values())
    return sale_print - h >= cfg.PRICE_CLIP[0] - 1e-12 and buy_print + h <= cfg.PRICE_CLIP[1] + 1e-12


def trade(sale_print: float, buy_print: float, fa: tuple[float, float], fb: tuple[float, float], mult: float,
          out_rich: float | None, out_cheap: float | None) -> dict:
    c = cfg.COSTS[mult]
    sa, bb = sale_print - c["haircut"], buy_print + c["haircut"]
    f_a, f_b = float(fee(sa, *fa, c["fee_mult"])), float(fee(bb, *fb, c["fee_mult"]))
    edge = (sa - f_a) - (bb + f_b)
    capital = (1.0 - sa) + f_a + bb + f_b
    if out_rich is not None and out_cheap is not None:
        pnl, how = edge + out_cheap - out_rich, "result"
    else:
        pnl, how = edge, "open (entry edge only)"
    return {"sell_at": sa, "buy_at": bb, "fee_rich": f_a, "fee_cheap": f_b, "edge": edge, "capital": capital, "pnl": pnl, "settled_by": how}


def oos_cut(dates) -> str | None:
    d = sorted(set(dates))
    if not d:
        return None
    k = math.ceil(cfg.OOS_SHARE * len(d))
    return d[len(d) - k]


def boot(df: pd.DataFrame, col: str) -> tuple[float, float, float, int, int]:
    d = df[df[col].notna()]
    if not len(d):
        return (float("nan"),) * 3 + (0, 0)
    by = d.groupby("date")[col].agg(["sum", "count"])
    m = float(d[col].mean())
    if len(by) < 5:
        return m, float("nan"), float("nan"), len(d), len(by)
    rng = np.random.default_rng(cfg.BOOT_SEED)
    pick = rng.integers(0, len(by), size=(cfg.N_BOOT, len(by)))
    s, n = by["sum"].to_numpy()[pick].sum(1), by["count"].to_numpy()[pick].sum(1)
    lo, hi = np.percentile(s / n, [2.5, 97.5])
    return m, float(lo), float(hi), len(d), len(by)


def perf(tr: pd.DataFrame, pnl_col: str, cap_col: str, booking: str = "result", last_day: str | None = None) -> dict:
    if not len(tr):
        return {}
    d = tr.assign(_e=pd.to_datetime(tr["date"]), _s=pd.to_datetime(tr["settle_date"]))
    end = max(d["_s"].max(), d["_e"].max(), pd.Timestamp(last_day) if last_day else d["_e"].max())
    idx = pd.date_range(d["_e"].min(), end, freq="D")
    locked = pd.Series(0.0, index=idx)
    for e, s, k in zip(d["_e"], d["_s"], d[cap_col]):
        locked.loc[e:s] += k
    if booking == "result":
        pnl = d.groupby("_s")[pnl_col].sum().reindex(idx, fill_value=0.0)
        K = float(locked.max())
    else:
        pnl = d.groupby("_e")[pnl_col].sum().reindex(idx, fill_value=0.0)
        K = float(d.groupby("_e")[cap_col].sum().max())
    r = pnl / K
    eq = K + pnl.cumsum()
    dd = (eq.cummax() - eq) / K
    sd = r.std(ddof=1)
    months = r.groupby(r.index.to_period("M")).sum()
    cap_days = float(locked.sum())
    return {"capital_base": K, "net_pnl": float(pnl.sum()), "sharpe": float(r.mean() / sd * math.sqrt(365)) if sd > 0 else float("nan"),
            "max_drawdown": float(dd.max()), "worst_month": float(months.min()), "days": len(idx),
            "capital_days": cap_days, "mean_capital_locked": cap_days / len(idx),
            "return_on_locked_capital_per_year": float(pnl.sum()) / (cap_days / 365.0) if cap_days > 0 else float("nan"),
            "equity": eq, "locked": locked, "daily_pnl": pnl}
