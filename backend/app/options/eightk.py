"""8-K signal for the Opportunity division: ``eightk_score(ticker)`` in [-1, 1], 0 when there is no qualifying filing.

Data: the pre-registered tag families from the v3 research (research/HYPOTHESIS_TAGS.md, mirrored in
``polybridge_research.schema``):

- H1 hedge tags (litigation, class action, regulatory investigation, cybersecurity incident, goodwill / asset /
  investment impairment) are slow-burning bad news  -> negative score;
- H2 opportunity tags (restructuring plan, workforce reduction, facility closure, business-line exit) are
  restructurings the chain tends to over-fear -> positive score;
- a filing carrying tags from both families is ambiguous about its side (research rule 2) -> it does not qualify;
- other tags (atlas-only) do not qualify.

Mapping: the most recent qualifying filing on or before ``as_of`` and within ``window_days`` gives
``score = sign(family) * (1 - age_days / window_days)``: +/-1 on the filing day, decaying linearly to 0 at the
window's edge. With the default 30-day window the C++ ``eightk_opportunity`` thresholds 0.3 / 0.5 / 0.7 mean
"filed within 21 / 15 / 9 days". The score is a direction prior from the tag taxonomy, not a measured edge: the
in-sample H1/H2 tests were null (research/results/in_sample/*_verdict.txt).

Sources, in order: filings passed in by the caller; the bundled ``app/data/eightk_filings.json`` (in-sample
2024-01-01..2025-12-31, written by ``build_eightk_file`` from the research's Massive disclosures); live Massive
disclosures for recent dates, loaded into a process-wide store by ``await refresh_eightk()`` (never inside the
frozen out-of-sample window 2026-01-01..2026-08-31; that guard is enforced here).

"No filing" vs "no data": ``eightk_score`` returns 0.0 only when the data covering ``as_of`` was loaded and holds
no qualifying filing. When nothing covers ``as_of`` (a live date before ``refresh_eightk`` ran, no key, a Massive
outage, or a date inside the frozen OOS window) it returns NaN, the MarketTick default, which the C++ EightK
signal reads as "no signal". ``eightk_coverage(as_of)`` names the source ("in_sample" | "live" | None).
"""
from __future__ import annotations

import datetime as dt
import json
import math
import time
from pathlib import Path
from typing import Any, Iterable

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "eightk_filings.json"
WINDOW_DAYS = 30
OOS_START, OOS_END = dt.date(2026, 1, 1), dt.date(2026, 8, 31)   # HYPOTHESIS.md: never touched before the freeze
IN_SAMPLE = ("2024-01-01", "2025-12-31")
DISCLOSURES = "/stocks/filings/8-K/vX/disclosures"

H1_TAGS = frozenset({"material_litigation", "class_action_filing", "regulatory_investigation",
                     "cybersecurity_incident", "goodwill_impairment", "asset_impairment", "investment_impairment"})
H2_TAGS = frozenset({"restructuring_plan", "workforce_reduction", "facility_closure", "business_line_exit"})
FAMILY_SIGN = {"hedge": -1.0, "opportunity": 1.0}


class OOSWindowError(ValueError):
    """A request would read 8-K data inside the frozen out-of-sample window."""


def family_of(tags: Iterable[str]) -> str | None:
    """'hedge' | 'opportunity' | None (no family tag, or both: ambiguous). Same rule as research assign_family."""
    t = set(tags or ())
    h1, h2 = bool(t & H1_TAGS), bool(t & H2_TAGS)
    if h1 and not h2:
        return "hedge"
    if h2 and not h1:
        return "opportunity"
    return None


def _date(x: Any) -> dt.date | None:
    if x is None:
        return None
    if isinstance(x, dt.datetime):
        return x.date()
    if isinstance(x, dt.date):
        return x
    try:
        return dt.date.fromisoformat(str(x)[:10])
    except ValueError:
        return None


def _norm(t: Any) -> str:
    return str(t or "").strip().upper().replace("/", ".")


_FILE_CACHE: list[dict] | None = None


def load_filings(path: Path = DATA_FILE) -> list[dict]:
    """Bundled filings [{ticker, filing_date, tags, family, accession_number}]; [] when the file is missing."""
    global _FILE_CACHE
    if path == DATA_FILE and _FILE_CACHE is not None:
        return _FILE_CACHE
    try:
        rows = json.loads(path.read_text()).get("filings", [])
    except (OSError, ValueError, AttributeError):
        rows = []
    if path == DATA_FILE:
        _FILE_CACHE = rows
    return rows


