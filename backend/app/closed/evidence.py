"""Evidence gate for closed-market numbers (docs/design.md, section 6; research R1, R2, R3).

A closed-market expected gap (and the hedge sized on it) is shown as **validated** only for a market whose OWN
out-of-sample record passes R2's pre-set rule (``backend/app/data/gap_evidence.json``, written by
``scripts/build_gap_evidence.py`` from research/results/gap_model/tests.json). Today that is one market: US recession
in 2025 (sign 64.2% of 151, slope +1.28, permutation p < 0.001). Every other market, including the ten markets of the
replication panel (pooled sign 50.2%, slope -0.23: not accurate), gets an **unvalidated estimate** with its band and
the number of closures behind the rate.

The hedges follow R1: hedge B (an equity order staged for the first tradable moment) cut the post-open variance
(+11.4%, CI +5.1..+18.1) and is the default closed-market action; hedge A (holding the PM contract over the closure)
showed no evidence (+4.8%, CI -0.8..+10.0; it increased the variance on the replication panel), so it is offered only
as an explicit, labelled estimate, off by default, never as protection. Opportunity at the open is research-only (R3:
the net residual gap is NULL).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parents[1] / "data"
EVIDENCE_PATH = DATA / "gap_evidence.json"

VALIDATED = "validated"
UNVALIDATED = "unvalidated estimate"

HEDGE_A_LABEL = ("Estimate only, not protection: simulated prediction-market leg (no Polymarket trading account). "
                 "Research R1 found no evidence that holding the PM contract over a closure reduces the open-gap loss "
                 "(variance reduction +4.8%, 95% CI -0.8% to +10.0%; it increased the variance on the 10-market "
                 "replication panel). Off unless the proposal opts in.")
HEDGE_B_LABEL = ("Default closed-market action: an equity order staged for the first tradable moment, sent only after "
                 "approval. Research R1: it cut the post-open P&L variance by 11.4% (95% CI +5.1% to +18.1%), by timing, "
                 "not direction; it executes after the gap, so it cannot recover the gap itself.")
HEDGE_B_PREMARKET_NOTE = ("This plan executes in the pre-market (the broker supports extended hours): R1's pre-market "
                          "variant (08:00 ET) was only partial (variance reduction +13.2%, CI +3.3% to +25.5%, not "
                          "better than a static hedge); the 09:30 version is the one with evidence.")
OPPORTUNITY_LABEL = ("Research only, not a trade recommendation: options reflected 0.44 of the weekend PM move at the "
                     "Monday open (CI 0.33 to 0.57) but the residual gap net of option costs is NULL (+0.79 pt, CI -1.21 "
                     "to +2.78; R3).")


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> dict:
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def load(path: Path | str | None = None) -> dict:
    """The evidence document ({} when missing: nothing is validated)."""
    p = Path(path) if path is not None else EVIDENCE_PATH
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return {}
    return _load(str(p), mtime)


def _match(doc: dict, market_source: str | None, market_id: str | None, token_id: str | None) -> tuple[str, dict] | None:
    keys = {k for k in (market_id, token_id) if k}
    for slug, row in (doc.get("markets") or {}).items():
        if not isinstance(row, dict):
            continue
        names = {slug, row.get("token_id"), row.get("polymarket_id")} - {None}
        if market_source not in (None, "polymarket"):
            continue  # every studied market is a Polymarket market
        if keys & names:
            return slug, row
    return None


def market_evidence(market_source: str | None, market_id: str | None, token_id: str | None = None,
                    doc: dict | None = None) -> dict:
    """{validated, status, market, evidence (one short reason), oos {...} | None} for one market."""
    doc = load() if doc is None else doc
    hit = _match(doc, market_source, market_id, token_id)
    if hit is None:
        return {"validated": False, "status": UNVALIDATED, "market": None, "token_id": None, "oos": None,
                "evidence": "No out-of-sample test for this market: the expected gap is an unvalidated estimate "
                            "(the pooled rate's band spans both signs; the 10-market replication was not accurate)."}
    slug, row = hit
    oos = {k: row.get(k) for k in ("verdict", "n_test", "sign_k", "sign_n", "sign_rate", "sign_p", "slope",
                                   "slope_p_perm", "panel")}
    if row.get("validated"):
        why = (f"Validated out of sample on this market (R2): sign right in {row.get('sign_k')} of {row.get('sign_n')} "
               f"({100 * (row.get('sign_rate') or 0):.1f}%), slope {row.get('slope'):+.2f} (permutation p "
               f"{_p(row.get('slope_p_perm'))}).")
    else:
        sr, sl = row.get("sign_rate"), row.get("slope")
        why = ("Not validated: this market's own out-of-sample record fails R2's rule"
               + (f" (sign {100 * sr:.1f}% of {row.get('sign_n')}, slope {sl:+.2f})" if sr is not None and sl is not None
                  else "") + "; the expected gap is an unvalidated estimate.")
    return {"validated": bool(row.get("validated")), "status": VALIDATED if row.get("validated") else UNVALIDATED,
            "market": slug, "token_id": row.get("token_id"), "oos": oos, "evidence": why}


def gate(evid: dict, label: str | None, ticker: str | None, basis_ticker: str | None,
         reasons: list[str] | tuple[str, ...] = ()) -> tuple[bool, str, str]:
    """The evidence gate for one expected gap: (validated, status, evidence text).

    ``validated`` needs all three: the market's own out-of-sample record passes R2, its OWN rate is the one in use
    (``label == "market"``), and that rate was estimated on the ticker shown (R2 tested SPY gaps only; any other ticker
    borrows SPY's rate as a proxy). Everything else is an unvalidated estimate, with the reason taken from the rate
    choice's reason codes."""
    from .gap import GAP_POOLED_RATE, GAP_PROXY_TICKER, GAP_TOO_FEW_CLOSURES
    if not evid.get("validated"):
        return False, UNVALIDATED, str(evid.get("evidence") or "")
    reasons = list(reasons or ())
    if label != "market":
        if GAP_TOO_FEW_CLOSURES in reasons:
            why = ("This market passed R2 out of sample, but its own rate is not in use (too few closures or no "
                   "standard error), so the pooled rate gives an unvalidated estimate.")
        elif GAP_POOLED_RATE in reasons:
            why = ("This market passed R2 out of sample, but no per-market rate matched this id, so the pooled rate "
                   "gives an unvalidated estimate.")
        else:
            why = "The market's own rate is not in use, so this is an unvalidated estimate."
        return False, UNVALIDATED, why
    tick = (ticker or "").upper()
    basis = (basis_ticker or "").upper()
    if GAP_PROXY_TICKER in reasons or (tick and basis and tick != basis):
        why = (f"This market's rate was validated out of sample on {basis or 'SPY'} gaps only (R2); {tick or 'this '
               'ticker'} borrows that rate as a proxy, so the number is an unvalidated estimate.")
        return False, UNVALIDATED, why
    return True, VALIDATED, str(evid.get("evidence") or "")


def _p(p: Any) -> str:
    try:
        v = float(p)
    except (TypeError, ValueError):
        return "n/a"
    return "< 0.001" if v < 0.001 else f"{v:.3f}"


def hedge_evidence(doc: dict | None = None) -> dict:
    """R1/R3 headline numbers for the UI's labels."""
    doc = load() if doc is None else doc
    return {"hedge_a": {**(doc.get("hedge_a") or {}), "label": HEDGE_A_LABEL, "default": False},
            "hedge_b": {**(doc.get("hedge_b") or {}), "label": HEDGE_B_LABEL, "default": True},
            "opportunity": {**(doc.get("opportunity") or {}), "label": OPPORTUNITY_LABEL, "research_only": True}}
