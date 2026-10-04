"""Build research/massive_8k.ipynb: the Massive submission notebook, from the frozen 8-K cells of polybridge_8k.ipynb."""
import json
from pathlib import Path

R = Path(__file__).resolve().parent
src = json.loads((R / "polybridge_8k.ipynb").read_text())
cells = src["cells"]


def md(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text.strip("\n").splitlines(keepends=True)}


def code(text):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
            "source": text.strip("\n").splitlines(keepends=True)}


def reuse(i):
    c = json.loads(json.dumps(cells[i]))
    c["outputs"], c["execution_count"] = [], None
    return c


INTRO = r"""
# Trade the 8-K · PolyBridge (Jacob Crainic, Theo Machado)

**Gator Quant Hacks 2026 · Massive Challenge.** Built on the Massive starter notebook: the same endpoints, calendar,
put-call-parity spot, five-strategy P&L engine, fixed horizons, expiry buckets and placebo. The starter's code lives in
`polybridge_research/` (each module names the starter section it comes from) so that it is unit-tested.

**Pre-registration.** [HYPOTHESIS.md](HYPOTHESIS.md) and [HYPOTHESIS_TAGS.md](HYPOTHESIS_TAGS.md) were committed on
2 October 2026 before any 8-K event or option price was fetched. The out-of-sample window was run once after the method
freeze (git tag `method-freeze`). Our forecast for the out-of-sample and sealed windows, [FORECAST.md](FORECAST.md), was
committed before either was run.

- **H1 · protective put** after slow-burning bad news: `material_litigation`, `class_action_filing`,
  `regulatory_investigation`, `cybersecurity_incident`, `goodwill_impairment`, `asset_impairment`,
  `investment_impairment`. The stock keeps moving by more than the chain priced, because implied volatility is marked
  down once the headline passes while the damage resolves over weeks.
- **H2 · cash-secured put** after restructurings: `restructuring_plan`, `workforce_reduction`, `facility_closure`,
  `business_line_exit`. Holders who must sit through the event buy puts and dealers charge for that one-sided demand
  (Gârleanu, Pedersen and Poteshman, 2009), so the put is overpriced.

**Pass rule (fixed before results).** The 97.5% interval of the P&L edge (events minus ordinary days for the same names)
lies above zero at 2 or more of 21 sessions, 42 sessions and expiry, and the parity ratio (realized ÷ implied move)
points the predicted way at those horizons. Fewer than 2 testable headline horizons is reported as INSUFFICIENT.

## How to run (judges)

1. Put `MASSIVE_API_KEY` in the environment or a `.env` file in this folder or a parent. Nothing else is needed.
2. `pip install -r requirements.txt` from this folder (it installs `polybridge_research` in editable mode).
3. **Sealed window:** set `HOLDOUT_START`, `HOLDOUT_END` and `RUN_HOLDOUT = True` in the configuration cell, as in the
   starter, then run all cells. The last section runs the whole pipeline on that window, both families, with placebo,
   pass check, all fixed horizons and the parity decay, and prints our committed forecast for a window of that length.

A run from an empty cache takes roughly 15 to 25 minutes (both families plus their placebos); a warm cache takes about a minute.
"""

CONFIG = r'''
# ---- Windows (same names as the starter). Judges: set the sealed dates and flip RUN_HOLDOUT. ----------
STUDY_START, STUDY_END = "2024-01-01", "2025-12-31"      # in-sample, where the hypotheses were tested
OOS_START, OOS_END = "2026-01-01", "2026-08-31"          # out-of-sample, frozen method, run once on 3 Oct 2026
HOLDOUT_START, HOLDOUT_END = "2023-06-01", "2023-08-31"  # sealed: judges change these and flip RUN_HOLDOUT
RUN_HOLDOUT = False

RUN_OOS = True               # re-runs the frozen out-of-sample window with exits pinned to the freeze date (reproduces results/oos)
OOS_LAST_SESSION = "2026-10-02"   # the last session used for exits in the single out-of-sample run
MAX_WORKERS = 8

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from polybridge_research.analysis import (decay_table, difference_board, pass_check, robustness_table, sample_placebo,
                                         scoreboard, verdict)
from polybridge_research.atlas import count_variants
from polybridge_research.calendar import TradingCalendar
from polybridge_research.config import StudyConfig
from polybridge_research.costs import cost_table
from polybridge_research.evaluate import evaluate
from polybridge_research.massive import MassiveClient, load_api_key
from polybridge_research.pipeline import run_family_study
from polybridge_research.pricing import price_events

for _name in ("STUDY_START", "STUDY_END", "OOS_START", "OOS_END", "HOLDOUT_START", "HOLDOUT_END"):
    pd.Timestamp(globals()[_name])      # raises on an impossible date such as "2024-06-31"
assert STUDY_START < STUDY_END and OOS_START < OOS_END and HOLDOUT_START < HOLDOUT_END

cfg = StudyConfig(study_start=STUDY_START, study_end=STUDY_END, oos_start=OOS_START, oos_end=OOS_END)
cfg.validate()
START, END = STUDY_START, STUDY_END
LAST_SESSION = None      # None = the last completed session
'''

