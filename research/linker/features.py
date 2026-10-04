"""Inputs of the link scorer, version 2 (heldout2/PLAN.md section 2.4): everything known about a link before its own
equity-against-odds data are used. Works on any frame with the columns question, ticker, confidence, two_models,
links_on_question, days, odds_mean_abs_move, odds_share_nights_1pt, odds_share_between_10_and_90 and, where the
labellers gave one, impact_pct.

    version 1   the labellers' confidence, two models agreeing, links on the question, how alive the odds are, days
    instrument  its family (from linker/instruments.json) and the sd of its daily returns before 2025-10-01
    size        the stated move on full resolution, and that move in units of the instrument's daily sd
    text        deadline, numeric threshold, price proxy, length, theme and a keyword mechanism class

Nothing here reads a price dated 2025-10-01 or later, or any column derived from the link's gap regression.
build(df) returns raw inputs (NaN where unknown); imputation and the choice of columns belong to linker/scorer2.py.

Run from `research/`:  python -m linker.features   (prints the inputs of the training links, summarised)
"""
from __future__ import annotations

import re
import sys

import numpy as np
import pandas as pd

from s5_big_moves import granular as g5

from . import instruments, store

CUTOFF = "2025-10-01"
MIN_SESSIONS = 15
FORBIDDEN = ("gap_t", "gap_bp_per_point", "verdict", "intraday_bp_per_point", "intraday_t", "nights_10pt", "gap_on_10pt_nights_bp",
             "nights_with_a_move", "days_since_cutoff", "gap_t_since_cutoff", "gap_bp_per_point_since_cutoff", "verdict_since_cutoff")

FAMILY_OF_CLASS = {
    "crypto": "crypto", "broad_us": "broad", "volatility": "broad",
    "oil_gas": "commodity", "oil_companies_tankers": "commodity", "gold_metals": "commodity", "agriculture": "commodity",
    "rates_short": "rates", "rates_long": "rates", "credit": "rates", "rate_sensitive_equity": "rates", "banks": "rates",
    "dollar_fx": "fx",
    "china": "country", "asia_other": "country", "europe": "country", "latin_america": "country", "middle_east_africa": "country",
    "canada_australia": "country",
}
FAMILIES = ("commodity", "rates", "fx", "country", "sector", "single_stock", "crypto", "broad")

# First match wins, and only for questions s5_big_moves.granular.theme_of leaves as "Other".
EXTRA_THEMES = (
    ("AI and big tech", ("ai model", "gemini", "openai", "anthropic", "chatgpt", "nvidia", "apple", "google", "meta ", "spacex")),
    ("Crypto, other", ("ethereum", "crypto", "stablecoin", "clarity act", "solana", "xrp", "coinbase")),
    ("Trade and tariffs", ("tariff", "trade deal", "trade war")),
    ("Middle East, other", ("israel", "gaza", "hamas", "houthi", "bab el-mandeb", "red sea", "lebanon", "hezbollah", "saudi", "syria")),
    ("Oil and commodities", ("oil", "crude", "opec", "gold", "natural gas", "gas price")),
    ("Elections and leaders", ("election", "win the", "midterm", "balance of power", "president", "prime minister", "leader out",
                               " out as ", " out by ", " out before ", " out in ", "nominee", "senate", "house")),
)
THEMES = tuple(n for n, _ in g5.THEMES) + tuple(n for n, _ in EXTRA_THEMES) + ("Other",)

MECHANISMS = ("commodity_supply", "rates_policy", "fx_macro", "country_election", "regulation_sector", "company_specific",
              "crypto_policy", "war_geopolitics", "trade_tariffs", "other")
