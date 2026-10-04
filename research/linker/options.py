"""From a link to an option contract: which listed option carries a question's risk.

A link says "this question moves this ticker, this way". The option that carries it is fixed by three rules:
    underlying   the linked ticker
    expiry       the first listed expiry on or after the day the question resolves (so the option is alive when the
                 news lands and expires soon after)
    strike       the listed strike nearest the underlying's last close (at the money)
    structure    a call if the link is up-on-yes, a put if down-on-yes; the straddle (both) when the bet is on the
                 size of the move, not its direction

Contracts come from Massive's reference list. Run from `research/` to print the worked examples:
    python -m linker.options
"""
from __future__ import annotations

import csv
import sys
from datetime import date

from s4_linked_assets import data as d4

from .benchmark import OUT

# (question, ticker, direction, the day the question resolves)
EXAMPLES = (
    ("Will Flávio Bolsonaro win the 2026 Brazilian presidential election? (first round Sun 2026-10-04)", "EWZ", "up_on_yes", "2026-10-05"),
    ("Brazil presidential runoff (Sun 2026-10-25)", "EWZ", "up_on_yes", "2026-10-26"),
    ("Strait of Hormuz traffic returns to normal by December 31?", "USO", "down_on_yes", "2026-12-31"),
    ("Will the U.S. invade Iran before 2027?", "XLE", "up_on_yes", "2026-12-31"),
    ("Will the Fed increase interest rates by 25 bps after the October 2026 meeting? (decision 2026-10-28)", "TLT", "down_on_yes", "2026-10-28"),
)


def contracts(s, base: str, ticker: str, resolves: str, horizon_days: int = 45) -> list[dict]:
    """Listed contracts on the ticker expiring from the resolution day up to `horizon_days` later."""
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
    """The contract(s) for one link: first expiry on or after the resolution day, strike nearest the last close."""
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


def main() -> int:
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
