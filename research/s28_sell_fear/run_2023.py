from __future__ import annotations

import json
import sys

import pandas as pd

from .run import RESULTS, h3, high_fear
from polybridge_research.calendar import TradingCalendar
from polybridge_research.config import StudyConfig
from polybridge_research.massive import MassiveClient, load_api_key
from polybridge_research.pipeline import run_family_study
from pathlib import Path


def main() -> int:
    start, end = (sys.argv[1], sys.argv[2]) if len(sys.argv) == 3 else ("2023-01-01", "2023-12-31")
    done = RESULTS / f"oos_{start}_{end}.done"
    if done.exists():
        print(f"already run once: {done}")
        return 1
    years = (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25
    cfg, cal = StudyConfig(), TradingCalendar()
    st = run_family_study(MassiveClient(load_api_key(search_from=Path.cwd())), cal, cfg, start, end, pd.Timestamp("2026-10-02"))
    done.write_text("run once\n")
    ev = st["results"][st["results"].family == "hedge"]
    pl = st["placebo_results"][st["placebo_results"].family == "hedge"]
    out = []
    for scope, (a, b) in {"high fear": (high_fear(ev), high_fear(pl)), "all H1": (ev, pl)}.items():
        d, v, ok, n, s_ev, s_pl = h3(a, b, cfg, years)
        print(f"\n== {start}..{end} | {scope}: {v} (above zero at {ok}); events at 21: {n}; Sharpe {s_ev:.2f} vs ordinary {s_pl:.2f}")
        if len(d):
            print((d[d.horizon.isin([5, 10, 21, 42, 63, "exp"])][["horizon", "n_a", "n_b", "difference", "ci_lo", "ci_hi"]]
                   .set_index("horizon") * [1, 1, 100, 100, 100]).round(2).to_string())
            d.to_csv(RESULTS / f"oos_{start}_{end}_{scope.replace(' ', '_')}.csv", index=False)
        out.append({"window": f"{start}..{end}", "scope": scope, "verdict": v, "above_zero_at": ok, "events_21": n,
                    "sharpe_events": s_ev, "sharpe_ordinary": s_pl})
    (RESULTS / f"oos_{start}_{end}.json").write_text(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
