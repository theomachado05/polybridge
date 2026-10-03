"""Question parsing and universe filters (METHOD.md section 1). Pure functions."""
from __future__ import annotations

import re
from dataclasses import dataclass

_TICKER = re.compile(r"\(([A-Z][A-Z0-9.]{0,5})\)")
_STRIKE = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)")
_EXCLUDE = re.compile(r"\b(hit|hits|reach|reaches|dip|dips|between|below|under|up or down|market cap|earnings|bitcoin|ethereum|btc|eth)\b", re.I)
_ABOVE = re.compile(r"\b(close|closes|closing|finish|finishes|end|ends)\b.*\babove\b|\babove\b.*\b(close|closes|finish|end)\b", re.I)


@dataclass(frozen=True)
class Threshold:
    ticker: str
    strike: float
    kind: str          # daily | weekly | monthly | other


def parse_pm_question(question: str, event_title: str = "") -> tuple[Threshold | None, str]:
    """Returns (Threshold, "") when the market is an in-scope 'close above $K' threshold, else (None, reason)."""
    q = question or ""
    if _EXCLUDE.search(q):
        return None, "out_of_scope_type"
    if not _ABOVE.search(q):
        return None, "not_above_threshold"
    m_t = _TICKER.search(q) or _TICKER.search(event_title or "")
    if not m_t:
        return None, "no_ticker"
    m_k = _STRIKE.search(q)
    if not m_k:
        return None, "no_strike"
    strike = float(m_k.group(1).replace(",", ""))
    low = q.lower()
    if "week" in low:
        kind = "weekly"
    elif re.search(r"end of (january|february|march|april|may|june|july|august|september|october|november|december)", low):
        kind = "monthly"
    elif " on " in low:
        kind = "daily"
    else:
        kind = "other"
    return Threshold(m_t.group(1), strike, kind), ""


KALSHI_UNDERLYING = {"KXINXU": "SPX", "INXU": "SPX", "KXINXAB": "SPX", "INXAB": "SPX",
                     "KXNASDAQ100U": "NDX", "NASDAQ100U": "NDX"}


def kalshi_is_close(event_ticker: str) -> bool:
    """16:00 ET settlement hourlies (`...H1600`) and the daily close series (no hour suffix)."""
    return event_ticker.endswith("H1600") or not re.search(r"H\d{4}$", event_ticker)
