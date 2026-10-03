"""Write backend/app/data/gap_evidence.json: which markets' expected-gap numbers are validated out of sample, and what
the closed-market research found about each hedge (the product's evidence gate, app/closed/evidence.py).

Reads only committed research results (no data is fetched, no statistic is recomputed):

- research/results/gap_model/tests.json (R2): per-market out-of-sample verdicts. The pre-set rule (research/gap_model/
  METHOD.md): sign accuracy > 50% with binomial p < 0.05 AND slope of realized on predicted > 0 with permutation
  p < 0.05. The two leadlag_closed panel markets are labelled "election" / "recession" there (research/leadlag_closed/
  config.py); the 10 replication markets by their slugs.
- research/results/closed_hedge/results.json (R1): hedge A (PM contract over the closure) and hedge B (equity order
  at the open) variance reductions, with the replication-panel run of hedge A.
- research/results/open_options/stats.json (R3): options catch-up at the Monday open and the net residual gap.
- research/results/leadlag_replication/tests.json: the overnight-gap relation on 10 new markets.

    cd backend && uv run python scripts/build_gap_evidence.py
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "research" / "results"
OUT = ROOT / "backend" / "app" / "data" / "gap_evidence.json"
RATES = ROOT / "backend" / "app" / "data" / "gap_rates.json"

# research/leadlag_closed labels -> the gap_rates.json market keys (Polymarket slugs). The Polymarket numeric id of
# the recession market (gamma-api.polymarket.com/markets?slug=us-recession-in-2025&closed=true) is 516710.
PANEL_A = {"election": "will-donald-trump-win-the-2024-us-presidential-election", "recession": "us-recession-in-2025"}
POLYMARKET_IDS = {"us-recession-in-2025": "516710"}
PASS = "Accurate out of sample"


def _market_row(label: str, d: dict, panel: str) -> dict:
    g1, g2 = d.get("g1") or {}, d.get("g2") or {}
    return {"label": label, "panel": panel, "verdict": d.get("verdict"), "validated": d.get("verdict") == PASS,
            "n_test": d.get("n_test"), "sign_k": g1.get("k"), "sign_n": g1.get("n"), "sign_rate": g1.get("rate"),
            "sign_p": g1.get("p"), "slope": g2.get("c"), "slope_hc3_t": g2.get("t"), "slope_p_perm": g2.get("p_perm")}


def build() -> dict:
    r2 = json.loads((RESULTS / "gap_model" / "tests.json").read_text())
    r1 = json.loads((RESULTS / "closed_hedge" / "results.json").read_text())
    r3 = json.loads((RESULTS / "open_options" / "stats.json").read_text())
    rep = json.loads((RESULTS / "leadlag_replication" / "tests.json").read_text())
    rates = json.loads(RATES.read_text()).get("markets") or {}

    markets: dict[str, dict] = {}
    for label, d in (r2["primary"]["SPY"].get("by_market") or {}).items():
        slug = PANEL_A.get(label, label)
        markets[slug] = _market_row(label, d, "leadlag_closed (panel A, 380 unselected closures)")
    for slug, d in ((r2.get("panel_b") or {}).get("by_market") or {}).items():
        markets[slug] = _market_row(slug, d, "leadlag_replication (panel B, 10 rule-selected markets)")
    for slug, row in markets.items():
        e = rates.get(slug) or {}
        row["token_id"] = e.get("token_id")
        row["question"] = e.get("question")
        if slug in POLYMARKET_IDS:
            row["polymarket_id"] = POLYMARKET_IDS[slug]

    t = r1["primary"]["tests"]
    a, b, b08 = t["A"], t["B"], t["B08"]
    ra = r1.get("replication") or {}
    pm = r3["primary"]
    s1 = rep["s1"]
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "generator": "backend/scripts/build_gap_evidence.py",
        "rule": "validated = the market's own out-of-sample record passes R2's pre-set rule (research/gap_model/METHOD.md): "
                "sign accuracy > 50% with binomial p < 0.05 and slope of realized on predicted gap > 0 with permutation "
                "p < 0.05. Every other market's expected gap is an unvalidated estimate.",
        "sources": {"r2": "research/results/gap_model/tests.json", "r1": "research/results/closed_hedge/results.json",
                    "r3": "research/results/open_options/stats.json",
                    "replication": "research/results/leadlag_replication/tests.json"},
        "r2_pooled": {"verdict": r2["primary"]["SPY"]["verdict"], "panel_b_verdict": (r2.get("panel_b") or {}).get("verdict"),
                      "panel_b_sign_rate": ((r2.get("panel_b") or {}).get("g1") or {}).get("rate"),
                      "panel_b_slope": ((r2.get("panel_b") or {}).get("g2") or {}).get("c")},
        "markets": markets,
        "hedge_a": {"verdict": a["verdict"], "n": a["n"], "vr0": a["VR0"], "vr0_ci": [a["VR0_lo"], a["VR0_hi"]],
                    "vrs": a["VRS"], "vrs_ci": [a["VRS_lo"], a["VRS_hi"]],
                    "replication_verdict": ra.get("verdict"), "replication_vr0": ra.get("VR0"),
                    "replication_vr0_ci": [ra.get("VR0_lo"), ra.get("VR0_hi")]},
        "hedge_b": {"verdict": b["verdict"], "n": b["n"], "vr0": b["VR0"], "vr0_ci": [b["VR0_lo"], b["VR0_hi"]],
                    "vrs": b["VRS"], "vrs_ci": [b["VRS_lo"], b["VRS_hi"]], "window": "09:30 to 10:00 ET",
                    "pre_market_variant": {"verdict": b08["verdict"], "vr0": b08["VR0"],
                                           "vr0_ci": [b08["VR0_lo"], b08["VR0_hi"]]}},
        "opportunity": {"verdict": r3["verdict"], "n": pm["n"], "closures": pm["clusters"], "catchup": pm["beta"],
                        "catchup_ci": pm["beta_ci"], "net_gap_pt": 100 * pm["g_net"]["mean"],
                        "net_gap_ci_pt": [100 * x for x in pm["g_net"]["mean_ci"]]},
        "overnight_gap_replication": {"verdict": rep["verdict"], "slope_bp_per_pp": s1["b"], "p_perm": s1["p_perm"],
                                      "n": s1["n"], "n_markets": rep["n_markets"]},
    }


def main() -> int:
    doc = build()
    OUT.write_text(json.dumps(doc, indent=1) + "\n")
    ok = [k for k, v in doc["markets"].items() if v["validated"]]
    print(f"{len(doc['markets'])} markets, validated: {ok} -> {OUT.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
