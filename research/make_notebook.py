"""Generate polybridge_8k.ipynb (no outputs). Run: python make_notebook.py"""
from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell as code, new_markdown_cell as md, new_notebook

HERE = Path(__file__).resolve().parent

C1 = """\
# PolyBridge research · Trade the 8-K

Pre-registration: [HYPOTHESIS.md](HYPOTHESIS.md) (19:38 ET, 2 Oct 2026) and [HYPOTHESIS_TAGS.md](HYPOTHESIS_TAGS.md)
(20:08 ET), both committed before any event data was fetched.

Two confirmatory hypotheses, each on the top-100 US stocks, judged against a placebo of ordinary days:

- **H1 (hedge):** after a litigation, investigation, cybersecurity or impairment 8-K the stock keeps moving by more than the options priced, so the protective put beats the placebo's.
- **H2 (opportunity):** after a restructuring plan, workforce reduction, facility closure or business-line exit 8-K the stock moves by less than the options priced, so the cash-secured put beats the placebo's.

**Pass rule (decided before results).** A hypothesis passes only if the 97.5% CI of the P&L edge (events minus ordinary days) is entirely above 0 at 2 or more of 21, 42 and expiry,
and the price-gap ratio points the predicted way (H1 above ordinary days, H2 below) at those horizons. Otherwise it is a null result.

If a pairing fails, PolyBridge reports "no edge for this event and stock — try another", and that is a valid result.

**How to run.** Only `MASSIVE_API_KEY` is required (environment variable or a `.env` file). Edit `START, END` in the next cell and rerun all cells.
Timing is frozen to the conservative rule (every filing is treated as public after the close).
"""

C2 = '''\
# ---- Window. Judges: set your sealed window here and rerun all cells. ----
START, END = "2024-01-01", "2025-12-31"
RUN_OOS = False          # flipped once, after the method freeze (see research/HYPOTHESIS.md §4)
RUN_ATLAS = False        # exploratory atlas over every 8-K tag (HYPOTHESIS.md §5); stretch goal, slow
ATLAS_MAX_EVENTS = 15
MAX_WORKERS = 8
LAST_SESSION = None      # pinned at the method freeze, e.g. "2026-10-03"; None = today's last completed session

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from polybridge_research.analysis import (decay_table, difference_board, pass_check, robustness_table, sample_placebo,
                                         scoreboard, verdict)
from polybridge_research.atlas import count_variants, run_atlas
from polybridge_research.calendar import TradingCalendar
from polybridge_research.config import StudyConfig
from polybridge_research.costs import cost_table
from polybridge_research.evaluate import evaluate
from polybridge_research.massive import MassiveClient, load_api_key
from polybridge_research.pipeline import run_family_study
from polybridge_research.pricing import price_events

cfg = StudyConfig()
cfg.validate()
'''

C3 = '''\
from IPython.display import Markdown, display

key = load_api_key(search_from=Path.cwd())
client = MassiveClient(key)
cal = TradingCalendar()
LAST = pd.Timestamp(LAST_SESSION) if LAST_SESSION else cal.last_completed()
FAMILIES = ["hedge", "opportunity"]
HEADS = list(cfg.headline_horizons)
print("Timing mode: conservative (every filing treated as public after the close; frozen for all confirmatory runs)")
print(f"Window {START} -> {END}; last session used for exits {LAST.date()} ({'pinned' if LAST_SESSION else 'today, not pinned'})")


def show(df, title=None):
    """Display a frame, or say so when there is nothing to show."""
    if title:
        print(title)
    if df is None or len(df) == 0:
        print("no events in this window")
    else:
        display(df)


def of_family(df, fam):
    if df is None or len(df) == 0 or "family" not in df:
        return pd.DataFrame() if df is None else df.iloc[0:0]
    return df[df["family"] == fam]


def hpos(horizons):
    order = [*cfg.horizons, "exp"]
    return [order.index(h) for h in horizons]
'''

