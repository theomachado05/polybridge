from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from .tracker import ClosureState

DATA = Path(__file__).resolve().parents[1] / "data"
GAP_RATES_PATH = DATA / "gap_rates.json"

POOLED_RATE = 7.523237932200106
POOLED_T = 2.5780622896081757
POOLED_SE = POOLED_RATE / POOLED_T
POOLED_N = 380
POOLED_N_NONZERO = 256
POOLED_RESID_SD = 58.49011796037221
POOLED_TAU = 8.621704972717438
POOLED_SOURCE = "research/results/leadlag_closed/SUMMARY.md (placebo closures, SPY gap on oriented PM move)"
N_MIN = 20
POOLED_FROM_FILE = True
Z80 = 1.2816
BAND_LEVEL = 0.80
BASIS_TICKER = "SPY"

GAP_MARKET_RATE = "GAP_MARKET_RATE"
GAP_POOLED_RATE = "GAP_POOLED_RATE"
GAP_TOO_FEW_CLOSURES = "GAP_TOO_FEW_CLOSURES"
GAP_ORIENTATION_ASSUMED = "GAP_ORIENTATION_ASSUMED"
GAP_PROXY_TICKER = "GAP_PROXY_TICKER"
GAP_NOT_IN_CLOSURE = "GAP_NOT_IN_CLOSURE"
GAP_NO_MOVE = "GAP_NO_MOVE"


@dataclass(frozen=True)
class GapRate:
    rate_bp_per_pp: float
    se: float
    n_closures: int
    n_nonzero: int
    label: str
    source: str
    resid_sd_bp: float
    se_eff: float
    sign: int | None = None
    ticker: str = BASIS_TICKER
    use: str | None = None

    def band_rate(self, z: float = Z80) -> tuple[float, float]:
        return self.rate_bp_per_pp - z * self.se_eff, self.rate_bp_per_pp + z * self.se_eff


POOLED = GapRate(POOLED_RATE, POOLED_SE, POOLED_N, POOLED_N_NONZERO, "pooled", POOLED_SOURCE, POOLED_RESID_SD,
                 math.sqrt(POOLED_SE ** 2 + POOLED_TAU ** 2))


