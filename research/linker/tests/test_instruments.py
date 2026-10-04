"""Offline checks on the written linker/instruments.json, and on validate_off_menu against a fake Massive."""
from __future__ import annotations

import pytest
import requests

from linker import instruments as I

built = pytest.mark.skipif(not I.OUT.exists(), reason="instruments.json not built")


@built
def test_every_required_ticker_has_a_class():
    assert I.required() - set(I.load()["tickers"]) == set()


@built
def test_spy_is_classed_but_never_listed():
    d = I.load()
    assert d["tickers"]["SPY"]["class"] == "broad_us"
    assert not I.on_menu("SPY")
    assert all(r["ticker"] != "SPY" for rows in d["classes"].values() for r in rows)


@built
def test_no_duplicates_and_classes_agree_with_tickers():
    d = I.load()
    listed = [(c, r["ticker"]) for c, rows in d["classes"].items() for r in rows]
    names = [t for _, t in listed]
    assert len(names) == len(set(names))
    assert all(d["tickers"][t]["class"] == c for c, t in listed)
    assert all(set(r) == {"ticker", "name"} for rows in d["classes"].values() for r in rows)


@built
def test_order_follows_the_candidate_list():
    for c, rows in I.load()["classes"].items():
        cand = I.candidates()[c]
        idx = [cand.index(r["ticker"]) for r in rows]
        assert idx == sorted(idx)


@built
def test_lookups():
    assert I.class_of("uso") == "oil_gas"
    assert I.class_of("NOT_A_TICKER") == "single_stock"
    assert I.on_menu("USO") and not I.on_menu("NOT_A_TICKER")
    t = I.load()["tickers"]["USO"]
    assert set(t) == {"class", "name", "type", "has_options"} and isinstance(t["has_options"], bool)


class _Resp:
    def __init__(self, code: int, body: dict | None = None):
        self.status_code, self._body = code, body or {}

    def json(self) -> dict:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} for fake url")


class _Fake:
    """Massive's reference endpoints as seen live: hyphenated tickers are a 400, reused tickers come back active."""
    TICKERS = {"BRK.B": {"name": "Berkshire Hathaway Inc.", "type": "CS", "active": True, "list_date": "1996-05-09",
                         "primary_exchange": "XNYS"},
               "FB": {"name": "ProShares S&P 500 Dynamic Buffer ETF", "type": "ETF", "active": True,
                      "list_date": "2025-06-24", "primary_exchange": "BATS"}}

    def __init__(self):
        self.calls: list[str] = []

    def get(self, url: str, params: dict | None = None, timeout: int = 30) -> _Resp:
        self.calls.append(url)
        if url.endswith("/options/contracts"):
            return _Resp(200, {"results": [{}] if params["underlying_ticker"] == "BRK.B" else []})
        t = url.rsplit("/", 1)[1]
        if "-" in t or "/" in t:
            return _Resp(400)
        if t == "VIX":
            return _Resp(403)
        return _Resp(200, {"results": self.TICKERS[t]}) if t in self.TICKERS else _Resp(404)


@pytest.fixture
def fake(tmp_path, monkeypatch):
    monkeypatch.setattr(I, "REF", tmp_path / "reference.json")
    return _Fake()


def test_off_menu_class_shares_and_refusals(fake):
    got = I.validate_off_menu("brk-b", fake, "https://x")
    assert got["ticker"] == "BRK.B" and got["has_options"] and not got["recent_listing"]
    assert I.validate_off_menu("BRK/B", fake, "https://x")["ticker"] == "BRK.B"
    assert I.validate_off_menu("VIX", fake, "https://x") is None
    assert I.validate_off_menu("ZZZZ", fake, "https://x") is None
    assert I._cache()["VIX"]["served"] is False
    n = len(fake.calls)
    assert I.validate_off_menu("VIX", fake, "https://x") is None and len(fake.calls) == n


def test_off_menu_flags_a_reused_ticker(fake):
    got = I.validate_off_menu("FB", fake, "https://x")
    assert got["name"].startswith("ProShares") and got["recent_listing"]
    assert got["list_date"] == "2025-06-24" and got["primary_exchange"] == "BATS"
    assert I.recent("") and not I.recent("2010-01-01")


def test_old_cache_row_is_refetched_for_its_date(fake):
    I._save_cache({"FB": {"served": True, "name": "Meta", "type": "CS", "active": True, "has_options": True}})
    assert I.validate_off_menu("FB", fake, "https://x")["name"].startswith("ProShares")