C4 = '''\
study = run_family_study(client, cal, cfg, START, END, LAST, user_agent=None, max_workers=MAX_WORKERS)
ev = study["events"]
if ev.empty:
    print("no events in this window")
else:
    by_year = ev.assign(year=pd.to_datetime(ev["filing_date"]).dt.year).groupby(["family", "year"]).size().unstack(fill_value=0)
    show(by_year, "Events by family and year")
print("Filings excluded because they fit neither family (cross-family or other tags):", len(study["excluded"]))
print("Timing counts:", study["timing_counts"])
dropped = study["dropped"]
if len(dropped):
    show(dropped.groupby("reason").size().rename("n").to_frame(), "Events dropped before pricing, by reason")
else:
    print("no events dropped")
'''

C5 = '''\
res, pl = study["results"], study["placebo_results"]
rows_f = [f for f in FAMILIES if len(of_family(res, f))]
if not rows_f:
    print("no events in this window")
else:
    fig, axes = plt.subplots(len(rows_f), 6, figsize=(22, 3.6 * len(rows_f)), squeeze=False, sharex=True)
    for i, fam in enumerate(rows_f):
        ev_r, pl_r = of_family(res, fam), of_family(pl, fam)
        sb_e = scoreboard(ev_r, cfg)
        show(sb_e, f"[{fam}] events: mean P&L per $1 of spot (95% CI)")
        if len(pl_r):
            sb_p = scoreboard(pl_r, cfg)
            show(sb_p, f"[{fam}] placebo")
            show(difference_board(ev_r, pl_r, cfg, level=cfg.confirmatory_level),
                 f"[{fam}] events minus placebo (97.5% CI)")
        else:
            sb_p = None
            print(f"[{fam}] no placebo days priced")
        for j, s in enumerate(sb_e["strategy"].unique()):
            ax = axes[i][j]
            for sb, label, colr in ((sb_e, "events", "tab:red"), (sb_p, "placebo", "tab:gray")):
                if sb is None:
                    continue
                d = sb[sb.strategy == s].dropna(subset=["mean"])
                if d.empty:
                    continue
                x = hpos(d["horizon"])
                ax.plot(x, d["mean"], marker="o", color=colr, label=label)
                ax.fill_between(x, d["ci_lo"], d["ci_hi"], color=colr, alpha=0.2)
            ax.axhline(0, color="k", lw=0.5)
            ax.set_title(f"{fam}: {s}", fontsize=9)
            ax.set_xticks(range(len(cfg.horizons) + 1))
            ax.set_xticklabels([*map(str, cfg.horizons), "exp"], fontsize=7)
        axes[i][0].legend(fontsize=7)
    fig.suptitle("Mean P&L per $1 of spot by horizon: events vs placebo (95% CI band)")
    plt.tight_layout()
    plt.show()
'''

C6 = '''\
for fam in FAMILIES:
    chk = study["checks"].get(fam)
    if chk is None:
        print(f"{fam}: no events in this window")
        continue
    pnl, ratio = chk["pnl"], chk["ratio"]
    if pnl.empty:
        print(f"{fam}: no headline horizons available in this window")
    else:
        t = pnl[["horizon", "n_a", "n_b", "difference", "ci_lo", "ci_hi"]].rename(
            columns={"n_a": "n_events", "n_b": "n_placebo", "difference": "pnl_edge", "ci_lo": "pnl_ci_lo", "ci_hi": "pnl_ci_hi"})
        t = t.merge(ratio[["horizon", "difference"]].rename(columns={"difference": "ratio_diff"}), on="horizon", how="left")
        t["pnl_ok"] = t["horizon"].isin(chk["horizons_pnl_ok"])
        t["ratio_ok"] = t["horizon"].isin(chk["horizons_ratio_ok"])
        show(t.set_index("horizon"), f"{fam} ({chk['strategy']}): events minus placebo at the headline horizons")
    display(Markdown(f"**{fam.upper()}: {verdict(chk)}**. INSUFFICIENT means fewer than 2 headline horizons had the 5 events a CI needs. PASS rule: the 97.5% CI of the P&L edge (events minus ordinary days) is entirely above 0, "
                     "and the price-gap ratio points the predicted way (H1 above ordinary days, H2 below), "
                     "at 2 or more of 21, 42 and expiry."))
'''

C6R = '''\
for fam in FAMILIES:
    chk = study["checks"].get(fam)
    if chk is None:
        continue
    rob = robustness_table(of_family(study["results"], fam), of_family(study["placebo_results"], fam), fam, cfg)
    show(rob.set_index(["check", "horizon"]),
         f"[{fam}] robustness, 97.5% CIs (reported next to the pass rule, never instead of it): company-clustered bootstrap"
         + ("; put leg only = protective put minus stock, the put's own edge" if fam == "hedge" else ""))
'''

