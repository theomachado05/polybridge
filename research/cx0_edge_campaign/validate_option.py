"""Independent recomputation from saved NAV, not from reported return summaries."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .review import Evidence, nav_metrics, screen


RESEARCH = Path(__file__).resolve().parent.parent
SOURCE = RESEARCH / "results" / "cx1_option_insurance"
OUT = RESEARCH / "results" / "cx0_edge_campaign"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    equity = pd.read_csv(SOURCE / "equity.csv")
    reported = pd.read_csv(SOURCE / "metrics.csv")
    rows = []
    for (variant, cost), g in equity.groupby(["variant", "cost_multiplier"]):
        g = g.sort_values("day")
        if g.day.duplicated().any():
            raise ValueError("Duplicate portfolio dates")
        for segment in ("IS", "OOS", "ALL"):
            part = g if segment == "ALL" else g[g.segment == segment]
            if part.empty:
                continue
            prior_rows = g[g.day < part.day.iloc[0]]
            initial = float(prior_rows.equity.iloc[-1]) if len(prior_rows) else 1.0
            check = nav_metrics(part.equity.to_numpy(), initial)
            original = reported[(reported.variant == variant) & (reported.cost_multiplier == cost)
                                & (reported.segment == segment)]
            if len(original) != 1:
                raise ValueError("Ambiguous or missing reported curve")
            r = original.iloc[0]
            differences = {"sharpe_difference": abs(check["sharpe"] - r.annualized_sharpe),
                           "return_difference": abs(check["total_return"] - r.total_return),
                           "drawdown_difference": abs(check["max_drawdown"] + r.max_drawdown)}
            if not all(np.isfinite(x) and x <= 1e-9 for x in differences.values()):
                raise ValueError(f"Independent NAV mismatch for {variant}, {cost}, {segment}")
            rows.append({"variant": variant, "cost_multiplier": cost, "segment": segment,
                         "independent_sharpe": check["sharpe"],
                         "independent_return": check["total_return"],
                         "independent_max_drawdown": check["max_drawdown"], **differences})
    pd.DataFrame(rows).to_csv(OUT / "independent_nav_audit.csv", index=False)
    oos = reported[(reported.variant == "V0") & (reported.segment == "OOS")]
    one = oos[oos.cost_multiplier == 1].iloc[0]
    two = oos[oos.cost_multiplier == 2].iloc[0]
    verdict, reasons = screen(Evidence(
        float(one.annualized_sharpe), float(one.total_return), float(two.total_return),
        float(one.event_ci_low), int(one.executed_entry_dates), int(one.daily_observations),
        True, True, False))
    # Supported means the expressly assumed historical NBBO simulation can be
    # recomputed; it does not certify live fills, integer lots or complete marks.
    economic_pass = (one.annualized_sharpe >= 1.5 and one.total_return > 0
                     and two.total_return > 0 and one.event_ci_low > 0)
    meta = {"run_utc": datetime.now(timezone.utc).isoformat(), "curves_checked": len(rows),
            "nav_accounting_reconciles": True, "primary_screen": verdict, "screen_reasons": reasons,
            "primary_economic_gates_pass": bool(economic_pass),
            "primary_observed_oos_profitable": bool(one.total_return > 0 and two.total_return > 0),
            "independent_confirmation": False,
            "accounting_limits": ["normalized fractional contracts", "entry snapshot five minutes before close",
                                  "historical NBBO fills are simulated, not a live track record"],
            "input_hashes": {name: hashlib.sha256((SOURCE / name).read_bytes()).hexdigest()
                             for name in ("equity.csv", "metrics.csv", "trades.csv")}}
    (OUT / "validation.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps({"curves_checked": len(rows), "primary_screen": verdict, "reasons": reasons}))


if __name__ == "__main__":
    main()
