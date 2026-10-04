"""S26 link tiers: classify each S14 link by economic link quality from its question text and ticker ONLY.

Fixed before any S26 number is computed (METHOD.md). No result column is read here.
"""
from __future__ import annotations

import re

# Tier A: the question names the asset's own underlying (commodity, rate, coin, currency or the company itself).
OWN_UNDERLYING = {
    **{t: r"\b(oil|crude|wti|brent|opec|hormuz|gasoline|refiner)" for t in ("USO", "XLE", "XOP", "CVX", "VLO", "MPC", "PSX", "STNG", "FRO")},
    **{t: r"\b(fed|fomc|rate|rates|interest|powell|treasury|yield|recession|inflation|cpi)\b" for t in ("SHY", "IEF", "TLT")},
    "GLD": r"\bgold\b", "UUP": r"\b(dollar|usd|dxy)\b",
    **{t: r"\b(bitcoin|btc|crypto)" for t in ("IBIT", "MSTR", "COIN", "HOOD", "GLXY")},
    "MSFT": r"\bmicrosoft\b", "AMZN": r"\bamazon\b", "GOOGL": r"\b(google|alphabet)\b", "ORCL": r"\boracle\b",
    "NVDA": r"\bnvidia\b", "TSLA": r"\btesla\b", "META": r"\bmeta\b|\bfacebook\b", "TSM": r"\b(tsmc|taiwan semiconductor)\b",
    "DJT": r"\b(trump media|truth social|djt)\b", "CRWV": r"\bcoreweave\b", "OKLO": r"\boklo\b", "SMR": r"\bnuscale\b",
    "VRT": r"\bvertiv\b", "ZIM": r"\bzim\b",
}
# Tier B: a country ETF whose country (or bloc) is named in the question.
COUNTRY = {"EPOL": r"\bpoland|polish\b", "VGK": r"\b(europe|european|eu)\b", "EWT": r"\btaiwan\b", "EWU": r"\b(uk|britain|british|england)\b",
           "FXI": r"\bchina|chinese\b", "KWEB": r"\bchina|chinese\b"}


def tier(question: str, ticker: str) -> str:
    q = (question or "").lower()
    if ticker in OWN_UNDERLYING and re.search(OWN_UNDERLYING[ticker], q):
        return "A"
    if ticker in COUNTRY and re.search(COUNTRY[ticker], q):
        return "B"
    return "C"