C7 = '''\
decay = {}
for fam in FAMILIES:
    de = decay_table(of_family(study["results"], fam), cfg)
    dp = decay_table(of_family(study["placebo_results"], fam), cfg)
    decay[fam] = (de, dp)
    show(de, f"[{fam}] parity decay, events (ratio = realized / priced, entry on the pre-event session)")
    show(dp, f"[{fam}] parity decay, placebo")
if all(de.empty for de, _ in decay.values()):
    print("no events in this window")
else:
    fig, axes = plt.subplots(1, len(FAMILIES), figsize=(12, 3.8), squeeze=False)
    for ax, fam in zip(axes[0], FAMILIES):
        for tbl, label, colr in ((decay[fam][0], "events", "tab:red"), (decay[fam][1], "placebo", "tab:gray")):
            d = tbl.dropna(subset=["mean_ratio"])
            if d.empty:
                continue
            x = hpos(d.index)
            ax.plot(x, d["mean_ratio"], marker="o", color=colr, label=label)
            ax.fill_between(x, d["ci_lo"], d["ci_hi"], color=colr, alpha=0.2)
        ax.axhline(1, color="k", lw=0.5, ls="--")
        ax.set_title(f"{fam}: mean parity ratio by horizon")
        ax.set_xticks(range(len(cfg.horizons) + 1))
        ax.set_xticklabels([*map(str, cfg.horizons), "exp"])
        ax.legend()
    plt.tight_layout()
    plt.show()
'''

C8 = '''\
from polybridge_research.schema import STRATEGY_FOR_FAMILY, Family

for fam in FAMILIES:
    strat = STRATEGY_FOR_FAMILY[Family(fam)]
    r = of_family(study["results"], fam)
    r = r[r["horizon"] == 21] if len(r) else r
    if len(r):
        grid = r.groupby(["bucket", "entry", "otm"])[strat].agg(n="count", mean_pnl="mean")
        show(grid, f"[{fam}] {strat}: mean P&L at h=21 by bucket x entry x OTM (the starter's grid; entry 'pre' is a pricing statement, not a trade)")
    else:
        print(f"[{fam}] no events in this window")
print("Variants in this sensitivity grid (one tag):", count_variants(cfg))
'''

C9 = '''\
from polybridge_research.costs import cost_summary

cost_summ = []
QUOTES_OK = True
for fam in FAMILIES:
    strat = STRATEGY_FOR_FAMILY[Family(fam)]
    res_f = of_family(study["results"], fam)
    pl_f = of_family(study["placebo_results"], fam)
    priced_f = [p for p in study["priced"] if str(getattr(p.family, "value", p.family)) == fam]
    pl_priced_f = [p for p in study["placebo_priced"] if str(getattr(p.family, "value", p.family)) == fam]
    for h in (21, 42, "exp"):
        if res_f.empty or not priced_f:
            print(f"[{fam}] h={h}: no events in this window")
            continue
        ct = None
        if QUOTES_OK:
            try:
                ct = cost_table(res_f, priced_f, strat, h, cfg, client=client)
            except Exception as e:
                QUOTES_OK = False
                print(f"Options quotes unavailable on this key ({type(e).__name__}: {e}); spread cost not computed (haircut costs shown).")
        if ct is None:
            ct = cost_table(res_f, priced_f, strat, h, cfg, client=None)
        if ct.empty:
            print(f"[{fam}] h={h}: no events in this window")
            continue
        ct_pl = cost_table(pl_f, pl_priced_f, strat, h, cfg, client=None) if len(pl_f) and pl_priced_f else None
        cost_summ.append({"family": fam, "strategy": strat, "horizon": h, **cost_summary(ct, ct_pl)})
if cost_summ:
    show(pd.DataFrame(cost_summ).set_index(["family", "horizon"]),
         "Costs: mean P&L per $1 of spot. *_paired columns use only rows with both gross and spread (one common sample); "
         "net_haircut_Nx = net of the 5% premium haircut at Nx; net_edge_Nx = events minus placebo, both net of the haircut")
'''

