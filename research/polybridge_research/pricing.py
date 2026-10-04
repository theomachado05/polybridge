from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .calendar import TradingCalendar
from .config import StudyConfig

CONTRACTS = "/v3/reference/options/contracts"


def option_bars(client, opt_ticker: str, start, end) -> pd.DataFrame:
    rows = client.get_all(f"/v2/aggs/ticker/{opt_ticker}/range/1/day/{pd.Timestamp(start):%Y-%m-%d}/{pd.Timestamp(end):%Y-%m-%d}",
                          {"adjusted": "false", "sort": "asc", "limit": 50000})
    if not rows:
        return pd.DataFrame(columns=["close", "volume"], index=pd.DatetimeIndex([], name="session"))
    idx = (pd.to_datetime([r["t"] for r in rows], unit="ms", utc=True)
             .tz_convert("America/New_York").normalize().tz_localize(None))
    return pd.DataFrame({"close": [float(r["c"]) for r in rows], "volume": [float(r.get("v") or 0) for r in rows]},
                        index=pd.DatetimeIndex(idx, name="session"))


def fetch_chain(client, ticker: str, as_of: pd.Timestamp, dte_lo: int, dte_hi: int) -> pd.DataFrame:
    rows = client.get_all(CONTRACTS, {
        "underlying_ticker": ticker, "as_of": as_of.strftime("%Y-%m-%d"),
        "expiration_date.gte": (as_of + pd.Timedelta(days=dte_lo)).strftime("%Y-%m-%d"),
        "expiration_date.lte": (as_of + pd.Timedelta(days=dte_hi)).strftime("%Y-%m-%d"),
        "limit": 1000,
    })
    chain = pd.DataFrame(rows)
    if chain.empty:
        return chain
    if "shares_per_contract" in chain:
        chain = chain[chain["shares_per_contract"].fillna(100) == 100]
    chain = chain[["ticker", "contract_type", "strike_price", "expiration_date"]].copy()
    chain["expiration_date"] = pd.to_datetime(chain["expiration_date"])
    chain["dte"] = (chain["expiration_date"] - as_of).dt.days
    chain["strike_price"] = chain["strike_price"].astype(float)
    return chain.reset_index(drop=True)


def _paired_strikes(e: pd.DataFrame) -> np.ndarray:
    both = e.groupby("strike_price")["contract_type"].nunique()
    return both[both == 2].index.to_numpy(dtype=float)


def _contract(e: pd.DataFrame, strike: float, kind: str) -> str:
    return e[(e.strike_price == strike) & (e.contract_type == kind)]["ticker"].iloc[0]


def _last_close(client, opt_ticker: str, day: pd.Timestamp, lookback_days: int = 7) -> float | None:
    bars = option_bars(client, opt_ticker, day - pd.Timedelta(days=lookback_days), day)
    return float(bars["close"].iloc[-1]) if len(bars) else None


def locate_spot(client, chain: pd.DataFrame, day: pd.Timestamp, risk_free: float, max_iter: int = 8) -> dict | None:
    near = chain[chain.dte >= 3]
    if near.empty:
        return None
    near = near[near.dte == near.dte.min()]
    strikes = _paired_strikes(near)
    if len(strikes) < 3:
        return None
    T = near.dte.iloc[0] / 365
    k, tried, est = float(np.median(strikes)), set(), None
    k = strikes[np.abs(strikes - k).argmin()]
    for _ in range(max_iter):
        tried.add(k)
        c = _last_close(client, _contract(near, k, "call"), day)
        p = _last_close(client, _contract(near, k, "put"), day)
        if c is None or p is None:
            rest = [s for s in strikes if s not in tried]
            if not rest:
                break
            k = rest[int(np.abs(np.array(rest) - k).argmin())]
            continue
        est = k * np.exp(-risk_free * T) + c - p
        k_new = strikes[np.abs(strikes - est).argmin()]
        if k_new == k or k_new in tried:
            break
        k = k_new
    if est is None:
        return None
    return {"spot": float(est), "strike": float(k), "expiry": near.expiration_date.iloc[0], "dte": int(near.dte.iloc[0])}


def pick_expiry(chain: pd.DataFrame, lo: int, hi: int, target: int) -> pd.Timestamp | None:
    cand = chain[(chain.dte >= lo) & (chain.dte <= hi)]
    if cand.empty:
        return None
    dte_of = cand.groupby("expiration_date")["dte"].first()
    ok = [x for x, g in cand.groupby("expiration_date") if len(_paired_strikes(g)) >= 3]
    if not ok:
        return None
    return min(ok, key=lambda x: abs(dte_of[x] - target))


def select_strikes(e: pd.DataFrame, spot: float, otm_pcts, strike_window: float) -> dict[str, float] | None:
    both = _paired_strikes(e)
    both = both[(both >= spot * (1 - strike_window)) & (both <= spot * (1 + strike_window))]
    if len(both) == 0:
        return None
    calls = np.sort(e.loc[e.contract_type == "call", "strike_price"].unique())
    puts = np.sort(e.loc[e.contract_type == "put", "strike_price"].unique())
    out = {"K": float(both[np.abs(both - spot).argmin()])}
    for pct in otm_pcts:
        up, dn = calls[calls >= spot * (1 + pct)], puts[puts <= spot * (1 - pct)]
        out[f"U{pct}"] = float(up.min()) if len(up) else float(calls.max())
        out[f"L{pct}"] = float(dn.max()) if len(dn) else float(puts.min())
    return out


