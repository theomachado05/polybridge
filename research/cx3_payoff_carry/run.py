"""Local-only evidence audit. Never opens forward/raw or sealed OOS.

Run from research/: .venv/bin/python -m cx3_payoff_carry.run
The only numerical arrays opened are timestamps. S1 numerical results are an
explicitly reused, already-published baseline audit, not a new strategy trial.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import os
import subprocess
import time

_CACHE = Path(__file__).resolve().parent / ".cache"
_CACHE.mkdir(exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_CACHE / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(_CACHE / "xdg"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from . import config as cfg

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
RESULTS = RESEARCH / "results" / HERE.name
FREEZE_COMMIT = "6e33ff0"
SOURCES = (
    ("S1_PM", "s1_twin_spread/.cache", "p_*.npz"),
    ("S1_Kalshi", "s1_twin_spread/.cache", "k_*.npz"),
    ("S4_PM", "s4_linked_assets/.cache", "pm_*.npz"),
    ("S5_PM", "s5_big_moves/.cache", "pm_*.npz"),
    ("S9_PM", "s9_weekend_price_markets/.cache", "pm_*.npz"),
    ("S11_PM", "s11_bundles/.cache", "pm_*.npz"),
)
META = (
    ("S1_twins", "s1_twin_spread/.cache/pull_meta.json", "pairs"),
    ("S9_price_markets", "s9_weekend_price_markets/universe.json", "markets"),
    ("S11_history", "s11_bundles/bundles.json", "markets"),
    ("S11_live_metadata_only", "s11_bundles/live_bundles.json", "markets"),
)
DOCS = {
    "resolution": "https://docs.polymarket.com/concepts/resolution",
    "negative_risk": "https://docs.polymarket.com/concepts/negative-risk",
    "pm_fees": "https://docs.polymarket.com/trading/fees",
    "kalshi_fees": "https://kalshi.com/docs/kalshi-fee-schedule.pdf",
    "prices_orderbook": "https://docs.polymarket.com/concepts/prices-orderbook",
}


def iso(ts):
    return datetime.fromtimestamp(float(ts), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_csv(path: Path, rows: list[dict], fields=None):
    if fields is None:
        fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def check_freeze():
    """Abort if a frozen rule has silently changed after seeing data."""
    for name in ("METHOD.md", "config.py", ".gitignore"):
        rel = f"research/{HERE.name}/{name}"
        frozen = subprocess.run(["git", "show", f"{FREEZE_COMMIT}:{rel}"],
                                cwd=RESEARCH.parent, capture_output=True, check=True).stdout
        if frozen != (HERE / name).read_bytes():
            raise RuntimeError(f"Frozen file differs from {FREEZE_COMMIT}: {rel}")


def timestamp_inventory():
    rows = []
    details = []
    for label, folder, pattern in SOURCES:
        files = sorted((RESEARCH / folder).glob(pattern))
        schema = Counter()
        points, lo, hi, failures = 0, None, None, []
        day_counts = Counter()
        for path in files:
            try:
                with np.load(path, allow_pickle=False) as archive:
                    schema[",".join(sorted(archive.files))] += 1
                    # Deliberately never access p/bid/ask/volume arrays.
                    t = archive["t"]
                    if t.ndim != 1 or not np.isfinite(t).all() or (np.diff(t) < 0).any():
                        raise ValueError("invalid timestamp array")
                    if len(t):
                        l, h = int(t.min()), int(t.max())
                        lo = l if lo is None else min(lo, l)
                        hi = h if hi is None else max(hi, h)
                        d, n = np.unique(t // 86400, return_counts=True)
                        day_counts.update(dict(zip(map(int, d), map(int, n))))
                    points += len(t)
            except (ValueError, OSError, EOFError) as exc:
                failures.append({"file": str(path.relative_to(RESEARCH)), "error": str(exc)})
        split = math.floor((lo + (1 - cfg.OOS_FRACTION) * (hi - lo)) / 86400) * 86400 if lo is not None else None
        oos_days = sum(d * 86400 >= split for d in day_counts) if split is not None else 0
        span_days = (hi - lo) / 86400 if lo is not None else None
        row = {
            "source": label, "folder": folder, "files": len(files),
            "bytes": sum(p.stat().st_size for p in files), "timestamp_rows": points,
            "first_timestamp": iso(lo) if lo is not None else "",
            "last_timestamp": iso(hi) if hi is not None else "",
            "span_days": span_days, "calendar_dates_with_timestamps": len(day_counts),
            "recent20_percent_start": iso(split) if split is not None else "",
            "raw_timestamp_dates_recent20_percent": oos_days,
            "book_depth_records": 0, "qualified_portfolio_daily_marks": 0,
            "schemas": json.dumps(dict(schema), sort_keys=True), "read_failures": len(failures),
        }
        rows.append(row)
        details.append({"source": label, "failures": failures})
    return rows, details


def metadata_inventory():
    rows = []
    for label, rel, field in META:
        path = RESEARCH / rel
        payload = path.read_bytes()
        data = json.loads(payload)
        records = data[field]
        records = list(records.values()) if isinstance(records, dict) else records
        counts = {}
        for k in ("description", "rules_primary", "rules_secondary", "resolutionSource",
                  "source_publication_time", "observed_publication_time", "resolved_time",
                  "redemption_time"):
            counts[k + "_nonnull"] = sum(r.get(k) not in (None, "", []) for r in records)
        # ClosedTime is metadata, not an observed official publication or release time.
        counts["closed_time_field_nonnull"] = sum(r.get("closedTime", r.get("closed_time"))
                                                  not in (None, "") for r in records)
        rows.append({"source": label, "path": rel, "market_records": len(records),
                     "sha256": hashlib.sha256(payload).hexdigest(), **counts,
                     "qualified_contract_proofs": 0, "qualified_source_observations": 0})
    return rows


def s1_baseline_audit():
    base = RESEARCH / "results" / "s1_twin_spread"
    with (base / "trades.csv").open() as f:
        trades = list(csv.DictReader(f))
    with (base / "metrics.csv").open() as f:
        metrics = list(csv.DictReader(f))
    with (base / "equity_history.csv").open() as f:
        equity = list(csv.DictReader(f))
    rows, concentration = [], []
    for cost in cfg.COST_MULTIPLIERS:
        chosen = [r for r in trades if r["quote_rule"] == "registered" and r["variant"] == "V0"
                  and float(r["cost_mult"]) == cost]
        supported = [r for r in chosen if r["segment"] == "OOS" and r["verified"] == "True"]
        all_oos = [r for r in chosen if r["segment"] == "OOS"]
        met = next(r for r in metrics if r["quote_rule"] == "registered" and r["variant"] == "V0"
                   and float(r["cost_mult"]) == cost and r["segment"] == "OOS")
        edge_values = [float(r["edge_at_entry_verified"]) for r in supported]
        edge = sum(edge_values)
        # Independent reconstruction from quantities and per-contract modeled edge.
        independently_edge = sum(float(r["edge_in"]) * float(r["verified_qty"]) for r in supported)
        if abs(edge - independently_edge) > 1e-9 or abs(edge - float(met["edge_at_entry_verified"])) > 1e-9:
            raise RuntimeError("S1 edge accounting discrepancy")
        collat = sum(float(r["cost_in"]) * float(r["verified_qty"]) for r in supported)
        path = sorted([r for r in equity if r["quote_rule"] == "registered" and r["variant"] == "V0"
                       and float(r["cost_mult"]) == cost and r["segment"] == "OOS"
                       and r["mark"] == "mid_verified"], key=lambda r: float(r["t"]))
        pnl = np.array([float(r["pnl"]) for r in path])
        returns = np.diff(np.r_[0., pnl]) / float(met["capital_base"])
        sharpe = float(returns.mean() / returns.std(ddof=1) * np.sqrt(365))
        if abs(sharpe - float(met["sharpe_mid_verified"])) > 1e-9:
            raise RuntimeError("S1 modeled daily Sharpe reconstruction mismatch")
        open_is = [r for r in chosen if r["segment"] == "IS" and not r["t_out"]]
        open_pairs = {r["pair"] for r in open_is}
        reused = [r for r in all_oos if r["pair"] in open_pairs]
        by_pair = defaultdict(float)
        for r in supported:
            by_pair[r["pair"]] += float(r["edge_at_entry_verified"])
        for pair, value in sorted(by_pair.items()):
            concentration.append({"cost_mult": cost, "pair": pair, "modeled_entry_edge": value,
                                  "share_of_modeled_edge": value / edge})
        events = sorted([(float(r["t_in"]), float(r["capital"])) for r in all_oos]
                        + [(float(r["t_out"]), -float(r["capital"])) for r in all_oos if r["t_out"]],
                        key=lambda x: (x[0], x[1]))
        locked, peak = 0., 0.
        for _, amount in events:
            locked += amount
            peak = max(peak, locked)
        rows.append({
            "study": "S1_already_published_reused_baseline", "quote_rule": "registered", "variant": "V0",
            "segment": "OOS", "cost_mult": cost, "modeled_entries": len(all_oos),
            "pm_print_supported_entries": len(supported),
            "pm_print_supported_independent_entry_dates": len({r["entry_utc"][:10] for r in supported}),
            "pm_print_supported_pairs": len(by_pair), "modeled_entry_edge": edge,
            "independently_recomputed_modeled_edge": independently_edge,
            "scaled_entry_collateral": collat, "supported_contract_pairs": sum(float(r["verified_qty"]) for r in supported),
            "top_two_modeled_edge": sum(sorted(edge_values, reverse=True)[:2]),
            "top_two_share": sum(sorted(edge_values, reverse=True)[:2]) / edge,
            "modeled_mid_pnl": float(met["pnl_mid_verified"]),
            "modeled_mid_sharpe": float(met["sharpe_mid_verified"]),
            "recomputed_modeled_mid_sharpe": sharpe, "equity_mark_count": len(path),
            "equity_calendar_span_days": (float(path[-1]["t"]) - float(met_to_ts(met["start"]))) / 86400,
            "IS_open_positions_at_split": len(open_is),
            "IS_open_collateral_at_split": sum(float(r["capital"]) for r in open_is),
            "OOS_pairs_with_open_IS_positions": len({r["pair"] for r in reused}),
            "OOS_entries_on_those_pairs": len(reused), "OOS_peak_entry_collateral": peak,
            "OOS_reported_end_locked_collateral": float(met["max_capital_locked"]),
            "pm_print_window_plus_minus_seconds": 600,
            "simultaneous_depth_proven_entries": 0, "qualified_cx3_entries": 0,
        })
    return rows, concentration


def met_to_ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def unavailable_plot(path, title):
    fig, ax = plt.subplots(figsize=(9, 3.3))
    ax.axis("off")
    ax.set_title(title, loc="left", fontsize=15, fontweight="bold")
    ax.text(.02, .64, "NOT TESTABLE — financial observations unavailable", transform=ax.transAxes, fontsize=15)
    ax.text(.02, .35, "Historical PM prices have no executable depth.\nOfficial publication and collateral-release timestamps are absent.",
            transform=ax.transAxes, fontsize=12, linespacing=1.6)
    ax.text(.02, .10, "No fabricated zero-return curve; no historical Sharpe claim.", transform=ax.transAxes, fontsize=11, color="#555")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def main():
    start = time.time()
    check_freeze()
    RESULTS.mkdir(parents=True, exist_ok=True)
    inv, details = timestamp_inventory()
    meta = metadata_inventory()
    audit, concentrations = s1_baseline_audit()
    write_csv(RESULTS / "inventory.csv", inv)
    write_csv(RESULTS / "metadata_inventory.csv", meta)
    write_csv(RESULTS / "s1_baseline_audit.csv", audit)
    write_csv(RESULTS / "s1_concentration.csv", concentrations)
    (RESULTS / "inventory_read_log.json").write_text(json.dumps(details, indent=2))
    metrics = [
        {"rule": rule, "segment": seg, "cost_mult": cost,
         "status": "not_testable", "data_label": cfg.DATA_LABEL,
         "evidence_qualified_entries": 0, "qualified_daily_observations": 0,
         "independent_entry_dates": 0, "tested_opportunities": "NA",
         "net_pnl": "NA", "total_return": "NA", "sharpe": "NA",
         "max_drawdown": "NA", "worst_month": "NA", "turnover": "NA",
         "capacity": "NA", "bootstrap_ci": "NA", "capital_base": cfg.CAPITAL,
         "funding_assumption_ann": cfg.FUNDING_RATE * cost, "success": False}
        for rule in cfg.RULE_IDS for cost in cfg.COST_MULTIPLIERS for seg in ("IS", "OOS")
    ]
    write_csv(RESULTS / "metrics.csv", metrics)
    write_csv(RESULTS / "trades.csv", [], ["rule", "basket_id", "family", "entry_utc", "exit_utc",
                                         "cost_mult", "quantity", "entry_cost", "fees", "funding", "net_pnl"])
    write_csv(RESULTS / "equity.csv", [], ["rule", "segment", "cost_mult", "utc", "equity", "drawdown"])
    unavailable_plot(RESULTS / "equity_curve.png", "Exact baskets and resolution carry — equity unavailable")
    unavailable_plot(RESULTS / "drawdown.png", "Exact baskets and resolution carry — drawdown unavailable")
    git_log = subprocess.run(["git", "log", "-1", "--format=%H %cI %s", "--", f"research/{HERE.name}"],
                             cwd=RESEARCH.parent, capture_output=True, text=True, check=True).stdout.strip()
    run_meta = {"started_utc": iso(start), "finished_utc": iso(time.time()), "seconds": time.time() - start,
                "freeze_commit": FREEZE_COMMIT, "last_own_path_commit": git_log,
                "protected_forward_read": False, "sealed_oos_read": False, "network_data_pulls": 0,
                "price_arrays_accessed": False, "reused_baseline_numeric_results_read": True,
                "docs_checked_utc": "2026-10-04", "official_docs": DOCS,
                "frozen_hashes": {f: hashlib.sha256((HERE / f).read_bytes()).hexdigest()
                                  for f in ("METHOD.md", "config.py", ".gitignore")}}
    (RESULTS / "run_meta.json").write_text(json.dumps(run_meta, indent=2))
    print(json.dumps({"status": "not_testable", "freeze_commit": FREEZE_COMMIT,
                      "PM_files": sum(r["files"] for r in inv if r["source"] != "S1_Kalshi"),
                      "PM_timestamp_rows": sum(r["timestamp_rows"] for r in inv if r["source"] != "S1_Kalshi"),
                      "qualified_entries": 0, "financial_metrics": None,
                      "S1_1x_independent_entry_dates": audit[0]["pm_print_supported_independent_entry_dates"],
                      "S1_1x_top_two_share": audit[0]["top_two_share"]}, indent=2))


if __name__ == "__main__":
    main()