C10 = '''\
if RUN_ATLAS:
    rows = client.get_all("/stocks/taxonomies/vX/disclosures", {"limit": 1000})
    tags = sorted({t["tertiary_category"] for t in rows})
    base = {cfg.baseline_bucket: cfg.buckets[cfg.baseline_bucket]}
    atlas_pl_events = sample_placebo(pd.DataFrame({"ticker": list(cfg.universe),
                                                   "filing_date": [pd.Timestamp("1900-01-01")] * len(cfg.universe)}),
                                     300, START, END, cal, gap_days=0, seed=11)
    atlas_pl_priced, _ = price_events(client, atlas_pl_events, cal, cfg, buckets=base, max_workers=MAX_WORKERS,
                                      label="atlas placebo")
    atlas_pl_res = evaluate(atlas_pl_priced, cal, cfg, LAST)
    atlas = run_atlas(client, cal, cfg, tags, START, END, LAST, atlas_pl_res,
                      max_events_per_tag=ATLAS_MAX_EVENTS, max_workers=MAX_WORKERS)
    print("EXPLORATORY: the 15 lowest q-values across tags. Nothing here is a headline (HYPOTHESIS.md §5).")
    show(atlas.sort_values("q_value").head(15))
    print("Variants counted (all tags, full grid):", count_variants(cfg, n_tags=len(tags)))
else:
    print("Atlas not run (RUN_ATLAS = False). It is exploratory and slow; set RUN_ATLAS = True to include it.")
'''

C11 = '''\
if RUN_OOS:
    oos = run_family_study(client, cal, cfg, cfg.oos_start, cfg.oos_end, LAST, user_agent=None, max_workers=MAX_WORKERS)
    print(f"Out-of-sample window {cfg.oos_start} -> {cfg.oos_end}; last session used for exits {LAST.date()}")
    IN_SAMPLE = Path("results/in_sample")
    for fam, chk in oos["checks"].items():
        heads = chk["pnl"][["horizon", "n_a", "n_b", "difference", "ci_lo", "ci_hi"]].rename(
            columns={"n_a": "n_events", "n_b": "n_placebo", "difference": "edge_oos"})
        print(f"{fam}: OOS n per headline horizon (events / placebo), edge of {chk['strategy']} and verdict")
        display(heads.set_index("horizon"))
        print(f"{fam}: OOS verdict {verdict(chk)}")
        display(robustness_table(of_family(oos["results"], fam), of_family(oos["placebo_results"], fam), fam, cfg)
                .set_index(["check", "horizon"]))
        saved = IN_SAMPLE / f"{fam}_pass_check.csv"
        if saved.exists():
            ins = pd.read_csv(saved)[["horizon", "pnl_difference"]].rename(columns={"pnl_difference": "edge_in_sample"})
            ins["horizon"] = ins["horizon"].astype(str)
            cmp_ = heads[["horizon", "edge_oos"]].assign(horizon=lambda d: d["horizon"].astype(str)).merge(ins, on="horizon")
            cmp_["same_sign"] = np.sign(cmp_.edge_in_sample) == np.sign(cmp_.edge_oos)
            print(f"{fam}: committed in-sample result (research/results/in_sample) vs out-of-sample edge")
            display(cmp_)
        else:
            print(f"{fam}: committed in-sample pass check not found; no comparison")
        ins_now = study["checks"].get(fam)
        if ins_now is not None and (START, END) != (cfg.study_start, cfg.study_end):
            print(f"note: the `study` object above covers {START} -> {END}, not the in-sample window")
else:
    print("Out-of-sample not run: it runs once, after the method freeze.")
'''

C12M = """\
## Sealed window for judges

Set `START` / `END` in the configuration cell to your window and rerun all cells. Nothing else is needed:
the study, placebo, pass check, decay, sensitivity and costs all follow the window.
"""

C12 = '''\
print(f"This run covered {START} -> {END}. Events: {len(study['events'])}; priced (event, bucket) pairs: {len(study['priced'])}.")
for fam in FAMILIES:
    print(f"{fam}: {verdict(study['checks'].get(fam))}")
print("Our forecast for this window, committed before the method freeze: research/FORECAST.md")
'''

