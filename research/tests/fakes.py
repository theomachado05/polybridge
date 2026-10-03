"""Offline stand-in for MassiveClient. Disclosures come from a dict keyed by tag; market data from FakeMarket."""
from __future__ import annotations


def disclosure(accession: str, cik: str, tickers: list[str], filing_date: str, text: str = "") -> dict:
    return {"accession_number": accession, "cik": cik, "tickers": tickers, "filing_date": filing_date,
            "filing_url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}.txt", "supporting_text": text}


class FakeClient:
    def __init__(self, disclosures: dict[str, list[dict]] | None = None, market=None):
        self.disclosures = disclosures or {}
        self.market = market
        self.calls: list[tuple[str, dict]] = []

    def get_all(self, path: str, params: dict | None = None, max_pages: int = 500) -> list[dict]:
        params = params or {}
        self.calls.append((path, params))
        if path == "/stocks/filings/8-K/vX/disclosures":
            rows = self.disclosures.get(params["tertiary_category"], [])
            lo, hi = params.get("filing_date.gte", "0000"), params.get("filing_date.lte", "9999")
            return [r for r in rows if lo <= r["filing_date"] <= hi]
        if self.market is not None:
            return self.market.get_all(path, params)
        return []

    def get(self, path_or_url: str, params: dict | None = None) -> dict:
        return {"results": self.get_all(path_or_url, params)}
