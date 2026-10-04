"""Pin existing headline rows and independently audit S17 concentration.

Run from research/: .venv/bin/python -m cx5_strategy_selection.compare
This comparison deliberately preserves each study's Sharpe convention.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

RESULTS = Path(__file__).resolve().parents[1] / "results"
OUT = RESULTS / "cx5_strategy_selection"


def read_table(relative: str, manifest: dict) -> list[dict]:
    path = RESULTS / relative
    raw = path.read_bytes()
    manifest[relative] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    return list(csv.DictReader(io.StringIO(raw.decode())))


def exactly_one(rows: list[dict], **filters) -> dict:
    matches = [r for r in rows if all(r.get(k) == str(v) for k, v in filters.items())]
    if len(matches) != 1:
        raise ValueError(f"Expected one row for {filters}; found {len(matches)}")
    return matches[0]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest: dict = {}
    selected = []

    def add(study: str, row: dict, kind: str, assessment: str) -> None:
        selected.append({"study": study, "sharpe_definition": kind,
                         "evidence_assessment": assessment, "source_row": row})

    s1 = read_table("s1_twin_spread/metrics.csv", manifest)
    for cost in ("1.0", "2.0"):
        add("S1 cross-venue twins", exactly_one(s1, quote_rule="registered", segment="OOS", variant="V0", cost_mult=cost),
            "Daily modeled mid marks on fixed $3,300; annualized sqrt(365)",
            "Print support is sparse and asynchronous; current IPO rules reveal payoff mismatch")
    s6 = read_table("s6_monday_fade/metrics.csv", manifest)
    for cost in ("1.0", "2.0"):
        add("S6 Monday options anchor", exactly_one(s6, segment="OOS", variant="V0", cost_mult=cost),
            "Closure-level returns; annualized sqrt(51)",
            "Only one OOS 1x entry has print support; no OOS 2x entry has support")
    s11 = read_table("s11_bundles/metrics.csv", manifest)
    for cost in ("1.0", "2.0"):
        s11_row = exactly_one(s11, study="violation, exit at gap close or result", segment="OOS", entries="all", cost_mult=cost)
        add("S11 logical violations", s11_row,
            "Eventual modeled P&L attributed to entry dates; annualized daily diagnostic",
            f"Current source row: {s11_row['verified']}/{s11_row['trades']} print-supported; "
            "later-same-day entry ranking; not a complete daily NAV. "
            "The separate audit distinguishes archived and updated source generations.")
    s17 = read_table("s17_first_minute/metrics.csv", manifest)
    for segment in ("IS", "OOS"):
        for cost in ("1", "2"):
            add("S17 continuation variant", exactly_one(s17, trade="T2", threshold="5", segment=segment, cost_mult=cost),
                "Daily mean of concurrent trade returns including idle sessions; sqrt(252)",
                "Real stock NBBO, but positive only in recent segment and concentrated in one question")
    s18 = read_table("s18_price_market_calibration/prints_book.csv", manifest)
    for segment in ("IS", "OOS", "ALL"):
        add("S18 traded-price sellers", exactly_one(s18, book="sellers", segment=segment),
            "P&L in result months / ex-post peak locked principal; annualized sqrt(12)",
            "Actual traded-price observational cohort; all-market recent premium not positive")
    s19 = read_table("s19_crypto_price_markets/book.csv", manifest)
    for segment in ("IS", "OOS", "ALL"):
        add("S19 crypto sellers", exactly_one(s19, book="sellers", segment=segment),
            "P&L in result months / ex-post peak locked principal; annualized sqrt(12)",
            "Broader print-based replication has no full-period seller premium")

    trades = read_table("s17_first_minute/trades.csv", manifest)
    concentration = []
    for cost in ("1", "2"):
        subset = [r for r in trades if r["trade"] == "T2" and r["threshold"] == "5"
                  and r["segment"] == "OOS" and r["cost_mult"] == cost]
        by_question: dict[str, float] = defaultdict(float)
        by_date: dict[str, float] = defaultdict(float)
        for row in subset:
            by_question[row["question"]] += float(row["pnl"])
            by_date[row["day"]] += float(row["pnl"])
        total = sum(float(r["pnl"]) for r in subset)
        top_question, top_pnl = max(by_question.items(), key=lambda x: x[1])
        concentration.append({"cost_mult": cost, "trades": len(subset), "dates": len(by_date),
                              "pnl_usd_fixed_10000_each_trade": total,
                              "mean_net_bp": sum(float(r["net_bp"]) for r in subset) / len(subset),
                              "largest_question": top_question, "largest_question_pnl": top_pnl,
                              "largest_question_share": top_pnl / total,
                              "three_largest_dates_share": sum(sorted(by_date.values(), reverse=True)[:3]) / total})
        expected = exactly_one(s17, trade="T2", threshold="5", segment="OOS", cost_mult=cost)
        # Published source tables round values; this verifies their reported P&L.
        assert abs(total - float(expected["pnl_usd"])) < 0.02

    snapshot = {"run_utc": datetime.now(timezone.utc).isoformat(),
                "purpose": "Evidence comparison on exposed history; not fresh validation",
                "headline_rows": selected, "s17_concentration": concentration,
                "s11_print_supported_rows": [
                    exactly_one(s11, study="violation, exit at gap close or result",
                                segment=segment, entries="print-verified", cost_mult="1.0")
                    for segment in ("ALL", "OOS")],
                "inputs": manifest,
                "pending": ["S21 study in progress; no finished result used"]}
    (OUT / "comparison_snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n")
    print(json.dumps({"rows_pinned": len(selected), "source_tables": len(manifest),
                      "s17_largest_question_share": concentration[0]["largest_question_share"]}))


if __name__ == "__main__":
    main()
