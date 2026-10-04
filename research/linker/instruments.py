"""The wider instrument list the version-3 labellers read (PLAN.md section 2.2): US-listed stocks and ETFs by class,
the standard ones first, each checked against Massive's reference data (name, type, active, whether options are
listed). Reference endpoints only: no price or bar is requested here. Answers are cached in
`linker/.cache/reference.json`; `instruments.json` is written next to this file.

An off-list ticker a labeller names goes through validate_off_menu(): class-share hyphens become dots (BRK-B ->
BRK.B), a ticker Massive refuses (400, 403, 404) is None, and the answer carries `list_date`, `primary_exchange` and
`recent_listing`. Tickers get reused (FB is now a ProShares ETF, PARA a Banzai share), so the caller must compare the
returned name with the company the labeller meant and hold a recent listing for a manual check.

Run from `research/`:  python -m linker.instruments   (rebuilds the file; prints counts per class, dropped tickers and
tickers without options)
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

from s1_twin_spread import data as ds
from s5_big_moves.config import MENU

from . import store

HERE = Path(__file__).resolve().parent
OUT = HERE / "instruments.json"
REF = store.NEW / "reference.json"
RESULTS = HERE.parent / "results" / "linker"
AS_OF = "2026-10-03"
RECENT_DAYS = 3 * 365
NOT_SERVED = {400, 403, 404}
HEDGE = "SPY"

CANDIDATES: dict[str, str] = {
    "broad_us": "QQQ IWM DIA",
    "volatility": "VIXY UVXY SVXY",
    "rates_short": "SHY IEI VGSH UTWO",
    "rates_long": "TLT IEF TLH ZROZ",
    "credit": "HYG LQD JNK",
    "rate_sensitive_equity": "KRE XHB ITB XLU IYR XLF AEP AEE ETR",
    "banks": "JPM GS BAC WFC",
    "dollar_fx": "UUP FXE FXY FXB FXC FXA",
    "gold_metals": "GLD SLV GDX CPER COPX PPLT",
    "oil_gas": "USO BNO XLE XOP OIH UNG UGA",
    "oil_companies_tankers": "XOM CVX OXY COP LNG FRO STNG DHT ZIM MPC PSX VLO",
    "agriculture": "DBA CORN WEAT SOYB",
    "uranium_nuclear_power": "URA CCJ CEG VST SMR OKLO LEU",
    "defense": "ITA XAR LMT RTX NOC GD LHX HII KTOS AVAV",
    "airlines_travel": "JETS DAL UAL AAL CCL",
    "crypto": "IBIT ETHA COIN MSTR MARA HOOD RIOT CLSK BMNR GLXY CRCL BITO",
    "semis_ai": "SMH NVDA AMD TSM INTC AVGO MU ASML ARM",
    "big_tech": "XLK AAPL MSFT GOOGL AMZN META ORCL NFLX PLTR CRWV DIS",
    "ai_power_datacenter": "VRT DLR EQIX ETN",
    "tesla_ev_space": "TSLA RIVN RKLB ASTS UBER",
    "health": "XLV XBI UNH PFE MRNA LLY NVO HUM CVS HIMS",
    "consumer_tariff": "XLY XLP XRT WMT COST TGT NKE F GM",
    "industrials_metals": "XLI NUE CLF CAT DE BA AA",
    "clean_energy": "ICLN TAN FSLR ENPH",
    "policy_single_names": "DJT GEO CXW MSOS",
    "china": "FXI KWEB MCHI BABA PDD JD BIDU",
    "asia_other": "EWT EWY EWJ INDA",
    "europe": "VGK EWG EWU EWQ EWI EWP EPOL GREK EWN EWD EWL",
    "latin_america": "EWZ EWW ARGT ECH EPU ILF PBR VALE ITUB YPF GGAL BMA",
    "middle_east_africa": "EIS TUR EZA KSA UAE QAT",
    "canada_australia": "EWC EWA",
}


def candidates() -> dict[str, list[str]]:
    return {c: v.split() for c, v in CANDIDATES.items()}


def required() -> set[str]:
    """Tickers that must have a class: S5's menu and every ticker already scored by the benchmark or held-out test."""
    need = set(MENU)
    for f in ("benchmark.csv", "heldout_links.csv"):
        if (RESULTS / f).exists():
            need |= set(pd.read_csv(RESULTS / f, usecols=["ticker"]).ticker.dropna().astype(str))
    return need


def _scrub(text: str) -> str:
    return re.sub(r"(?i)(bearer\s+|apikey=)[^\s&'\"]+", r"\1***", text)


def _get(s: requests.Session, url: str, params: dict | None = None) -> dict | None:
    """One page of a Massive reference request, with retries; None when Massive refuses the ticker (400, 403, 404)."""
    for attempt in range(8):
        try:
            r = s.get(url, params=params, timeout=30)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            time.sleep(min(2 ** attempt, 20))
            continue
        if r.status_code in ds.RETRY:
            time.sleep(min(2 ** attempt, 20))
            continue
        if r.status_code in NOT_SERVED:
            return None
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Massive kept failing on {url}")


def _cache() -> dict:
    try:
        return json.loads(REF.read_text())
    except (OSError, ValueError):
        return {}