@dataclass
class Leg:
    ticker: str
    kind: str
    strike: float
    bars: pd.DataFrame
    cal: TradingCalendar = field(repr=False)
    max_stale: int = 3

    def mark(self, day) -> float:
        b = self.bars.loc[: pd.Timestamp(day)]
        if b.empty or self.cal.between(b.index[-1], day) > self.max_stale:
            return np.nan
        return float(b["close"].iloc[-1])

    def volume_on(self, day) -> float:
        return float(self.bars["volume"].get(pd.Timestamp(day), 0.0))


@dataclass
class PricedEvent:
    ticker: str
    event_date: pd.Timestamp
    t_pre: pd.Timestamp
    t_0: pd.Timestamp
    bucket: str
    expiry: pd.Timestamp
    expiry_session: pd.Timestamp
    spot_pre: float
    strikes: dict[str, float]
    legs: dict[str, Leg]
    risk_free: float
    family: str | None = None

    def marks(self, day) -> dict[str, float]:
        return {name: leg.mark(day) for name, leg in self.legs.items()}

    def synthetic_spot(self, day, m: dict[str, float] | None = None) -> float:
        m = m if m is not None else self.marks(day)
        T = max((self.expiry - pd.Timestamp(day)).days, 0) / 365
        return self.strikes["K"] * np.exp(-self.risk_free * T) + m["C_K"] - m["P_K"]


def price_event(client, row, cal: TradingCalendar, cfg: StudyConfig, buckets: dict) -> tuple[list[PricedEvent], list[str]]:
    t_pre, t_0 = pd.Timestamp(row.t_pre), pd.Timestamp(row.t_0)
    family = getattr(row, "family", None)
    dte_hi = max(b[1] for b in buckets.values())
    chain = fetch_chain(client, row.ticker, t_pre, 2, dte_hi)
    if chain.empty:
        return [], ["no option chain as of the pre-event session"]
    loc = locate_spot(client, chain, t_pre, cfg.risk_free)
    if loc is None:
        return [], ["could not recover spot from the chain (no liquid near-dated pair)"]
    priced, notes = [], []
    for name, (lo, hi, target) in buckets.items():
        expiry = pick_expiry(chain, lo, hi, target)
        if expiry is None:
            notes.append(f"{name}: no expiry {lo}-{hi} days out")
            continue
        e = chain[chain.expiration_date == expiry]
        strikes = select_strikes(e, loc["spot"], cfg.otm_grid, cfg.strike_window)
        if strikes is None:
            notes.append(f"{name}: no paired strikes near spot")
            continue
        wanted = {"C_K": ("call", strikes["K"]), "P_K": ("put", strikes["K"])}
        for pct in cfg.otm_grid:
            wanted[f"C_U{pct}"] = ("call", strikes[f"U{pct}"])
            wanted[f"P_L{pct}"] = ("put", strikes[f"L{pct}"])
        legs = {}
        for key, (kind, k) in wanted.items():
            tk = _contract(e, k, kind)
            legs[key] = Leg(tk, kind, k, option_bars(client, tk, t_pre - pd.Timedelta(days=10), expiry), cal, cfg.max_stale_sessions)
        exp_session = cal.sessions[cal.sessions.searchsorted(expiry, side="right") - 1]
        pe = PricedEvent(row.ticker, pd.Timestamp(row.filing_date), t_pre, t_0, name, expiry, exp_session,
                         loc["spot"], strikes, legs, cfg.risk_free, family)
        if np.isnan(pe.legs["C_K"].mark(t_pre)) or np.isnan(pe.legs["P_K"].mark(t_pre)):
            notes.append(f"{name}: ATM pair did not trade on or near the pre-event session")
            continue
        priced.append(pe)
    return priced, notes


def price_events(client, events: pd.DataFrame, cal: TradingCalendar, cfg: StudyConfig, buckets: dict | None = None,
                 max_workers: int = 8, label: str = "events") -> tuple[list[PricedEvent], pd.DataFrame]:
    buckets = buckets or cfg.buckets
    rows = list(events.itertuples(index=False))
    if not rows:
        return [], pd.DataFrame(columns=["ticker", "t_0", "reason"])
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        results = list(pool.map(lambda r: price_event(client, r, cal, cfg, buckets), rows))
    priced, dropped = [], []
    for row, (got, notes) in zip(rows, results):
        priced += got
        dropped += [(row.ticker, row.t_0, note) for note in notes]
    print(f"{label}: {len(rows)} events -> {len(priced)} priced (event, bucket) pairs; {len(dropped)} drops")
    return priced, pd.DataFrame(dropped, columns=["ticker", "t_0", "reason"])