_W = {
    "crypto": r"bitcoin|ethereum|crypto|stablecoin|clarity act|satoshi|microstrategy|solana|\bxrp\b|coinbase",
    "rates": r"\bfed\b|interest rate|rate cut|rate hike|fomc|\bbps\b|treasury|yield|powell",
    "tariff": r"tariff|trade deal|trade war|export control|import",
    "oil": r"\boil\b|crude|opec|hormuz|kharg|blockade|bab el-mandeb|strait|refiner|pipeline|natural gas|\blng\b",
    "war": r"iran|israel|russia|ukraine|strike|invade|invasion|\bwar\b|ceasefire|military|nato|airspace|clash|regime|missile|"
           r"nuclear|enrichment|uranium|peace deal|conflict|taiwan|venezuela|maduro|cuba|gaza|houthi",
    "election": r"election|win the|midterm|balance of power|president|prime minister|leader out|\bout as\b|\bout by\b|\bout before\b|"
                r"\bout in\b|nominee|\bsenate\b|\bhouse\b|chancellor|parliament|referendum|impeach",
    "company": r"\bai model\b|gemini|openai|anthropic|tesla|tiktok|apple|google|microsoft|meta\b|nvidia|amazon|spacex|launch|release|"
               r"ipo\b|acquire|merger|\bsale\b|earnings|ceo",
    "regulation": r"\bact\b|\blaw\b|\bban\b|moratorium|regulat|approve|\bfda\b|antitrust|supreme court|ruling|bill\b|executive order",
}
_RX = {k: re.compile(v) for k, v in _W.items()}
DEADLINE = re.compile(r"\bby\b|\bbefore\b|\bthrough\b|\bend of\b|\bin 20\d\d\b")
THRESHOLD = re.compile(r"\$\s?[\d,.]+|\d+\s?\+?\s?bps|\d+(\.\d+)?\s?%|\b\d+\s+(fed\s+)?rate\s+(cuts|hikes)|\b\d{2,}(,\d{3})+\b|\b\d+(\.\d+)?\s?(k|m|b|million|billion|trillion)\b")
PRICE_PROXY = re.compile(r"\breach\b|\bdip to\b|all[- ]time high|market cap|largest company|sells? any bitcoin|close (above|below)|"
                         r"price of|\babove \$|\bbelow \$|move any bitcoin")


def family_of(ticker: str) -> str:
    """One of FAMILIES: by the instrument's class, and for the other classes a single stock unless it is a fund."""
    t = str(ticker).upper()
    cls = instruments.class_of(t)
    if cls in FAMILY_OF_CLASS:
        return FAMILY_OF_CLASS[cls]
    info = instruments.load()["tickers"].get(t)
    if info is None or info.get("type") in ("CS", "ADRC"):
        return "single_stock"
    return "sector"


def theme_of(question: str) -> str:
    th = g5.theme_of(str(question))
    if th != "Other":
        return th
    q = f" {str(question).lower()} "
    for name, words in EXTRA_THEMES:
        if any(w in q for w in words):
            return name
    return "Other"


def mechanism_of(question: str, family: str) -> str:
    """A mechanism class from keywords in the question and the instrument's family, so every row has one without a labeller."""
    q = str(question).lower()
    hit = {k: bool(r.search(q)) for k, r in _RX.items()}
    if hit["crypto"] or family == "crypto" and not (hit["war"] or hit["rates"]):
        return "crypto_policy"
    if hit["rates"]:
        return "rates_policy"
    if hit["tariff"]:
        return "trade_tariffs"
    if family == "commodity" and (hit["oil"] or hit["war"]):
        return "commodity_supply"
    if hit["war"] or hit["oil"]:
        return "war_geopolitics"
    if hit["election"]:
        return "country_election"
    if hit["company"]:
        return "company_specific"
    if hit["regulation"]:
        return "regulation_sector"
    if family == "fx":
        return "fx_macro"
    return "other"


def pre_window_vol(ticker: str) -> float:
    """sd of daily close-to-close log returns over sessions dated before 2025-10-01; NaN with fewer than 15 sessions."""
    d = store.npz(f"day_{str(ticker).upper()}.npz")
    if d is None or "day" not in d or "c" not in d:
        return float("nan")
    day, c = np.asarray(d["day"]).astype(str), np.asarray(d["c"], float)
    order = np.argsort(day, kind="stable")
    day, c = day[order], c[order]
    keep = (day < CUTOFF) & np.isfinite(c) & (c > 0)
    c = c[keep]
    if len(c) < MIN_SESSIONS:
        return float("nan")
    return float(np.std(np.diff(np.log(c)), ddof=1))


