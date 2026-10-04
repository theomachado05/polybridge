from __future__ import annotations

import csv
import sys
from datetime import date

from s4_linked_assets import data as d4
from s21_options_anchor import config as s21cfg
from s21_options_anchor import engine as s21

EXAMPLES = (
    ("Will Flávio Bolsonaro win the 2026 Brazilian presidential election? (first round Sun 2026-10-04)", "EWZ", "up_on_yes", "2026-10-05"),
    ("Brazil presidential runoff (Sun 2026-10-25)", "EWZ", "up_on_yes", "2026-10-26"),
    ("Strait of Hormuz traffic returns to normal by December 31?", "USO", "down_on_yes", "2026-12-31"),
    ("Will the U.S. invade Iran before 2027?", "XLE", "up_on_yes", "2026-12-31"),
    ("Will the Fed increase interest rates by 25 bps after the October 2026 meeting? (decision 2026-10-28)", "TLT", "down_on_yes", "2026-10-28"),
)


def contracts(s, base: str, ticker: str, resolves: str, horizon_days: int = 45) -> list[dict]:
    y, m, d = (int(x) for x in resolves.split("-"))
    hi = date.fromordinal(date(y, m, d).toordinal() + horizon_days).isoformat()
    return d4.massive_rows(s, f"{base}/v3/reference/options/contracts",
                           {"underlying_ticker": ticker, "expiration_date.gte": resolves, "expiration_date.lte": hi, "limit": 1000})


def last_close(s, base: str, ticker: str, on_or_before: str) -> float:
    y, m, d = (int(x) for x in on_or_before.split("-"))
    lo = date.fromordinal(date(y, m, d).toordinal() - 10).isoformat()
    rows = d4.massive_rows(s, f"{base}/v2/aggs/ticker/{ticker}/range/1/day/{lo}/{on_or_before}", {"adjusted": "true", "sort": "asc", "limit": 50})
    return float(rows[-1]["c"])


def resolve(s, base: str, ticker: str, direction: str, resolves: str, as_of: str) -> dict | None:
    rows = [r for r in contracts(s, base, ticker, resolves) if r.get("shares_per_contract", 100) == 100]
    if not rows:
        return None
    expiry = min(r["expiration_date"] for r in rows)
    spot = last_close(s, base, ticker, as_of)
    chain = [r for r in rows if r["expiration_date"] == expiry]
    strike = min({float(r["strike_price"]) for r in chain}, key=lambda k: abs(k - spot))
    leg = {r["contract_type"]: r["ticker"] for r in chain if float(r["strike_price"]) == strike}
    return {"underlying": ticker, "last_close": spot, "resolves": resolves, "expiry": expiry, "strike": strike,
            "directional_leg": leg.get("call" if direction == "up_on_yes" else "put"), "call": leg.get("call"), "put": leg.get("put"),
            "strikes_listed": len({float(r["strike_price"]) for r in chain})}


def option_root(ticker: str) -> str:
    return s21cfg.INDEX_ROOT.get(ticker.upper(), f"O:{ticker.upper()}")


def exact_ticket_link(rows: list[dict], ticker: str, level: float, direction: str, window_end: str) -> dict:
    out: dict = {"ok": False, "underlying": ticker.upper(), "option_root": option_root(ticker), "level": level,
                 "direction": direction, "window_end": window_end, "rule": "research/s21_options_anchor/METHOD.md section 3"}
    if direction not in ("up", "down"):
        return {**out, "reason": "no direction: a ticket needs up or down to choose calls or puts"}
    try:
        end = date.fromisoformat(str(window_end)[:10])
    except ValueError:
        return {**out, "reason": "no window end"}
    end_session = s21.last_weekday(end)
    hi = date.fromordinal(end_session.toordinal() + s21cfg.MAX_EXPIRY_GAP_DAYS)
    out["end_session"] = end_session.isoformat()
    kind = "call" if direction == "up" else "put"
    root = out["option_root"]
    chain = [r for r in rows if r.get("contract_type") == kind and str(r.get("ticker", "")).startswith(root)
             and float(r.get("shares_per_contract", 100) or 100) == 100]
    expiries = sorted({str(r["expiration_date"])[:10] for r in chain
                       if end_session.isoformat() <= str(r["expiration_date"])[:10] <= hi.isoformat()})
    if not expiries:
        return {**out, "reason": f"no listed {kind} expiry from {end_session.isoformat()} to {hi.isoformat()} (45 days)"}
    tried = []
    for exp in expiries[:s21cfg.MAX_EXPIRY_TRIES]:
        legs = {float(r["strike_price"]): r["ticker"] for r in chain if str(r["expiration_date"])[:10] == exp}
        strikes = sorted(legs)
        ij = s21.bracket_indices(strikes, float(level))
        tried.append(exp)
        if ij is None:
            continue
        k_lo, k_hi = strikes[ij[0]], strikes[ij[1]]
        long_k, short_k = (k_lo, k_hi) if direction == "up" else (k_hi, k_lo)
        return {**out, "ok": True, "reason": "", "expiry": exp, "expiries_tried": tried, "option_type": kind,
                "lower_strike": k_lo, "upper_strike": k_hi, "strike_width": k_hi - k_lo,
                "long_leg": legs[long_k], "short_leg": legs[short_k], "long_strike": long_k, "short_strike": short_k,
                "strikes_listed": len(strikes)}
    return {**out, "expiries_tried": tried, "reason": f"the level {level:g} has no two bracketing listed strikes in the "
                                                      f"first {len(tried)} expiries"}


def resolve_exact(s, base: str, ticker: str, level: float, direction: str, window_end: str) -> dict:
    try:
        end_session = s21.last_weekday(date.fromisoformat(str(window_end)[:10])).isoformat()
    except ValueError:
        return exact_ticket_link([], ticker, level, direction, window_end)
    underlying = "SPX" if ticker.upper() == "SPX" else ticker.upper()
    return exact_ticket_link(contracts(s, base, underlying, end_session, s21cfg.MAX_EXPIRY_GAP_DAYS), ticker, level, direction, window_end)


def main() -> int:
    from .benchmark import OUT
    s, base = d4._massive_session()
    as_of = "2026-10-02"
    out = []
    for question, ticker, direction, resolves in EXAMPLES:
        try:
            r = resolve(s, base, ticker, direction, resolves, as_of)
        except Exception as e:
            r = None
            print("failed:", ticker, repr(e)[:120].replace(s.headers["Authorization"], "<key>"))
        out.append({"question": question, "ticker": ticker, "direction": direction, **(r or {"expiry": "no listed contract found"})})
    OUT.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    for r in out:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(OUT / "option_examples.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(out)
    for r in out:
        print(f"{r['question'][:70]:70} | {r['ticker']} {r['direction']:11} | close {r.get('last_close')} | expiry {r.get('expiry')} | strike {r.get('strike')} | "
              f"{r.get('directional_leg')} | straddle {r.get('call')} + {r.get('put')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