def latest_filing(ticker: str, filings: Iterable[dict], as_of: Any = None,
                  window_days: int = WINDOW_DAYS) -> dict | None:
    """Most recent qualifying filing for ``ticker`` on or before ``as_of`` and within ``window_days``."""
    tk = _norm(ticker)
    a = _date(as_of) or dt.date.today()
    best: tuple[dt.date, dict] | None = None
    for f in filings or ():
        if not isinstance(f, dict) or _norm(f.get("ticker")) != tk:
            continue
        d = _date(f.get("filing_date"))
        fam = f.get("family") or family_of(f.get("tags") or ())
        if d is None or fam not in FAMILY_SIGN or d > a or (a - d).days > window_days:
            continue
        if best is None or d > best[0]:
            best = (d, {**f, "family": fam})
    return best[1] if best else None


def score_filing(filing: dict | None, as_of: Any = None, window_days: int = WINDOW_DAYS) -> float:
    if not filing or window_days <= 0:
        return 0.0
    d, a = _date(filing.get("filing_date")), _date(as_of) or dt.date.today()
    sign = FAMILY_SIGN.get(filing.get("family") or family_of(filing.get("tags") or ()) or "", 0.0)
    if d is None or sign == 0.0 or d > a:
        return 0.0
    age = (a - d).days
    if age > window_days:
        return 0.0
    s = sign * (1.0 - age / window_days)
    return max(-1.0, min(1.0, s)) if math.isfinite(s) else 0.0


# Live filings loaded by refresh_eightk(): {"filings": [...], "from": date, "to": date, "window_days": int, "at": ts}
_LIVE: dict[str, Any] = {}
LIVE_TTL_S = 3600.0


def _in_sample_covers(a: dt.date) -> bool:
    return dt.date.fromisoformat(IN_SAMPLE[0]) <= a <= dt.date.fromisoformat(IN_SAMPLE[1])


def _live_covers(a: dt.date, window_days: int) -> bool:
    if not _LIVE:
        return False
    need_from = max(a - dt.timedelta(days=window_days), OOS_END + dt.timedelta(days=1))
    return _LIVE["from"] <= need_from and _LIVE["to"] >= a


def eightk_coverage(as_of: Any = None, window_days: int = WINDOW_DAYS) -> str | None:
    """Which loaded data covers ``as_of``: "in_sample", "live", or None (score would be NaN)."""
    a = _date(as_of) or dt.date.today()
    if _in_sample_covers(a):
        return "in_sample"
    if a > OOS_END and _live_covers(a, window_days):
        return "live"
    return None


def _rows_for(as_of: dt.date) -> list[dict]:
    rows = list(load_filings())
    if as_of > OOS_END and _LIVE:
        rows += _LIVE["filings"]
    return rows


def eightk_score(ticker: str, as_of: Any = None, window_days: int = WINDOW_DAYS,
                 filings: Iterable[dict] | None = None) -> float:
    """[-1, 1]; 0.0 when the data covering ``as_of`` holds no qualifying filing; NaN when no loaded data covers
    ``as_of`` (see module docstring). With ``filings`` given, that list is the whole truth (0.0 if none). Never
    raises."""
    try:
        a = _date(as_of) or dt.date.today()
        if filings is not None:
            rows = list(filings)
        elif eightk_coverage(a, window_days) is None:
            return math.nan
        else:
            rows = _rows_for(a)
        return score_filing(latest_filing(ticker, rows, a, window_days), a, window_days)
    except Exception:
        return math.nan


def eightk_detail(ticker: str, as_of: Any = None, window_days: int = WINDOW_DAYS,
                  filings: Iterable[dict] | None = None) -> dict:
    a = _date(as_of) or dt.date.today()
    cov = "caller" if filings is not None else eightk_coverage(a, window_days)
    rows = list(filings) if filings is not None else _rows_for(a)
    f = latest_filing(ticker, rows, a, window_days) if cov else None
    score = score_filing(f, a, window_days) if cov else None
    return {"ticker": _norm(ticker), "as_of": a.isoformat(), "window_days": window_days, "score": score,
            "coverage": cov,
            "filing": None if f is None else {k: (sorted(v) if isinstance(v, (set, frozenset, list)) else v)
                                              for k, v in f.items()}}