def _save_cache(c: dict) -> None:
    REF.parent.mkdir(parents=True, exist_ok=True)
    REF.write_text(json.dumps(c, indent=0, sort_keys=True))


def reference(ticker: str, s: requests.Session, base: str, cache: dict | None = None, dated: bool = False) -> dict:
    """Massive's answer for one ticker: {served, name, type, active, has_options, list_date, primary_exchange}. Cached;
    with `dated`, a served row cached before list_date was recorded is fetched again."""
    c = _cache() if cache is None else cache
    if ticker in c and not (dated and c[ticker]["served"] and "list_date" not in c[ticker]):
        return c[ticker]
    d = _get(s, f"{base}/v3/reference/tickers/{ticker}")
    res = (d or {}).get("results") or {}
    row = {"served": bool(res), "name": res.get("name", ""), "type": res.get("type", ""),
           "active": bool(res.get("active", False)), "has_options": False,
           "list_date": res.get("list_date", ""), "primary_exchange": res.get("primary_exchange", "")}
    if res:
        o = _get(s, f"{base}/v3/reference/options/contracts", {"underlying_ticker": ticker, "limit": 1})
        row["has_options"] = bool((o or {}).get("results"))
    c[ticker] = row
    if cache is None:
        _save_cache(c)
    return row


def build(session: requests.Session | None = None, base: str | None = None) -> dict:
    """Check every candidate against Massive and write instruments.json. Returns the written dict plus `dropped`."""
    if session is None:
        from s4_linked_assets.data import _massive_session
        session, base = _massive_session()
    cache = _cache()
    if not reference(HEDGE, session, base, {})["served"]:
        raise RuntimeError("Massive does not serve SPY: the key or the endpoint is wrong, nothing written")
    classes: dict[str, list[dict]] = {}
    tickers: dict[str, dict] = {}
    dropped: list[dict] = []
    todo = [(c, t) for c, ts in candidates().items() for t in ts] + [("broad_us", HEDGE)]
    try:
        for cls, t in todo:
            ref = reference(t, session, base, cache)
            if not ref["served"] or not ref["active"]:
                dropped.append({"ticker": t, "class": cls, "why": "not served" if not ref["served"] else "inactive"})
                continue
            tickers[t] = {"class": cls, "name": ref["name"], "type": ref["type"], "has_options": ref["has_options"]}
            if t != HEDGE:
                classes.setdefault(cls, []).append({"ticker": t, "name": ref["name"]})
    finally:
        _save_cache(cache)
    out = {"as_of": AS_OF, "classes": classes, "tickers": tickers}
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    global _LOADED
    _LOADED = None
    return {**out, "dropped": dropped}


_LOADED: dict | None = None


def load() -> dict:
    """instruments.json as written by build()."""
    global _LOADED
    if _LOADED is None:
        _LOADED = json.loads(OUT.read_text())
    return _LOADED


def class_of(ticker: str) -> str:
    """The ticker's class; "single_stock" for a ticker not on the list."""
    t = load()["tickers"].get(str(ticker).upper())
    return t["class"] if t else "single_stock"


def on_menu(ticker: str) -> bool:
    """True when the ticker is listed under a class (SPY, the hedge, is not)."""
    t = str(ticker).upper()
    return any(r["ticker"] == t for rows in load()["classes"].values() for r in rows)


def normalise(ticker: str) -> str:
    """Upper case, class-share separator as Massive writes it: BRK-B and BRK/B become BRK.B."""
    return re.sub(r"[-/]", ".", str(ticker).upper().strip())


def recent(list_date: str, as_of: str = AS_OF) -> bool:
    """True when the listing is less than RECENT_DAYS old, or its date is unknown: a ticker that may have been reused."""
    d = pd.to_datetime(list_date, errors="coerce")
    return bool(pd.isna(d) or (pd.Timestamp(as_of) - d).days < RECENT_DAYS)


def validate_off_menu(ticker: str, session: requests.Session, base: str) -> dict | None:
    """A ticker a labeller named off the list: {ticker, name, type, has_options, list_date, primary_exchange,
    recent_listing} when Massive serves it as active, else None. Cached in reference.json like the candidates.
    The caller must check that `name` is the company the labeller meant (tickers are reused)."""
    t = normalise(ticker)
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", t):
        return None
    ref = reference(t, session, base, dated=True)
    if not ref["served"] or not ref["active"]:
        return None
    return {"ticker": t, "name": ref["name"], "type": ref["type"], "has_options": ref["has_options"],
            "list_date": ref.get("list_date", ""), "primary_exchange": ref.get("primary_exchange", ""),
            "recent_listing": recent(ref.get("list_date", ""))}


def main() -> int:
    try:
        out = build()
    except Exception as e:  # noqa: BLE001
        print("build failed:", _scrub(f"{type(e).__name__}: {e}"))
        return 1
    for cls, rows in out["classes"].items():
        print(f"{cls:24s} {len(rows):3d}")
    print(f"listed {sum(len(r) for r in out['classes'].values())}, with SPY {len(out['tickers'])}")
    print("dropped:", ", ".join(f"{d['ticker']} ({d['why']})" for d in out["dropped"]) or "none")
    print("no options:", ", ".join(t for t, v in out["tickers"].items() if not v["has_options"]) or "none")
    missing = sorted(required() - set(out["tickers"]))
    print("required but unclassed:", ", ".join(missing) or "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
