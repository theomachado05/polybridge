"""Expected open gap = rate x oriented prediction-market move since the last regular close, with a band.

Rate source, in order:

1. ``backend/app/data/gap_rates.json`` (written by research/gap_model/run.py): a per-market rate fitted on that market's
   own unselected closures, used when it rests on at least ``n_min`` (20) closures with a non-zero move (the file's
   ``use: "own"``).
2. Otherwise the pooled rate: the file's ``pooled`` entry, or, with no file, the research placebo slope
   (research/results/leadlag_closed/SUMMARY.md: +7.52 bp of SPY gap per pp of oriented PM move, 380 unselected
   closures, HC3 t +2.58, so se = 7.52 / 2.58 = 2.92). Labelled "pooled".

Which pooled rate (open decision, see POOLED_FROM_FILE): with the file present, its ``pooled`` entry is used: the
same through-origin estimator the pre-registered out-of-sample test (research/gap_model/METHOD.md) validated, over
1591 unselected closures in 12 markets (0.81 bp/pp, se 0.55, tau 4.23 in the 2026-10-03 export). That is about nine
times smaller than the 7.52 bp/pp headline in the plan, so unlisted markets show much smaller expected gaps and hedge B
sizes. Setting POOLED_FROM_FILE = False keeps the file's per-market rates but uses the research placebo slope (7.52)
as the pooled rate. Every response names the rate's ``source`` and ``n_closures`` either way.

Band (the file's ``band_rule``, research/gap_model/METHOD.md): 80% band = expected gap +- z80 * sqrt(x^2 * se_eff^2 +
resid_sd^2), x = oriented move in pp. se_eff = the market's se for its own rate; for the pooled rate (a market with too
few closures, or not listed) se_eff = sqrt(pooled se^2 + tau^2), tau = the between-market SD of rates: the wide band.
With no file: resid_sd 58.49 bp (residual SD of the placebo regression) and tau 8.62 bp/pp (SD of the two placebo
panels' own rates, -1.46 and +10.73), both computed from research/results/leadlag_closed/closures_all.csv.

Orientation: rates apply to the ORIENTED move x = sign * (YES now - YES at close), in pp; positive x = equity-bullish.
A listed market carries its research sign. Otherwise the sign comes from the proposal direction (up_on_yes +1,
down_on_yes -1); with neither, +1 is assumed and the reason GAP_ORIENTATION_ASSUMED is attached.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from .tracker import ClosureState

DATA = Path(__file__).resolve().parents[1] / "data"
GAP_RATES_PATH = DATA / "gap_rates.json"

POOLED_RATE = 7.523237932200106   # research/results/leadlag_closed/tests.json p1_t2.b
POOLED_T = 2.5780622896081757     # p1_t2.t (HC3)
POOLED_SE = POOLED_RATE / POOLED_T
POOLED_N = 380
POOLED_N_NONZERO = 256
POOLED_RESID_SD = 58.49011796037221
POOLED_TAU = 8.621704972717438
POOLED_SOURCE = "research/results/leadlag_closed/SUMMARY.md (placebo closures, SPY gap on oriented PM move)"
N_MIN = 20
# Pooled-rate source when gap_rates.json exists: True = the file's pooled entry (current choice), False = the research
# placebo slope POOLED (7.52 bp/pp, 380 closures). Pinned by tests/test_closed_gap.py; change it only on a decision.
POOLED_FROM_FILE = True
Z80 = 1.2816
BAND_LEVEL = 0.80
BASIS_TICKER = "SPY"

# Reason codes.
GAP_MARKET_RATE = "GAP_MARKET_RATE"            # per-market rate from gap_rates.json
GAP_POOLED_RATE = "GAP_POOLED_RATE"            # market not listed: pooled rate, wide band
GAP_TOO_FEW_CLOSURES = "GAP_TOO_FEW_CLOSURES"  # listed with too few closures (or no se): pooled rate, wide band
GAP_ORIENTATION_ASSUMED = "GAP_ORIENTATION_ASSUMED"  # no research sign and no direction: YES assumed equity-bullish
GAP_PROXY_TICKER = "GAP_PROXY_TICKER"          # the rate was estimated on another ticker's gap (SPY)
GAP_NOT_IN_CLOSURE = "GAP_NOT_IN_CLOSURE"      # regular session in progress: no expected gap
GAP_NO_MOVE = "GAP_NO_MOVE"                    # PM move unknown (no close anchor or no current price)


@dataclass(frozen=True)
class GapRate:
    rate_bp_per_pp: float           # per pp of ORIENTED move
    se: float
    n_closures: int
    n_nonzero: int
    label: str                      # "market" | "pooled"
    source: str
    resid_sd_bp: float
    se_eff: float                   # se used for the band (pooled: sqrt(se^2 + tau^2))
    sign: int | None = None         # research orientation of a listed market
    ticker: str = BASIS_TICKER      # the equity whose gap the rate was estimated on
    use: str | None = None          # the file's "own" | "pooled" decision for a listed market

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
    """Parsed gap_rates.json (or nothing: the research pooled rate only)."""

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
    """Re-read on every call: the file is small and research/gap_model may rewrite it while the server runs."""
    return GapRates.load(path)


def choose_rate(rates: GapRates, market_source: str, market_id: str, ticker: str | None = None,
                token_id: str | None = None) -> tuple[GapRate, GapRate | None, list[str]]:
    """(rate used, the market's own entry or None, reason codes). Own rate only with >= n_min non-zero closures,
    a finite se, and not marked use=pooled by the file."""
    m = rates.lookup(market_source, market_id, ticker, token_id)
    if m is None:
        return rates.pooled, None, [GAP_POOLED_RATE]
    if m.use == "pooled" or m.n_nonzero < rates.n_min or not math.isfinite(m.se):
        return rates.pooled, m, [GAP_TOO_FEW_CLOSURES]
    return m, m, [GAP_MARKET_RATE]


def direction_sign(direction: str | None) -> int | None:
    """+1 for up_on_yes (YES is equity-bullish), -1 for down_on_yes, None when unknown."""
    return {"up_on_yes": 1, "down_on_yes": -1}.get(direction or "")


@dataclass(frozen=True)
class ExpectedGap:
    market_key: str
    ticker: str
    basis_ticker: str
    label: str                       # "market" | "pooled"
    rate_bp_per_pp: float
    se: float
    se_eff: float
    resid_sd_bp: float
    band_rate: tuple[float, float]   # rate +- z * se_eff, bp per pp
    band_level: float
    z: float
    n_closures: int
    n_nonzero: int
    source: str
    move_pp: float | None            # raw YES move since the last close, pp
    sign: int                        # orientation applied to the move
    oriented_move_pp: float | None
    expected_gap_bp: float | None    # None outside a closure or without a move
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
    """Pure: expected gap (bp) = rate x sign x move; band = gap +- z * sqrt(x^2 se_eff^2 + resid_sd^2)."""
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
    """The expected gap for a tracked market at the tracker state's instant (P5 calls this per tick or per summary)."""
    rates = rates if rates is not None else load_rates()
    rate, own, reasons = choose_rate(rates, market_source, market_id, ticker, token_id)
    sign = own.sign if own is not None and own.sign is not None else direction_sign(direction)
    if sign is None:
        sign = 1
        reasons.append(GAP_ORIENTATION_ASSUMED)
    return expected_gap(state.move_pp, rate, sign=sign, in_closure=state.session.closed, market_key=state.key,
                        ticker=ticker, reasons=reasons, z=rates.z)


def rate_for(mkey: str, token_id: str | None = None, rates: GapRates | None = None) -> GapRate | None:
    """The per-market rate for a tracker key ``"<source>:<id>"`` when it is usable on its own (>= n_min closures,
    finite se), else None: the caller then uses the pooled rate. The P3 staged-order book calls this."""
    source, _, mid = (mkey or "").partition(":")
    if not mid:
        return None
    rate, _, _ = choose_rate(rates if rates is not None else load_rates(), source, mid, None, token_id)
    return rate if rate.label == "market" else None
