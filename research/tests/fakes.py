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


import datetime as _dt

import pandas as _pd


def _occ(underlying: str, expiry: _pd.Timestamp, kind: str, strike: float) -> str:
    return f"O:{underlying}{expiry:%y%m%d}{'C' if kind == 'call' else 'P'}{int(round(strike * 1000)):08d}"


class FakeMarket:

    def __init__(self, spot_by_ticker: dict[str, float], start: str = "2023-01-02", end: str = "2026-12-31"):
        self.spot = spot_by_ticker
        self.days = _pd.bdate_range(start, end)

    def _expiries(self, as_of: _pd.Timestamp) -> list[_pd.Timestamp]:
        fridays = _pd.date_range(as_of, as_of + _pd.Timedelta(days=200), freq="W-FRI")
        return list(fridays)

    def _contracts(self, underlying: str, as_of: _pd.Timestamp, lo: _pd.Timestamp, hi: _pd.Timestamp) -> list[dict]:
        s = self.spot[underlying]
        strikes = [round(s * (1 + k / 100), 2) for k in range(-40, 41, 5)]
        out = []
        for exp in self._expiries(as_of):
            if not (lo <= exp <= hi):
                continue
            for k in strikes:
                for kind in ("call", "put"):
                    out.append({"ticker": _occ(underlying, exp, kind, k), "contract_type": kind, "strike_price": k,
                                "expiration_date": exp.strftime("%Y-%m-%d"), "shares_per_contract": 100})
        return out

    def _bars(self, opt: str, start: _pd.Timestamp, end: _pd.Timestamp) -> list[dict]:
        body = opt[2:]
        und = body[: len(body) - 15]
        if und == "ILLQ":
            return []
        kind = "call" if body[-9] == "C" else "put"
        strike = int(body[-8:]) / 1000
        s = self.spot[und]
        price = max(s - strike, 0.0) + 1.0 if kind == "call" else max(strike - s, 0.0) + 1.0
        rows = []
        for d in self.days[(self.days >= start) & (self.days <= end)]:
            ms = int(_dt.datetime(d.year, d.month, d.day, 20, 0, tzinfo=_dt.timezone.utc).timestamp() * 1000)
            rows.append({"t": ms, "c": price, "v": 50})
        return rows

    def get_all(self, path: str, params: dict) -> list[dict]:
        if path == "/v3/reference/options/contracts":
            return self._contracts(params["underlying_ticker"], _pd.Timestamp(params["as_of"]),
                                   _pd.Timestamp(params["expiration_date.gte"]), _pd.Timestamp(params["expiration_date.lte"]))
        if path.startswith("/v2/aggs/ticker/"):
            parts = path.split("/")
            return self._bars(parts[4], _pd.Timestamp(parts[8]), _pd.Timestamp(parts[9]))
        return []