C13 = """\
## Known limitations

- **Static universe.** `TOP_100` is today's list applied to the whole window: a survivorship bias.
- **Spot is inferred.** The stock price comes from put-call parity on the ATM pair with a flat carry rate and no dividend term; both legs are last trades and can be stale. The error largely cancels in P&L because entry and exit use the same construction.
- **The synthetic stock is not shares.** It collects no dividends and its short put can be assigned early; neither is modelled.
- **Last-trade marks, no spreads.** P&L is theoretical, mid-market at best. The cost section applies a 5% premium haircut (1x and 2x) and real half-spreads where quotes exist.
- **Small samples.** Intervals are wide; read the `n` columns before the means.
- **No earnings flag.** Events that share their window with an earnings release are not separated.
- **Filing lag and time of day.** `filing_date` has no time of day. **Every filing is treated as public after the close** (the next session is `t_0`): conservative, no lookahead, and slightly late for pre-market filings. EDGAR acceptance times are not used in the confirmatory path (the conservative rule is frozen; EDGAR's fixed 16:00 cutoff also mishandles 13:00 early closes).
- **Pre-event reference under conservative timing.** `t_pre` is the filing day itself, which may already contain intraday news for filings made during market hours.
- **Bootstrap.** The pass rule uses the pre-registered iid bootstrap. The robustness cell also resamples whole companies, which allows for same-company clustering; neither interval accounts for overlapping holding windows across companies.
- **Multi-ticker filings** keep the first in-universe ticker.
- **Run date and cache.** The client caches bar responses for unexpired contracts, so a cache built on one run date must not be treated as complete on a later date. Pin `LAST_SESSION` at the freeze and run the out-of-sample window once.
- **Strike availability.** When no strike sits at the requested OTM distance, the nearest listed one is used.
- **Exploratory material** (the atlas, off by default) shares one placebo across tags and never replaces H1 or H2.
"""


CM_MD = """\
## Closed-market evidence (stocks close, prediction markets don't)

The 8-K study above is the rigorous "what didn't work". This section is the evidence behind PolyBridge's closed-market mode
and its principle, **evidence gating**: a market's signal may act on a position only after it passed a pre-registered
out-of-sample test; otherwise it is shown as an unvalidated estimate.

**Reproducible offline.** These cells read only the committed files in `results/leadlag_closed`, `results/leadlag_replication`,
`results/gap_model`, `results/closed_hedge` and `results/open_options`. They make no network call and do not need
`MASSIVE_API_KEY`, so they run on their own (run the first code cell of this section, then the rest). Every headline number
is recomputed from the CSVs with the studies' own functions, parameters and seeds (10,000 permutations or bootstrap draws),
then checked against the committed JSON. Methods: the `METHOD.md` file in each study folder; numbers quoted elsewhere come
from `EVIDENCE.md`.

**How to read the verdicts.** *Confirmatory* = pre-registered and run once on new data. *Pre-registered analysis of a
known panel* = the rule was fixed in advance, but the 380-closure panel had already been seen, so it is not confirmatory.
*Exploratory* = a reading made after seeing the results.
"""

CM1 = '''\
# Closed-market evidence: recompute every headline number from the committed result files (no network, no key)
import sys
from pathlib import Path

import pandas as pd
from IPython.display import display

RESEARCH = next(p for p in (Path.cwd(), Path.cwd() / "research") if (p / "closed_market_section.py").exists())
if str(RESEARCH) not in sys.path:
    sys.path.insert(0, str(RESEARCH))
import closed_market_section as cms

cm_data = cms.load(RESEARCH / "results")
cm = cms.recompute(cm_data)
cm_check = cms.comparison(cm, cm_data)
with pd.option_context("display.float_format", "{:.6g}".format):
    display(cm_check.set_index(["study", "statistic"]))
print(f"{int(cm_check['match'].sum())} of {len(cm_check)} recomputed numbers match the committed JSON"
      + ("" if cm_check["match"].all() else "  <-- MISMATCH: the committed files disagree; trust neither until resolved"))
'''

CM2 = '''\
import matplotlib.pyplot as plt

cms.chart(cm_data, cm)
plt.show()
'''

CM3 = '''\
cm_summary = cms.summary(cm)
with pd.option_context("display.max_colwidth", None):
    display(cm_summary.set_index("finding"))
'''