def _num(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _first(d: dict, *names: str) -> Any:
    for n in names:
        if d.get(n) is not None:
            return d[n]
    return None


def _entry(d: Any, label: str, source: str, resid_default: float) -> GapRate | None:
    if not isinstance(d, dict):
        return None
    rate = _num(_first(d, "rate_bp_per_pp", "rate", "bp_per_pp", "b", "slope"))
    if rate is None:
        return None
    se = _num(_first(d, "se", "rate_se"))
    if se is None:
        t = _num(_first(d, "t", "b_t"))
        se = abs(rate / t) if t else None
    se = se if se is not None and se > 0 else float("nan")
    n = _num(_first(d, "n_closures", "n"))
    nz = _num(d.get("n_nonzero"))
    resid = _num(_first(d, "resid_sd_bp", "resid_sd"))
    sign = _num(d.get("sign"))
    tick = d.get("etf") or d.get("ticker") or BASIS_TICKER
    return GapRate(rate, se, int(n or 0), int(nz if nz is not None else (n or 0)), label, source,
                   resid if resid is not None else resid_default, se,
                   sign=int(math.copysign(1, sign)) if sign else None, ticker=str(tick).upper(),
                   use=d.get("use") if isinstance(d.get("use"), str) else None)


class GapRates:

    def __init__(self, pooled: GapRate = POOLED, markets: dict[str, GapRate] | None = None, n_min: int = N_MIN,
                 z: float = Z80, source: str | None = None) -> None:
        self.pooled = pooled
        self.markets = markets or {}
        self.n_min = n_min
        self.z = z
        self.source = source

    @classmethod
    def load(cls, path: Path | str | None = None) -> "GapRates":
        p = Path(path) if path is not None else GAP_RATES_PATH
        try:
            doc = json.loads(p.read_text())
        except (OSError, ValueError):
            return cls()
        return cls.from_doc(doc, source=f"backend/app/data/{p.name}")

    @classmethod
    def from_doc(cls, doc: Any, source: str = "gap_rates.json") -> "GapRates":
        if not isinstance(doc, dict):
            return cls()
        n_min = int(_num(doc.get("n_min")) or N_MIN)
        z = _num(doc.get("z80")) or Z80
        pooled = POOLED
        pe = _entry(doc.get("pooled"), "pooled", source, POOLED_RESID_SD) if POOLED_FROM_FILE else None
        if pe is not None and math.isfinite(pe.se):
            tau = _num(doc.get("tau_bp_per_pp"))
            tau = tau if tau is not None else POOLED_TAU
            pooled = replace(pe, se_eff=math.sqrt(pe.se ** 2 + tau ** 2), sign=None, use=None)
        markets: dict[str, GapRate] = {}
        raw = doc.get("markets") or {}
        items = (list(raw.items()) if isinstance(raw, dict)
                 else [(None, e) for e in raw] if isinstance(raw, list) else [])
        for key, e in items:
            g = _entry(e, "market", source, pooled.resid_sd_bp)
            if g is None:
                continue
            names = {str(key)} if key else set()
            src = e.get("market_source") or e.get("source")
            for k in ("key", "market_key", "market_id", "id", "token_id", "condition_id", "slug", "market_slug"):
                v = e.get(k)
                if v:
                    names.add(str(v))
                    if src and k not in ("key", "market_key"):
                        names.add(f"{src}:{v}")
            for nm in names:
                markets[nm] = g
        return cls(pooled, markets, n_min, z, source)

    def lookup(self, market_source: str, market_id: str, ticker: str | None = None,
               token_id: str | None = None) -> GapRate | None:
        cands: list[str] = []
        for i in [market_id] + ([token_id] if token_id else []):
            if ticker:
                cands += [f"{market_source}:{i}:{ticker.upper()}", f"{i}:{ticker.upper()}"]
            cands += [f"{market_source}:{i}", i]
        for c in cands:
            if c in self.markets:
                return self.markets[c]
        return None


def load_rates(path: Path | str | None = None) -> GapRates:
    return GapRates.load(path)


def choose_rate(rates: GapRates, market_source: str, market_id: str, ticker: str | None = None,
                token_id: str | None = None) -> tuple[GapRate, GapRate | None, list[str]]:
    m = rates.lookup(market_source, market_id, ticker, token_id)
    if m is None:
        return rates.pooled, None, [GAP_POOLED_RATE]
    if m.use == "pooled" or m.n_nonzero < rates.n_min or not math.isfinite(m.se):
        return rates.pooled, m, [GAP_TOO_FEW_CLOSURES]
    return m, m, [GAP_MARKET_RATE]


def direction_sign(direction: str | None) -> int | None:
    return {"up_on_yes": 1, "down_on_yes": -1}.get(direction or "")


@dataclass(frozen=True)
class ExpectedGap:
    market_key: str
    ticker: str
    basis_ticker: str
    label: str
    rate_bp_per_pp: float
    se: float
    se_eff: float
    resid_sd_bp: float
    band_rate: tuple[float, float]
    band_level: float
    z: float
    n_closures: int
    n_nonzero: int
    source: str
    move_pp: float | None
    sign: int
    oriented_move_pp: float | None
    expected_gap_bp: float | None
    band_bp: tuple[float, float] | None
    active: bool
    reasons: list[str]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["band_rate"] = list(self.band_rate)
        d["band_bp"] = list(self.band_bp) if self.band_bp else None
        return d


def expected_gap(move_pp: float | None, rate: GapRate, *, sign: int = 1, in_closure: bool = True,
                 market_key: str = "", ticker: str | None = None, reasons: list[str] | None = None,
                 z: float = Z80) -> ExpectedGap:
    reasons = list(reasons or [])
    tick = (ticker or rate.ticker).upper()
    if tick != rate.ticker and GAP_PROXY_TICKER not in reasons:
        reasons.append(GAP_PROXY_TICKER)
    x = None if move_pp is None else sign * move_pp
    gap = band = None
    if not in_closure:
        reasons.append(GAP_NOT_IN_CLOSURE)
    elif x is None:
        reasons.append(GAP_NO_MOVE)
    else:
        gap = rate.rate_bp_per_pp * x
        hw = z * math.sqrt(x * x * rate.se_eff ** 2 + rate.resid_sd_bp ** 2)
        band = (gap - hw, gap + hw)
    return ExpectedGap(market_key=market_key, ticker=tick, basis_ticker=rate.ticker, label=rate.label,
                       rate_bp_per_pp=rate.rate_bp_per_pp, se=rate.se, se_eff=rate.se_eff,
                       resid_sd_bp=rate.resid_sd_bp, band_rate=rate.band_rate(z), band_level=BAND_LEVEL if z == Z80
                       else math.erf(z / math.sqrt(2)), z=z, n_closures=rate.n_closures, n_nonzero=rate.n_nonzero,
                       source=rate.source, move_pp=move_pp, sign=sign, oriented_move_pp=x, expected_gap_bp=gap,
                       band_bp=band, active=gap is not None, reasons=reasons)


def expected_gap_for(state: ClosureState, market_source: str, market_id: str, *, ticker: str | None = None,
                     direction: str | None = None, token_id: str | None = None,
                     rates: GapRates | None = None) -> ExpectedGap:
    rates = rates if rates is not None else load_rates()
    rate, own, reasons = choose_rate(rates, market_source, market_id, ticker, token_id)
    sign = own.sign if own is not None and own.sign is not None else direction_sign(direction)
    if sign is None:
        sign = 1
        reasons.append(GAP_ORIENTATION_ASSUMED)
    return expected_gap(state.move_pp, rate, sign=sign, in_closure=state.session.closed, market_key=state.key,
                        ticker=ticker, reasons=reasons, z=rates.z)


def rate_for(mkey: str, token_id: str | None = None, rates: GapRates | None = None) -> GapRate | None:
    source, _, mid = (mkey or "").partition(":")
    if not mid:
        return None
    rate, _, _ = choose_rate(rates if rates is not None else load_rates(), source, mid, None, token_id)
    return rate if rate.label == "market" else None
