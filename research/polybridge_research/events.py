from __future__ import annotations

import pandas as pd

from .calendar import TradingCalendar
from .schema import H1_TAGS, H2_TAGS, assign_family, normalize_ticker

DISCLOSURES = "/stocks/filings/8-K/vX/disclosures"
_BASE_COLS = ["ticker", "cik", "filing_date", "accession_number", "filing_url", "supporting_text", "tags", "t_0", "t_pre"]


def fetch_disclosures(client, tag: str, start: str, end: str) -> pd.DataFrame:
    rows = client.get_all(DISCLOSURES, {"tertiary_category": tag, "filing_date.gte": start, "filing_date.lte": end,
                                        "limit": 1000, "sort": "filing_date.asc"})
    df = pd.DataFrame(rows)
    if not df.empty:
        df["filing_date"] = pd.to_datetime(df["filing_date"])
        df["tag"] = tag
    return df


def _in_universe(raw: pd.DataFrame, universe) -> pd.DataFrame:
    raw = raw.copy()

    if "tickers" not in raw.columns:
        if "ticker" not in raw.columns:
            return pd.DataFrame(columns=list(raw.columns) + ["ticker"])
        raw["tickers"] = raw["ticker"].apply(lambda x: [x] if pd.notna(x) and x else [])
        raw = raw.drop("ticker", axis=1)

    def has_valid_tickers(x):
        return isinstance(x, list) and len(x) > 0

    raw = raw[raw["tickers"].apply(has_valid_tickers)]

    if raw.empty:
        cols = [c for c in raw.columns if c != "tickers"] + ["ticker"]
        return pd.DataFrame(columns=cols)

    ex = raw.explode("tickers").rename(columns={"tickers": "ticker"})
    ex["ticker"] = ex["ticker"].map(normalize_ticker)
    return ex[ex["ticker"].isin(set(universe))]


def _per_filing(ex: pd.DataFrame) -> pd.DataFrame:
    return (ex.sort_values(["cik", "filing_date"])
              .groupby("accession_number", as_index=False)
              .agg(ticker=("ticker", "first"), cik=("cik", "first"), filing_date=("filing_date", "first"),
                   filing_url=("filing_url", "first"), supporting_text=("supporting_text", "first"),
                   tags=("tag", lambda s: frozenset(s))))


def _collapse(per_filing: pd.DataFrame, keys: list[str], cal: TradingCalendar) -> pd.DataFrame:
    ev = (per_filing.sort_values(["cik", "filing_date", "accession_number"])
                    .groupby(keys, as_index=False)
                    .agg(ticker=("ticker", "first"), accession_number=("accession_number", "first"),
                         filing_url=("filing_url", "first"), supporting_text=("supporting_text", "first"),
                         tags=("tags", lambda s: frozenset().union(*s)))
                    .sort_values(["filing_date", "ticker"]).reset_index(drop=True))
    ev["t_0"] = ev["filing_date"].map(cal.on_or_after)
    ev["t_pre"] = ev["t_0"].map(cal.before)
    return ev


def build_confirmatory_events(client, start: str, end: str, universe, cal: TradingCalendar) -> tuple[pd.DataFrame, pd.DataFrame]:
    frames = [f for f in (fetch_disclosures(client, t, start, end) for t in sorted(H1_TAGS | H2_TAGS)) if not f.empty]
    empty_ev = pd.DataFrame(columns=_BASE_COLS + ["family"])
    empty_ex = pd.DataFrame(columns=["accession_number", "ticker", "filing_date", "tags"])
    if not frames:
        return empty_ev, empty_ex
    ex = _in_universe(pd.concat(frames, ignore_index=True), universe)
    if ex.empty:
        return empty_ev, empty_ex
    pf = _per_filing(ex)
    fam = pf["tags"].map(assign_family)
    excluded = pf[fam.isna()][["accession_number", "ticker", "filing_date", "tags"]].reset_index(drop=True)
    keep = pf[fam.notna()].assign(family=fam[fam.notna()].map(lambda f: f.value))
    if keep.empty:
        return empty_ev, excluded
    ev = _collapse(keep, ["cik", "filing_date", "family"], cal)
    return ev[_BASE_COLS + ["family"]], excluded


def build_tag_events(client, tag: str, start: str, end: str, universe, cal: TradingCalendar) -> pd.DataFrame:
    raw = fetch_disclosures(client, tag, start, end)
    if raw.empty:
        return pd.DataFrame(columns=_BASE_COLS)
    ex = _in_universe(raw, universe)
    if ex.empty:
        return pd.DataFrame(columns=_BASE_COLS)
    return _collapse(_per_filing(ex), ["cik", "filing_date"], cal)[_BASE_COLS]