def _col(df: pd.DataFrame, name: str) -> np.ndarray:
    return df[name].to_numpy(float) if name in df else np.full(len(df), np.nan)


def build(df: pd.DataFrame) -> pd.DataFrame:
    """Every candidate input, one row per link, index aligned with df. NaN where a value is unknown."""
    vol_cache: dict[str, float] = {}
    tickers = df.ticker.astype(str).str.upper()
    for t in tickers.unique():
        vol_cache[t] = pre_window_vol(t)
    q = df.question.astype(str)
    fam = tickers.map(family_of)
    vol = tickers.map(vol_cache).to_numpy(float)
    imp = np.abs(_col(df, "impact_pct"))
    imp[imp <= 0] = np.nan
    th = q.map(theme_of)
    mech = [mechanism_of(a, b) for a, b in zip(q, fam)]
    out = pd.DataFrame(index=df.index)
    out["confidence"] = _col(df, "confidence")
    out["two_models"] = _col(df, "two_models")
    out["log_mean_abs_move"] = np.log1p(_col(df, "odds_mean_abs_move"))
    out["share_nights_1pt"] = _col(df, "odds_share_nights_1pt")
    out["share_between_10_and_90"] = _col(df, "odds_share_between_10_and_90")
    out["log_days"] = np.log(np.clip(_col(df, "days"), 1, None))
    out["links_on_question"] = _col(df, "links_on_question")
    for f in FAMILIES:
        out[f"family_{f}"] = (fam == f).to_numpy(float)
    out["log_vol"] = np.log(vol)
    out["log_impact"] = np.log1p(imp)
    out["impact_missing"] = np.isnan(imp).astype(float)
    out["log_size_over_vol"] = np.log1p(imp / 100.0 / vol)
    out["has_deadline"] = q.str.lower().map(lambda s: bool(DEADLINE.search(s))).to_numpy(float)
    out["has_threshold"] = q.str.lower().map(lambda s: bool(THRESHOLD.search(s))).to_numpy(float)
    out["price_proxy"] = q.str.lower().map(lambda s: bool(PRICE_PROXY.search(s))).to_numpy(float)
    out["log_words"] = np.log(q.str.split().str.len().clip(lower=1).to_numpy(float))
    for t in THEMES:
        out[f"theme_{_slug(t)}"] = (th == t).to_numpy(float)
    for m in MECHANISMS:
        out[f"mech_{m}"] = np.array([x == m for x in mech], float)
    return out


def labels(df: pd.DataFrame) -> pd.DataFrame:
    """The readable categories behind the one-hot inputs: family, theme, mechanism class."""
    fam = df.ticker.astype(str).str.upper().map(family_of)
    return pd.DataFrame({"family": fam, "theme_v2": df.question.astype(str).map(theme_of),
                         "mechanism_class_rule": [mechanism_of(a, b) for a, b in zip(df.question.astype(str), fam)]}, index=df.index)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


# Groups of inputs that enter or leave the model together (scorer2 selects among them).
V1 = ("confidence", "two_models", "log_mean_abs_move", "share_nights_1pt", "share_between_10_and_90", "log_days", "links_on_question")
GROUPS: dict[str, tuple[str, ...]] = {
    "family": tuple(f"family_{f}" for f in FAMILIES),
    "volatility": ("log_vol",),
    "impact": ("log_impact", "impact_missing"),
    "size_over_vol": ("log_size_over_vol", "impact_missing"),
    "deadline": ("has_deadline",),
    "threshold": ("has_threshold",),
    "price_proxy": ("price_proxy",),
    "length": ("log_words",),
    "theme": tuple(f"theme_{_slug(t)}" for t in THEMES),
    "mechanism": tuple(f"mech_{m}" for m in MECHANISMS),
}


def main() -> int:
    from .scorer2 import training_table
    df = training_table()
    x = build(df)
    pd.set_option("display.width", 200)
    print(x.describe().T[["count", "mean", "std", "min", "max"]].round(3).to_string())
    print(labels(df).apply(lambda s: s.value_counts().to_dict()).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
