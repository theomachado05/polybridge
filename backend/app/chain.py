"""Shared live-chain snapshot: spot, 3-6m expiry, strikes and today's marks for one ticker (sync; call via a thread)."""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from polybridge_research.calendar import TradingCalendar
from polybridge_research.config import EXPIRY_BUCKETS, StudyConfig
from polybridge_research.massive import MassiveClient, MissingApiKey, load_api_key
from polybridge_research.pricing import _contract, fetch_chain, locate_spot, option_bars, pick_expiry, select_strikes

CACHE_DIR = Path(os.environ.get("MASSIVE_CACHE_DIR", Path(__file__).resolve().parent.parent / ".massive_cache"))
_CAL: TradingCalendar | None = None


def calendar() -> TradingCalendar:
    global _CAL
    if _CAL is None:
        _CAL = TradingCalendar()
    return _CAL


def make_client():
    """MassiveClient, or None when no key is configured."""
    try:
        key = load_api_key(interactive=False)
    except MissingApiKey:
        return None
    return MassiveClient(key, cache_dir=CACHE_DIR)


def snapshot(client, ticker: str, today=None, cfg: StudyConfig | None = None) -> tuple[dict | None, str | None]:
    """Returns (snap, note). snap has spot, expiry, as_of, strikes, legs {name: {ticker, kind, strike, mark}}."""
    cfg = cfg or StudyConfig()
    cal = calendar()
    today = pd.Timestamp.today().normalize() if today is None else pd.Timestamp(today).normalize()
    day = cal.before(today)  # last completed session
    lo, hi, target = EXPIRY_BUCKETS["3-6m"]
    chain = fetch_chain(client, ticker, day, 2, hi)
    if chain.empty:
        return None, "no listed options"
    loc = locate_spot(client, chain, day, cfg.risk_free)
    if loc is None:
        return None, "could not recover spot from the option chain"
    expiry = pick_expiry(chain, lo, hi, target)
    if expiry is None:
        return None, "no 3-6 month expiry listed"
    e = chain[chain.expiration_date == expiry]
    strikes = select_strikes(e, loc["spot"], (cfg.otm_pct,), cfg.strike_window)
    if strikes is None:
        return None, "no paired strikes near spot"
    wanted = {"C_K": ("call", strikes["K"]), "P_K": ("put", strikes["K"]),
              f"C_U{cfg.otm_pct}": ("call", strikes[f"U{cfg.otm_pct}"]),
              f"P_L{cfg.otm_pct}": ("put", strikes[f"L{cfg.otm_pct}"])}
    legs = {}
    for name, (kind, k) in wanted.items():
        tk = _contract(e, k, kind)
        bars = option_bars(client, tk, day - pd.Timedelta(days=7), day)
        mark, mark_date = None, None
        if len(bars):
            last = bars.index[-1]
            if cal.between(last, day) <= cfg.max_stale_sessions:  # research rule (Leg.max_stale): older is not a price
                mark, mark_date = float(bars["close"].iloc[-1]), last.strftime("%Y-%m-%d")
        legs[name] = {"ticker": tk, "kind": kind, "strike": float(k), "mark": mark, "mark_date": mark_date}
    notes = []
    stale = sorted({legs[n]["mark_date"] for n in ("C_K", "P_K") if legs[n]["mark_date"] not in (None, day.strftime("%Y-%m-%d"))})
    if stale:
        notes.append(f"option prices from {stale[0]}, not the last session")
    return {"spot": loc["spot"], "expiry": expiry.strftime("%Y-%m-%d"), "as_of": day.strftime("%Y-%m-%d"),
            "strikes": strikes, "legs": legs, "notes": notes, "otm": cfg.otm_pct}, None