CM_END = """\
**What this supports.** Options at the Monday open had repriced by about 0.44 of the prediction market's closure move
(R3, fresh data), but after option costs the residual gap is not above zero, so R3 is NULL: information, not an arbitrage.
The expected-gap model held out of sample in time on the US-recession market only (R2), which is why each market is gated on
its own result. Staging the equity hedge for 09:30 reduced post-open variance (R1 hedge B), fragile and on a known panel.

**What it does not support.** That prediction markets lead or predict the open, or beat futures (futures were not observed);
that the 380-closure relation is confirmed (it did not replicate); that the expected gap works beyond the recession market;
that hedge B reduces the gap itself; that the PM-contract hedge (hedge A) protects; that options at the open are a tradable
arbitrage.
"""

S1_MD = """\
## Twin spread: the same question on Polymarket and Kalshi (S1)

Thirty-three questions trade on both venues with the same resolution terms. When YES is cheaper on one venue than on the
other by more than every cost, buying YES on the cheap venue and NO on the rich one pays exactly $1 at resolution. The
method was committed before any price history was pulled (`s1_twin_spread/METHOD.md`).

**Reproducible offline.** These cells read only the committed files in `results/s1_twin_spread`. They make no network
call and need no key. The headline numbers are recomputed from the committed trade list and equity path with the
study's own functions, then checked against the committed `metrics.csv`.
"""

S1_1 = '''\
# S1 twin spread: recompute the headline numbers from the committed files (no network, no key)
import sys
from pathlib import Path

import pandas as pd
from IPython.display import display

RESEARCH = next(p for p in (Path.cwd(), Path.cwd() / "research") if (p / "twin_spread_section.py").exists())
if str(RESEARCH) not in sys.path:
    sys.path.insert(0, str(RESEARCH))
import twin_spread_section as tss

s1_data = tss.load(RESEARCH / "results" / "s1_twin_spread")
s1 = tss.recompute(s1_data)
s1_check = tss.comparison(s1, s1_data)
with pd.option_context("display.float_format", "{:.6g}".format):
    display(s1_check.set_index(["segment", "costs", "statistic"]))
print(f"{int(s1_check['match'].sum())} of {len(s1_check)} recomputed S1 numbers match the committed metrics.csv"
      + ("" if s1_check["match"].all() else "  <-- MISMATCH: the committed files disagree; trust neither until resolved"))
'''

S1_2 = '''\
import matplotlib.pyplot as plt

tss.chart(s1_data)
plt.show()
'''

S1_3 = '''\
with pd.option_context("display.max_colwidth", None):
    display(tss.summary(s1).set_index("finding"))
s1_forward = tss.forward_table(s1_data)
if s1_forward is None:
    print("Forward paper test on the recorded weekend books: not run yet.")
else:
    display(s1_forward)
'''

S1_END = """\
**What this supports.** Cross-venue gaps on the same question do appear, and the ones a public Polymarket trade print
confirms were profitable after Kalshi fees, Polymarket fees, both spreads and the cost of capital locked until
resolution, at 1x and at 2x costs. They are few and small.

**What it does not support.** That the twin spread is a strategy with capacity: the pre-registered test is not a pass,
because most backtest entries have no trade print behind the Polymarket price. The blue curve above is what an assumed
Polymarket spread manufactures, and its Sharpe ratio is an artifact. No pair has resolved, so resolution risk is unmeasured.
"""


def build(path: Path | None = None) -> None:
    nb = new_notebook(cells=[md(C1), code(C2), code(C3), code(C4), code(C5), code(C6), code(C6R), code(C7), code(C8), code(C9),
                             code(C10), code(C11), md(C12M), code(C12), md(C13),
                             md(CM_MD), code(CM1), code(CM2), code(CM3), md(CM_END),
                             md(S1_MD), code(S1_1), code(S1_2), code(S1_3), md(S1_END)])
    nb.metadata["kernelspec"] = {"display_name": "Python 3", "language": "python", "name": "python3"}
    for i, cell in enumerate(nb.cells):
        cell["id"] = f"cell-{i:02d}"
    nbformat.validate(nb)
    nbformat.write(nb, path or HERE / "polybridge_8k.ipynb")


if __name__ == "__main__":
    import sys

    build(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