async def refresh_eightk(as_of: Any = None, window_days: int = WINDOW_DAYS, client=None) -> str | None:
    """Load live 8-K filings for the ``window_days`` before ``as_of`` (default today) into the shared store that
    ``eightk_score`` reads (bounded, TTL ``LIVE_TTL_S``; never inside the OOS window). Returns the coverage for
    ``as_of`` afterwards. No key or an outage leaves the store as it was: never raises."""
    a = _date(as_of) or dt.date.today()
    if a <= OOS_END:
        return eightk_coverage(a, window_days)
    if _live_covers(a, window_days) and time.time() - _LIVE.get("at", 0.0) < LIVE_TTL_S:
        return "live"
    try:
        from ..chain import bounded, make_client
        client = client if client is not None else make_client()
        if client is None:
            return eightk_coverage(a, window_days)
        live = await bounded(fetch_recent, client, a, window_days)
    except Exception:
        return eightk_coverage(a, window_days)
    _LIVE.clear()
    _LIVE.update(filings=list(live), to=a, window_days=window_days, at=time.time(),
                 **{"from": max(a - dt.timedelta(days=window_days), OOS_END + dt.timedelta(days=1))})
    return eightk_coverage(a, window_days)


# ---------------------------------------------------------------- data (Massive disclosures)

def check_window(start: Any, end: Any) -> None:
    """Raise OOSWindowError if [start, end] overlaps the frozen out-of-sample window."""
    s, e = _date(start), _date(end)
    if s is None or e is None:
        raise ValueError("bad date range")
    if s <= OOS_END and e >= OOS_START:
        raise OOSWindowError(f"{s}..{e} overlaps the frozen 8-K out-of-sample window {OOS_START}..{OOS_END}")


def rows_to_filings(rows: Iterable[dict]) -> list[dict]:
    """Massive disclosure rows (one per tag) -> one record per (accession, ticker) with its tag set and family."""
    acc: dict[tuple[str, str], dict] = {}
    for r in rows or ():
        tag = r.get("tertiary_category") or r.get("tag")
        tickers = r.get("tickers") or ([r["ticker"]] if r.get("ticker") else [])
        an = str(r.get("accession_number") or "")
        d = _date(r.get("filing_date"))
        if not tag or not an or d is None:
            continue
        for t in tickers:
            tk = _norm(t)
            if not tk:
                continue
            rec = acc.setdefault((an, tk), {"ticker": tk, "filing_date": d.isoformat(), "accession_number": an,
                                            "tags": set()})
            rec["tags"].add(str(tag))
    out = []
    for rec in acc.values():
        fam = family_of(rec["tags"])
        out.append({**rec, "tags": sorted(rec["tags"]), "family": fam})
    return sorted(out, key=lambda f: (f["filing_date"], f["ticker"], f["accession_number"]))


def fetch_disclosure_rows(get_all, start: str, end: str) -> list[dict]:
    """All H1/H2 disclosure rows in [start, end] via ``get_all(path, params)``; OOS-guarded."""
    check_window(start, end)
    rows: list[dict] = []
    for tag in sorted(H1_TAGS | H2_TAGS):
        for r in get_all(DISCLOSURES, {"tertiary_category": tag, "filing_date.gte": start, "filing_date.lte": end,
                                       "limit": 1000, "sort": "filing_date.asc"}) or []:
            rows.append({**r, "tertiary_category": tag})
    return rows


def fetch_recent(client, as_of: Any = None, window_days: int = WINDOW_DAYS) -> list[dict]:
    """Live filings for the last ``window_days`` (start clamped to after the OOS window). Sync; run via a thread."""
    a = _date(as_of) or dt.date.today()
    start = max(a - dt.timedelta(days=window_days), OOS_END + dt.timedelta(days=1))
    if start > a:
        return []
    return rows_to_filings(fetch_disclosure_rows(client.get_all, start.isoformat(), a.isoformat()))


def build_eightk_file(client, out: Path = DATA_FILE) -> int:
    """Write the in-sample filings file (research window only). Returns the number of filings written."""
    filings = [f for f in rows_to_filings(fetch_disclosure_rows(client.get_all, *IN_SAMPLE)) if f["family"]]
    payload = {"source": "Massive /stocks/filings/8-K/vX/disclosures (research H1/H2 tags)",
               "window": list(IN_SAMPLE), "built_at": dt.date.today().isoformat(),
               "note": "in-sample only; the out-of-sample window 2026-01-01..2026-08-31 is never read",
               "mapping": "hedge (H1) -> negative, opportunity (H2) -> positive, both -> excluded",
               "filings": filings}
    out.write_text(json.dumps(payload, separators=(",", ":")))
    return len(filings)


if __name__ == "__main__":  # uv run --env-file ../.env python -m app.options.eightk [cache_dir]
    import sys

    from polybridge_research.massive import MassiveClient, load_api_key

    cache = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[3] / "research" / ".massive_cache"
    n = build_eightk_file(MassiveClient(load_api_key(interactive=False), cache_dir=cache))
    print(f"wrote {n} filings to {DATA_FILE}")
