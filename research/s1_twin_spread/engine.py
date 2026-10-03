"""S1 engine: executable prices, edges, entries, exits and marks on 1-minute arrays (METHOD.md sections 2 to 6).

Everything is vectorised per pair; the position logic jumps between candidate minutes with searchsorted."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .config import DAYS_PER_YEAR, KALSHI_FEE_COEFF, MAX_QUOTE_AGE_S, PRICE_CLIP

YEAR_S = DAYS_PER_YEAR * 86400.0


# ---------------------------------------------------------------- costs

def kalshi_fee(price, qty: float, multiplier: float = 1.0):
    """Taker fee per contract: ceil_to_cent(0.07 * multiplier * qty * P * (1 - P)) / qty."""
    p = np.asarray(price, dtype=float)
    cents = np.ceil(KALSHI_FEE_COEFF * multiplier * qty * p * (1.0 - p) * 100.0 - 1e-9)
    return np.where((p > 0) & (p < 1), cents / 100.0 / qty, 0.0)


def pm_fee(price, rate: float, exponent: float = 1.0):
    """Polymarket taker fee per share: rate * (P * (1 - P)) ** exponent. Rate 0 when the market charges none."""
    p = np.asarray(price, dtype=float)
    return np.where((p > 0) & (p < 1), rate * (p * (1.0 - p)) ** exponent, 0.0)


# ---------------------------------------------------------------- alignment

def asof(grid: np.ndarray, ts: np.ndarray, values: np.ndarray, max_age: float = MAX_QUOTE_AGE_S) -> np.ndarray:
    """Last observation at or before each grid time, NaN when there is none or it is older than max_age."""
    out = np.full(len(grid), np.nan)
    if len(ts) == 0:
        return out
    idx = np.searchsorted(ts, grid, side="right") - 1
    ok = idx >= 0
    j = idx[ok]
    v = values[j].astype(float)
    v[(grid[ok] - ts[j]) > max_age] = np.nan
    out[ok] = v
    return out


def ffill(a: np.ndarray) -> np.ndarray:
    idx = np.where(~np.isnan(a), np.arange(len(a)), 0)
    np.maximum.accumulate(idx, out=idx)
    return a[idx]


@dataclass
class Pair:
    key: str                 # Kalshi ticker
    t: np.ndarray            # grid, epoch seconds, 60 s apart
    kb: np.ndarray           # Kalshi YES bid, NaN when stale or the book is one-sided
    ka: np.ndarray           # Kalshi YES ask
    pm: np.ndarray           # Polymarket history price, NaN when stale
    tau: np.ndarray          # years to the deadline
    h: float                 # modelled Polymarket half-spread
    k_mult: float = 1.0
    pm_rate: float = 0.0
    pm_exp: float = 1.0


def build_pair(key: str, start: int, end: int, k_t, k_bid, k_ask, p_t, p_px, deadline: float, h: float,
               k_mult: float, pm_rate: float, pm_exp: float, k_max_age: float = MAX_QUOTE_AGE_S) -> Pair:
    grid = np.arange(int(math.ceil(start / 60.0)) * 60, int(end) + 1, 60, dtype=np.int64)
    kb, ka = asof(grid, k_t, k_bid, k_max_age), asof(grid, k_t, k_ask, k_max_age)
    bad = ~((kb > 0) & (ka < 1) & (ka >= kb))          # an empty side is never a price
    kb[bad], ka[bad] = np.nan, np.nan
    pm = asof(grid, p_t, p_px)
    pm[~((pm > 0) & (pm < 1))] = np.nan
    tau = np.maximum(deadline - grid, 0.0) / YEAR_S
    return Pair(key, grid, kb, ka, pm, tau, h, k_mult, pm_rate, pm_exp)


# ---------------------------------------------------------------- prices, edges, marks

@dataclass
class Legs:
    """Per-minute arrays for one pair under one cost multiplier. A = Polymarket YES + Kalshi NO; B = Kalshi YES +
    Polymarket NO. `cost` is dollars per contract pair including fees; `liq` is what the pair sells for, net of fees."""
    cost: dict = field(default_factory=dict)
    edge: dict = field(default_factory=dict)
    liq: dict = field(default_factory=dict)
    liq_ff: dict = field(default_factory=dict)
    mid_ff: dict = field(default_factory=dict)
    fees: dict = field(default_factory=dict)
    spread: dict = field(default_factory=dict)
    pm_px: dict = field(default_factory=dict)      # Polymarket YES-equivalent price the entry trades at
    k_px: dict = field(default_factory=dict)       # Kalshi YES-equivalent price the entry trades at
    pv: np.ndarray | None = None
    carry_rate: np.ndarray | None = None           # c * r * tau


def legs(P: Pair, c: float, r: float, qty: float) -> Legs:
    lo, hi = PRICE_CLIP
    mk, hk = (P.kb + P.ka) / 2.0, (P.ka - P.kb) / 2.0
    kb, ka = np.clip(mk - c * hk, lo, hi), np.clip(mk + c * hk, lo, hi)
    pb, pa = np.clip(P.pm - c * P.h, lo, hi), np.clip(P.pm + c * P.h, lo, hi)

    def fk(p):
        return c * kalshi_fee(p, qty, P.k_mult)

    def fp(p):
        return c * pm_fee(p, P.pm_rate, P.pm_exp)

    L = Legs()
    L.carry_rate = c * r * P.tau
    L.pv = 1.0 - L.carry_rate
    L.fees = {"A": fp(pa) + fk(1 - kb), "B": fk(ka) + fp(1 - pb)}
    L.spread = {"A": (pa - P.pm) + (mk - kb), "B": (ka - mk) + (P.pm - pb)}
    L.cost = {"A": pa + (1 - kb) + L.fees["A"], "B": ka + (1 - pb) + L.fees["B"]}
    L.edge = {d: 1.0 - L.cost[d] * (1.0 + L.carry_rate) for d in "AB"}
    L.liq = {"A": pb - fp(pb) + (1 - ka) - fk(1 - ka), "B": kb - fk(kb) + (1 - pa) - fp(1 - pa)}
    L.liq_ff = {d: ffill(L.liq[d]) for d in "AB"}
    L.mid_ff = {"A": ffill(P.pm + 1 - mk), "B": ffill(mk + 1 - P.pm)}
    L.pm_px = {"A": pa, "B": pb}
    L.k_px = {"A": kb, "B": ka}
    return L


def two_in_a_row(cond: np.ndarray) -> np.ndarray:
    """True at t when the condition holds at t-1 and at t (adjacent grid minutes). NaN comparisons are False."""
    out = np.zeros(len(cond), dtype=bool)
    out[1:] = cond[1:] & cond[:-1]
    return out


# ---------------------------------------------------------------- positions

@dataclass
class Trade:
    pair: str
    dir: str
    i_in: int
    t_in: int
    qty: float
    cost_in: float           # per contract pair, fees included
    edge_in: float           # locked edge per contract pair, after carry
    fees_in: float
    spread_in: float
    carry_in: float          # carry rate at entry times cost
    pm_px: float
    k_px: float
    i_out: int | None = None
    t_out: int | None = None
    liq_out: float | None = None


def simulate(P: Pair, L: Legs, theta: float, exit_on: bool, i0: int, i1: int, qty: float) -> list[Trade]:
    """Entries and exits for one pair inside grid indices [i0, i1). Signals never look before i0."""
    with np.errstate(invalid="ignore"):
        ent = {d: two_in_a_row(L.edge[d] >= theta) for d in "AB"}
        ext = {d: two_in_a_row(L.liq[d] >= L.pv) for d in "AB"}
    for d in "AB":
        ent[d][: i0 + 1] = False
        ext[d][: i0 + 1] = False
    cand = {d: np.flatnonzero(ent[d][:i1]) for d in "AB"}
    exits = {d: np.flatnonzero(ext[d][:i1]) for d in "AB"}
    trades: list[Trade] = []
    t = i0 + 1
    while t < i1:
        nxt = {}
        for d in "AB":
            j = np.searchsorted(cand[d], t)
            if j < len(cand[d]):
                nxt[d] = int(cand[d][j])
        if not nxt:
            break
        n = min(nxt.values())
        d = max((x for x in nxt if nxt[x] == n), key=lambda x: L.edge[x][n])
        tr = Trade(P.key, d, n, int(P.t[n]), qty, float(L.cost[d][n]), float(L.edge[d][n]), float(L.fees[d][n]),
                   float(L.spread[d][n]), float(L.carry_rate[n] * L.cost[d][n]), float(L.pm_px[d][n]),
                   float(L.k_px[d][n]))
        trades.append(tr)
        if not exit_on:
            break
        j = np.searchsorted(exits[d], n + 1)
        if j >= len(exits[d]):
            break
        x = int(exits[d][j])
        tr.i_out, tr.t_out, tr.liq_out = x, int(P.t[x]), float(L.liq[d][x])
        t = x + 1
    return trades


def pnl_at(P: Pair, L: Legs, tr: Trade, i: int, c: float, r: float, mark: str) -> float:
    """Net P&L of one trade at grid index i under a mark: 'mid', 'liq' or 'locked'. Financing accrues daily."""
    if i < tr.i_in:
        return 0.0
    j = min(i, tr.i_out) if tr.i_out is not None else i
    accrued = c * r * tr.cost_in * (P.t[j] - tr.t_in) / YEAR_S
    if tr.i_out is not None and i >= tr.i_out:
        value = tr.liq_out
    elif mark == "mid":
        value = L.mid_ff[tr.dir][i]
    elif mark == "liq":
        value = L.liq_ff[tr.dir][i]
    else:
        value = 1.0 - L.carry_rate[i] * tr.cost_in
    return float(tr.qty * (value - tr.cost_in - accrued))


# ---------------------------------------------------------------- portfolio metrics

def day_marks(start: int, end: int) -> np.ndarray:
    """00:00 UTC boundaries strictly inside (start, end), then the end itself."""
    first = (start // 86400 + 1) * 86400
    days = np.arange(first, end, 86400, dtype=np.int64)
    return np.append(days, end)


def metrics(equity: np.ndarray, marks: np.ndarray, capital: float, traded_dollars: float, start: int) -> dict:
    """Daily-return statistics of an equity path that starts at 0 (dollars of P&L on a fixed capital base)."""
    e = np.concatenate([[0.0], equity]) / capital
    r = np.diff(e)
    n = len(r)
    sd = float(np.std(r, ddof=1)) if n > 2 else 0.0
    sharpe = float(np.mean(r) / sd * math.sqrt(DAYS_PER_YEAR)) if sd > 0 else float("nan")
    dd = float(np.max(np.maximum.accumulate(e) - e))
    months: dict[str, float] = {}
    for ret, m in zip(r, marks):
        key = np.datetime64(int(m) - 1, "s").astype("datetime64[M]").astype(str)
        months[key] = months.get(key, 0.0) + float(ret)
    years = max((int(marks[-1]) - start) / YEAR_S, 1e-9)
    return {"days": n, "total_return": float(e[-1]), "ann_return": float(e[-1] / years),
            "ann_vol": sd * math.sqrt(DAYS_PER_YEAR), "sharpe": sharpe, "max_drawdown": dd,
            "worst_month": min(months.values()) if months else float("nan"),
            "worst_month_label": min(months, key=months.get) if months else "",
            "turnover_ann": traded_dollars / capital / years,
            "skew": float(_moment(r, 3)), "kurtosis": float(_moment(r, 4)), "daily_sharpe": float(np.mean(r) / sd) if sd > 0 else float("nan")}


def _moment(r: np.ndarray, k: int) -> float:
    sd = np.std(r)
    if len(r) < 3 or sd == 0:
        return 0.0 if k == 3 else 3.0
    return float(np.mean(((r - np.mean(r)) / sd) ** k))


def pair_bootstrap(by_pair: dict[str, list[float]], n_boot: int, seed: int) -> tuple[float, float, float]:
    """Mean P&L per trade and its 95% interval, resampling pairs (trades of one pair are not independent)."""
    keys = [k for k, v in by_pair.items() if v]
    allv = [x for k in keys for x in by_pair[k]]
    if not allv:
        return (float("nan"),) * 3
    if len(keys) < 3:
        return (float(np.mean(allv)), float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    sums = np.array([sum(by_pair[k]) for k in keys])
    cnts = np.array([len(by_pair[k]) for k in keys])
    pick = rng.integers(0, len(keys), size=(n_boot, len(keys)))
    means = sums[pick].sum(axis=1) / cnts[pick].sum(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return (float(np.mean(allv)), float(lo), float(hi))
