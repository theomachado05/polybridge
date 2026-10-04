from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

import pandas as pd
import requests

from .calendar import TradingCalendar

_CLOSE = pd.Timestamp("16:00").time()


def fetch_acceptance_time(filing_url: str, user_agent: str, cache_dir: Path, session=None,
                          sleep=time.sleep) -> pd.Timestamp | None:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = cache_dir / ("sec_" + hashlib.sha1(filing_url.encode()).hexdigest() + ".txt")
    if key.exists():
        head = key.read_text()
    else:
        resp = (session or requests).get(filing_url, headers={"User-Agent": user_agent}, timeout=30, stream=True)
        resp.raise_for_status()
        head = next(resp.iter_content(4096, decode_unicode=True))
        key.write_text(head)
        sleep(0.12)
    m = re.search(r"<ACCEPTANCE-DATETIME>(\d{14})", head)
    return pd.Timestamp(m.group(1)) if m else None


def _t0(filing_date: pd.Timestamp, accepted: pd.Timestamp | None, cal: TradingCalendar) -> tuple[pd.Timestamp, str]:
    sessions = set(cal.sessions)
    if accepted is not None and not pd.isna(accepted):
        day = accepted.normalize()
        if day in sessions and accepted.time() >= _CLOSE:
            return cal.after(day), "edgar"
        return cal.on_or_after(day), "edgar"
    day = pd.Timestamp(filing_date).normalize()
    return (cal.after(day) if day in sessions else cal.on_or_after(day)), "conservative"


def apply_filing_session(events: pd.DataFrame, cal: TradingCalendar, accepted_at: pd.Series | None = None) -> pd.DataFrame:
    out = events.copy()
    acc = list(accepted_at) if accepted_at is not None else [None] * len(out)
    pairs = [_t0(fd, a, cal) for fd, a in zip(out["filing_date"], acc)]
    out["t_0"] = [p[0] for p in pairs]
    out["timing"] = [p[1] for p in pairs]
    out["t_pre"] = out["t_0"].map(cal.before)
    return out