OOS = r'''
if RUN_OOS:
    OOS_LAST = pd.Timestamp(OOS_LAST_SESSION)
    oos = run_family_study(client, cal, cfg, cfg.oos_start, cfg.oos_end, OOS_LAST, user_agent=None, max_workers=MAX_WORKERS)
    print(f"Out-of-sample window {cfg.oos_start} -> {cfg.oos_end}; last session used for exits {OOS_LAST.date()} (pinned)")
    for fam in FAMILIES:
        chk = oos["checks"].get(fam)
        r_e, r_p = of_family(oos["results"], fam), of_family(oos["placebo_results"], fam)
        print(f"\n[{fam}] out-of-sample verdict: {verdict(chk)}")
        if len(r_e) and len(r_p):
            strat = chk["strategy"] if chk else None
            show(difference_board(r_e, r_p, cfg, level=cfg.confirmatory_level, strategies=[strat]),
                 f"[{fam}] {strat}: events minus ordinary days at every fixed horizon (97.5% CI; n < 5 has no interval)")
            show(decay_table(r_e, cfg), f"[{fam}] parity decay, out-of-sample events")
        ins = study["checks"].get(fam)
        if chk is not None and ins is not None:
            a = ins["pnl"][["horizon", "difference"]].rename(columns={"difference": "edge_in_sample"})
            b = chk["pnl"][["horizon", "n_a", "difference"]].rename(columns={"n_a": "n_oos", "difference": "edge_oos"})
            cmp_ = a.merge(b, on="horizon", how="left")
            cmp_["same_sign"] = np.sign(cmp_.edge_in_sample) == np.sign(cmp_.edge_oos)
            show(cmp_.set_index("horizon"), f"[{fam}] headline horizons: in-sample vs out-of-sample edge")
else:
    print("Out-of-sample not run (RUN_OOS = False). The committed single run is in results/oos/SUMMARY.md.")
'''

HOLDOUT_MD = r"""
## Sealed window · judges only

Set `HOLDOUT_START`, `HOLDOUT_END` and `RUN_HOLDOUT = True` in the configuration cell and run all cells. This cell runs
the frozen pipeline (same tags, same pass rule, same conservative timing) on that window for both families. Horizons that
have not resolved by today are absent rather than guessed.

**What we predicted** ([FORECAST.md](FORECAST.md), committed before any window outside 2024–2025 was run): a 3-month window
gives about 4 H1 and 3 H2 events, too few for an interval, so INSUFFICIENT for both; 4–5 months NULL or INSUFFICIENT;
6 months or more NULL for both. A PASS would contradict the forecast and we would call it a surprise, not a confirmation.
"""

