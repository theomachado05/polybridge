"""S24 engine: prints in YES terms, detection of an out-of-order ladder from two prints, the trade, statistics.

Pure functions (numpy, pandas). Nothing here reads the network or a file.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import config as cfg

NY = "America/New_York"


def fee(p, rate: float, exponent: float, mult: float = 1.0):
    """A market's own taker fee per contract: rate * (p(1-p))^exponent (as S11)."""
    p = np.asarray(p, dtype=float)
    return np.where((p > 0) & (p < 1), mult * rate * (p * (1.0 - p)) ** exponent, 0.0)


def yes_terms(price, side, out):
    """A print in YES terms (as S11's print check). side: +1 the taker bought, -1 the taker sold. out: 1 the YES token,
    0 the NO token. A taker who buys NO at p sells YES at 1 - p; a taker who sells NO at p buys YES at 1 - p."""
    price, side, out = np.asarray(price, float), np.asarray(side, int), np.asarray(out, int)
    return np.where(out == 1, price, 1.0 - price), np.where(out == 1, side, -side)


def ny_date(t) -> np.ndarray:
    return pd.to_datetime(np.asarray(t, dtype="int64"), unit="s", utc=True).tz_convert(NY).strftime("%Y-%m-%d").to_numpy()


# ---------------------------------------------------------------- range minimum / maximum (sparse table)

def _table(arr: np.ndarray, op) -> list[np.ndarray]:
    st, k = [arr], 1
    while 2 * k <= len(arr):
        prev = st[-1]
        st.append(op(prev[:-k], prev[k:]))
        k *= 2
    return st


def _query(st: list[np.ndarray], lo: np.ndarray, hi: np.ndarray, op, empty: float) -> np.ndarray:
    """op over arr[lo:hi] for every (lo, hi); `empty` where hi <= lo."""
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


# ---------------------------------------------------------------- detection

def first_matches(ta, pa, za, tb, pb, zb, fa: tuple[float, float], fb: tuple[float, float], window: int) -> list[dict]:
    """The first qualifying match of each New York day for one pair.

    ta, pa, za: time, YES price and size of every taker SELL of YES on the rich rung, sorted by time.
    tb, pb, zb: the same for every taker BUY of YES on the cheap rung.
    A match is a sale i and a purchase j with |ta[i] - tb[j]| <= window and pa[i] - pb[j] > fee_rich(pa[i]) + fee_cheap(pb[j]).
    It completes at the later print's time T. The trade of a day is the match that completes first. The later print is
    matched with the most recent print of the other rung that qualifies with it. Several matches completing in the same
    second: the smallest time difference, then the largest price gap, then the largest size.
    """
    ta, tb = np.asarray(ta, np.int64), np.asarray(tb, np.int64)
    pa, pb, za, zb = (np.asarray(x, float) for x in (pa, pb, za, zb))
    if not len(ta) or not len(tb):
        return []
    v = pa - fee(pa, *fa)                 # what the sale brings after the rich rung's fee
    c = pb + fee(pb, *fb)                 # what the purchase costs after the cheap rung's fee
    # the sale is the later print: purchases in [ta - window, ta]
    lo_a, hi_a = np.searchsorted(tb, ta - window, "left"), np.searchsorted(tb, ta, "right")
    qa = _query(_table(c, np.minimum), lo_a, hi_a, np.minimum, np.inf) < v - 1e-12
    # the purchase is the later print: sales in [tb - window, tb]
    lo_b, hi_b = np.searchsorted(ta, tb - window, "left"), np.searchsorted(ta, tb, "right")
    qb = _query(_table(v, np.maximum), lo_b, hi_b, np.maximum, -np.inf) > c + 1e-12
    ia, ib = np.flatnonzero(qa), np.flatnonzero(qb)
    if not len(ia) and not len(ib):
        return []
    T = np.concatenate([ta[ia], tb[ib]])
    which = np.concatenate([np.zeros(len(ia), int), np.ones(len(ib), int)])     # 0: the sale is later; 1: the purchase is later
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
                j = int(js[-1])              # the most recent qualifying purchase
            else:
                j = int(idx[s])
                iis = np.arange(lo_b[j], hi_b[j])
                iis = iis[v[iis] > c[j] + 1e-12]
                i = int(iis[-1])             # the most recent qualifying sale
            key = (abs(int(ta[i]) - int(tb[j])), -(pa[i] - pb[j]), -min(za[i], zb[j]), int(which[s]), i, j)
            if best is None or key < best[0]:
                best = (key, i, j)
        _, i, j = best
        out.append({"date": str(day), "t_entry": int(t0), "t_sale": int(ta[i]), "t_buy": int(tb[j]), "i_sale": i, "i_buy": j,
                    "sale_print": float(pa[i]), "buy_print": float(pb[j]), "size_sale": float(za[i]), "size_buy": float(zb[j])})
    return out


def fills_exist(sale_print: float, buy_print: float) -> bool:
    """Both fills are real prices at 1x and at 2x costs (METHOD.md section 3)."""
    h = max(c["haircut"] for c in cfg.COSTS.values())
    return sale_print - h >= cfg.PRICE_CLIP[0] - 1e-12 and buy_print + h <= cfg.PRICE_CLIP[1] + 1e-12


# ---------------------------------------------------------------- the trade

def trade(sale_print: float, buy_print: float, fa: tuple[float, float], fb: tuple[float, float], mult: float,
          out_rich: float | None, out_cheap: float | None) -> dict:
    """Sell YES on the rich rung below the sale print, buy YES on the cheap rung above the purchase print, hold both to
    the result. Per contract. A pair without both results is booked at its entry edge alone (the least it pays if the
    ladder's order holds)."""
    c = cfg.COSTS[mult]
    sa, bb = sale_print - c["haircut"], buy_print + c["haircut"]
    f_a, f_b = float(fee(sa, *fa, c["fee_mult"])), float(fee(bb, *fb, c["fee_mult"]))
    edge = (sa - f_a) - (bb + f_b)
    capital = (1.0 - sa) + f_a + bb + f_b               # the NO side of the rich rung costs 1 - sa
    if out_rich is not None and out_cheap is not None:
        pnl, how = edge + out_cheap - out_rich, "result"
    else:
        pnl, how = edge, "open (entry edge only)"
    return {"sell_at": sa, "buy_at": bb, "fee_rich": f_a, "fee_cheap": f_b, "edge": edge, "capital": capital, "pnl": pnl, "settled_by": how}


# ---------------------------------------------------------------- out-of-sample cut

def oos_cut(dates) -> str | None:
    """The first out-of-sample date: the most recent 20% (rounded up) of the distinct dates that have a trade."""
    d = sorted(set(dates))
    if not d:
        return None
    k = math.ceil(cfg.OOS_SHARE * len(d))
    return d[len(d) - k]


# ---------------------------------------------------------------- statistics

def boot(df: pd.DataFrame, col: str) -> tuple[float, float, float, int, int]:
    """Mean per trade, and a 95% interval by bootstrap over dates (several pairs on one date are one bet). As S11."""
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
    """Daily P&L over every calendar day, first entry to the last day.

    booking 'result' (primary): a trade's P&L is booked on the day the pair is settled (`settle_date`); its capital is
      locked from the entry date to that day; the capital base is the most capital locked at once.
    booking 'entry' (S11's convention, for comparison): P&L on the entry date; base = the most capital opened in one day.
    """
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