HOLDOUT = r'''
FORECAST = [(3.5, "INSUFFICIENT", "INSUFFICIENT"), (5.5, "NULL or INSUFFICIENT", "INSUFFICIENT"),
            (12.5, "NULL", "NULL"), (float("inf"), "NULL", "NULL")]


def forecast_for(start, end):
    months = (pd.Timestamp(end) - pd.Timestamp(start)).days / 30.44
    h1, h2 = next((a, b) for m, a, b in FORECAST if months <= m)
    return months, {"hedge": h1, "opportunity": h2}


if RUN_HOLDOUT:
    LAST_H = cal.last_completed()
    holdout = run_family_study(client, cal, cfg, HOLDOUT_START, HOLDOUT_END, LAST_H, user_agent=None, max_workers=MAX_WORKERS)
    months, fc = forecast_for(HOLDOUT_START, HOLDOUT_END)
    print(f"Sealed window {HOLDOUT_START} -> {HOLDOUT_END} ({months:.1f} months); exits up to {LAST_H.date()}")
    rows = []
    for fam in FAMILIES:
        chk = holdout["checks"].get(fam)
        r_e, r_p = of_family(holdout["results"], fam), of_family(holdout["placebo_results"], fam)
        sb = scoreboard(r_e, cfg, strategies=["stock"], horizons=[21]) if len(r_e) else None
        n_ev = int(sb["n"].sum()) if sb is not None and len(sb) else 0
        rows.append({"family": fam, "events_at_21": n_ev, "verdict": verdict(chk), "our_forecast": fc[fam]})
        if len(r_e) and len(r_p):
            strat = chk["strategy"] if chk else None
            show(difference_board(r_e, r_p, cfg, level=cfg.confirmatory_level, strategies=[strat]),
                 f"[{fam}] {strat}: events minus ordinary days at every fixed horizon (97.5% CI)")
            show(scoreboard(r_e, cfg), f"[{fam}] all five strategies, events (95% CI)")
            de = decay_table(r_e, cfg)
            show(de, f"[{fam}] parity decay, sealed-window events")
            de_in = decay[fam][0]
            if len(de) and len(de_in):
                fig, ax = plt.subplots(figsize=(6, 3.2))
                order = [*cfg.horizons, "exp"]
                for tbl, label, colr in ((de_in, "in-sample events", "tab:red"), (de, "sealed-window events", "tab:green"),
                                         (decay[fam][1], "in-sample ordinary days", "tab:gray")):
                    t = tbl.dropna(subset=["mean_ratio"])
                    ax.plot([order.index(h) for h in t.index], t["mean_ratio"], "o-", label=label, color=colr)
                ax.axhline(1, color="k", lw=0.6)
                ax.set_xticks(range(len(order)), [str(h) for h in order])
                ax.set_xlabel("sessions after the filing"); ax.set_ylabel("|realized| / implied")
                ax.set_title(f"[{fam}] parity decay"); ax.legend(fontsize=8)
                plt.show()
        else:
            print(f"[{fam}] no priced events or no placebo in this window")
    show(pd.DataFrame(rows).set_index("family"), "Sealed window: verdict against our committed forecast")
else:
    print(f"Sealed window {HOLDOUT_START}..{HOLDOUT_END} not run. Judges: set RUN_HOLDOUT = True.")
'''

new = [md(INTRO), code(CONFIG), reuse(2),
       md("## 1 · In-sample study, 2024-01-01 to 2025-12-31\n\nEvents by family, exclusions (cross-family filings are dropped from both tests) and drops before pricing."),
       reuse(3),
       md("## 2 · Scoreboards and the placebo gap at every fixed horizon\n\nAll five strategies for events and for ordinary days, then the event-minus-placebo edge with its interval."),
       reuse(4),
       md("## 3 · The pre-registered pass check"), reuse(5),
       md("## 4 · Robustness (reported next to the pass rule, never instead of it)"), reuse(6),
       md("## 5 · The yardstick: parity decay (|realized| ÷ implied move)\n\nEntry on the pre-event session, so this is a statement about pricing, not a trade."),
       reuse(7),
       md("## 6 · Parameter sensitivity\n\nThe starter's grid: expiry bucket × entry session × OTM distance, at 21 sessions."),
       reuse(8),
       md("## 7 · Trade specification: costs, liquidity, capacity\n\nA 5% premium haircut each way at 1× and 2×, and real half-spreads where quotes exist; median leg volume on the entry day."),
       reuse(9),
       md("## 8 · Out-of-sample, 2026-01-01 to 2026-08-31\n\nThe frozen pipeline, exits pinned to 2 October 2026 as in the single committed run (`results/oos/`)."),
       code(OOS),
       md(HOLDOUT_MD), code(HOLDOUT),
       reuse(14)]

nb = {"cells": new, "metadata": src["metadata"], "nbformat": src["nbformat"], "nbformat_minor": src["nbformat_minor"]}
(R / "massive_8k.ipynb").write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n")
print("cells:", len(new))
